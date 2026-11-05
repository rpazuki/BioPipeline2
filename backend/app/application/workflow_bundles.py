"""Install reviewed workflow definitions through the normal authoring services."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.audit import RequestContext, record
from app.application.pipelines import archive_pipeline, create_revision
from app.application.publication_library import read_library, save_library
from app.application.publications import FieldSpec, archive, create_publication_revision, publish
from app.domain.bindings import FieldBinding
from app.domain.compiler import compile_pipeline
from app.domain.enums import LifecycleStatus, PublicationStatus
from app.domain.errors import ValidationFailed
from app.domain.publication_library import parse_library
from app.infrastructure.component_store import ComponentStore, validate_source
from app.infrastructure.db.models import Pipeline, Publication, PublicationRevision
from app.infrastructure.pipeline_loader import parse_document


def _read(root: Path, reference: str) -> str:
    path = (root / reference).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValidationFailed(
            "A bundle reference must identify a file inside the bundle directory."
        )
    return path.read_bytes().decode("utf-8")


@contextmanager
def install_bundle(
    session: Session,
    *,
    root: Path,
    component_root: Path,
    actor_id: uuid.UUID,
    replace_existing: bool = False,
    dry_run: bool = False,
) -> Iterator[dict[str, Any]]:
    """Prepare a reviewed bundle and restore component files if its transaction fails.

    The caller must commit or roll back the database transaction inside this
    context. Dry runs validate publications with the normal services but never
    write component files. Replacement archives other workflows and withdraws
    other catalog entries while preserving their immutable history.
    """
    root = root.resolve()
    manifest_text = _read(root, "bundle.yaml")
    bundle = yaml.safe_load(manifest_text)
    if not isinstance(bundle, dict) or bundle.get("version") != 1:
        raise ValidationFailed("Unsupported workflow bundle version.")
    sources = {reference: _read(root, reference) for reference in bundle["components"]}
    sources[bundle["library"]] = _read(root, bundle["library"])
    for publication in bundle["publications"]:
        reference = publication["pipeline"]
        sources[reference] = _read(root, reference)
    digest = hashlib.sha256(
        json.dumps(
            {"manifest": manifest_text, "sources": sources},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    libraries = {
        Path(name).name: validate_source(source)
        for name, source in sources.items()
        if name in bundle["components"]
    }
    if len(libraries) != len(bundle["components"]):
        raise ValidationFailed("Bundle component filenames must be unique.")

    def load_library(reference: str):
        if reference not in libraries:
            raise ValidationFailed(f"Component '{reference}' is not part of this bundle.")
        return libraries[reference]

    for publication in bundle["publications"]:
        result = compile_pipeline(
            parse_document(sources[publication["pipeline"]]),
            load_library=load_library,
        )
        if not result.ok:
            raise ValidationFailed(
                "A bundled pipeline does not compile.",
                details={
                    "errors": [item.model_dump() for item in result.errors],
                },
            )
    current = read_library(session)
    existing = yaml.safe_load(current.source_text)
    incoming = yaml.safe_load(sources[bundle["library"]])
    merged = {
        **existing,
        "definitions": {**existing.get("definitions", {}), **incoming.get("definitions", {})},
        "presets": {**existing.get("presets", {}), **incoming.get("presets", {})},
    }
    library_source = yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)
    parse_library(library_source)
    library = save_library(session, library_source, current.digest, actor_id)
    imported_pipelines: set[uuid.UUID] = set()
    imported_publications: set[uuid.UUID] = set()
    report: dict[str, Any] = {
        "bundle": bundle["name"],
        "digest": digest,
        "dry_run": dry_run,
        "publications": [],
        "archived_pipelines": 0,
        "withdrawn_publications": 0,
    }
    for specification in bundle["publications"]:
        revision = create_revision(
            session,
            source_text=sources[specification["pipeline"]],
            owner_id=actor_id,
            title=specification["title"],
            load_library=load_library,
        )
        imported_pipelines.add(revision.pipeline_id)
        pipeline = session.get(Pipeline, revision.pipeline_id)
        if pipeline is None:
            raise ValidationFailed("The imported pipeline is no longer available.")
        pipeline.status = LifecycleStatus.ACTIVE
        existing_publication = session.execute(
            select(Publication).where(
                Publication.slug == specification["slug"],
            )
        ).scalar_one_or_none()
        previous = (
            session.get(PublicationRevision, existing_publication.current_revision_id)
            if (existing_publication and existing_publication.current_revision_id)
            else None
        )
        if (
            previous
            and previous.pipeline_revision_id == revision.revision_id
            and previous.display_metadata.get("bundle_digest") == digest
        ):
            publication_id, publication_revision_id = previous.publication_id, previous.id
        else:
            fields = [
                FieldSpec(
                    **{key: value for key, value in field.items() if key != "binding"},
                    binding=FieldBinding(key=field["key"], **field["binding"]),
                )
                for field in specification["fields"]
            ]
            created = create_publication_revision(
                session,
                slug=specification["slug"],
                pipeline_revision_id=revision.revision_id,
                title=specification["title"],
                description=specification.get("description"),
                fields=fields,
                created_by=actor_id,
                library_digest=library.digest,
                display_metadata={
                    **specification.get("display_metadata", {}),
                    "bundle_digest": digest,
                },
            )
            publication_id, publication_revision_id = created.publication_id, created.revision_id
        publish(session, publication_id=publication_id, revision_id=publication_revision_id)
        imported_publications.add(publication_id)
        report["publications"].append(
            {"slug": specification["slug"], "revision_id": str(publication_revision_id)}
        )
    if replace_existing:
        for publication in session.scalars(select(Publication)):
            if (
                publication.id not in imported_publications
                and publication.status != PublicationStatus.ARCHIVED
            ):
                archive(session, publication_id=publication.id)
                report["withdrawn_publications"] += 1
        for pipeline in session.scalars(select(Pipeline)):
            if (
                pipeline.id not in imported_pipelines
                and pipeline.status != LifecycleStatus.ARCHIVED
            ):
                archive_pipeline(session, pipeline.id)
                report["archived_pipelines"] += 1
    record(
        session,
        action="workflow_bundle.imported",
        target_type="workflow_bundle",
        context=RequestContext(actor_id=actor_id),
        bundle=bundle["name"],
        digest=digest,
        replace_existing=replace_existing,
    )
    store = ComponentStore(component_root)
    changes: list[tuple[str, dict | None, str | None]] = []
    try:
        if not dry_run:
            current_components = {item["name"]: item for item in store.list()}
            for reference in bundle["components"]:
                name, source = Path(reference).name, sources[reference]
                before = current_components.get(name)
                saved = store.save(name, source, before["digest"] if before else None)
                changes.append((name, before, saved["digest"]))
            if replace_existing:
                for name, before in current_components.items():
                    if name not in libraries:
                        store.remove(name, before["digest"])
                        changes.append((name, before, None))
        yield report
    except BaseException:
        for name, before, installed_digest in reversed(changes):
            if before:
                store.restore_snapshot(name, before["digest"], installed_digest)
            elif installed_digest:
                store.remove(name, installed_digest)
        raise

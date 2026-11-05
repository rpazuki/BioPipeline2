from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.application.workflow_bundles import install_bundle
from app.infrastructure.component_store import ComponentStore
from app.infrastructure.db.models import PipelineRevision, Publication, PublicationRevision

pytestmark = pytest.mark.db
ROOT = Path(__file__).resolve().parents[3] / "examples/migrations/od600"


def test_bundle_import_is_idempotent_and_preserves_the_researcher_contract(
    sessions, admin, as_researcher, tmp_path
):
    imported_revisions = []
    for _ in range(2):
        with (
            sessions() as session,
            install_bundle(
                session, root=ROOT, component_root=tmp_path, actor_id=admin[0]
            ) as report,
        ):
            session.commit()
        assert len(report["publications"]) == 2
        imported_revisions.append(report["publications"])
    assert imported_revisions[0] == imported_revisions[1]
    with sessions() as session:
        publications = list(
            session.scalars(
                select(Publication).where(
                    Publication.slug.in_(
                        ["od600-growth-rates-single", "od600-growth-rates-multiple"]
                    )
                )
            )
        )
        for publication in publications:
            current = session.get(PublicationRevision, publication.current_revision_id)
            assert current.display_metadata["result_delivery"] == ["individual", "zip"]
    single = as_researcher.get("/api/v1/catalog/od600-growth-rates-single").json()
    fields = {field["key"]: field for field in single["fields"]}
    assert fields["raw_file"]["field_type"] == "file"
    assert fields["metadata_file"]["source_policy"]["sources"] == ["upload"]
    assert fields["custom_rules"]["type_schema"]["container"] == "map"
    assert fields["custom_rules"]["default_value"]["WT"]["sample_size"] == 2
    assert len(fields["method"]["type_schema"]["options"]) == 3
    multiple = as_researcher.get("/api/v1/catalog/od600-growth-rates-multiple").json()
    fields = {field["key"]: field for field in multiple["fields"]}
    assert fields["data_root"]["field_type"] == "directory"
    assert fields["data_to_metadata_mapping_yaml"]["field_type"] == "file"


def test_dry_run_does_not_change_files_or_database(sessions, admin, tmp_path):
    store = ComponentStore(tmp_path)
    original = store.save(
        "original.yaml", "graphs: {convert: [{name: result, package: builtins, method: str}]}", None
    )
    with sessions() as session:
        before = session.scalar(select(func.count()).select_from(PipelineRevision))
        with install_bundle(
            session,
            root=ROOT,
            component_root=tmp_path,
            actor_id=admin[0],
            replace_existing=True,
            dry_run=True,
        ):
            session.rollback()
        assert session.scalar(select(func.count()).select_from(PipelineRevision)) == before
    assert [item["name"] for item in store.list()] == ["original.yaml"]
    assert store.read("original.yaml")["digest"] == original["digest"]


@pytest.mark.parametrize("invalid_draft", [False, True])
def test_failed_transaction_restores_removed_and_replaced_component_sources(
    sessions, admin, tmp_path, invalid_draft
):
    store = ComponentStore(tmp_path)
    source = "graphs: {convert: [{name: result, package: builtins, method: str}]}"
    for name in ("original.yaml", "growth_rates_pipeline.yaml"):
        store.save(name, source, None)
    if invalid_draft:
        source = "unfinished: ["
        for name in ("original.yaml", "growth_rates_pipeline.yaml"):
            (tmp_path / name).write_text(source)
    with sessions() as session:
        with (
            pytest.raises(RuntimeError, match="commit failed"),
            install_bundle(
                session,
                root=ROOT,
                component_root=tmp_path,
                actor_id=admin[0],
                replace_existing=True,
            ),
        ):
            assert [item["name"] for item in store.list()] == ["growth_rates_pipeline.yaml"]
            raise RuntimeError("commit failed")
        session.rollback()
    assert {item["name"]: item["source_text"] for item in store.list()} == {
        "original.yaml": source,
        "growth_rates_pipeline.yaml": source,
    }

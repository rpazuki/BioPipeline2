"""Read and atomically update the project's publication authoring library."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.pipelines import default_project_id
from app.domain.errors import Conflict
from app.domain.publication_library import EMPTY_SOURCE, LibraryDocument, parse_library
from app.infrastructure.db.models import Project, PublicationLibrary


def read_library(session: Session) -> LibraryDocument:
    """Return the current library, or an empty document before its first save."""
    row = session.get(PublicationLibrary, default_project_id(session))
    return parse_library(row.source_text if row else EMPTY_SOURCE)


def save_library(
    session: Session, source: str, expected_digest: str, updated_by: uuid.UUID
) -> LibraryDocument:
    """Save valid source if the administrator edited the current document."""
    parsed = parse_library(source)
    project_id = default_project_id(session)
    session.execute(select(Project).where(Project.id == project_id).with_for_update()).scalar_one()
    current = read_library(session)
    if current.digest != expected_digest:
        raise Conflict("The publication library changed. Reload it before saving your edits.")
    row = session.get(PublicationLibrary, project_id)
    if row is None:
        row = PublicationLibrary(project_id=project_id)
        session.add(row)
    row.source_text = source
    row.updated_by = updated_by
    session.flush()
    return parsed

"""Administrator-only publication library authoring."""

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import AdminUser, Db
from app.application.publication_library import read_library, save_library
from app.domain.errors import Conflict
from app.domain.library_import import import_library
from app.domain.publication_library import LibraryDocument, parse_library

router = APIRouter(prefix="/publication-library", tags=["publications"])


class LibraryResponse(BaseModel):
    source_text: str
    digest: str
    schemas: dict[str, dict[str, Any]]
    presets: dict[str, dict[str, Any]]


class LibraryValidationRequest(BaseModel):
    source_text: str = Field(min_length=1, max_length=200_000)


class LibrarySaveRequest(LibraryValidationRequest):
    expected_digest: str = Field(min_length=64, max_length=64)


class LibraryImportRequest(LibrarySaveRequest):
    base_source: str = Field(min_length=1, max_length=200_000)
    format: Literal["legacy_types", "legacy_constants", "presets"]


class LibraryImportResponse(BaseModel):
    source_text: str
    base_digest: str
    notes: list[str]


@router.post("/import-preview", response_model=LibraryImportResponse)
def preview_import(
    payload: LibraryImportRequest, db: Db, _admin: AdminUser
) -> LibraryImportResponse:
    """Preview an explicit import without changing the stored library."""
    current = read_library(db)
    if current.digest != payload.expected_digest:
        raise Conflict("The publication library changed. Reload it before importing.")
    source, notes = import_library(payload.base_source, payload.source_text, payload.format)
    return LibraryImportResponse(source_text=source, base_digest=current.digest, notes=notes)


@router.get("", response_model=LibraryResponse)
def read(db: Db, _admin: AdminUser) -> LibraryDocument:
    """Read types and presets available to publication authors."""
    return read_library(db)


@router.post("/validate", response_model=LibraryResponse)
def validate(payload: LibraryValidationRequest, _admin: AdminUser) -> LibraryDocument:
    """Resolve types and check preset values without saving."""
    return parse_library(payload.source_text)


@router.put("", response_model=LibraryResponse)
def save(payload: LibrarySaveRequest, db: Db, admin: AdminUser) -> LibraryDocument:
    """Save a validated library without overwriting concurrent edits."""
    return save_library(db, payload.source_text, payload.expected_digest, admin.user_id)

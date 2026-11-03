"""Administrator-only publication library authoring."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import AdminUser, Db
from app.application.publication_library import read_library, save_library
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

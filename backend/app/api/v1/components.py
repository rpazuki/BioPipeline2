"""Administer component library sources and immutable source snapshots."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import AdminUser, Config
from app.domain.errors import ValidationFailed
from app.infrastructure.component_store import ComponentStore, validate_source

router = APIRouter(prefix="/components", tags=["components"])


class ComponentSource(BaseModel):
    name: str
    digest: str
    reference: str
    source_text: str
    graphs: list[str]
    error: str | None = None


class ComponentSummary(BaseModel):
    name: str
    digest: str
    graphs: list[str]
    error: str | None = None


class ComponentSaveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source_text: str = Field(min_length=1, max_length=1_000_000)
    expected_digest: str | None = None


class ComponentValidationRequest(BaseModel):
    source_text: str = Field(min_length=1, max_length=1_000_000)


class ComponentValidationResponse(BaseModel):
    ok: bool
    graphs: list[str] = Field(default_factory=list)
    message: str | None = None


@router.get("", response_model=list[ComponentSummary])
def list_components(settings: Config, _admin: AdminUser) -> list[dict[str, Any]]:
    """List the component libraries available for pipeline authoring."""
    return ComponentStore(settings.component_library_root).list()


@router.get("/source", response_model=ComponentSource)
def read_source(
    name: str, settings: Config, _admin: AdminUser, revision: str | None = None
) -> dict[str, Any]:
    """Return the exact current or historical source of one library."""
    return ComponentStore(settings.component_library_root).read(name, revision)


@router.delete("/source", status_code=204)
def remove_source(name: str, expected_digest: str, settings: Config, _admin: AdminUser) -> None:
    """Remove a current component source without changing compiled pipelines."""
    ComponentStore(settings.component_library_root).remove(name, expected_digest)


@router.get("/revisions", response_model=list[ComponentSource])
def list_revisions(name: str, settings: Config, _admin: AdminUser) -> list[dict[str, Any]]:
    """List retained source versions of a component library."""
    return ComponentStore(settings.component_library_root).revisions(name)


@router.post("/validate", response_model=ComponentValidationResponse)
def validate_component(
    payload: ComponentValidationRequest, _admin: AdminUser
) -> ComponentValidationResponse:
    """Check named component graphs without saving or executing their functions."""
    try:
        library = validate_source(payload.source_text)
        return ComponentValidationResponse(ok=True, graphs=sorted(library.graphs))
    except ValidationFailed as error:
        return ComponentValidationResponse(ok=False, message=error.message)


@router.post("/revisions", response_model=ComponentSource, status_code=201)
def save_revision(
    payload: ComponentSaveRequest, settings: Config, _admin: AdminUser
) -> dict[str, Any]:
    """Save validated source and retain the previous component version."""
    return ComponentStore(settings.component_library_root).save(
        payload.name, payload.source_text, payload.expected_digest
    )

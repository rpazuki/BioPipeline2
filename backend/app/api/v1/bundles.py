"""Queue result ZIP preparation and expose its progress to the run owner."""

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import Config, CurrentUser, Db
from app.api.v1.runs import _visible_or_404
from app.application.bundles import create_bundle
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.db.models import Artifact, ArtifactBundle

router = APIRouter(prefix="/runs", tags=["artifacts"])


class BundleRequest(BaseModel):
    artifact_ids: list[uuid.UUID] | None = Field(default=None, max_length=1000)


class BundleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    run_id: uuid.UUID
    status: Literal["pending", "working", "ready", "failed", "expired"]
    total_bytes: int
    completed_bytes: int
    artifact_id: uuid.UUID | None = None
    message: str | None = None


def _response(job: ArtifactBundle, db: Db, settings: Config) -> BundleResponse:
    response = BundleResponse.model_validate(job)
    if job.status == "ready":
        artifact = db.get(Artifact, job.artifact_id)
        if (
            artifact is None
            or artifact.deleted_at
            or artifact.purged_at
            or not PosixArtifactStore(settings.artifact_root).exists(artifact.storage_key)
        ):
            response.status = "expired"
            response.message = (
                "This ZIP has expired. Prepare it again if the original outputs "
                "are still available."
            )
    return response


@router.post("/{run_id}/bundles", response_model=BundleResponse, status_code=201)
def prepare(
    run_id: uuid.UUID, payload: BundleRequest, db: Db, principal: CurrentUser, settings: Config
) -> BundleResponse:
    """Queue a bounded ZIP of available outputs belonging to this run."""
    run = _visible_or_404(db, run_id, principal)
    return _response(
        create_bundle(db, run, principal.user_id, settings, payload.artifact_ids), db, settings
    )


@router.get("/{run_id}/bundles/{bundle_id}", response_model=BundleResponse)
def progress(
    run_id: uuid.UUID, bundle_id: uuid.UUID, db: Db, principal: CurrentUser, settings: Config
) -> BundleResponse:
    """Return durable preparation progress for a visible run."""
    _visible_or_404(db, run_id, principal)
    job = db.get(ArtifactBundle, bundle_id)
    if job is None or job.run_id != run_id:
        raise HTTPException(status_code=404, detail="No such ZIP preparation request.")
    return _response(job, db, settings)

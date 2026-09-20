"""Shared storage roots: the first thing a deployment configures.

Until a root is registered nothing can be submitted that names a file the lab
already has — `readable_roots` is empty and every fan-out is refused — so this
is what turns a fresh install into one somebody can use. Admin-only, because
registering a root is an attestation about a filesystem, not a preference.

A change here reaches a worker on its next start, not immediately: mounts are
resolved once per process rather than per task, because the set changes when
somebody attests a root and re-reading it for every claim would be a query per
task for an answer that almost never differs.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AdminUser, Audit, Config, Db
from app.api.schemas import (
    Page,
    RegisterRootRequest,
    ReinstateRootRequest,
    RevokeRootRequest,
    StorageRootResponse,
)
from app.application import audit as audit_log
from app.application.storage_roots import (
    RootView,
    get_root,
    list_roots,
    register_root,
    reinstate,
    revoke,
)

router = APIRouter(prefix="/storage/roots", tags=["storage"])


def _response(view: RootView) -> StorageRootResponse:
    root = view.root
    return StorageRootResponse(
        id=root.id,
        label=root.label,
        root_path=root.root_path,
        readable=root.readable,
        writable=root.writable,
        identity_mode=root.identity_mode,
        attested_by=root.attested_by,
        attested_at=root.attested_at,
        attestation_note=root.attestation_note,
        revoked_at=root.revoked_at,
        created_at=root.created_at,
        visible=view.visible,
        in_use=view.in_use,
    )


def _or_404(db: Db, root_id: str) -> RootView:
    view = get_root(db, root_id)
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "storage_root.not_found", "message": "No such storage root."},
        )
    return view


@router.get("", response_model=Page[StorageRootResponse])
def list_storage_roots(db: Db, _admin: AdminUser) -> Page[StorageRootResponse]:
    """Every root, working or not.

    Withdrawn and unreachable roots are listed rather than filtered out: "the
    share is gone" and "nobody ever registered it" are different problems and
    a list that shows only working roots cannot tell them apart.
    """
    views = list_roots(db)
    return Page[StorageRootResponse](items=[_response(view) for view in views], total=len(views))


@router.post("", response_model=StorageRootResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRootRequest, db: Db, admin: AdminUser, settings: Config, context: Audit
) -> StorageRootResponse:
    """Allowlist a path for task containers to read.

    The path is refused if it is relative, if the platform cannot see it as a
    directory, if it overlaps the platform's own storage — which would give
    every task a read-only view of every other run's outputs — or if it
    overlaps a root that already exists, whose permissions it would then
    silently contradict. `RootRejected` is a `ValidationFailed`, so each of
    those reaches the caller as a 422 saying which one it was.
    """
    root = register_root(
        db,
        root_id=payload.id,
        label=payload.label,
        root_path=payload.root_path,
        readable=payload.readable,
        writable=payload.writable,
        attested_by=admin.user_id,
        attestation_note=payload.attestation_note,
        settings=settings,
    )
    # The attestation is the thing worth keeping: it is a human judgement the
    # platform cannot verify, and who made it is part of the record.
    audit_log.record(
        db,
        action=audit_log.ROOT_REGISTERED,
        target_type="storage_root",
        context=context,
        root_id=root.id,
        root_path=root.root_path,
        writable=root.writable,
        attestation=payload.attestation_note,
    )
    return _response(_or_404(db, root.id))


@router.post("/{root_id}/revoke", response_model=StorageRootResponse)
def revoke_root(
    root_id: str, payload: RevokeRootRequest, db: Db, admin: AdminUser, context: Audit
) -> StorageRootResponse:
    """Stop offering a root.

    Withdrawn, not deleted: a delivery that went here still names it, and who
    attested it is part of the record whether or not it is still mounted.
    Anything already running keeps the mount it was given.
    """
    _or_404(db, root_id)
    revoke(db, root_id, actor_id=admin.user_id, reason=payload.reason)
    audit_log.record(
        db,
        action=audit_log.ROOT_REVOKED,
        target_type="storage_root",
        context=context,
        root_id=root_id,
        reason=payload.reason,
    )
    return _response(_or_404(db, root_id))


@router.post("/{root_id}/reinstate", response_model=StorageRootResponse)
def reinstate_root(
    root_id: str,
    payload: ReinstateRootRequest,
    db: Db,
    admin: AdminUser,
    settings: Config,
    context: Audit,
) -> StorageRootResponse:
    """Put a withdrawn root back, on a fresh attestation.

    Not an undo: the path is checked again and the attestation is made again,
    because the reason it was withdrawn may have been that the share's
    permissions changed.
    """
    _or_404(db, root_id)
    reinstate(
        db,
        root_id,
        actor_id=admin.user_id,
        attestation_note=payload.attestation_note,
        readable=payload.readable,
        writable=payload.writable,
        settings=settings,
    )
    audit_log.record(
        db,
        action=audit_log.ROOT_REINSTATED,
        target_type="storage_root",
        context=context,
        root_id=root_id,
        writable=payload.writable,
        attestation=payload.attestation_note,
    )
    return _response(_or_404(db, root_id))

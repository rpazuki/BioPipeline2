"""Enforce publication input sources independently of computational definitions."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.application.uploads import StagedInput, is_reference, resolve_reference
from app.domain.errors import ValidationFailed
from app.infrastructure.mounts import readable_roots


def source_policy(field_type: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize supported transport choices for a published file or directory."""
    if field_type not in {"file", "directory"}:
        if raw:
            raise ValidationFailed("Input sources apply only to file and directory fields.")
        return {}
    allowed = ["upload", "shared"] if field_type == "file" else ["folder", "zip", "shared"]
    sources = (raw or {}).get("sources", allowed)
    if not isinstance(sources, list) or not sources or any(item not in allowed for item in sources):
        raise ValidationFailed(
            f"A {field_type} field needs sources chosen from {', '.join(allowed)}."
        )
    if set(raw or {}) - {"sources"}:
        raise ValidationFailed("Unknown input source policy property.")
    return {"sources": list(dict.fromkeys(sources))}


def prepare_input(
    session: Session,
    value: Any,
    *,
    field_type: str,
    policy: dict[str, Any],
    requested_by: uuid.UUID,
    check_paths: bool = True,
) -> tuple[str, StagedInput | None]:
    """Resolve an owned upload or verify an allowed, registered shared path."""
    allowed = source_policy(field_type, policy)["sources"]
    if is_reference(value):
        staged = resolve_reference(session, value, requested_by=requested_by)
        method = "upload" if staged.kind == "file" else staged.kind
        if (field_type == "file") != (staged.kind == "file"):
            raise ValidationFailed(f"This field requires a {field_type}, not this upload format.")
        if method not in allowed:
            raise ValidationFailed(f"This publication does not allow the '{method}' input method.")
        return staged.path, staged
    if "shared" not in allowed:
        raise ValidationFailed("This publication requires an uploaded input for this field.")
    if not isinstance(value, str) or not value.startswith("/") or "\\" in value:
        raise ValidationFailed("Choose an upload or an absolute path on registered shared storage.")
    try:
        candidate = Path(value).resolve()
    except (ValueError, OSError) as error:
        raise ValidationFailed("The shared input path is invalid.") from error
    if not any(candidate.is_relative_to(root.resolve()) for root in readable_roots(session)):
        raise ValidationFailed("The input is outside registered, readable shared storage.")
    if check_paths and not (candidate.is_file() if field_type == "file" else candidate.is_dir()):
        raise ValidationFailed(f"The shared {field_type} does not exist or is unavailable.")
    return str(candidate), None


def result_modes(metadata: dict[str, Any] | None) -> list[str]:
    """Read and validate a publication's result download choices."""
    modes = (metadata or {}).get("result_delivery", ["individual"])
    if (
        not isinstance(modes, list)
        or not modes
        or any(not isinstance(mode, str) or mode not in {"individual", "zip"} for mode in modes)
    ):
        raise ValidationFailed("Choose individual downloads, ZIP downloads, or both.")
    return list(dict.fromkeys(modes))

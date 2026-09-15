"""Request and response shapes.

Separate from the domain models on purpose: the wire format is a contract with
clients and changes for different reasons than the domain does. Collapsing
them means a refactor becomes a breaking API change.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Page[T](BaseModel):
    """One page of a collection.

    One envelope for every list endpoint, so a client writes the paging logic
    once. ``total`` is nullable because counting is expensive on large tables
    and an endpoint that cannot afford it should say so rather than guess.
    """

    items: list[T]
    next_cursor: str | None = None
    total: int | None = None


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


class SessionResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class CreateRevisionRequest(BaseModel):
    source_text: str = Field(min_length=1, max_length=1_000_000)
    title: str | None = Field(default=None, max_length=256)


class DiagnosticResponse(BaseModel):
    severity: str
    code: str
    message: str
    location: str = ""


class RevisionResponse(BaseModel):
    revision_id: uuid.UUID
    pipeline_id: uuid.UUID
    version: int
    graph_hash: str
    reused: bool
    warnings: list[DiagnosticResponse] = Field(default_factory=list)


class PipelineSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    status: str
    created_at: datetime


class CompilePreviewRequest(BaseModel):
    source_text: str = Field(min_length=1, max_length=1_000_000)
    values: dict[str, Any] = Field(default_factory=dict)


class CompilePreviewResponse(BaseModel):
    ok: bool
    graph_hash: str | None = None
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    stages: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: list[DiagnosticResponse] = Field(default_factory=list)


class SubmitRunRequest(BaseModel):
    pipeline_revision_id: uuid.UUID
    values: dict[str, Any] = Field(default_factory=dict)


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    pipeline_revision_id: uuid.UUID
    requested_by: uuid.UUID
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunDetail(RunSummary):
    task_counts: dict[str, int] = Field(default_factory=dict)
    total_tasks: int = 0
    input_values: dict[str, Any] = Field(default_factory=dict)
    cancel_requested_at: datetime | None = None


class TaskSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_key: str
    stage_key: str
    status: str
    status_reason: str | None = None
    task_class: str
    attempt_count: int
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ArtifactSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    filename: str
    size_bytes: int
    checksum_sha256: str | None = None
    created_at: datetime
    expires_at: datetime | None = None


class DeliverySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    field_key: str
    mode: str
    status: str
    target_root_id: str | None = None
    message: str | None = None
    delivered_at: datetime | None = None


class SubmitRunResponse(BaseModel):
    run_id: uuid.UUID
    task_count: int
    reused: bool
    warnings: list[DiagnosticResponse] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    version: str


class ReadyResponse(BaseModel):
    status: str
    checks: dict[str, str]

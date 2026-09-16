"""Request and response shapes.

Separate from the domain models on purpose: the wire format is a contract with
clients and changes for different reasons than the domain does. Collapsing
them means a refactor becomes a breaking API change.

Status fields are typed with the domain enumerations rather than ``str``,
because the wire format is what a generated client is built from: as ``str``
every status is opaque, a client renders an unknown value as a blank badge,
and nothing fails until somebody notices. As an enumeration the allowed set
reaches the OpenAPI document, a generated TypeScript client gets a union, and
a status added here stops a client's build instead of its rendering.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    ArtifactKind,
    DeliveryMode,
    DeliveryStatus,
    InputSourceMode,
    LifecycleStatus,
    RunStatus,
    TaskClass,
    TaskStatus,
    UserRole,
    ValidationStatus,
)
from app.domain.ir import Severity


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
    role: UserRole


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class CreateRevisionRequest(BaseModel):
    source_text: str = Field(min_length=1, max_length=1_000_000)
    title: str | None = Field(default=None, max_length=256)


class DiagnosticResponse(BaseModel):
    severity: Severity
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
    status: LifecycleStatus
    created_at: datetime


class CompilePreviewRequest(BaseModel):
    source_text: str = Field(min_length=1, max_length=1_000_000)
    values: dict[str, Any] = Field(default_factory=dict)


class CompiledInputResponse(BaseModel):
    """One value a run must supply."""

    key: str
    accept: Literal["file", "directory", "value"]
    sources: list[InputSourceMode] = Field(default_factory=list)
    required: bool = True
    type_ref: str | None = None
    help: str | None = None


class CompiledStageResponse(BaseModel):
    """One stage of the compiled graph."""

    key: str
    name: str
    variant: dict[str, Any] | None = None
    needs: list[str] = Field(default_factory=list)
    fanout: str
    steps: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    task_class: TaskClass


class CompilePreviewResponse(BaseModel):
    """What a document compiles to, or why it does not.

    ``inputs`` and ``stages`` are described rather than dumped as free-form
    objects: this is the only place a client can learn a pipeline's input
    contract, and a client that has to guess the field names guesses wrong.
    """

    ok: bool
    graph_hash: str | None = None
    inputs: list[CompiledInputResponse] = Field(default_factory=list)
    stages: list[CompiledStageResponse] = Field(default_factory=list)
    diagnostics: list[DiagnosticResponse] = Field(default_factory=list)


class CompiledOutputResponse(BaseModel):
    """One file or directory a run will produce, and where it goes."""

    stage: str
    key: str
    path: str
    delivery: list[DeliveryMode] = Field(default_factory=list)
    shared_root: str | None = None
    retention_days: int | None = None
    optional: bool = False


class RevisionDetail(BaseModel):
    """One stored revision, with the contract a submission must satisfy.

    The input contract is the whole point of this endpoint. Without it a client
    can only offer a free-text box for the submitted values, and the person
    filling it in has to already know the keys, which of them are required, and
    whether each wants a path or a value -- none of which is written down
    anywhere they can see.
    """

    revision_id: uuid.UUID
    pipeline_id: uuid.UUID
    version: int
    graph_hash: str
    created_at: datetime
    validation_status: ValidationStatus
    inputs: list[CompiledInputResponse] = Field(default_factory=list)
    outputs: list[CompiledOutputResponse] = Field(default_factory=list)


class SubmitRunRequest(BaseModel):
    pipeline_revision_id: uuid.UUID
    values: dict[str, Any] = Field(default_factory=dict)


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: RunStatus
    pipeline_revision_id: uuid.UUID
    requested_by: uuid.UUID
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunDetail(RunSummary):
    task_counts: dict[TaskStatus, int] = Field(default_factory=dict)
    total_tasks: int = 0
    input_values: dict[str, Any] = Field(default_factory=dict)
    cancel_requested_at: datetime | None = None


class TaskSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_key: str
    stage_key: str
    status: TaskStatus
    status_reason: str | None = None
    task_class: TaskClass
    attempt_count: int
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ArtifactSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: ArtifactKind
    filename: str
    size_bytes: int
    checksum_sha256: str | None = None
    created_at: datetime
    expires_at: datetime | None = None


class DeliverySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    field_key: str
    # Which task produced it. A fanned-out run has one delivery per task under
    # a single field name, so `results` alone names nothing a researcher can
    # act on -- and "which plate failed to reach the share" is the question
    # they are actually asking.
    task_key: str | None = None
    mode: DeliveryMode
    status: DeliveryStatus
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


class ClientConfigResponse(BaseModel):
    """What a browser may read before it has a session.

    The field names mirror :meth:`app.settings.Settings.public` exactly, and a
    test asserts they still do: the allowlist is the security boundary, and a
    response model that quietly drifts from it would either hide a setting the
    frontend needs or publish one nobody reviewed.
    """

    app_name: str
    environment: str
    api_prefix: str
    base_path: str
    upload_chunk_max_bytes: int
    upload_max_total_bytes: int
    csrf_header: str
    csrf_value: str

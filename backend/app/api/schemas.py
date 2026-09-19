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

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import (
    ArtifactKind,
    AttemptStatus,
    BindingTarget,
    CatchupPolicy,
    DeliveryMode,
    DeliveryStatus,
    DstPolicy,
    FieldVisibility,
    FireOutcome,
    InputSourceMode,
    LifecycleStatus,
    OverlapPolicy,
    PrimitiveType,
    PublicationStatus,
    RunStatus,
    RunTrigger,
    ScheduleStatus,
    TaskClass,
    TaskStatus,
    UploadStatus,
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


class BindableTargetResponse(BaseModel):
    """One place in a pipeline a publication field could attach to.

    Offered only where a binding would actually be valid and actually take
    effect, so an editor built on this list cannot compose a field that the
    publish then refuses.
    """

    target: BindingTarget
    stage: str | None = None
    step: str | None = None
    key: str
    value_type: str | None = None
    current_value: Any = None


class FieldBindingRequest(BaseModel):
    """Where a field reaches into the pipeline revision (ADR 0031)."""

    target: BindingTarget
    stage: str | None = Field(default=None, max_length=128)
    step: str | None = Field(default=None, max_length=128)
    binding_key: str = Field(max_length=128)


class PublicationFieldRequest(BaseModel):
    key: str = Field(max_length=128)
    label: str = Field(max_length=256)
    binding: FieldBindingRequest
    field_type: PrimitiveType = PrimitiveType.STRING
    required: bool = True
    help_text: str | None = Field(default=None, max_length=2048)
    placeholder: str | None = Field(default=None, max_length=256)
    ui_group: str | None = Field(default=None, max_length=128)
    default_value: Any = None
    fixed_value: Any = None
    visibility: FieldVisibility = FieldVisibility.VISIBLE
    type_ref: str | None = Field(default=None, max_length=128)
    # Whether a researcher may keep this value and reuse it. Unset means "if
    # it is typed", which is what saving is for.
    saveable: bool | None = None
    source_policy: dict[str, Any] = Field(default_factory=dict)
    delivery_policy: dict[str, Any] = Field(default_factory=dict)


class CreatePublicationRevisionRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=128)
    pipeline_revision_id: uuid.UUID
    title: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4096)
    fields: list[PublicationFieldRequest] = Field(default_factory=list)
    display_metadata: dict[str, Any] = Field(default_factory=dict)


class PublicationRevisionResponse(BaseModel):
    publication_id: uuid.UUID
    revision_id: uuid.UUID
    version: int
    warnings: list[DiagnosticResponse] = Field(default_factory=list)


class PublicationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    status: PublicationStatus
    current_revision_id: uuid.UUID | None = None
    created_at: datetime


class PublicationFieldResponse(BaseModel):
    """One field as a researcher's form should render it.

    The binding is **not** here. Which parameter of which step a field feeds is
    the admin's business; publishing it would tell every reader of the catalog
    how the pipeline is wired, and change nothing they could do about it.
    """

    key: str
    label: str
    field_type: PrimitiveType
    required: bool
    help_text: str | None = None
    placeholder: str | None = None
    ui_group: str | None = None
    default_value: Any = None
    type_ref: str | None = None
    # The resolved type, frozen when this revision was published. What the
    # form renders a control from, and what a saved value is checked against.
    type_schema: dict[str, Any] | None = None
    # Whether a researcher may keep what they fill in here and use it again.
    saveable: bool = False
    source_policy: dict[str, Any] = Field(default_factory=dict)
    order_index: int = 0


class CatalogSummary(BaseModel):
    slug: str
    title: str
    description: str | None = None
    version: int


class CatalogDetail(CatalogSummary):
    publication_id: uuid.UUID
    revision_id: uuid.UUID
    fields: list[PublicationFieldResponse] = Field(default_factory=list)


class CatalogSubmitRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class SubmitRunRequest(BaseModel):
    pipeline_revision_id: uuid.UUID
    values: dict[str, Any] = Field(default_factory=dict)


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: RunStatus
    pipeline_revision_id: uuid.UUID
    requested_by: uuid.UUID
    # What started it. Now that a clock can, "I did not submit this" is a
    # question a researcher will actually ask of their own run list.
    requested_from: RunTrigger
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
    # Whether it is a tree of results rather than one file, so a list can
    # offer the right control without a round trip per row. A directory is
    # retrieved a file at a time; see the artifacts router.
    is_directory: bool = False


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
    # Where it actually landed. The answer to the question a researcher asks
    # next — "so where is it?" — which they would otherwise have to work out
    # from the root's path and a layout nobody has told them.
    target_path: str | None = None
    message: str | None = None
    attempts: int = 0
    next_attempt_at: datetime | None = None
    delivered_at: datetime | None = None


class SubmitRunResponse(BaseModel):
    run_id: uuid.UUID
    task_count: int
    reused: bool
    warnings: list[DiagnosticResponse] = Field(default_factory=list)


# --- task logs -------------------------------------------------------------


class AttemptSummary(BaseModel):
    """One attempt at a task.

    A retry produces a second attempt with its own log and its own exit code,
    and "which attempt was this" is unanswerable without them.
    """

    id: uuid.UUID
    attempt_number: int
    status: AttemptStatus
    exit_code: int | None = None
    worker_id: str | None = None
    image_ref: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Present once the attempt has finished and printed something; the whole
    # log is an ordinary artifact download.
    log_artifact_id: uuid.UUID | None = None


class TaskLogResponse(BaseModel):
    attempt_number: int
    text: str
    bytes_read: int
    bytes_total: int
    # Only the tail is shown. The rest is in the artifact.
    truncated: bool
    # Read from a running task's workspace, so the same request later returns
    # more — a client showing this should keep asking.
    live: bool
    artifact_id: uuid.UUID | None = None
    # Why there is nothing to show, when there is nothing to show.
    message: str | None = None


# --- storage roots ---------------------------------------------------------


class RegisterRootRequest(BaseModel):
    """Allowlist an institutional path, on the caller's stated authority.

    `attestation_note` is required, not optional. The thing being recorded is
    not that somebody ticked a box but *what they checked* — which share, whose
    members, against which access list — and nobody can reconstruct that later.
    """

    id: str = Field(max_length=64)
    label: str = Field(max_length=256)
    root_path: str = Field(max_length=1024)
    attestation_note: str = Field(min_length=1, max_length=512)
    readable: bool = True
    writable: bool = False


class ReinstateRootRequest(BaseModel):
    attestation_note: str = Field(min_length=1, max_length=512)
    readable: bool = True
    writable: bool = False


class RevokeRootRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=512)


class StorageRootResponse(BaseModel):
    id: str
    label: str
    root_path: str
    readable: bool
    writable: bool
    identity_mode: str
    attested_by: uuid.UUID | None = None
    attested_at: datetime | None = None
    attestation_note: str | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    # Whether the path is a directory the platform can see right now. A share
    # that was unmounted is skipped silently when mounts are built, which is
    # correct there and invisible everywhere else.
    visible: bool
    # Whether tasks will actually be given it: visible, readable, attested and
    # not withdrawn. Computed rather than inferred by a client from four
    # fields, so there is one answer to "is this working".
    in_use: bool


# --- artifacts -------------------------------------------------------------


class ArtifactFile(BaseModel):
    """One file inside a directory artifact."""

    path: str
    size_bytes: int
    checksum_sha256: str


class ArtifactDetail(ArtifactSummary):
    run_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    content_type: str | None = None
    is_directory: bool = False
    available: bool = True
    """False once the bytes are gone, while the record of the run remains."""
    unavailable_reason: str | None = None
    files: list[ArtifactFile] = Field(default_factory=list)
    """The manifest of a directory artifact; empty for a single file.

    A large output tree is retrieved a file at a time rather than packaged:
    building a multi-gigabyte archive inside the process that also answers
    every other request is not a thing to do on a click.
    """


# --- uploads ---------------------------------------------------------------


class CreateUploadRequest(BaseModel):
    """Open a resumable upload.

    Both of the optional fields buy something specific. `declared_size_bytes`
    lets the server refuse a file that is too large before a byte of it is
    sent, and makes "finished" checkable rather than assumed.
    `checksum_sha256` is what turns "the bytes arrived" into "the right bytes
    arrived"; without it the platform records the checksum it computed, which
    proves nothing about what left the researcher's machine.
    """

    filename: str = Field(min_length=1, max_length=255)
    declared_size_bytes: int | None = Field(default=None, ge=0)
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class UploadResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: UploadStatus
    # Where the next chunk goes. The whole protocol is this number.
    received_bytes: int
    declared_size_bytes: int | None = None
    checksum_sha256: str | None = None
    # The most one `PATCH` may carry, so a client does not have to fetch the
    # configuration separately to know how to slice a file.
    chunk_max_bytes: int
    expires_at: datetime
    completed_at: datetime | None = None
    artifact_id: uuid.UUID | None = None
    # What to put in the field once the upload is complete.
    reference: str | None = None


# --- saved values ----------------------------------------------------------


class SaveValueRequest(BaseModel):
    """Keep a filled-in value under a name.

    The schema is not sent: it comes from the field being saved from, so a
    client cannot save a value against a type of its own invention.
    """

    field_key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    value: Any = None
    container: Literal["single", "list", "map"] = "single"


class UpdateSavedValueRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    value: Any = None
    # Explicit, because `value: null` is a legitimate thing to store and a
    # rename-only request would otherwise be indistinguishable from one.
    replace_value: bool = False


class SavedValueResponse(BaseModel):
    id: uuid.UUID
    type_key: str
    name: str
    container: str
    value: Any = None
    type_schema: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    # Whether it still fits the field it was offered for, and why not. The
    # value's schema was frozen when it was saved and the field's when the
    # entry was published, so they can legitimately disagree.
    usable: bool = True
    unusable_reason: str | None = None


# --- schedules -------------------------------------------------------------


class CreateScheduleRequest(BaseModel):
    """A schedule names a catalog entry by slug, as a person would.

    The revision that entry currently points at is pinned at creation, so
    re-publishing the entry never silently changes what the schedule runs.
    """

    slug: str = Field(max_length=128)
    title: str = Field(max_length=256)
    values: dict[str, Any] = Field(default_factory=dict)
    rrule: str | None = Field(default=None, max_length=512)
    interval_seconds: int | None = Field(default=None, ge=60)
    timezone: str = Field(default="UTC", max_length=64)
    dst_policy: DstPolicy = DstPolicy.SKIP_NONEXISTENT
    catchup_policy: CatchupPolicy = CatchupPolicy.SKIP_MISSED
    overlap_policy: OverlapPolicy = OverlapPolicy.SKIP
    max_concurrent_runs: int = Field(default=1, ge=1, le=64)
    start_at: datetime | None = None
    end_at: datetime | None = None

    @model_validator(mode="after")
    def _exactly_one_recurrence(self) -> CreateScheduleRequest:
        """The same rule the database enforces, said where a form can show it."""
        if (self.rrule is None) == (self.interval_seconds is None):
            raise ValueError(
                "A schedule has either a recurrence rule or an interval, and exactly one of them."
            )
        return self


class ScheduleSummary(BaseModel):
    id: uuid.UUID
    title: str
    status: ScheduleStatus
    owner_id: uuid.UUID
    slug: str
    entry_title: str
    version: int
    # A schedule pins its revision on purpose. Saying so is what stops it
    # falling quietly behind a re-published entry.
    revision_is_current: bool
    rrule: str | None = None
    interval_seconds: int | None = None
    timezone: str
    dst_policy: DstPolicy
    catchup_policy: CatchupPolicy
    overlap_policy: OverlapPolicy
    max_concurrent_runs: int
    next_fire_at: datetime | None = None
    last_fire_at: datetime | None = None
    last_run_id: uuid.UUID | None = None
    end_at: datetime | None = None
    created_at: datetime


class ScheduleFireResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # The scheduled window, never the wall-clock moment the scheduler woke.
    fire_at: datetime
    outcome: FireOutcome
    run_id: uuid.UUID | None = None
    message: str | None = None


class ScheduleEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_type: str
    created_at: datetime
    run_id: uuid.UUID | None = None
    message: str | None = None


class ScheduleDetail(ScheduleSummary):
    values: dict[str, Any] = Field(default_factory=dict)
    fields: list[PublicationFieldResponse] = Field(default_factory=list)
    fires: list[ScheduleFireResponse] = Field(default_factory=list)
    events: list[ScheduleEventResponse] = Field(default_factory=list)


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

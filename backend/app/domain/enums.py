"""Domain enumerations.

Single source of truth for every constrained string in the system (G37).
The database renders each of these as ``text`` plus a *named* CHECK constraint
rather than a native Postgres enum, because adding a value must be an ordinary
migration and Postgres cannot drop an enum value. ``check_values`` below is what
the SQLAlchemy models and the Alembic migrations consume, so the database and
the API can never disagree about the allowed set.
"""

from __future__ import annotations

from enum import StrEnum


class DomainEnum(StrEnum):
    """A string enum that can render itself as a SQL CHECK constraint."""

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(member.value for member in cls)

    @classmethod
    def check_values(cls) -> str:
        """Render the ``IN (...)`` body for a CHECK constraint."""
        return ", ".join(f"'{value}'" for value in cls.values())


# --- identity -------------------------------------------------------------


class UserRole(DomainEnum):
    ADMIN = "admin"
    RESEARCHER = "researcher"


class ProjectRole(DomainEnum):
    """Per-project membership role.

    Present from the first migration under the tenancy assumption recorded in
    ``ASSUMPTIONS.md`` (ADR 0009 pending). A single default project is seeded,
    so this is inert until multi-project is switched on.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


# --- authoring ------------------------------------------------------------


class LifecycleStatus(DomainEnum):
    """Status of a mutable authoring container (definition, template)."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ValidationStatus(DomainEnum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"


class PublicationStatus(DomainEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class SourceFormat(DomainEnum):
    YAML = "yaml"
    JSON = "json"


# --- inputs and outputs ---------------------------------------------------


class InputSourceMode(DomainEnum):
    """How a file-like input may be supplied.

    ``URL`` is carried from the current system (G15) and is the reason
    ``docs/architecture/security.md`` specifies SSRF controls; the fetch is
    performed by a worker, never by the API process.
    """

    UPLOAD = "upload"
    SHARED = "shared"
    URL = "url"


class DeliveryMode(DomainEnum):
    """Where a declared output is placed once a run succeeds (G16)."""

    DOWNLOAD = "download"
    SHARED = "shared"


class DeliveryStatus(DomainEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"


class ArtifactKind(DomainEnum):
    UPLOAD_INPUT = "upload_input"
    SHARED_INPUT_REFERENCE = "shared_input_reference"
    URL_INPUT = "url_input"
    TASK_OUTPUT = "task_output"
    RUN_OUTPUT_PACKAGE = "run_output_package"
    TASK_LOG = "task_log"
    MANIFEST = "manifest"
    DIAGNOSTIC = "diagnostic"


class Visibility(DomainEnum):
    PRIVATE = "private"
    PROJECT = "project"
    PUBLIC = "public"


class FieldVisibility(DomainEnum):
    VISIBLE = "visible"
    HIDDEN = "hidden"
    READONLY = "readonly"


class UploadStatus(DomainEnum):
    """Chunked upload session state (G14)."""

    OPEN = "open"
    COMPLETED = "completed"
    ABORTED = "aborted"
    EXPIRED = "expired"


# --- execution ------------------------------------------------------------


class RunStatus(DomainEnum):
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(DomainEnum):
    CREATED = "created"
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class AttemptStatus(DomainEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LOST = "lost"
    TIMED_OUT = "timed_out"


class RunTrigger(DomainEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    API = "api"
    ADMIN = "admin"


class TaskClass(DomainEnum):
    """Resource profile for a task.

    Work here spans plate-reader parsing that finishes in under a second and
    RNA-seq alignment that runs for a day. One timeout and one memory limit
    cannot serve both, and the heavy classes must not run concurrently or they
    exhaust the VM.

    The class is a *request*, not a hint: the admission rule in
    ``docs/architecture/execution-model.md`` refuses to start a task whose
    request does not fit the remaining budget, so a task requesting the whole
    budget runs alone. Sequential execution of heavy work falls out of that
    rather than needing a separate mode.
    """

    SMALL = "small"
    STANDARD = "standard"
    LARGE = "large"
    EXCLUSIVE = "exclusive"


class WorkerStatus(DomainEnum):
    STARTING = "starting"
    ACTIVE = "active"
    DRAINING = "draining"
    STOPPED = "stopped"


# --- scheduling -----------------------------------------------------------


class ScheduleStatus(DomainEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class CatchupPolicy(DomainEnum):
    """What to do about windows missed while the scheduler was down."""

    SKIP_MISSED = "skip_missed"
    RUN_ONCE = "run_once"
    RUN_ALL = "run_all"


class OverlapPolicy(DomainEnum):
    """What to do when the previous run of a schedule is still going."""

    SKIP = "skip"
    QUEUE = "queue"
    ALLOW = "allow"


class FireOutcome(DomainEnum):
    CREATED = "created"
    SKIPPED_OVERLAP = "skipped_overlap"
    SKIPPED_CATCHUP = "skipped_catchup"
    FAILED = "failed"


# --- storage and workspaces ----------------------------------------------


class StorageBackend(DomainEnum):
    POSIX = "posix"
    S3 = "s3"


class WorkspaceStatus(DomainEnum):
    ACTIVE = "active"
    PACKAGED = "packaged"
    EXPIRED = "expired"
    DELETED = "deleted"


class RetentionClass(DomainEnum):
    """Drives janitor behaviour independently of a bare expiry timestamp."""

    EPHEMERAL = "ephemeral"
    STANDARD = "standard"
    LONG_TERM = "long_term"
    PERMANENT = "permanent"


class RuntimeEnvironmentStatus(DomainEnum):
    BUILDING = "building"
    AVAILABLE = "available"
    DEPRECATED = "deprecated"
    FAILED = "failed"


# --- primitives -----------------------------------------------------------


class PrimitiveType(DomainEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"
    FILE = "file"
    DIRECTORY = "directory"
    URL = "url"
    OBJECT = "object"
    ARRAY = "array"


FILE_LIKE_TYPES = frozenset({PrimitiveType.FILE, PrimitiveType.DIRECTORY, PrimitiveType.URL})
"""Types that carry a source policy and materialise into the workspace."""

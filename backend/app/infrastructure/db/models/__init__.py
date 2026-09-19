"""All ORM models.

Importing this package registers every table on ``Base.metadata``, which is
what Alembic autogenerate and the test fixtures rely on.
"""

from app.infrastructure.db.base import Base
from app.infrastructure.db.models.artifacts import (
    Artifact,
    RunDelivery,
    SharedStorageRoot,
    Upload,
    Workspace,
)
from app.infrastructure.db.models.authoring import (
    IR_VERSION,
    Pipeline,
    PipelineInput,
    PipelineOutput,
    PipelineRevision,
)
from app.infrastructure.db.models.catalog import (
    Publication,
    PublicationField,
    PublicationRevision,
)
from app.infrastructure.db.models.execution import (
    Run,
    RunFieldValue,
    RunTask,
    RunTaskAttempt,
    RunTaskDependency,
    Worker,
)
from app.infrastructure.db.models.identity import (
    Project,
    ProjectMember,
    Session,
    User,
)
from app.infrastructure.db.models.ops import (
    ArtifactAccessEvent,
    AuditEvent,
    EnvironmentGeneration,
    PackageOperation,
    RuntimeEnvironment,
)
from app.infrastructure.db.models.scheduling import (
    Schedule,
    ScheduleEvent,
    ScheduleFire,
)
from app.infrastructure.db.models.typelib import SavedValue, TypeDefinition

IMMUTABLE_TABLES: tuple[str, ...] = (
    "pipeline_revisions",
    "pipeline_inputs",
    "pipeline_outputs",
    "publication_revisions",
    "publication_fields",
)
"""Tables protected by the immutability trigger (G23).

Anything used to run work is immutable. Enforced in the database so a service
with a deadline cannot quietly bypass it.
"""

__all__ = [
    "IMMUTABLE_TABLES",
    "IR_VERSION",
    "Artifact",
    "ArtifactAccessEvent",
    "AuditEvent",
    "Base",
    "EnvironmentGeneration",
    "PackageOperation",
    "Pipeline",
    "PipelineInput",
    "PipelineOutput",
    "PipelineRevision",
    "Project",
    "ProjectMember",
    "Publication",
    "PublicationField",
    "PublicationRevision",
    "Run",
    "RunDelivery",
    "RunFieldValue",
    "RunTask",
    "RunTaskAttempt",
    "RunTaskDependency",
    "RuntimeEnvironment",
    "SavedValue",
    "Schedule",
    "ScheduleEvent",
    "ScheduleFire",
    "Session",
    "SharedStorageRoot",
    "TypeDefinition",
    "Upload",
    "User",
    "Worker",
    "Workspace",
]

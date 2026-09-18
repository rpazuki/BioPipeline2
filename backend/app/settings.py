"""Application configuration.

ADR 0010 is open. This build implements the recommended option (G11):

* **Precedence** is defaults, then an optional YAML file, then environment
  variables. Environment always wins, so a deployment can override anything
  without editing a file.
* **Validation at boot.** A missing or malformed required setting raises here,
  at import time, rather than at the first request that needs it.
* **Secrets are separate.** They are read only from the environment, never
  from the YAML file, so the config file can be committed and reviewed.
* **The frontend reads its settings at runtime**, from a public endpoint built
  out of :meth:`Settings.public`, so one image can serve several deployments.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_PATH_ENV = "BP_CONFIG_FILE"
ENV_PREFIX = "BP_"


def _load_config_file() -> dict[str, Any]:
    """Read the optional YAML layer.

    Environment profiles keep the shape the current system uses: a ``shared``
    block plus a per-environment block that overrides it.
    """
    raw_path = os.environ.get(CONFIG_PATH_ENV)
    if not raw_path:
        return {}
    path = Path(raw_path)
    if not path.is_file():
        raise FileNotFoundError(f"{CONFIG_PATH_ENV} points at {path}, which does not exist")
    document = yaml.safe_load(path.read_text()) or {}
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a mapping at the top level")

    environment = os.environ.get(
        f"{ENV_PREFIX}ENVIRONMENT", document.get("environment", "development")
    )
    merged: dict[str, Any] = dict(document.get("shared") or {})
    merged.update(document.get(str(environment)) or {})
    merged.pop("shared", None)
    return merged


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_nested_delimiter="__",
        extra="forbid",
        frozen=True,
    )

    # --- deployment ---
    environment: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "BioPipeline2"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_prefix: str = "/api/v1"
    # Every asset, redirect, and cookie path must respect this. Required from
    # the beginning per document 06, not retrofitted.
    base_path: str = ""

    # --- database ---
    database_url: PostgresDsn = Field(
        default=PostgresDsn(
            "postgresql+psycopg://biopipeline:biopipeline@localhost:5432/biopipeline2"
        )
    )
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_pool_max_overflow: int = Field(default=5, ge=0, le=100)
    database_statement_timeout_ms: int = Field(default=30_000, ge=1000)

    # --- security ---
    session_cookie_name: str = "bp_session"
    session_ttl_hours: int = Field(default=168, ge=1)
    session_idle_timeout_hours: int = Field(default=24, ge=1)
    secure_cookies: bool = True
    cookie_samesite: Literal["strict", "lax", "none"] = "lax"
    # Cookie auth plus state-changing requests needs an explicit answer (G43).
    csrf_protection: bool = True
    cors_origins: list[str] = Field(default_factory=list)
    login_rate_limit_per_minute: int = Field(default=10, ge=1)
    login_lockout_threshold: int = Field(default=10, ge=1)
    login_lockout_minutes: int = Field(default=15, ge=1)

    # --- execution ---
    container_runtime: Literal["docker", "podman"] = "docker"
    task_default_image: str = "biopipeline2/task-base:latest"
    task_default_cpu_millicores: int = Field(default=2000, gt=0)
    task_default_memory_bytes: int = Field(default=4 * 1024**3, gt=0)
    # Tasks range from seconds to days, so one profile cannot serve both.
    # A pipeline revision selects a class; these are the class defaults.
    task_default_wall_time_seconds: int = Field(default=6 * 3600, gt=0)
    task_max_wall_time_seconds: int = Field(default=14 * 24 * 3600, gt=0)

    # --- admission control ---
    #
    # The total resource the workers on this host may commit at once. A task
    # is claimed only if its request fits the unused remainder, so a task
    # requesting the whole budget runs alone. This is how heavy work
    # (RNA-seq alignment, FBA sweeps) is kept sequential without starving
    # short tasks or needing a separate serial queue.
    #
    # Set these below the host's real capacity, leaving headroom for the API,
    # the database and the operating system.
    worker_budget_cpu_millicores: int = Field(default=4000, gt=0)
    worker_budget_memory_bytes: int = Field(default=12 * 1024**3, gt=0)
    worker_max_concurrent_tasks: int = Field(default=4, ge=1)

    # Packaging a multi-gigabyte output set into one archive is neither fast
    # nor useful. Above this, the janitor writes a manifest and the UI offers
    # per-file download instead.
    package_outputs_max_total_bytes: int = Field(default=2 * 1024**3, gt=0)
    # A lease must be renewed during execution, never sized to outlast a task.
    task_lease_seconds: int = Field(default=120, ge=30)
    task_heartbeat_seconds: int = Field(default=30, ge=5)
    task_cancel_grace_seconds: int = Field(default=30, ge=1)
    # What a task printed, kept for every outcome. The *tail* is kept when a
    # log is bigger than this: a stack trace is at the end, and so is whatever
    # the tool said before it stopped. The workspace copy is uncapped and goes
    # with the workspace when retention reclaims it.
    task_log_max_bytes: int = Field(default=32 * 1024**2, gt=0)
    # Logs outlive outputs on purpose: a failure is often diagnosed long after
    # the results it did not produce were cleaned up.
    task_log_retention_days: int = Field(default=365, ge=1)
    # After this many lease expiries without a clean outcome, stop retrying.
    task_poison_limit: int = Field(default=3, ge=1)
    worker_concurrency: int = Field(default=1, ge=1)

    # --- scheduling ---
    #
    # Several schedulers may run at once; correctness comes from the
    # `schedule_fires` unique constraint, not from there being one of them.
    scheduler_poll_seconds: int = Field(default=30, ge=5)
    # How late a window may be and still count as on time. Below this the
    # catchup policy never applies, which is why a healthy deployment never
    # notices which policy its schedules chose. Sized above the poll interval
    # so an ordinary tick is never treated as an outage.
    scheduler_misfire_grace_seconds: int = Field(default=120, ge=1)
    # The most runs one schedule may create in a single tick while catching
    # up. A week of downtime on an hourly schedule owes 168 runs; creating
    # them all in one transaction would be one enormous write and would starve
    # every other schedule behind it.
    scheduler_max_catchup_runs: int = Field(default=25, ge=1)
    scheduler_batch_size: int = Field(default=100, ge=1)

    # --- delivery ---
    #
    # Its own process (`app.workers.courier`), because a delivery is a copy of
    # arbitrarily many gigabytes and everything else that could host it -- a
    # worker's execution slot, the reaper's lease reclamation -- has to stay
    # responsive while it runs.
    delivery_poll_seconds: int = Field(default=30, ge=5)
    delivery_batch_size: int = Field(default=20, ge=1)
    # After this many attempts a delivery stops retrying and waits for a
    # person. The failures that survive five tries are configuration, not
    # weather.
    delivery_max_attempts: int = Field(default=5, ge=1)
    # How long one attempt may hold a delivery before another courier may take
    # it. Long, because the thing being leased is a copy that can legitimately
    # take hours; the cost of the length is how long a crashed courier's
    # delivery sits before somebody else picks it up.
    delivery_lease_seconds: int = Field(default=2 * 3600, ge=60)
    # Base of the exponential backoff between attempts.
    delivery_retry_seconds: int = Field(default=60, ge=1)

    # --- storage ---
    artifact_root: Path = Path("/var/lib/biopipeline2/artifacts")
    workspace_root: Path = Path("/var/lib/biopipeline2/workspaces")
    # Where component libraries are read from (ADR 0026). The only directory a
    # `library:` reference may resolve inside; the loader refuses anything that
    # escapes it, because that reference is author-supplied text.
    component_library_root: Path = Path("/var/lib/biopipeline2/components")
    # Directories holding the science libraries tasks import (ADR 0028).
    # Mounted read-only into every task container at their own path and
    # prepended to PYTHONPATH. Empty means a task can import only what the
    # image itself carries, which is the runner and the standard library.
    task_library_paths: list[Path] = Field(default_factory=list)
    workspace_default_quota_bytes: int = Field(default=100 * 1024**3, gt=0)
    upload_chunk_max_bytes: int = Field(default=64 * 1024**2, gt=0)
    upload_max_total_bytes: int = Field(default=500 * 1024**3, gt=0)
    upload_expiry_hours: int = Field(default=48, ge=1)

    # --- governance ---
    # ADR 0001 is open and blocking. The safe default is on: relaxing later is
    # cheap, retrofitting read auditing is not.
    audit_artifact_reads: bool = True
    default_retention_days: int = Field(default=90, ge=1)

    # --- secrets: environment only, never the YAML layer ---
    session_secret: SecretStr = SecretStr("dev-only-insecure-change-me")

    @field_validator("base_path")
    @classmethod
    def _normalise_base_path(cls, value: str) -> str:
        if not value:
            return ""
        if not value.startswith("/"):
            raise ValueError("base_path must start with '/'")
        return value.rstrip("/")

    @model_validator(mode="after")
    def _production_is_not_insecure(self) -> Settings:
        """Fail at boot rather than serving production with dev defaults."""
        if self.environment != "production":
            return self
        problems: list[str] = []
        if self.session_secret.get_secret_value() == "dev-only-insecure-change-me":
            problems.append("BP_SESSION_SECRET is still the development default")
        if not self.secure_cookies:
            problems.append("BP_SECURE_COOKIES must be true in production")
        if not self.csrf_protection:
            problems.append("BP_CSRF_PROTECTION must be true in production")
        if "*" in self.cors_origins:
            problems.append("BP_CORS_ORIGINS must not contain '*' in production")
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self

    def public(self) -> dict[str, Any]:
        """The subset the browser may see.

        An allowlist, not a denylist: a new secret setting is private by
        default because it simply is not named here.
        """
        return {
            "app_name": self.app_name,
            "environment": self.environment,
            "api_prefix": self.api_prefix,
            "base_path": self.base_path,
            "upload_chunk_max_bytes": self.upload_chunk_max_bytes,
            "upload_max_total_bytes": self.upload_max_total_bytes,
        }

    def redacted(self) -> dict[str, Any]:
        """The effective configuration, safe to log at boot."""
        data = self.model_dump(mode="json")
        for key in list(data):
            if isinstance(getattr(self, key, None), SecretStr):
                data[key] = "***"
        data["database_url"] = str(self.database_url).split("@")[-1]
        return data


def load_settings(**overrides: Any) -> Settings:
    """Build settings from defaults, the YAML layer, then the environment."""
    return Settings(**{**_load_config_file(), **overrides})

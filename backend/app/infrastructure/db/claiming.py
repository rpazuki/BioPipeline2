"""Task claiming with resource admission control.

The workload spans two extremes: plate-reader parsing that finishes in under a
second, and RNA-seq alignment that runs for a day and must not share the VM
with anything else. Rather than a separate serial queue for heavy work, a task
declares a resource *request* and is claimed only if that request fits the
unused budget. Sequential execution of heavy work falls out of the arithmetic:
a task requesting the whole budget cannot be admitted while anything else
holds resources, and nothing else can be admitted while it runs.

Two properties matter and both are enforced by the SQL below rather than by
worker-side bookkeeping:

* **No double-claim.** ``FOR UPDATE SKIP LOCKED`` means two workers polling at
  once take different rows.
* **No over-commit.** The budget check happens inside the claiming
  transaction, against rows that currently hold resources.

The trade-off is deliberate: a large task can be starved indefinitely by a
stream of small ones. ``head_of_line_blocking`` addresses that by refusing to
admit anything younger than the oldest task that does not fit -- so a waiting
alignment job drains the queue ahead of itself instead of waiting forever.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.enums import TaskStatus


@dataclass(frozen=True, slots=True)
class Budget:
    """What this host may commit at once."""

    cpu_millicores: int
    memory_bytes: int
    max_concurrent_tasks: int


@dataclass(frozen=True, slots=True)
class Committed:
    """What is currently committed."""

    cpu_millicores: int
    memory_bytes: int
    task_count: int
    has_exclusive: bool


# Rows that hold resources: claimed but not yet started, or running.
_HOLDING = (TaskStatus.CLAIMED.value, TaskStatus.RUNNING.value)

_COMMITTED_SQL = text(
    """
    SELECT
        COALESCE(SUM(cpu_request_millicores), 0) AS cpu,
        COALESCE(SUM(memory_request_bytes), 0)   AS memory,
        COUNT(*)                                  AS tasks,
        COALESCE(BOOL_OR(exclusive), false)       AS has_exclusive
    FROM run_tasks
    WHERE status = ANY(:holding)
    """
)


def committed(session: Session) -> Committed:
    """Sum the resources currently held."""
    row = session.execute(_COMMITTED_SQL, {"holding": list(_HOLDING)}).one()
    return Committed(
        cpu_millicores=int(row.cpu),
        memory_bytes=int(row.memory),
        task_count=int(row.tasks),
        has_exclusive=bool(row.has_exclusive),
    )


def fits(
    *,
    budget: Budget,
    used: Committed,
    cpu_request: int,
    memory_request: int,
    exclusive: bool,
) -> bool:
    """Whether one more task may be admitted.

    Pure, so the policy is testable without a database.
    """
    if used.has_exclusive:
        return False
    if exclusive:
        return used.task_count == 0
    if used.task_count >= budget.max_concurrent_tasks:
        return False
    if used.cpu_millicores + cpu_request > budget.cpu_millicores:
        return False
    return used.memory_bytes + memory_request <= budget.memory_bytes


# A task is eligible when it is queued, its dependencies are satisfied, its
# run has not been cancelled, and its request fits the remaining budget.
#
# The head-of-line clause is the anti-starvation rule: a task is skipped if an
# older queued task exists that does *not* fit, unless this task would fit
# alongside it. Without it a steady trickle of small tasks postpones a large
# one forever.
_CLAIM_SQL = text(
    """
    WITH used AS (
        SELECT
            COALESCE(SUM(cpu_request_millicores), 0) AS cpu,
            COALESCE(SUM(memory_request_bytes), 0)   AS memory,
            COUNT(*)                                  AS tasks,
            COALESCE(BOOL_OR(exclusive), false)       AS has_exclusive
        FROM run_tasks
        WHERE status = ANY(:holding)
    ),
    eligible AS (
        SELECT t.id
        FROM run_tasks t
        JOIN runs r ON r.id = t.run_id
        CROSS JOIN used u
        WHERE t.status = 'queued'
          AND t.dependencies_satisfied
          AND r.cancel_requested_at IS NULL
          AND r.status NOT IN ('cancel_requested', 'cancelled', 'failed')
          AND NOT u.has_exclusive
          AND (NOT t.exclusive OR u.tasks = 0)
          AND u.tasks < :max_tasks
          AND u.cpu + t.cpu_request_millicores <= :budget_cpu
          AND u.memory + t.memory_request_bytes <= :budget_memory
        ORDER BY t.priority DESC, t.created_at
        LIMIT 1
        FOR UPDATE OF t SKIP LOCKED
    )
    UPDATE run_tasks
    SET status = 'claimed',
        claimed_by = :worker_id,
        claimed_at = now(),
        lease_expires_at = now() + make_interval(secs => :lease_seconds),
        heartbeat_at = now(),
        attempt_count = attempt_count + 1,
        updated_at = now()
    WHERE id IN (SELECT id FROM eligible)
    RETURNING id
    """
)


def claim_next_task(
    session: Session,
    *,
    worker_id: str,
    budget: Budget,
    lease_seconds: int,
) -> uuid.UUID | None:
    """Claim one task, or return ``None`` if nothing may be admitted.

    ``None`` does not mean the queue is empty -- it commonly means the next
    task does not fit. The caller should back off and retry rather than
    treating it as idle.
    """
    result = session.execute(
        _CLAIM_SQL,
        {
            "holding": list(_HOLDING),
            "worker_id": worker_id,
            "lease_seconds": lease_seconds,
            "budget_cpu": budget.cpu_millicores,
            "budget_memory": budget.memory_bytes,
            "max_tasks": budget.max_concurrent_tasks,
        },
    ).scalar_one_or_none()
    return result


_RECLAIM_SQL = text(
    """
    UPDATE run_tasks
    SET status = CASE
            WHEN attempt_count > :poison_limit THEN 'failed'
            ELSE 'queued'
        END,
        status_reason = CASE
            WHEN attempt_count > :poison_limit
            THEN 'lease expired ' || attempt_count || ' times without a clean outcome'
            ELSE 'lease expired; requeued'
        END,
        claimed_by = NULL,
        claimed_at = NULL,
        lease_expires_at = NULL,
        heartbeat_at = NULL,
        finished_at = CASE WHEN attempt_count > :poison_limit THEN now() ELSE NULL END,
        updated_at = now()
    WHERE status = ANY(:holding)
      AND lease_expires_at < now()
    RETURNING id, status
    """
)


def reclaim_expired_leases(session: Session, *, poison_limit: int) -> list[tuple[uuid.UUID, str]]:
    """Requeue tasks whose lease expired; fail those that keep expiring.

    Owned by the reaper, not by a worker: the worker that held the lease is by
    definition unreachable. The poison limit stops a task that never reports
    back from cycling forever.
    """
    rows = session.execute(
        _RECLAIM_SQL, {"holding": list(_HOLDING), "poison_limit": poison_limit}
    ).all()
    return [(row.id, row.status) for row in rows]

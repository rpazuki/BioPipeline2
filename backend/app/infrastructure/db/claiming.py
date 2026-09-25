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
* **No over-commit.** The budget is an *aggregate* predicate, and a row lock
  cannot protect one. Two transactions each compute what is committed from
  their own snapshot, in which the other's claim does not exist yet, and
  ``SKIP LOCKED`` is deliberately sending them at different rows -- so both
  can pass the same budget check and both commit. That is write skew, and it
  was real: two claimers each took a task requesting the entire budget and
  the host ended up committed to twice its CPU.

  Admission is therefore serialised by an advisory lock held for the length
  of the claiming transaction. One decision at a time, deployment-wide. The
  lock is *tried*, not waited for: a worker that finds another claim in
  flight is told there is nothing for it and backs off, which is already the
  contract for "nothing fits". Waiting would be the more obvious choice and
  the wrong one -- it makes the claim block on a transaction it knows
  nothing about, and any caller that holds its claim open (a test, a future
  batch claimer) would deadlock rather than merely miss a turn.

Fairness is bounded rather than absolute: see the commentary above
``_CLAIM_SQL``. A task that cannot fit backfills around for at most
``Budget.starvation_grace_seconds``, then reserves capacity.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.enums import TaskStatus


@dataclass(frozen=True, slots=True)
class Budget:
    """What this host may commit at once, and how fairness is bounded."""

    cpu_millicores: int
    memory_bytes: int
    max_concurrent_tasks: int
    # How long a task that does not fit may be passed over before it reserves
    # capacity. Until then, smaller tasks backfill freely; after it, nothing
    # is admitted that would not also fit alongside the waiting task.
    starvation_grace_seconds: int = 900


@dataclass(frozen=True, slots=True)
class Committed:
    """What is currently committed."""

    cpu_millicores: int
    memory_bytes: int
    task_count: int
    has_exclusive: bool


# Rows that hold resources: claimed but not yet started, or running.
_HOLDING = (TaskStatus.CLAIMED.value, TaskStatus.RUNNING.value)

# The key every claim transaction locks before deciding. Arbitrary, but it
# must not collide with another advisory-lock user in the same database, so
# it is written down here rather than computed somewhere.
#
# Deployment-wide rather than per host, because the budget this SQL enforces
# is deployment-wide: `used` sums every task holding resources, whichever
# host holds it. A second execution host would need a budget row per host and
# a lock per host, and both halves have to change together -- a per-host lock
# over a global sum would serialise nothing.
ADMISSION_LOCK_KEY = 4_242_001

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
# Fairness: admission control alone lets a steady trickle of small tasks
# postpone a large one forever. An immediate global barrier -- refusing
# everything younger than the oldest task that does not fit -- fixes that but
# stalls all short work behind a task waiting for a day-long job to finish,
# wasting capacity that is genuinely free.
#
# So the policy is bounded backfill, then reservation:
#
#   * A queued task that does not currently fit begins to age.
#   * While its age is under `starvation_grace_seconds`, smaller tasks may
#     backfill around it.
#   * Once it exceeds the grace period it becomes a *reserving* task, and
#     only reserving tasks are admitted until it starts.
#
# The invariant this buys: a task waits at most the grace period plus the
# runtime of the tasks already holding resources when it began reserving. It
# is not starvation-free in the strict sense -- nothing can be, while a
# day-long task holds the budget -- but the wait is bounded by something
# other than the arrival rate of other work.
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
    reserving AS (
        -- Tasks that have waited past the grace period without fitting. Their
        -- requests are reserved against the budget. Selected from the base
        -- table, not a CTE, so `eligible` can still take a row lock.
        SELECT
            COALESCE(SUM(t.cpu_request_millicores), 0) AS cpu,
            COALESCE(SUM(t.memory_request_bytes), 0)   AS memory,
            COUNT(*)                                    AS tasks,
            COALESCE(BOOL_OR(t.exclusive), false)       AS has_exclusive
        FROM run_tasks t
        JOIN runs r ON r.id = t.run_id
        CROSS JOIN used u
        WHERE t.status = 'queued'
          AND t.dependencies_satisfied
          AND r.cancel_requested_at IS NULL
          AND r.status NOT IN ('cancel_requested', 'cancelled', 'failed')
          AND t.created_at < now() - make_interval(secs => :grace_seconds)
          AND (
              u.cpu + t.cpu_request_millicores > :budget_cpu
              OR u.memory + t.memory_request_bytes > :budget_memory
              OR u.tasks >= :max_tasks
              OR (t.exclusive AND u.tasks > 0)
          )
    ),
    eligible AS (
        SELECT t.id
        FROM run_tasks t
        JOIN runs r ON r.id = t.run_id
        CROSS JOIN used u
        CROSS JOIN reserving res
        WHERE t.status = 'queued'
          AND t.dependencies_satisfied
          AND r.cancel_requested_at IS NULL
          AND r.status NOT IN ('cancel_requested', 'cancelled', 'failed')
          AND NOT u.has_exclusive
          AND (NOT t.exclusive OR u.tasks = 0)
          AND u.tasks < :max_tasks
          AND u.cpu + t.cpu_request_millicores <= :budget_cpu
          AND u.memory + t.memory_request_bytes <= :budget_memory
          -- Once anything is reserving, only reserving tasks are admitted.
          --
          -- A "fits alongside the reservation" exemption looks attractive but
          -- is unreachable: if used + reserved + candidate fits the budget,
          -- then used + reserved fits too, so the reserving task would have
          -- been admitted and would not be reserving. The barrier is strict
          -- by arithmetic, not by choice.
          AND (
              res.tasks = 0
              OR t.created_at < now() - make_interval(secs => :grace_seconds)
          )
        ORDER BY
            -- Reserving tasks first, then priority, then age.
            (t.created_at < now() - make_interval(secs => :grace_seconds)) DESC,
            t.priority DESC,
            t.created_at
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

    The advisory lock is what makes the budget true under concurrency; see
    the module docstring. Not acquiring it is an ordinary outcome and not an
    error: another claim is deciding right now, and this worker backs off
    exactly as it would if nothing fitted.
    """
    mine = session.execute(
        text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": ADMISSION_LOCK_KEY}
    ).scalar_one()
    if not mine:
        return None
    result = session.execute(
        _CLAIM_SQL,
        {
            "holding": list(_HOLDING),
            "worker_id": worker_id,
            "lease_seconds": lease_seconds,
            "budget_cpu": budget.cpu_millicores,
            "budget_memory": budget.memory_bytes,
            "max_tasks": budget.max_concurrent_tasks,
            "grace_seconds": budget.starvation_grace_seconds,
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

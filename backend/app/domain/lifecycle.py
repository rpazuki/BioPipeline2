"""Run, task, and attempt state machines.

Document 03 lists the statuses but not the transitions, not who owns each one,
and not the terminal-state rule. All three are encoded here so that the rules
live in one testable place rather than being re-implemented by the worker, the
reaper, the scheduler, and the API.

Two rules are load-bearing:

* **Terminal states are final.** ``succeeded``, ``failed``, and ``cancelled``
  are absorbing. Nothing may reopen them (G23).
* **Transitions have owners.** ``cancel_requested -> cancelled`` is owned by the
  reaper, not the worker, because the worker holding the task may already be
  gone. Encoding the owner lets a caller assert it holds the right role (G52).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from app.domain.enums import AttemptStatus, RunStatus, TaskStatus
from app.domain.errors import InvalidTransition, TerminalStateModified


class Actor(StrEnum):
    """Which process is permitted to drive a transition."""

    API = "api"
    WORKER = "worker"
    SCHEDULER = "scheduler"
    REAPER = "reaper"
    ORCHESTRATOR = "orchestrator"


@dataclass(frozen=True, slots=True)
class Transition:
    source: str
    target: str
    actors: frozenset[Actor]
    note: str = ""


class StateMachine:
    """An explicit transition table with terminal-state protection."""

    def __init__(self, entity: str, transitions: Iterable[Transition], terminal: Iterable[str]):
        self.entity = entity
        self.terminal = frozenset(terminal)
        self._table: dict[tuple[str, str], Transition] = {}
        for transition in transitions:
            if transition.source in self.terminal:
                raise ValueError(
                    f"{entity}: '{transition.source}' is terminal and cannot have an outgoing "
                    f"transition to '{transition.target}'."
                )
            self._table[(transition.source, transition.target)] = transition

    def can(self, source: str, target: str, actor: Actor | None = None) -> bool:
        transition = self._table.get((source, target))
        if transition is None:
            return False
        return actor is None or actor in transition.actors

    def check(self, source: str, target: str, actor: Actor | None = None) -> None:
        """Raise unless the transition is legal for ``actor``."""
        if source in self.terminal:
            raise TerminalStateModified(self.entity, source)
        transition = self._table.get((source, target))
        if transition is None:
            raise InvalidTransition(self.entity, source, target)
        if actor is not None and actor not in transition.actors:
            raise InvalidTransition(self.entity, source, target)

    def is_terminal(self, state: str) -> bool:
        return state in self.terminal

    def targets(self, source: str) -> frozenset[str]:
        return frozenset(target for (src, target) in self._table if src == source)

    def reachable_from_start(self, start: str) -> frozenset[str]:
        """Every state reachable from ``start``. Used to prove no state is orphaned."""
        seen: set[str] = {start}
        frontier = [start]
        while frontier:
            current = frontier.pop()
            for target in self.targets(current):
                if target not in seen:
                    seen.add(target)
                    frontier.append(target)
        return frozenset(seen)


_ALL = frozenset(Actor)
_WORKER = frozenset({Actor.WORKER})
_REAPER = frozenset({Actor.REAPER})
_API = frozenset({Actor.API})
_ORCH = frozenset({Actor.ORCHESTRATOR})


RUN_MACHINE = StateMachine(
    entity="Run",
    terminal=(RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED),
    transitions=[
        Transition(RunStatus.QUEUED, RunStatus.RUNNING, _ORCH | _WORKER, "first task starts"),
        Transition(
            RunStatus.QUEUED,
            RunStatus.BLOCKED,
            _ORCH,
            "quota, dependency, or resource prevents progress",
        ),
        Transition(RunStatus.QUEUED, RunStatus.CANCEL_REQUESTED, _API),
        Transition(
            RunStatus.QUEUED, RunStatus.FAILED, _ORCH, "materialisation failed before any task ran"
        ),
        # A short run can finish entirely between two orchestrator passes, so
        # it never looks `running` to anyone. Without these edges the
        # aggregate would be right and the transition refused, leaving the run
        # stuck at `queued` with all its work done.
        Transition(
            RunStatus.QUEUED,
            RunStatus.SUCCEEDED,
            _ORCH,
            "every task finished before the run was next examined",
        ),
        Transition(
            RunStatus.QUEUED,
            RunStatus.CANCELLED,
            _ORCH | _REAPER,
            "every task was cancelled before any started",
        ),
        Transition(RunStatus.RUNNING, RunStatus.BLOCKED, _ORCH),
        Transition(RunStatus.RUNNING, RunStatus.CANCEL_REQUESTED, _API),
        Transition(RunStatus.RUNNING, RunStatus.SUCCEEDED, _ORCH),
        Transition(RunStatus.RUNNING, RunStatus.FAILED, _ORCH),
        Transition(
            RunStatus.BLOCKED, RunStatus.QUEUED, _ORCH | _REAPER, "blocking condition cleared"
        ),
        Transition(RunStatus.BLOCKED, RunStatus.CANCEL_REQUESTED, _API),
        Transition(RunStatus.BLOCKED, RunStatus.FAILED, _ORCH),
        # Only the reaper closes out a cancellation: the worker that owned the
        # running task may be dead, and a cancel must still converge (G52).
        Transition(
            RunStatus.CANCEL_REQUESTED,
            RunStatus.CANCELLED,
            _REAPER | _ORCH,
            "all tasks stopped; reaper owns convergence",
        ),
        Transition(
            RunStatus.CANCEL_REQUESTED,
            RunStatus.SUCCEEDED,
            _ORCH,
            "race: every task finished before the cancel landed",
        ),
        Transition(
            RunStatus.CANCEL_REQUESTED,
            RunStatus.FAILED,
            _ORCH,
            "race: a task failed before the cancel landed",
        ),
    ],
)
"""Run lifecycle.

Note what is *absent*: there is no ``expired`` run status. A run whose outputs
were cleaned still succeeded, so expiry is recorded on artifacts and workspaces
rather than overwriting the run outcome (document 03 review addition).
"""


TASK_MACHINE = StateMachine(
    entity="Task",
    terminal=(TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.SKIPPED),
    transitions=[
        Transition(TaskStatus.CREATED, TaskStatus.QUEUED, _ORCH, "dependencies satisfied"),
        Transition(
            TaskStatus.CREATED, TaskStatus.SKIPPED, _ORCH, "workflow logic skipped the branch"
        ),
        Transition(TaskStatus.CREATED, TaskStatus.CANCELLED, _ORCH | _REAPER),
        Transition(
            TaskStatus.QUEUED,
            TaskStatus.CLAIMED,
            _WORKER,
            "FOR UPDATE SKIP LOCKED claim; sets a lease",
        ),
        Transition(TaskStatus.QUEUED, TaskStatus.CANCELLED, _ORCH | _REAPER),
        Transition(TaskStatus.CLAIMED, TaskStatus.RUNNING, _WORKER, "container started"),
        # A lease that expires between claim and start returns the task to the
        # pool. The reaper owns this because the claiming worker is unreachable.
        Transition(TaskStatus.CLAIMED, TaskStatus.QUEUED, _REAPER, "lease expired before start"),
        Transition(TaskStatus.CLAIMED, TaskStatus.CANCELLED, _WORKER | _REAPER),
        Transition(TaskStatus.RUNNING, TaskStatus.SUCCEEDED, _WORKER),
        Transition(
            TaskStatus.RUNNING,
            TaskStatus.RETRY_WAIT,
            _WORKER | _REAPER,
            "attempt failed, retries remain",
        ),
        Transition(
            TaskStatus.RUNNING,
            TaskStatus.FAILED,
            _WORKER | _REAPER,
            "attempt failed, no retries remain",
        ),
        Transition(
            TaskStatus.RUNNING,
            TaskStatus.QUEUED,
            _REAPER,
            "lease expired mid-run; attempt marked lost",
        ),
        Transition(TaskStatus.RUNNING, TaskStatus.CANCELLED, _WORKER | _REAPER),
        Transition(TaskStatus.RETRY_WAIT, TaskStatus.QUEUED, _ORCH | _REAPER, "backoff elapsed"),
        Transition(TaskStatus.RETRY_WAIT, TaskStatus.CANCELLED, _ORCH | _REAPER),
        Transition(TaskStatus.RETRY_WAIT, TaskStatus.FAILED, _REAPER, "poison-task limit reached"),
    ],
)

ATTEMPT_MACHINE = StateMachine(
    entity="TaskAttempt",
    terminal=(
        AttemptStatus.SUCCEEDED,
        AttemptStatus.FAILED,
        AttemptStatus.CANCELLED,
        AttemptStatus.LOST,
        AttemptStatus.TIMED_OUT,
    ),
    transitions=[
        Transition(AttemptStatus.RUNNING, AttemptStatus.SUCCEEDED, _WORKER),
        Transition(AttemptStatus.RUNNING, AttemptStatus.FAILED, _WORKER),
        Transition(AttemptStatus.RUNNING, AttemptStatus.CANCELLED, _WORKER | _REAPER),
        Transition(AttemptStatus.RUNNING, AttemptStatus.TIMED_OUT, _WORKER | _REAPER),
        # The worker vanished. The reaper closes the attempt so the task can be
        # retried without waiting for a process that will never report back.
        Transition(
            AttemptStatus.RUNNING,
            AttemptStatus.LOST,
            _REAPER,
            "lease expired; worker never reported",
        ),
    ],
)


def run_status_for_tasks(task_statuses: Iterable[str], *, cancel_requested: bool) -> str:
    """Derive the run status implied by its tasks.

    The orchestrator calls this after every task transition. Kept pure and
    total so the aggregation rule is testable without a database.
    """
    statuses = list(task_statuses)
    if not statuses:
        return RunStatus.CANCEL_REQUESTED if cancel_requested else RunStatus.QUEUED

    terminal = {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.SKIPPED}
    all_terminal = all(status in terminal for status in statuses)

    if all_terminal:
        if any(status == TaskStatus.FAILED for status in statuses):
            return RunStatus.FAILED
        if any(status == TaskStatus.CANCELLED for status in statuses):
            return RunStatus.CANCELLED
        return RunStatus.SUCCEEDED

    if cancel_requested:
        return RunStatus.CANCEL_REQUESTED

    # A run has started if anything is in flight *or has already finished*.
    # Counting only in-flight tasks reports a run as `queued` between a task
    # completing and the next being claimed -- and since the machine has no
    # `running -> queued` edge, the run would then be stuck.
    started = {
        TaskStatus.CLAIMED,
        TaskStatus.RUNNING,
        TaskStatus.RETRY_WAIT,
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.SKIPPED,
    }
    if any(status in started for status in statuses):
        return RunStatus.RUNNING
    return RunStatus.QUEUED

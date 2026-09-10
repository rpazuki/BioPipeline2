"""Tests for the run, task, and attempt state machines.

These encode the two rules the whole execution model rests on: terminal states
are absorbing (G23), and each transition has an owning actor (G52).
"""

from __future__ import annotations

import pytest

from app.domain.enums import AttemptStatus, RunStatus, TaskStatus
from app.domain.errors import InvalidTransition, TerminalStateModified
from app.domain.lifecycle import (
    ATTEMPT_MACHINE,
    RUN_MACHINE,
    TASK_MACHINE,
    Actor,
    StateMachine,
    Transition,
    run_status_for_tasks,
)

# --- structural properties ------------------------------------------------


def test_every_run_status_is_reachable():
    """A status nothing can reach is dead vocabulary."""
    reachable = RUN_MACHINE.reachable_from_start(RunStatus.QUEUED)
    assert reachable == set(RunStatus.values())


def test_every_task_status_is_reachable():
    reachable = TASK_MACHINE.reachable_from_start(TaskStatus.CREATED)
    assert reachable == set(TaskStatus.values())


def test_no_run_status_is_both_terminal_and_has_an_exit():
    for state in RUN_MACHINE.terminal:
        assert RUN_MACHINE.targets(state) == frozenset()


def test_a_machine_refuses_an_outgoing_edge_from_a_terminal_state():
    with pytest.raises(ValueError, match="terminal"):
        StateMachine(
            entity="Bad",
            terminal=["done"],
            transitions=[Transition("done", "open", frozenset({Actor.API}))],
        )


def test_there_is_no_expired_run_status():
    """Expiry is an artifact fact, not a run outcome (doc 03 review addition)."""
    assert "expired" not in RunStatus.values()


# --- terminal protection --------------------------------------------------


@pytest.mark.parametrize("state", [RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED])
def test_a_terminal_run_cannot_be_reopened(state: str):
    with pytest.raises(TerminalStateModified):
        RUN_MACHINE.check(state, RunStatus.RUNNING, Actor.ORCHESTRATOR)


def test_a_terminal_task_cannot_be_requeued_even_by_the_reaper():
    with pytest.raises(TerminalStateModified):
        TASK_MACHINE.check(TaskStatus.SUCCEEDED, TaskStatus.QUEUED, Actor.REAPER)


# --- actor ownership ------------------------------------------------------


def test_only_the_reaper_or_orchestrator_closes_a_cancellation():
    """The worker holding the task may be dead, so it cannot own convergence."""
    assert RUN_MACHINE.can(RunStatus.CANCEL_REQUESTED, RunStatus.CANCELLED, Actor.REAPER)
    assert not RUN_MACHINE.can(RunStatus.CANCEL_REQUESTED, RunStatus.CANCELLED, Actor.WORKER)
    assert not RUN_MACHINE.can(RunStatus.CANCEL_REQUESTED, RunStatus.CANCELLED, Actor.API)


def test_only_a_worker_claims_a_task():
    assert TASK_MACHINE.can(TaskStatus.QUEUED, TaskStatus.CLAIMED, Actor.WORKER)
    assert not TASK_MACHINE.can(TaskStatus.QUEUED, TaskStatus.CLAIMED, Actor.API)


def test_only_the_reaper_requeues_an_expired_lease():
    assert TASK_MACHINE.can(TaskStatus.RUNNING, TaskStatus.QUEUED, Actor.REAPER)
    assert not TASK_MACHINE.can(TaskStatus.RUNNING, TaskStatus.QUEUED, Actor.WORKER)


def test_only_the_reaper_marks_an_attempt_lost():
    assert ATTEMPT_MACHINE.can(AttemptStatus.RUNNING, AttemptStatus.LOST, Actor.REAPER)
    assert not ATTEMPT_MACHINE.can(AttemptStatus.RUNNING, AttemptStatus.LOST, Actor.WORKER)


def test_only_the_api_requests_a_cancellation():
    assert RUN_MACHINE.can(RunStatus.RUNNING, RunStatus.CANCEL_REQUESTED, Actor.API)
    assert not RUN_MACHINE.can(RunStatus.RUNNING, RunStatus.CANCEL_REQUESTED, Actor.WORKER)


def test_check_raises_for_a_wrong_actor():
    with pytest.raises(InvalidTransition):
        TASK_MACHINE.check(TaskStatus.QUEUED, TaskStatus.CLAIMED, Actor.API)


def test_check_raises_for_an_undefined_edge():
    with pytest.raises(InvalidTransition):
        RUN_MACHINE.check(RunStatus.QUEUED, RunStatus.SUCCEEDED, Actor.ORCHESTRATOR)


# --- cancellation converges ----------------------------------------------


def test_a_cancel_requested_run_can_still_reach_a_natural_outcome():
    """Race: every task finished between the request and the reaper waking."""
    assert RUN_MACHINE.can(RunStatus.CANCEL_REQUESTED, RunStatus.SUCCEEDED, Actor.ORCHESTRATOR)
    assert RUN_MACHINE.can(RunStatus.CANCEL_REQUESTED, RunStatus.FAILED, Actor.ORCHESTRATOR)


def test_cancel_requested_always_has_a_way_out():
    assert RUN_MACHINE.targets(RunStatus.CANCEL_REQUESTED)


# --- aggregation ----------------------------------------------------------


def test_no_tasks_yet_is_queued():
    assert run_status_for_tasks([], cancel_requested=False) == RunStatus.QUEUED


def test_all_succeeded_is_succeeded():
    statuses = [TaskStatus.SUCCEEDED, TaskStatus.SUCCEEDED, TaskStatus.SKIPPED]
    assert run_status_for_tasks(statuses, cancel_requested=False) == RunStatus.SUCCEEDED


def test_any_failed_is_failed():
    statuses = [TaskStatus.SUCCEEDED, TaskStatus.FAILED]
    assert run_status_for_tasks(statuses, cancel_requested=False) == RunStatus.FAILED


def test_failure_outranks_cancellation():
    statuses = [TaskStatus.FAILED, TaskStatus.CANCELLED]
    assert run_status_for_tasks(statuses, cancel_requested=False) == RunStatus.FAILED


def test_a_running_task_makes_the_run_running():
    statuses = [TaskStatus.SUCCEEDED, TaskStatus.RUNNING, TaskStatus.CREATED]
    assert run_status_for_tasks(statuses, cancel_requested=False) == RunStatus.RUNNING


def test_a_claimed_task_also_makes_the_run_running():
    assert run_status_for_tasks([TaskStatus.CLAIMED], cancel_requested=False) == RunStatus.RUNNING


def test_pending_work_with_a_cancel_request_stays_cancel_requested():
    statuses = [TaskStatus.RUNNING, TaskStatus.CREATED]
    assert run_status_for_tasks(statuses, cancel_requested=True) == RunStatus.CANCEL_REQUESTED


def test_a_cancel_request_does_not_override_a_finished_run():
    """If every task already finished, the real outcome wins over the request."""
    statuses = [TaskStatus.SUCCEEDED, TaskStatus.SUCCEEDED]
    assert run_status_for_tasks(statuses, cancel_requested=True) == RunStatus.SUCCEEDED


def test_all_cancelled_is_cancelled():
    statuses = [TaskStatus.CANCELLED, TaskStatus.SKIPPED]
    assert run_status_for_tasks(statuses, cancel_requested=True) == RunStatus.CANCELLED


def test_every_aggregate_result_is_a_real_run_status():
    assert run_status_for_tasks([TaskStatus.RETRY_WAIT], cancel_requested=False) in set(
        RunStatus.values()
    )

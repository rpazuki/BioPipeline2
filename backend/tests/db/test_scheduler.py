"""The scheduler: a clock submitting the same runs a person would.

Two things are being asserted throughout. A scheduled run is an *ordinary*
run -- same bindings, same tasks, same everything -- and a window fires exactly
once however badly the scheduler behaves around it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.pipelines import create_revision
from app.application.publications import (
    FieldSpec,
    SubmissionRefused,
    archive,
    create_publication_revision,
    publish,
)
from app.application.schedules import (
    FAILURES_BEFORE_PAUSE,
    create_schedule,
    due_schedule_ids,
    fire_due,
    pause,
    resume,
)
from app.domain.bindings import FieldBinding
from app.domain.enums import CatchupPolicy, OverlapPolicy
from app.domain.errors import ValidationFailed
from app.domain.materialise import folder_items
from app.settings import load_settings
from app.workers.scheduler import Scheduler

pytestmark = pytest.mark.db

PIPELINE = """
pipeline: __NAME__
defaults:
  root: /d
  window: 5
stages:
  - name: only
    fanout: {type: folders, data_dir: "{root}"}
    steps:
      - name: a
        package: labUtils.x
        method: run
        parameters: {moving_window_size: "{window}"}
"""

HOURLY = 3600


def fanout(_folder: str):
    return folder_items(["plate_01", "plate_02"])


@pytest.fixture
def user(db: Session) -> uuid.UUID:
    return db.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'S', 'admin') RETURNING id"
        ),
        {"e": f"s-{uuid.uuid4().hex[:10]}@example.org"},
    ).scalar_one()


@pytest.fixture
def publication(db: Session, user: uuid.UUID) -> uuid.UUID:
    """A published entry with one knob, exactly as an admin would compose it."""
    revision = create_revision(
        db,
        source_text=PIPELINE.replace("__NAME__", f"p_{uuid.uuid4().hex[:8]}"),
        owner_id=user,
    )
    created = create_publication_revision(
        db,
        slug=f"sched-{uuid.uuid4().hex[:8]}",
        pipeline_revision_id=revision.revision_id,
        title="Nightly fit",
        created_by=user,
        fields=[
            FieldSpec(
                key="smoothing",
                label="Smoothing window",
                field_type="integer",
                required=False,
                binding=FieldBinding(
                    key="smoothing",
                    target="step_parameter",
                    stage="only",
                    step="a",
                    binding_key="moving_window_size",
                ),
            )
        ],
    )
    publish(db, publication_id=created.publication_id, revision_id=created.revision_id)
    return created.revision_id


def schedule_for(db: Session, publication: uuid.UUID, user: uuid.UUID, **overrides):
    defaults = {
        "publication_revision_id": publication,
        "owner_id": user,
        "title": "Nightly fit",
        "input_values": {"smoothing": 3},
        "interval_seconds": HOURLY,
    }
    defaults.update(overrides)
    return create_schedule(db, **defaults)


def fires(db: Session, schedule_id: uuid.UUID) -> list[tuple]:
    return list(
        db.execute(
            text(
                "SELECT fire_at, outcome, run_id, message FROM schedule_fires "
                "WHERE schedule_id = :s ORDER BY fire_at"
            ),
            {"s": schedule_id},
        ).all()
    )


def events(db: Session, schedule_id: uuid.UUID) -> list[str]:
    return list(
        db.execute(
            text(
                "SELECT event_type FROM schedule_events WHERE schedule_id = :s "
                "ORDER BY created_at, id"
            ),
            {"s": schedule_id},
        ).scalars()
    )


def finish(db: Session, run_id: uuid.UUID, status: str = "succeeded") -> None:
    db.execute(
        text("UPDATE runs SET status = :s, finished_at = now() WHERE id = :i"),
        {"s": status, "i": run_id},
    )


# --- a schedule produces an ordinary run -----------------------------------


def test_a_due_schedule_creates_a_run(db: Session, publication, user):
    schedule = schedule_for(db, publication, user)
    due = schedule.next_fire_at

    report = fire_due(db, schedule.id, now=due, enumerate_fanout=fanout)

    assert len(report.created) == 1
    run = db.execute(
        text(
            "SELECT requested_from, publication_revision_id, requested_by FROM runs WHERE id = :i"
        ),
        {"i": report.created[0]},
    ).one()
    assert run.requested_from == "schedule"
    assert run.publication_revision_id == publication
    assert run.requested_by == user


def test_a_scheduled_run_has_the_same_tasks_a_person_would_have_got(db: Session, publication, user):
    """No separate execution path: it fans out and materialises identically."""
    schedule = schedule_for(db, publication, user)
    report = fire_due(db, schedule.id, now=schedule.next_fire_at, enumerate_fanout=fanout)
    keys = db.execute(
        text("SELECT task_key FROM run_tasks WHERE run_id = :r ORDER BY task_key"),
        {"r": report.created[0]},
    ).scalars()
    assert list(keys) == ["only:plate_01", "only:plate_02"]


def test_the_schedule_s_stored_values_reach_the_task(db: Session, publication, user):
    """The point of storing values at all: 3, not the pipeline's own 5."""
    schedule = schedule_for(db, publication, user)
    report = fire_due(db, schedule.id, now=schedule.next_fire_at, enumerate_fanout=fanout)
    spec = db.execute(
        text("SELECT task_spec FROM run_tasks WHERE run_id = :r LIMIT 1"),
        {"r": report.created[0]},
    ).scalar_one()
    assert spec["steps"][0]["parameters"]["moving_window_size"] == 3


def test_the_run_records_what_the_schedule_was_asked_for(db: Session, publication, user):
    schedule = schedule_for(db, publication, user)
    report = fire_due(db, schedule.id, now=schedule.next_fire_at, enumerate_fanout=fanout)
    values = db.execute(
        text("SELECT input_values FROM runs WHERE id = :i"), {"i": report.created[0]}
    ).scalar_one()
    assert values == {"smoothing": 3}


# --- once and only once (G25) ----------------------------------------------


def test_a_window_already_claimed_produces_nothing(db: Session, publication, user):
    """What a second scheduler sees. The row is staked before any work, so
    the loser creates nothing rather than discovering a duplicate afterwards.
    """
    schedule = schedule_for(db, publication, user)
    db.execute(
        text(
            "INSERT INTO schedule_fires (schedule_id, fire_at, outcome) VALUES (:s, :f, 'created')"
        ),
        {"s": schedule.id, "f": schedule.next_fire_at},
    )
    report = fire_due(db, schedule.id, now=schedule.next_fire_at, enumerate_fanout=fanout)
    assert report.created == []


def test_the_same_window_twice_is_still_one_run(db: Session, publication, user):
    schedule = schedule_for(db, publication, user)
    due = schedule.next_fire_at
    first = fire_due(db, schedule.id, now=due, enumerate_fanout=fanout)
    # A scheduler that restarted and re-read a schedule it had already fired.
    db.execute(
        text("UPDATE schedules SET next_fire_at = :f WHERE id = :i"),
        {"f": due, "i": schedule.id},
    )
    db.expire(schedule)
    second = fire_due(db, schedule.id, now=due, enumerate_fanout=fanout)
    assert len(first.created) == 1
    assert second.created == []


def test_a_window_is_keyed_on_the_window_not_on_when_the_scheduler_woke(
    db: Session, publication, user
):
    """`fire_at` is the scheduled window, so a late fire and an on-time one
    are the same window and cannot both happen."""
    schedule = schedule_for(db, publication, user)
    due = schedule.next_fire_at
    fire_due(db, schedule.id, now=due + timedelta(minutes=17), enumerate_fanout=fanout)
    assert [row.fire_at for row in fires(db, schedule.id)] == [due]


def test_the_run_carries_its_window_as_an_idempotency_key(db: Session, publication, user):
    """The second guarantee. Even a `schedule_fires` row deleted by hand
    cannot produce a second run for a window."""
    schedule = schedule_for(db, publication, user)
    due = schedule.next_fire_at
    first = fire_due(db, schedule.id, now=due, enumerate_fanout=fanout)
    db.execute(text("DELETE FROM schedule_fires WHERE schedule_id = :s"), {"s": schedule.id})
    db.execute(
        text("UPDATE schedules SET next_fire_at = :f WHERE id = :i"),
        {"f": due, "i": schedule.id},
    )
    db.expire(schedule)
    second = fire_due(db, schedule.id, now=due, enumerate_fanout=fanout)
    assert second.created == first.created


# --- the grid ---------------------------------------------------------------


def test_a_late_fire_does_not_move_the_grid(db: Session, publication, user):
    """Fired 17 minutes late, the next window is still on the hour."""
    schedule = schedule_for(db, publication, user)
    due = schedule.next_fire_at
    fire_due(db, schedule.id, now=due + timedelta(minutes=17), enumerate_fanout=fanout)
    db.refresh(schedule)
    assert schedule.next_fire_at == due + timedelta(seconds=HOURLY)


def test_a_schedule_not_yet_due_is_not_in_the_list(db: Session, publication, user):
    schedule = schedule_for(db, publication, user, start_at=datetime.now(UTC) + timedelta(days=1))
    assert schedule.id not in due_schedule_ids(db, now=datetime.now(UTC))


def test_a_due_schedule_is_in_the_list(db: Session, publication, user):
    schedule = schedule_for(db, publication, user)
    assert schedule.id in due_schedule_ids(db, now=schedule.next_fire_at)


def test_a_paused_schedule_is_not_in_the_list(db: Session, publication, user):
    schedule = schedule_for(db, publication, user)
    pause(db, schedule.id, actor_id=user)
    assert schedule.id not in due_schedule_ids(db, now=schedule.next_fire_at)


def test_a_paused_schedule_does_not_fire_even_if_asked(db: Session, publication, user):
    schedule = schedule_for(db, publication, user)
    due = schedule.next_fire_at
    pause(db, schedule.id, actor_id=user)
    assert fire_due(db, schedule.id, now=due, enumerate_fanout=fanout).created == []


# --- overlap ----------------------------------------------------------------


def running(db: Session, publication, user, policy: str, **overrides):
    """A schedule with one run of its own still going."""
    schedule = schedule_for(db, publication, user, overlap_policy=policy, **overrides)
    due = schedule.next_fire_at
    first = fire_due(db, schedule.id, now=due, enumerate_fanout=fanout)
    return schedule, first.created[0], due + timedelta(seconds=HOURLY)


def test_skip_drops_the_window_while_the_previous_run_is_going(db: Session, publication, user):
    schedule, _, next_due = running(db, publication, user, OverlapPolicy.SKIP)
    report = fire_due(db, schedule.id, now=next_due, enumerate_fanout=fanout)
    assert report.created == []
    assert report.skipped_overlap == 1
    assert [row.outcome for row in fires(db, schedule.id)] == ["created", "skipped_overlap"]
    db.refresh(schedule)
    assert schedule.next_fire_at == next_due + timedelta(seconds=HOURLY)


def test_queue_holds_the_window_rather_than_dropping_it(db: Session, publication, user):
    """The whole difference between `queue` and `skip`: the work is deferred,
    so it happens late instead of not at all."""
    schedule, run_id, next_due = running(db, publication, user, OverlapPolicy.QUEUE)
    report = fire_due(db, schedule.id, now=next_due, enumerate_fanout=fanout)
    assert report.created == []
    assert report.deferred == 1
    db.refresh(schedule)
    assert schedule.next_fire_at == next_due  # still owed

    finish(db, run_id)
    later = fire_due(db, schedule.id, now=next_due, enumerate_fanout=fanout)
    assert len(later.created) == 1


def test_allow_fires_regardless(db: Session, publication, user):
    schedule, _, next_due = running(db, publication, user, OverlapPolicy.ALLOW)
    assert len(fire_due(db, schedule.id, now=next_due, enumerate_fanout=fanout).created) == 1


def test_a_finished_run_is_not_an_overlap(db: Session, publication, user):
    schedule, run_id, next_due = running(db, publication, user, OverlapPolicy.SKIP)
    finish(db, run_id)
    assert len(fire_due(db, schedule.id, now=next_due, enumerate_fanout=fanout).created) == 1


def test_max_concurrent_runs_is_what_overlap_means(db: Session, publication, user):
    schedule, _, next_due = running(
        db, publication, user, OverlapPolicy.SKIP, max_concurrent_runs=2
    )
    assert len(fire_due(db, schedule.id, now=next_due, enumerate_fanout=fanout).created) == 1
    third = next_due + timedelta(seconds=HOURLY)
    assert fire_due(db, schedule.id, now=third, enumerate_fanout=fanout).skipped_overlap == 1


# --- catchup ----------------------------------------------------------------


def test_run_all_catches_up_on_every_missed_window(db: Session, publication, user):
    schedule = schedule_for(
        db,
        publication,
        user,
        catchup_policy=CatchupPolicy.RUN_ALL,
        overlap_policy=OverlapPolicy.ALLOW,
    )
    due = schedule.next_fire_at
    report = fire_due(db, schedule.id, now=due + timedelta(hours=3), enumerate_fanout=fanout)
    assert len(report.created) == 4


def test_skip_missed_records_the_backlog_in_one_row(db: Session, publication, user):
    """Not one row per missed window: a fortnight of hourly downtime is one
    fact, and writing it 336 times would be the scheduler's first act back."""
    schedule = schedule_for(db, publication, user, catchup_policy=CatchupPolicy.SKIP_MISSED)
    due = schedule.next_fire_at
    # Half an hour past the last window, so nothing is inside the grace.
    report = fire_due(
        db, schedule.id, now=due + timedelta(days=14, minutes=30), enumerate_fanout=fanout
    )
    assert report.created == []
    assert report.skipped_catchup == 1
    rows = fires(db, schedule.id)
    assert [row.outcome for row in rows] == ["skipped_catchup"]
    assert "catchup_policy = skip_missed" in rows[0].message


def test_run_once_collapses_the_backlog_into_one_run(db: Session, publication, user):
    schedule = schedule_for(db, publication, user, catchup_policy=CatchupPolicy.RUN_ONCE)
    due = schedule.next_fire_at
    report = fire_due(db, schedule.id, now=due + timedelta(hours=5), enumerate_fanout=fanout)
    assert len(report.created) == 1
    assert report.skipped_catchup == 1


def test_catching_up_is_capped_and_says_there_is_more(db: Session, publication, user):
    schedule = schedule_for(
        db,
        publication,
        user,
        catchup_policy=CatchupPolicy.RUN_ALL,
        overlap_policy=OverlapPolicy.ALLOW,
    )
    due = schedule.next_fire_at
    report = fire_due(
        db, schedule.id, now=due + timedelta(hours=20), enumerate_fanout=fanout, limit=3
    )
    assert len(report.created) == 3
    assert report.more_due is True


# --- failure ----------------------------------------------------------------


def test_a_schedule_whose_entry_was_withdrawn_fails_loudly(db: Session, publication, user):
    """Archiving removes an entry from the things that can be started, and a
    clock is one of the things that starts them."""
    schedule = schedule_for(db, publication, user)
    publication_id = db.execute(
        text("SELECT publication_id FROM publication_revisions WHERE id = :i"),
        {"i": publication},
    ).scalar_one()
    archive(db, publication_id=publication_id)

    report = fire_due(db, schedule.id, now=schedule.next_fire_at, enumerate_fanout=fanout)
    assert report.failed == 1
    assert report.created == []
    assert fires(db, schedule.id)[0].outcome == "failed"
    assert "no longer published" in fires(db, schedule.id)[0].message


def test_a_failed_window_says_what_was_wrong_not_how_many_things_were(db, publication, user):
    """The only place an owner will look to find out why results stopped.

    A domain error's headline counts its problems — "rejected with 2 error(s)"
    — which is exactly the information that is no use.
    """
    schedule = schedule_for(db, publication, user)
    # No fan-out enumerator, so materialisation cannot resolve the stage.
    report = fire_due(db, schedule.id, now=schedule.next_fire_at, enumerate_fanout=None)
    assert report.failed == 1
    message = fires(db, schedule.id)[0].message
    assert "error(s)" in message  # the headline is kept
    assert "fanout" in message or "fan-out" in message  # and so is the reason


def test_a_failure_still_advances_the_grid(db: Session, publication, user):
    """Otherwise the schedule retries the same broken window on every tick and
    never reaches the next one."""
    schedule = schedule_for(db, publication, user)
    due = schedule.next_fire_at
    publication_id = db.execute(
        text("SELECT publication_id FROM publication_revisions WHERE id = :i"),
        {"i": publication},
    ).scalar_one()
    archive(db, publication_id=publication_id)
    fire_due(db, schedule.id, now=due, enumerate_fanout=fanout)
    db.refresh(schedule)
    assert schedule.next_fire_at == due + timedelta(seconds=HOURLY)


def test_a_schedule_that_keeps_failing_pauses_itself(db: Session, publication, user):
    """Loud, not silent. A schedule failing every window for a month while
    still calling itself active is how nobody notices work stopped."""
    schedule = schedule_for(db, publication, user)
    publication_id = db.execute(
        text("SELECT publication_id FROM publication_revisions WHERE id = :i"),
        {"i": publication},
    ).scalar_one()
    archive(db, publication_id=publication_id)

    now = schedule.next_fire_at
    for _ in range(FAILURES_BEFORE_PAUSE):
        fire_due(db, schedule.id, now=now, enumerate_fanout=fanout)
        now += timedelta(seconds=HOURLY)
    db.refresh(schedule)
    assert schedule.status == "paused"
    assert "paused" in events(db, schedule.id)


def test_an_uninterpretable_recurrence_pauses_immediately(db: Session, publication, user):
    """There is no next window to advance to, so retrying would be forever."""
    schedule = schedule_for(db, publication, user)
    db.execute(
        text(
            "UPDATE schedules SET timezone = 'Mars/Olympus', interval_seconds = NULL, "
            "rrule = 'FREQ=DAILY' WHERE id = :i"
        ),
        {"i": schedule.id},
    )
    db.expire(schedule)
    report = fire_due(db, schedule.id, now=datetime.now(UTC), enumerate_fanout=fanout)
    assert report.paused is not None
    db.refresh(schedule)
    assert schedule.status == "paused"


# --- creating and administering ---------------------------------------------


def test_a_schedule_that_could_never_run_is_refused(db: Session, publication, user):
    """Checked where somebody can still do something about it, rather than
    discovered at 3am."""
    with pytest.raises(SubmissionRefused):
        schedule_for(db, publication, user, input_values={"nonsense": 1})


def test_a_recurrence_with_no_window_at_all_is_refused(db: Session, publication, user):
    with pytest.raises(ValidationFailed, match="never run"):
        schedule_for(
            db,
            publication,
            user,
            interval_seconds=None,
            rrule="FREQ=DAILY;COUNT=1",
            end_at=datetime.now(UTC) - timedelta(days=1),
        )


def test_a_schedule_on_an_unpublished_revision_is_refused(db: Session, publication, user):
    publication_id = db.execute(
        text("SELECT publication_id FROM publication_revisions WHERE id = :i"),
        {"i": publication},
    ).scalar_one()
    archive(db, publication_id=publication_id)
    with pytest.raises(ValidationFailed, match="published"):
        schedule_for(db, publication, user)


def test_a_rule_keeps_the_phase_it_was_created_with(db: Session, publication, user):
    """Stored in the rule itself, so a `shift_forward` spring-forward cannot
    move a nightly job to a new time for ever."""
    start = datetime(2026, 6, 1, 2, 30, tzinfo=UTC)
    schedule = schedule_for(
        db, publication, user, interval_seconds=None, rrule="FREQ=DAILY", start_at=start
    )
    assert schedule.rrule.startswith("DTSTART:20260601T023000")
    assert schedule.next_fire_at == start


def test_resuming_starts_from_the_next_window_not_from_the_backlog(db: Session, publication, user):
    """A fortnight paused must not answer with a fortnight of runs; that
    policy is about a scheduler that was down, not a decision somebody made."""
    schedule = schedule_for(db, publication, user, catchup_policy=CatchupPolicy.RUN_ALL)
    db.execute(
        text("UPDATE schedules SET next_fire_at = :f WHERE id = :i"),
        {"f": datetime.now(UTC) - timedelta(days=14), "i": schedule.id},
    )
    db.expire(schedule)
    pause(db, schedule.id, actor_id=user)
    resume(db, schedule.id, actor_id=user)
    db.refresh(schedule)
    assert schedule.status == "active"
    assert schedule.next_fire_at > datetime.now(UTC)


def test_a_schedule_records_its_history(db: Session, publication, user):
    """In order. One tick writes several events in one transaction, and
    PostgreSQL's `now()` would give all of them the same timestamp -- a
    history that cannot be sorted is not a history."""
    schedule = schedule_for(db, publication, user)
    fire_due(db, schedule.id, now=schedule.next_fire_at, enumerate_fanout=fanout)
    assert events(db, schedule.id) == ["created", "fired"]


# --- the loop ---------------------------------------------------------------


def test_a_tick_reports_what_it_did(engine):
    scheduler = Scheduler(engine, load_settings(), enumerate_fanout=fanout)
    assert isinstance(scheduler.tick().summary(), str)


def test_a_stopped_scheduler_performs_no_ticks(engine):
    scheduler = Scheduler(engine, load_settings(), enumerate_fanout=fanout)
    scheduler._stopping.set()
    assert scheduler.run_forever() == 0


def test_the_loop_is_bounded(engine):
    scheduler = Scheduler(engine, load_settings(), enumerate_fanout=fanout)
    scheduler.interval = 0
    assert scheduler.run_forever(max_ticks=2) == 2


def test_one_bad_schedule_does_not_stop_the_others(engine, monkeypatch):
    """The failure that matters most: a scheduler that stops scheduling."""
    from app.workers import scheduler as module

    bad, good = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(module, "due_schedule_ids", lambda *a, **k: [bad, good])

    seen: list[uuid.UUID] = []

    def flaky(_session, schedule_id, **_kwargs):
        seen.append(schedule_id)
        if schedule_id == bad:
            raise RuntimeError("this schedule is broken")
        return module.FireReport(schedule_id=schedule_id)

    monkeypatch.setattr(module, "fire_due", flaky)
    report = Scheduler(engine, load_settings(), enumerate_fanout=fanout).tick()
    assert seen == [bad, good]
    assert report.errors == 1
    assert report.considered == 1

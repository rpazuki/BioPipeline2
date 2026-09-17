"""When a schedule is due, and what it owes after an outage.

No database and no real clock: every test states the moment the scheduler
wakes at, which is the only way a spring-forward gap, a leap day and a week of
downtime are testable at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.domain.enums import CatchupPolicy
from app.domain.recurrence import (
    InvalidRecurrence,
    Recurrence,
    plan_fires,
)

LONDON = ZoneInfo("Europe/London")
MIDNIGHT = datetime(2026, 1, 1, tzinfo=UTC)


def hourly(**overrides) -> Recurrence:
    return Recurrence(start=overrides.pop("start", MIDNIGHT), interval_seconds=3600, **overrides)


def at(hours: float = 0, **kwargs) -> datetime:
    return MIDNIGHT + timedelta(hours=hours, **kwargs)


def clock(windows) -> list[str]:
    return [window.strftime("%H:%M") for window in windows]


# --- the grid --------------------------------------------------------------


def test_an_interval_grid_does_not_drift_when_the_scheduler_is_late():
    """The reason a window is a point on a grid and not `now + interval`.

    A scheduler ten minutes late fires the 02:00 window late. It must not
    decide the next one is 03:10, or a nightly job walks off its slot.
    """
    grid = hourly()
    assert grid.next_after(at(1, minutes=10)) == at(2)
    assert grid.next_after(at(2, minutes=59, seconds=59)) == at(3)


def test_a_window_exactly_on_the_grid_is_already_past():
    """`next_after` is strictly after, so a window cannot fire itself twice."""
    assert hourly().next_after(at(3)) == at(4)


def test_the_first_window_is_the_anchor_itself():
    assert hourly().first() == MIDNIGHT


def test_fractional_seconds_do_not_accumulate():
    """Window arithmetic never goes through a float.

    Rounding would eventually put two windows on one instant, and the second
    would vanish into the unique constraint that is supposed to be protecting
    them.
    """
    odd = Recurrence(start=MIDNIGHT + timedelta(microseconds=1), interval_seconds=7)
    window = odd.first()
    for _ in range(10_000):
        window = odd.next_after(window)
    assert window == MIDNIGHT + timedelta(microseconds=1, seconds=7 * 10_000)


def test_the_window_before_a_moment_is_found_without_walking_to_it():
    """A month of downtime on a minutely schedule must not be enumerated."""
    minutely = Recurrence(start=MIDNIGHT, interval_seconds=60)
    assert minutely.last_before(MIDNIGHT + timedelta(days=30)) == MIDNIGHT + timedelta(
        days=30, minutes=-1
    )


def test_a_schedule_stops_at_its_end():
    bounded = hourly(end_at=at(3))
    assert bounded.next_after(at(2)) == at(3)
    assert bounded.next_after(at(3)) is None


def test_the_last_window_before_a_moment_past_the_end_is_the_last_one_there_was():
    bounded = hourly(end_at=at(3))
    assert bounded.last_before(at(99)) == at(3)


# --- what a recurrence must say --------------------------------------------


def test_a_schedule_needs_exactly_one_recurrence():
    with pytest.raises(InvalidRecurrence):
        Recurrence(start=MIDNIGHT)
    with pytest.raises(InvalidRecurrence):
        Recurrence(start=MIDNIGHT, interval_seconds=60, rrule="FREQ=DAILY")


def test_an_unparseable_rule_is_refused_where_somebody_can_still_read_it():
    with pytest.raises(InvalidRecurrence, match="Cannot parse"):
        Recurrence(start=MIDNIGHT, rrule="every other tuesday")


def test_an_unknown_timezone_is_refused():
    with pytest.raises(InvalidRecurrence, match="Unknown timezone"):
        Recurrence(start=MIDNIGHT, rrule="FREQ=DAILY", timezone="Mars/Olympus")


def test_a_naive_anchor_is_refused():
    with pytest.raises(InvalidRecurrence, match="timezone-aware"):
        Recurrence(start=datetime(2026, 1, 1), interval_seconds=60)


# --- rules -----------------------------------------------------------------


def test_a_rule_keeps_its_own_phase():
    rule = Recurrence(start=MIDNIGHT, rrule="DTSTART:20260101T023000\nRRULE:FREQ=DAILY")
    assert rule.first() == datetime(2026, 1, 1, 2, 30, tzinfo=UTC)
    assert rule.next_after(datetime(2026, 1, 1, 2, 30, tzinfo=UTC)) == datetime(
        2026, 1, 2, 2, 30, tzinfo=UTC
    )


def test_a_rule_that_skips_short_months_does_not_invent_a_31st():
    rule = Recurrence(start=datetime(2026, 1, 31, tzinfo=UTC), rrule="FREQ=MONTHLY;BYMONTHDAY=31")
    assert rule.next_after(datetime(2026, 1, 31, tzinfo=UTC)) == datetime(2026, 3, 31, tzinfo=UTC)


def test_a_rule_can_run_out():
    rule = Recurrence(start=MIDNIGHT, rrule="FREQ=DAILY;COUNT=2")
    assert rule.next_after(at(0)) == at(24)
    assert rule.next_after(at(24)) is None


# --- daylight saving (G55) -------------------------------------------------
#
# The UK clock goes forward at 01:00 on 2026-03-29, so local 01:30 does not
# exist that day; it goes back at 02:00 on 2026-10-25, so local 01:30 happens
# twice.


def half_past_one(policy: str) -> Recurrence:
    return Recurrence(
        start=datetime(2026, 3, 27, 1, 30, tzinfo=UTC),
        rrule="FREQ=DAILY;BYHOUR=1;BYMINUTE=30",
        timezone="Europe/London",
        dst_policy=policy,
    )


def local_run(recurrence: Recurrence, count: int = 4) -> list[str]:
    cursor = datetime(2026, 3, 27, tzinfo=UTC)
    seen = []
    for _ in range(count):
        cursor = recurrence.next_after(cursor)
        seen.append(cursor.astimezone(LONDON).strftime("%d %H:%M %Z"))
    return seen


def test_a_nonexistent_local_time_can_be_skipped():
    assert local_run(half_past_one("skip_nonexistent")) == [
        "27 01:30 GMT",
        "28 01:30 GMT",
        "30 01:30 BST",  # the 29th has no 01:30 at all
        "31 01:30 BST",
    ]


def test_a_nonexistent_local_time_can_be_shifted_past_the_gap():
    """Shifted by the gap's length, not clamped to its end.

    Clamping would be easier to explain and wrong: 02:15 and 02:45 would both
    clamp to 03:00, two distinct windows would share one instant, and the
    second would be swallowed by the unique constraint meant to protect them.
    """
    assert local_run(half_past_one("shift_forward")) == [
        "27 01:30 GMT",
        "28 01:30 GMT",
        "29 02:30 BST",
        "30 01:30 BST",
    ]


def test_two_windows_inside_the_gap_stay_two_windows():
    """The property that rules out clamping."""
    gap = Recurrence(
        start=datetime(2026, 3, 28, tzinfo=UTC),
        rrule="FREQ=DAILY;BYHOUR=1;BYMINUTE=15,45",
        timezone="Europe/London",
        dst_policy="shift_forward",
    )
    cursor = datetime(2026, 3, 29, tzinfo=UTC)
    first = gap.next_after(cursor)
    second = gap.next_after(first)
    assert first != second
    assert [w.astimezone(LONDON).strftime("%H:%M") for w in (first, second)] == ["02:15", "02:45"]


def test_utc_only_has_no_local_time_to_be_ambiguous_about():
    """The schedule keeps its instant and the wall clock moves under it."""
    assert local_run(half_past_one("utc_only")) == [
        "27 01:30 GMT",
        "28 01:30 GMT",
        "29 02:30 BST",
        "30 02:30 BST",
    ]


def test_an_ambiguous_local_time_fires_once_not_twice():
    """01:30 happens twice on 2026-10-25; one rule occurrence is one run."""
    rule = Recurrence(
        start=datetime(2026, 10, 24, 0, 30, tzinfo=UTC),
        rrule="FREQ=DAILY;BYHOUR=1;BYMINUTE=30",
        timezone="Europe/London",
    )
    windows = []
    cursor = datetime(2026, 10, 24, tzinfo=UTC)
    for _ in range(3):
        cursor = rule.next_after(cursor)
        windows.append(cursor)
    the_day = datetime(2026, 10, 25).date()
    on_the_day = [w for w in windows if w.astimezone(LONDON).date() == the_day]
    assert len(on_the_day) == 1
    # The first of the two, the BST one.
    assert on_the_day[0] == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)


def test_an_interval_schedule_has_no_local_time_at_all():
    """Exact seconds, so no gap and no fold. The reason G17's imported
    interval schedules need no DST policy."""
    across = Recurrence(
        start=datetime(2026, 3, 29, 0, 30, tzinfo=UTC),
        interval_seconds=3600,
        timezone="Europe/London",
    )
    assert across.next_after(datetime(2026, 3, 29, 0, 30, tzinfo=UTC)) == datetime(
        2026, 3, 29, 1, 30, tzinfo=UTC
    )


# --- catchup ---------------------------------------------------------------


def plan(policy: str, *, due: datetime, now: datetime, **kwargs):
    return plan_fires(hourly(), due_at=due, now=now, catchup=policy, grace_seconds=60, **kwargs)


@pytest.mark.parametrize("policy", list(CatchupPolicy))
def test_a_healthy_tick_looks_the_same_under_every_policy(policy):
    """The property that keeps the choice invisible until it matters.

    Nothing is missed when a scheduler is running, so no policy applies.
    """
    result = plan(policy, due=at(5), now=at(5) + timedelta(seconds=3))
    assert clock(result.fire) == ["05:00"]
    assert result.skipped_through is None
    assert result.next_fire_at == at(6)


def test_a_window_not_yet_due_fires_nothing():
    result = plan(CatchupPolicy.RUN_ALL, due=at(6), now=at(5))
    assert result.fire == ()
    assert result.next_fire_at == at(6)


def test_run_all_gives_every_missed_window_its_own_run():
    result = plan(CatchupPolicy.RUN_ALL, due=at(1), now=at(5, minutes=2))
    assert clock(result.fire) == ["01:00", "02:00", "03:00", "04:00", "05:00"]
    assert result.skipped_through is None
    assert result.next_fire_at == at(6)


def test_run_once_collapses_the_backlog_into_one_run():
    result = plan(CatchupPolicy.RUN_ONCE, due=at(1), now=at(5, minutes=2))
    assert clock(result.fire) == ["05:00"]
    assert result.skipped_through == at(4)
    assert result.next_fire_at == at(6)


def test_skip_missed_runs_none_of_them():
    result = plan(CatchupPolicy.SKIP_MISSED, due=at(1), now=at(5, minutes=2))
    assert result.fire == ()
    assert result.skipped_through == at(5)
    assert result.next_fire_at == at(6)


def test_a_dropped_backlog_is_recorded_as_one_window_not_forty_thousand():
    """A month of downtime on a minutely schedule.

    The plan names the last window it dropped and stops. Enumerating them
    would be forty thousand rows all saying the same thing, and the scheduler
    would spend its first tick back writing them.
    """
    minutely = Recurrence(start=MIDNIGHT, interval_seconds=60)
    result = plan_fires(
        minutely,
        due_at=MIDNIGHT,
        now=MIDNIGHT + timedelta(days=30),
        catchup=CatchupPolicy.SKIP_MISSED,
        grace_seconds=30,
    )
    # One row for the whole backlog, and the window that is actually current.
    assert result.skipped_through == MIDNIGHT + timedelta(days=30, minutes=-1)
    assert result.fire == (MIDNIGHT + timedelta(days=30),)
    assert result.next_fire_at == MIDNIGHT + timedelta(days=30, minutes=1)


def test_one_missed_window_under_run_once_drops_nothing():
    result = plan(CatchupPolicy.RUN_ONCE, due=at(5), now=at(5, minutes=10))
    assert clock(result.fire) == ["05:00"]
    assert result.skipped_through is None


def test_catching_up_is_capped_so_one_tick_cannot_create_a_week_of_runs():
    result = plan(CatchupPolicy.RUN_ALL, due=at(1), now=at(50), limit=3)
    assert clock(result.fire) == ["01:00", "02:00", "03:00"]
    assert result.more_due is True
    assert result.next_fire_at == at(4)


def test_a_schedule_past_its_end_has_nowhere_left_to_go():
    result = plan_fires(
        hourly(end_at=at(2)),
        due_at=at(2),
        now=at(9),
        catchup=CatchupPolicy.RUN_ALL,
        grace_seconds=60,
    )
    assert clock(result.fire) == ["02:00"]
    assert result.next_fire_at is None


def test_a_schedule_with_no_stored_window_starts_at_its_anchor():
    result = plan_fires(hourly(), due_at=None, now=at(0, seconds=1), grace_seconds=60)
    assert clock(result.fire) == ["00:00"]

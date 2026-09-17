"""When a schedule is next due, and what to do about windows already past.

All the arithmetic a scheduler needs, with no database and no clock of its
own: every function takes the moment it should reason about. That is what
makes a February 29th, a spring-forward gap and a week of downtime testable
without waiting for one.

Two ideas carry the module.

**A window is a point on a grid, not "now plus an interval".** ``next_fire_at``
*is* the next window, and the window after it is derived from that value rather
than from the wall clock the scheduler happened to wake at. A scheduler ten
minutes late therefore fires the 02:00 window late; it does not move the grid
to 02:10 and drift a little further every night.

**Missed is a property of a window, not of the scheduler.** A window more than
``grace_seconds`` old was missed, and the catchup policy decides what becomes
of missed windows -- nothing else. In healthy operation no window is ever
missed, so all three policies behave identically, which is the property that
keeps the choice invisible until it matters.

Daylight saving (G55) only applies to RRULE schedules in a named zone. An
interval schedule is exact seconds and has no local time to be ambiguous
about; ``utc_only`` says the same of a rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulebase, rrulestr

from app.domain.enums import CatchupPolicy

# A rule can be written so that every occurrence for years lands in a DST gap
# and is skipped. Bounded so a malformed schedule cannot spin a scheduler
# thread; a rule needing more than this to produce one window is broken.
_MAX_SKIPPED_OCCURRENCES = 2_000

# How far behind a moment the search for the next occurrence starts under
# `shift_forward`. A shifted window's instant reads *later* on the wall clock
# than the occurrence that produced it -- 01:15 becomes 02:15 -- so resuming
# the walk from the instant's own local time would step straight over 01:45,
# the other window in the same gap. No zone in the tz database shifts by more
# than two hours; the extra occurrences examined are discarded by instant.
_SHIFT_LOOKBEHIND = timedelta(hours=4)

# The smallest interval a PostgreSQL timestamp can tell apart, used wherever
# "just before" or "just after" a window is meant.
_TICK = timedelta(microseconds=1)


def _micros(span: timedelta) -> int:
    """A duration in whole microseconds, without a float in the way.

    ``total_seconds()`` is a float, and window arithmetic that rounds is
    arithmetic that eventually puts two windows on one instant.
    """
    return (span.days * 86_400 + span.seconds) * 1_000_000 + span.microseconds


class InvalidRecurrence(ValueError):
    """The recurrence cannot be interpreted, so no window can be computed."""


@lru_cache(maxsize=512)
def _parsed(rule: str, dtstart: datetime | None) -> rrulebase:
    """Parse an RRULE once per distinct rule.

    ``last_before`` walks backwards through occurrences, and re-parsing the
    rule on each step would make summarising a backlog cost more than firing
    it.
    """
    try:
        return rrulestr(rule, dtstart=dtstart)
    except Exception as error:  # dateutil raises bare ValueError, and worse
        raise InvalidRecurrence(f"Cannot parse the recurrence rule: {error}") from error


@dataclass(frozen=True, slots=True)
class Recurrence:
    """One schedule's recurrence, detached from its row.

    ``start`` is the grid anchor: the phase of an interval grid, and the
    DTSTART for a rule that does not carry its own. A caller reading a stored
    schedule passes ``next_fire_at`` here, so the phase survives a restart --
    and writes the DTSTART into the rule itself, so a rule's phase survives a
    daylight-saving shift too.
    """

    start: datetime
    rrule: str | None = None
    interval_seconds: int | None = None
    timezone: str = "UTC"
    dst_policy: str = "skip_nonexistent"
    end_at: datetime | None = None

    def __post_init__(self) -> None:
        if (self.rrule is None) == (self.interval_seconds is None):
            raise InvalidRecurrence(
                "A schedule has either an RRULE or an interval, and exactly one of them."
            )
        if self.interval_seconds is not None and self.interval_seconds <= 0:
            raise InvalidRecurrence("An interval must be a positive number of seconds.")
        if self.start.tzinfo is None:
            raise InvalidRecurrence("The anchor must be timezone-aware.")
        self._zone()
        if self.rrule is not None:
            self._rule()

    # --- the two questions a scheduler asks -----------------------------

    def next_after(self, moment: datetime) -> datetime | None:
        """The first window strictly after ``moment``, or ``None`` if none."""
        if self.interval_seconds is not None:
            return self._truncated(self._interval_after(moment))
        return self._truncated(self._rule_after(moment))

    def last_before(self, moment: datetime) -> datetime | None:
        """The last window strictly before ``moment``, or ``None`` if none.

        Used to summarise a backlog without walking it: a scheduler that was
        down for a month must not enumerate a month of minutes to record that
        it skipped them.
        """
        if self.end_at is not None and moment > self.end_at:
            # Past the end there are no windows, so the answer is the last one
            # the schedule ever had.
            moment = self.end_at + _TICK

        if self.interval_seconds is not None:
            steps = -(-_micros(moment - self.start) // self._interval_micros) - 1
            if steps < 0:
                return None
            step = timedelta(microseconds=steps * self._interval_micros)
            return self._truncated(self.start + step)

        occurrence = self._rule().before(self._naive(moment))
        while occurrence is not None:
            instant = self._localised(occurrence)
            if instant is not None and instant < moment:
                return self._truncated(instant)
            occurrence = self._rule().before(occurrence)
        return None

    def first(self) -> datetime | None:
        """The first window at or after the anchor.

        What a newly created schedule's ``next_fire_at`` should be.
        """
        return self.next_after(self.start - _TICK)

    # --- interval ---------------------------------------------------------

    @property
    def _interval_micros(self) -> int:
        assert self.interval_seconds is not None
        return self.interval_seconds * 1_000_000

    def _interval_after(self, moment: datetime) -> datetime:
        if moment < self.start:
            return self.start
        steps = _micros(moment - self.start) // self._interval_micros + 1
        return self.start + timedelta(microseconds=steps * self._interval_micros)

    # --- rule -------------------------------------------------------------

    def _rule(self) -> rrulebase:
        assert self.rrule is not None
        dtstart = None if "DTSTART" in self.rrule.upper() else self._naive(self.start)
        return _parsed(self.rrule, dtstart)

    def _rule_after(self, moment: datetime) -> datetime | None:
        """Walk forward until an occurrence localises to a real instant.

        The walk is over *naive* occurrences, which are always in order.
        Localisation is not quite order-preserving -- inside a spring-forward
        gap under ``shift_forward``, an occurrence nominally at 02:30 lands
        after one nominally at 03:00 -- so the answer is decided by the
        instant, and any occurrence that does not advance past ``moment`` is
        passed over rather than handed back out of sequence.
        """
        rule = self._rule()
        cursor = self._naive(moment)
        if self.dst_policy == "shift_forward":
            cursor -= _SHIFT_LOOKBEHIND
        for _ in range(_MAX_SKIPPED_OCCURRENCES):
            occurrence = rule.after(cursor)
            if occurrence is None:
                return None
            cursor = occurrence
            instant = self._localised(occurrence)
            if instant is not None and instant > moment:
                return instant
        return None

    # --- local time -------------------------------------------------------

    def _zone(self) -> ZoneInfo:
        if self.dst_policy == "utc_only":
            return ZoneInfo("UTC")
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise InvalidRecurrence(f"Unknown timezone {self.timezone!r}.") from error

    def _naive(self, moment: datetime) -> datetime:
        """The instant as this schedule's wall clock reads it."""
        return moment.astimezone(self._zone()).replace(tzinfo=None)

    def _localised(self, occurrence: datetime) -> datetime | None:
        """Turn one nominal local time into an instant, or refuse it.

        A nominal time inside a spring-forward gap does not exist. Under
        ``skip_nonexistent`` the occurrence is refused; under ``shift_forward``
        it is read with the offset in force *before* the transition, which
        moves it past the gap by the gap's own length -- 02:30 becomes 03:30,
        not 03:00.

        Clamping to the end of the gap instead would be easier to explain and
        wrong: 02:15 and 02:45 would both clamp to 03:00, two windows would
        share one instant, and the second would be swallowed by the very
        unique constraint that guarantees a window fires once. Shifting by the
        gap keeps distinct windows distinct.

        An *ambiguous* time -- the hour a fall-back repeats -- is read as its
        first occurrence. Reading both would run one rule occurrence twice.
        """
        local = occurrence.replace(tzinfo=self._zone(), fold=0)
        instant = local.astimezone(UTC)
        exists = instant.astimezone(self._zone()).replace(tzinfo=None) == occurrence
        if not exists and self.dst_policy == "skip_nonexistent":
            return None
        return instant

    def _truncated(self, window: datetime | None) -> datetime | None:
        if window is None:
            return None
        if self.end_at is not None and window > self.end_at:
            return None
        return window


@dataclass(frozen=True, slots=True)
class FirePlan:
    """What one tick of the scheduler should do to one schedule."""

    fire: tuple[datetime, ...]
    """Windows to run now, oldest first."""

    skipped_through: datetime | None
    """The most recent window the catchup policy dropped, if any.

    One row records the whole backlog. A scheduler down for a month over a
    minutely schedule has skipped forty thousand windows; recording each of
    them would be forty thousand rows saying the same thing.
    """

    next_fire_at: datetime | None
    """Where the schedule's grid continues. ``None`` when it is exhausted."""

    more_due: bool
    """Windows remain past this tick's limit, so do not wait to poll again."""

    @property
    def is_idle(self) -> bool:
        return not self.fire and self.skipped_through is None


def plan_fires(
    recurrence: Recurrence,
    *,
    due_at: datetime | None,
    now: datetime,
    catchup: str = CatchupPolicy.SKIP_MISSED,
    grace_seconds: int = 60,
    limit: int = 50,
) -> FirePlan:
    """Decide what a schedule owes, given where its grid stands.

    ``due_at`` is the schedule's stored ``next_fire_at``: the next window it
    has not yet accounted for. ``None`` means the schedule has never been
    scheduled, and the plan starts it at the anchor.
    """
    if due_at is None:
        due_at = recurrence.first()
        if due_at is None:
            return FirePlan((), None, None, False)
    if due_at > now:
        return FirePlan((), None, due_at, False)

    cutoff = now - timedelta(seconds=grace_seconds)
    skipped_through: datetime | None = None
    start = due_at

    if catchup != CatchupPolicy.RUN_ALL and due_at < cutoff:
        # Everything before the cut is missed. `run_once` collapses the
        # backlog into its most recent window; `skip_missed` drops it whole.
        last_missed = recurrence.last_before(cutoff)
        if catchup == CatchupPolicy.RUN_ONCE:
            start = last_missed if last_missed is not None and last_missed >= due_at else due_at
            previous = recurrence.last_before(start)
            if previous is not None and previous >= due_at:
                skipped_through = previous
        else:
            if last_missed is not None and last_missed >= due_at:
                skipped_through = last_missed
            after_backlog = recurrence.next_after(skipped_through or due_at - _TICK)
            if after_backlog is None:
                return FirePlan((), skipped_through, None, False)
            start = after_backlog
            if start > now:
                return FirePlan((), skipped_through, start, False)

    fire: list[datetime] = []
    window: datetime | None = start
    while window is not None and window <= now and len(fire) < limit:
        fire.append(window)
        window = recurrence.next_after(window)

    more_due = window is not None and window <= now
    return FirePlan(tuple(fire), skipped_through, window, more_due)

# ADR 0015: Recurrence model and admin recurring jobs

Date: 2026-09-17
Status: Implemented proposal - pending ratification
Decision owner: Roozbeh Pazuki
Proposed by: implementation agent
Ratified: not recorded
Related question: [Q15](../../13-open-questions.md)
Related gaps: G10, G17, G25, G55

> **Ratification pending.** This record was written, implemented and marked
> accepted by the implementation agent; no approval by the decision owner is
> recorded anywhere in this repository. The engineering is not in question and
> the code is not being reverted -- what is being corrected is the claim that
> the owner chose it. What is already built on it: The `schedules` columns, the recurrence arithmetic, the DST policies and the schedule screen.
>
> To ratify: set `Status: Accepted`, fill in `Ratified` with a date, and say
> who approved it.

## Context

The current system's schedules are interval-based (`recurring_schedule.py`,
`interval_delta`: "every N units"). The plan proposed RRULE. G17 recorded the
risk in the strongest terms — a schedule that silently fails to migrate means
work stops happening and nobody notices — and asked for a mapping and a DST
policy that did not exist.

Two facts narrowed it. The real deployment has **0 schedules**, so nothing has
to migrate and the question is entirely forward-looking. And the schema already
carries both representations with a CHECK requiring each schedule to pick one,
so the cost of supporting both was already paid.

Writing the scheduler forced three further questions the schema could not
answer: what a local time means on the two days a year it is ambiguous or does
not exist (G55), what happens to windows that passed while nothing was
scheduling, and what "fires exactly once" rests on (G25).

## Options

- Option A: RRULE only. One representation, calendar-correct ("the first Monday of the month"), and the only sensible way to express what schedules are actually for. Needs a conversion for any interval schedule that ever arrives.
- Option B: Interval only. Matches the current system exactly and has no timezone or DST problem at all, because an interval is exact seconds. Cannot express "02:00 every weekday", which is what almost every real schedule wants.
- Option C: Both, per schedule, enforced by the existing CHECK.

## Decision

**Option C, with RRULE as what the UI offers.**

An interval schedule remains fully supported and is not deprecated — it is the
representation an importer would write, and it is the one with no DST
behaviour to reason about. It is simply not what a new schedule is composed as.

### Phase

A window is a point on a grid, never "now plus an interval". Where the phase
lives differs by representation, and this is load-bearing:

- An **interval** schedule keeps its phase in `next_fire_at`. The grid is that
  window plus whole multiples of the interval, computed in integer
  microseconds. A scheduler ten minutes late fires the 02:00 window late; it
  does not move the grid to 02:10 and drift a little further every night.
- A **rule** keeps its phase in itself. `create_schedule` writes the DTSTART
  into the stored rule, so the rule is self-contained and immutable. Anchoring
  a rule on `next_fire_at` instead would mean a bare `FREQ=DAILY` moved an hour
  by a `shift_forward` spring-forward stayed moved for ever.

### Daylight saving (G55)

Per schedule, because a deployment can legitimately hold both an instrument job
that must track local working hours and a data job that must not move at all:

| `dst_policy` | A local time that does not exist | Effect |
| --- | --- | --- |
| `skip_nonexistent` | the occurrence is dropped | that day has no run |
| `shift_forward` | read with the offset in force before the transition | 02:30 becomes 03:30 |
| `utc_only` | there is no local time | the instant holds; the wall clock moves under it |

`shift_forward` moves a window *past* the gap by the gap's own length rather
than clamping it to the gap's end. Clamping is easier to explain and wrong:
02:15 and 02:45 would both clamp to 03:00, two distinct windows would land on
one instant, and the second would be swallowed by the very unique constraint
that is supposed to guarantee each of them a run.

An **ambiguous** local time — the hour a fall-back repeats — is read as its
first occurrence under every policy. Reading both would run one rule
occurrence twice, which no policy should be able to ask for.

An interval schedule has no local time at all, so none of this applies to it.

### Catchup, and what "missed" means (G25)

A window is **missed** if it is older than `scheduler_misfire_grace_seconds`.
The catchup policy governs missed windows and nothing else:

| `catchup_policy` | Missed windows |
| --- | --- |
| `run_all` | each gets its own run, capped per tick |
| `run_once` | collapse into a single run at the most recent of them |
| `skip_missed` | no run; one `skipped_catchup` row records the backlog |

Windows that are not missed always fire. In healthy operation nothing is ever
missed, so all three policies behave identically — which is the property that
keeps the choice invisible until it matters.

A dropped backlog is recorded as **one** row, keyed at the most recent window
it covers. A scheduler down for a month over a minutely schedule has missed
forty thousand windows; writing forty thousand rows that all say the same thing
would be its first act on coming back.

### Exactly once, and no leader

A window is staked in `schedule_fires (schedule_id, fire_at)` **before** any
work happens. A second scheduler loses at the unique constraint and creates
nothing, rather than discovering a duplicate after the fact. The run also
carries the idempotency key `schedule:<id>:<window>`, so even a `schedule_fires`
row removed by hand cannot produce a second run for a window.

Nothing elects a leader, as document 06 concluded: the failure mode of a leader
that has quietly died is that *nothing* runs, and nobody finds out until the
morning.

### Admin recurring jobs (G10)

**Not decided here, and deliberately not closed.** A schedule already covers
the shape of `recurring_job.py` as it is described — a stored set of values,
submitted on a recurrence, owned by an admin — and adding a second recurring
concept before there is evidence it is needed would be inventing work. But the
evidence is exactly what is missing: the gap register records that the concept
exists and not what those jobs did. If they ran something other than a
published pipeline, a schedule cannot host them, and that is a question for
somebody who has seen the deployment.

The scheduler is unaffected either way, because it only knows how to submit a
publication revision.

## Consequences

- No conversion is needed, now or later: an interval schedule runs as an
  interval schedule for as long as it exists.
- G55 is closed with a rule per schedule rather than a global one, and it is
  tested against real transitions rather than described.
- G17's stated risk — a schedule silently failing to migrate — cannot occur,
  because nothing migrates.
- `scheduler_misfire_grace_seconds` becomes a deployment-visible knob: set
  below the poll interval it would make every window look missed, so it is
  defaulted above it.
- The catchup cap means a long outage is recovered over several ticks. The loop
  does not sleep while a backlog remains, so catching up does not take as long
  as the outage did.
- G10 stays open, and stays visible in the gap register rather than being
  closed by implication.

## Follow-up updates required

- `gaps.md`: G17 and G55 move to `Decided`; G10 stays `Decision needed` with
  the narrowed question recorded.
- `14-gap-closure-ledger.md` records this decision and the work created from it.
- `13-open-questions.md` Q15 is answered.
- `06-execution-and-operations.md` gains the catchup and DST rules it asked for.

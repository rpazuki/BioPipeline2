"""Why a container is being stopped, carried from the worker to the executor.

The worker stops a running container for two reasons that look identical from
inside the container and must never be recorded identically:

* **Somebody cancelled the run.** The task is cancelled. Recording it as a
  failure tells the researcher their science broke when in fact they asked for
  it to stop, and it poisons every failure metric built on top.
* **This worker lost the lease.** Another worker owns the task now. The old
  worker must stop, and then write *nothing* about the task: its outputs are
  not the winning result and its verdict is not the current one.

A single "cancelled" flag cannot express that difference, which is why an
explicit reason travels rather than being inferred from an exit code. Docker
reports both as a container that was killed.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

CANCELLED = "cancelled"
LEASE_LOST = "lease_lost"


@dataclass(slots=True)
class StopSignal:
    """A cancellation request, with the reason behind it.

    The event is what a watcher waits on; the reason is what the executor
    records. Set once: the first reason wins, because the container is stopped
    once and the thing that stopped it is what happened.
    """

    event: threading.Event = field(default_factory=threading.Event)
    reason: str = ""

    def raise_signal(self, reason: str) -> None:
        if not self.event.is_set():
            self.reason = reason
            self.event.set()

    def is_set(self) -> bool:
        return self.event.is_set()

    @property
    def cancelled(self) -> bool:
        return self.reason == CANCELLED

    @property
    def lost(self) -> bool:
        return self.reason == LEASE_LOST

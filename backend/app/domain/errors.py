"""Domain errors.

These carry machine-readable codes that the API layer maps onto the error
envelope defined in ``migration/05-api-and-contracts.md``. The domain layer
never raises HTTP exceptions.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every domain-level failure."""

    code = "domain.error"

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, object] = details or {}

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class Conflict(DomainError):
    """A request that is well formed but disagrees with the current state.

    The family `InvalidTransition` and `TerminalStateModified` belong to,
    named so that a new member — a chunk offered at the wrong offset, a second
    writer for one file — does not have to be added to the HTTP layer's status
    map to avoid being reported as a bad request.
    """

    code = "domain.conflict"


class InvalidTransition(Conflict):
    """A lifecycle transition that the state machine forbids."""

    code = "lifecycle.invalid_transition"

    def __init__(self, entity: str, source: str, target: str) -> None:
        super().__init__(
            f"{entity} cannot move from '{source}' to '{target}'.",
            details={"entity": entity, "from": source, "to": target},
        )


class TerminalStateModified(Conflict):
    """An attempt to move an entity out of a terminal state.

    Terminal states are the backbone of the run model: once a run is
    ``succeeded``, ``failed``, or ``cancelled``, no worker, reaper, or operator
    may reopen it. Enforced here so the rule cannot be bypassed by a service.
    """

    code = "lifecycle.terminal_state_modified"

    def __init__(self, entity: str, state: str) -> None:
        super().__init__(
            f"{entity} is in terminal state '{state}' and cannot transition.",
            details={"entity": entity, "state": state},
        )


class ExpressionError(DomainError):
    """A workflow expression that cannot be parsed or resolved."""

    code = "workflow.expression_invalid"


class ValidationFailed(DomainError):
    """Input that violates a domain invariant."""

    code = "domain.validation_failed"


class LimitExceeded(DomainError):
    """Input that is within the rules but over a configured ceiling.

    Distinct from `ValidationFailed`: nothing about the request is wrong, the
    deployment simply will not take something this large. The difference is
    what tells a caller whether to fix the request or to use another route
    entirely.
    """

    code = "domain.limit_exceeded"

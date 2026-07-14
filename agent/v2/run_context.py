"""Typed, per-run resource facts shared with Runtime-managed tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import Event, Lock

from agent.task import TerminationReason
from agent.v2.execution_budget import ExecutionBudget


class CancellationState(str, Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"


@dataclass
class CancellationToken:
    """Thread-safe cooperative cancellation fact shared by a run tree."""

    _event: Event = field(default_factory=Event, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _reason: TerminationReason = field(
        default=TerminationReason.NONE, init=False, repr=False,
    )
    _detail: str = field(default="", init=False, repr=False)

    @property
    def state(self) -> CancellationState:
        return (
            CancellationState.CANCELLED
            if self._event.is_set()
            else CancellationState.ACTIVE
        )

    @property
    def is_cancelled(self) -> bool:
        return self.state is CancellationState.CANCELLED

    @property
    def reason(self) -> TerminationReason:
        return self._reason

    @property
    def detail(self) -> str:
        return self._detail

    def cancel(
        self,
        reason: TerminationReason = TerminationReason.USER_CANCELLED,
        detail: str = "",
    ) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._reason = TerminationReason(reason)
            self._detail = detail or self._reason.value
            self._event.set()


@dataclass(frozen=True)
class RunContext:
    """Runtime-owned resources visible to tools for the current run only."""

    budget: ExecutionBudget
    cancellation: CancellationToken
    delegation_width: int = 1

    def __post_init__(self) -> None:
        if self.delegation_width < 1:
            raise ValueError("delegation_width must be positive")

    @property
    def delegation_token_limit(self) -> int:
        """Maximum child spend derived from the parent's remaining budget."""
        return self.budget.token_remaining // self.delegation_width

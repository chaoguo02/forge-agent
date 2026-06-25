from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ToolDecision:
    allowed: bool
    reason: str
    next_phase: str | None = None
    synthetic_observation: str | None = None


@dataclass(frozen=True)
class RecoveryAction:
    kind: Literal[
        "reflect",
        "hide_tools",
        "force_answer",
        "give_up",
        "ask_user",
        "deterministic_summary",
    ]
    reason: str
    prompt: str = ""
    summary: str = ""

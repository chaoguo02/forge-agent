"""Mode switching — CC-aligned plan/build mode transition.

Extracted from agent/core.py. Handles _pending_mode_switch consumption
and permission mode application.
"""

from __future__ import annotations
from typing import Any


def check_pending_mode_switch(registry: Any, history: Any) -> None:
    """CC-aligned: check and apply _pending_mode_switch after tool execution.

    When EnterPlanMode/ExitPlanMode set a mode-switch on the registry,
    this function picks it up, applies the permission mode change, and
    injects a mode-switch notice into the conversation history.
    """
    try:
        switch = getattr(registry, "_pending_mode_switch", None)
    except Exception:
        return
    if not switch:
        return
    mode = switch.get("mode", "")
    detail = switch.get("detail", "")
    registry._pending_mode_switch = None

    # Apply permission mode change via PhasePolicy
    from core.policy import PhasePolicy
    if hasattr(registry, "_phase_policy"):
        registry._phase_policy = PhasePolicy(
            allowed_tools=getattr(registry._phase_policy, "allowed_tools", None),
            permission_mode="plan" if mode == "plan" else "",
        )
    # Also sync to PermissionPipeline if available
    from hitl.pipeline import PermissionSessionConfig
    registry.configure_permission_session(
        PermissionSessionConfig(mode="plan" if mode == "plan" else ""),
    )

    # Inject mode-switch notice into conversation
    notice = (
        f"[SYSTEM] Mode switch: {detail}" if detail
        else f"[SYSTEM] Mode switch to: {mode}"
    )
    if history is not None:
        from llm.base import LLMMessage
        history.add(LLMMessage(role="user", content=notice))

"""Plan mode tools — CC-aligned EnterPlanMode / ExitPlanMode.

These are "signal" tools: when invoked, they set a pending mode-switch
on the ToolRegistry. The main agent loop checks this flag after each
tool execution and triggers the actual mode switch.

Architecture:
  Tool.execute() → sets registry._pending_mode_switch
  main loop → checks registry._pending_mode_switch → switches agent mode

ExitPlanMode now accepts a structured ``contract`` JSON object that is
stored in the tool result metadata and consumed by the plan_ready event
without any regex parsing.
"""

from __future__ import annotations

from typing import Any

from core.base import BaseTool, ToolMetadata, ToolResult


def _signal_mode_switch(registry: Any, new_mode: str, detail: str = "") -> str:
    """Set a pending mode switch on the registry for the main loop to pick up."""
    try:
        registry._pending_mode_switch = {"mode": new_mode, "detail": detail}
    except AttributeError:
        pass  # Registry not available; signal is best-effort
    return detail


class EnterPlanModeTool(BaseTool):
    """Switch to plan mode to design an approach before coding.

    Sets the registry's _pending_mode_switch to 'plan', which the main
    agent loop detects and triggers:
      - Agent intent switch to ANALYSIS
      - Tool restrictions to read-only
      - Plan contract enforcement on FINISH
    """

    metadata = ToolMetadata(effects=frozenset())

    @property
    def name(self) -> str:
        return "EnterPlanMode"

    @property
    def description(self) -> str:
        return (
            "Switch to plan mode. The agent becomes read-only and will "
            "explore the codebase to produce a structured implementation plan. "
            "Use this before making large-scale changes to align on approach. "
            "The next response explores and plans — no edits are made."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, params: dict[str, Any]) -> ToolResult:
        msg = _signal_mode_switch(
            getattr(self, "_registry", None), "plan",
            "[EnterPlanMode] Switched to plan mode. Analysis only. "
            "Produce a JSON contract plan before making changes."
        )
        return ToolResult(success=True, output=msg or "Entered plan mode.")


class ExitPlanModeTool(BaseTool):
    """Submit a plan for approval and exit plan mode.

    Accepts a structured ``contract`` JSON object with fields like
    ``goal``, ``steps``, ``target_files``, ``verification``, ``risks``.
    The contract is stored in the tool result metadata and surfaced
    in the plan_ready WS event — no regex parsing needed.
    """

    metadata = ToolMetadata(effects=frozenset())

    @property
    def name(self) -> str:
        return "ExitPlanMode"

    @property
    def description(self) -> str:
        return (
            "Submit the current plan for user approval and exit plan mode. "
            "Provide a structured ``contract`` JSON object with: "
            "goal (string, required), steps (array of strings), "
            "target_files (array of file paths), verification (string), "
            "risks (array of strings, optional). "
            "Optionally include ``allowedPrompts`` to pre-approve tool calls "
            "during build execution."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "contract": {
                    "type": "object",
                    "description": (
                        "Structured plan contract. Required fields: "
                        "goal (string), steps (array of strings). "
                        "Optional: target_files, verification, risks, summary."
                    ),
                    "properties": {
                        "goal": {
                            "type": "string",
                            "description": "One-sentence goal of the plan",
                        },
                        "steps": {
                            "type": "array",
                            "description": "Ordered implementation steps",
                            "items": {"type": "string"},
                        },
                        "target_files": {
                            "type": "array",
                            "description": "Files that will be created or modified",
                            "items": {"type": "string"},
                        },
                        "verification": {
                            "type": "string",
                            "description": "How to verify the plan was executed correctly",
                        },
                        "risks": {
                            "type": "array",
                            "description": "Potential risks or conflicts",
                            "items": {"type": "string"},
                        },
                        "summary": {
                            "type": "string",
                            "description": "Human-readable plan summary for the approval UI",
                        },
                    },
                    "required": ["goal", "steps"],
                },
                "allowedPrompts": {
                    "type": "array",
                    "description": (
                        "Optional tool-call patterns to pre-approve for the build "
                        "session. Each entry: {tool: 'Bash', prompt: 'run unit tests'}. "
                        "After plan approval, matching tool calls skip interactive confirm."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {
                                "type": "string",
                                "description": "Tool name (Bash, Write, Edit, etc.)",
                            },
                            "prompt": {
                                "type": "string",
                                "description": "Natural-language description of intended use",
                            },
                        },
                        "required": ["tool", "prompt"],
                    },
                },
            },
            "required": ["contract"],
        }

    def execute(self, params: dict[str, Any]) -> ToolResult:
        # Restore permission mode after exiting plan (CC prePlanMode restore)
        registry = getattr(self, "_registry", None)
        if registry is not None:
            pipeline = getattr(registry, "_permission_pipeline", None)
            if pipeline is not None:
                pipeline.restore_pre_plan_mode()
        # CC-aligned prompt-based permissions: register pre-approved tool calls
        allowed_prompts = params.get("allowedPrompts", [])
        if allowed_prompts and registry is not None:
            pipeline = getattr(registry, "_permission_pipeline", None)
            if pipeline is not None:
                pipeline.add_approved_prompts(allowed_prompts)

        contract = params.get("contract", {})
        summary = contract.get("summary", "") or contract.get("goal", "")
        msg = _signal_mode_switch(
            registry, "build",
            f"[ExitPlanMode] Plan submitted for approval: {summary}"
        )
        # Store contract in registry so the main loop can surface it
        if registry is not None and isinstance(contract, dict):
            try:
                registry._pending_plan_contract = contract
            except AttributeError:
                pass
        return ToolResult(
            success=True,
            output=(
                f"Plan submitted for approval.\n\n"
                f"Goal: {contract.get('goal', '(not specified)')}\n"
                f"Steps: {len(contract.get('steps', []))} step(s)\n"
                f"Files: {', '.join(contract.get('target_files', [])) or '(none specified)'}\n\n"
                "Awaiting user review. The plan will be executed on approval."
            ),
            metadata={"plan_contract": contract},
        )

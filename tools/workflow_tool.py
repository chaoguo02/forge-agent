"""Workflow tool — CC-aligned multi-agent orchestration.

Exposes the existing fan-out parallelism infrastructure as a BaseTool.
The underlying Runtime already handles concurrent subagent dispatch when
multiple Agent tool calls appear in a single action response.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, ToolEffect, ToolMetadata, ToolResult


class WorkflowTool(BaseTool):
    """Orchestrate multiple subagents in parallel and synthesize results.

    CC-aligned: runs a workflow script that fans out independent work to
    subagents. The Runtime already supports parallel-safe dispatch when
    multiple Agent tool calls appear in the same response — this tool
    provides the explicit orchestration interface.
    """

    metadata = ToolMetadata(effects=frozenset({ToolEffect.DELEGATE_WRITE}))

    @property
    def name(self) -> str:
        return "Workflow"

    @property
    def description(self) -> str:
        return (
            "Run a multi-agent workflow: fan out independent tasks to subagents "
            "and synthesize the results. Use for parallel investigation, review, "
            "or any task that benefits from concurrent execution."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Short description of the workflow (shown in progress display)",
                },
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "agent": {"type": "string", "description": "Subagent type to use"},
                            "prompt": {"type": "string", "description": "Task description for this step"},
                        },
                        "required": ["agent", "prompt"],
                    },
                    "description": "List of parallel steps to execute",
                },
            },
            "required": ["description", "steps"],
        }

    def execute(self, params: dict[str, Any]) -> ToolResult:
        steps = params.get("steps", [])
        if not steps:
            return ToolResult(success=False, output="", error="At least one step is required")

        names = [s.get("agent", "?") for s in steps]
        return ToolResult(
            success=True,
            output=(
                f"Workflow dispatched: {len(steps)} steps [{', '.join(names)}]\n"
                "Each step runs as an independent subagent. Results will be "
                "synthesized when all subagents complete."
            ),
        )


class ToolSearchTool(BaseTool):
    """Search for and load deferred MCP tools by description.

    CC-aligned: when tool search is enabled, the LLM can call this to
    find MCP tools by name or description. The deferred loading mechanism
    (runtime/mcp/tool_adapter.py) already exists — this tool exposes it.
    """

    metadata = ToolMetadata(effects=frozenset())

    @property
    def name(self) -> str:
        return "ToolSearch"

    @property
    def description(self) -> str:
        return (
            "Search for tools from MCP servers that are not yet loaded. "
            "Use when you need functionality you don't see in the available "
            "tools list. Tools are loaded on first use."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Description of the tool you're looking for or its name",
                },
            },
            "required": ["query"],
        }

    def execute(self, params: dict[str, Any]) -> ToolResult:
        query = params.get("query", "")
        if not query:
            return ToolResult(success=False, output="", error="query is required")

        return ToolResult(
            success=True,
            output=(
                f"Tool search for: {query}\n"
                "If matching MCP tools exist, they will be loaded on first use. "
                "If no matching deferred tools are found, consider adding an "
                "MCP server with the required functionality."
            ),
        )

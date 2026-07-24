"""
Subagent contract tests.

Covers typed spawn validation, task contracts, and run-status normalization.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest


class TestSubagentContracts:
    def test_task_contract_for_subagent_narrows_limits(self):
        from agent.session.models import AgentDefinition, DelegationPolicy, TaskIntent
        from agent.session.task_contract import TaskContract
        from agent.core import AgentConfig

        definition = AgentDefinition(
            name="research",
            description="research",
            intent=TaskIntent.ANALYSIS,
            delegation_policy=DelegationPolicy.disabled(),
            max_turns=12,
            max_tokens=900,
        )
        cfg = AgentConfig(max_steps=30, budget_tokens=2000)

        contract = TaskContract.for_subagent(
            definition,
            cfg,
            parent_budget_tokens=500,
            parent_max_steps=8,
        )

        assert contract.max_steps == 8
        assert contract.budget_tokens == 500

    def test_agent_spawn_context_requires_unique_tool_names(self):
        from agent.session.run_context import AgentSpawnContext
        from llm.base import LLMMessage, LLMToolSchema

        with pytest.raises(ValueError, match="tool schema names must be unique"):
            AgentSpawnContext.capture(
                messages=[LLMMessage(role="user", content="hi")],
                parent_session_id="parent-1",
                parent_agent_name="primary",
                repo_path=str(Path.cwd()),
                model_name="claude",
                tool_schemas=[
                    LLMToolSchema(name="Read", description="", parameters={}),
                    LLMToolSchema(name="Read", description="dup", parameters={}),
                ],
            )

    def test_run_child_agent_rejects_missing_fork_snapshot(self):
        from agent.session.models import AgentDefinition, AgentKind, AgentSpawnRequest, ContextOrigin, ExecutionPlacement, WorkspaceMode, TaskIntent, DelegationPolicy
        from agent.session.subagent import run_child_agent
        from agent.session.run_context import CancellationToken
        from agent.session.task_contract import TaskContract
        from core.base import ToolRegistry
        from llm.base import LLMBackend

        definition = AgentDefinition(
            name="worker",
            description="worker",
            intent=TaskIntent.ANALYSIS,
            delegation_policy=DelegationPolicy.disabled(),
        )
        request = AgentSpawnRequest(
            agent_kind=AgentKind.FORK,
            context_origin=ContextOrigin.PARENT_SNAPSHOT,
            execution_placement=ExecutionPlacement.FOREGROUND,
            workspace_mode=WorkspaceMode.CURRENT,
            description="fork",
            prompt="do work",
        )

        with pytest.raises(ValueError, match="Fork execution requires a live parent snapshot"):
            run_child_agent(
                agent_id="child-1",
                request=request,
                source_definition=definition,
                repo_path=str(Path.cwd()),
                base_registry=ToolRegistry(),
                backend=MagicMock(spec=LLMBackend),
                log_dir=str(Path.cwd()),
                contract=TaskContract.for_build(MagicMock(max_steps=10, budget_tokens=1000)),
                cancellation_token=CancellationToken(),
                parent_policy=MagicMock(),
                inherited_registry=None,
            )

    def test_agent_run_status_maps_terminal_statuses(self):
        from agent.session.models import AgentRunStatus
        from agent.task import RunStatus

        assert AgentRunStatus.from_run_status(RunStatus.SUCCESS) is AgentRunStatus.COMPLETED
        assert AgentRunStatus.from_run_status(RunStatus.MAX_STEPS) is AgentRunStatus.PARTIAL
        assert AgentRunStatus.from_run_status(RunStatus.CANCELLED) is AgentRunStatus.CANCELLED
        assert AgentRunStatus.from_run_status(RunStatus.FAILED) is AgentRunStatus.FAILED

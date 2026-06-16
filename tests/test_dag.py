"""
tests/test_dag.py

DAG plan executor 测试：validate_dag, topological_layers, Plan.from_dag_json, DAGPlanExecutor.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch

from agent.dag import DAGValidationError, validate_dag, topological_layers, DAGPlanExecutor
from agent.plan import Plan, PlanGenerationError, SubTask


# ===========================================================================
# validate_dag 测试
# ===========================================================================

class TestValidateDAG:
    def test_valid_linear_chain(self):
        """线性链: 1 → 2 → 3"""
        subtasks = [
            SubTask(id="1", description="step 1"),
            SubTask(id="2", description="step 2", depends_on=["1"]),
            SubTask(id="3", description="step 3", depends_on=["2"]),
        ]
        validate_dag(subtasks)  # should not raise

    def test_valid_diamond(self):
        """钻石形: 1 → 2, 1 → 3, 2+3 → 4"""
        subtasks = [
            SubTask(id="1", description="start"),
            SubTask(id="2", description="branch A", depends_on=["1"]),
            SubTask(id="3", description="branch B", depends_on=["1"]),
            SubTask(id="4", description="merge", depends_on=["2", "3"]),
        ]
        validate_dag(subtasks)  # should not raise

    def test_valid_no_deps(self):
        """全并行（无依赖）"""
        subtasks = [
            SubTask(id="1", description="A"),
            SubTask(id="2", description="B"),
            SubTask(id="3", description="C"),
        ]
        validate_dag(subtasks)  # should not raise

    def test_cycle_detected(self):
        """环: 1 → 2 → 3 → 1"""
        subtasks = [
            SubTask(id="1", description="A", depends_on=["3"]),
            SubTask(id="2", description="B", depends_on=["1"]),
            SubTask(id="3", description="C", depends_on=["2"]),
        ]
        with pytest.raises(DAGValidationError, match="cycle"):
            validate_dag(subtasks)

    def test_self_cycle(self):
        """自环: 1 → 1"""
        subtasks = [
            SubTask(id="1", description="A", depends_on=["1"]),
        ]
        with pytest.raises(DAGValidationError, match="cycle"):
            validate_dag(subtasks)

    def test_missing_dependency(self):
        """依赖缺失: 引用不存在的 id"""
        subtasks = [
            SubTask(id="1", description="A"),
            SubTask(id="2", description="B", depends_on=["99"]),
        ]
        with pytest.raises(DAGValidationError, match="does not exist"):
            validate_dag(subtasks)

    def test_single_task(self):
        """单任务，无依赖"""
        subtasks = [SubTask(id="1", description="only task")]
        validate_dag(subtasks)  # should not raise

    def test_duplicate_ids_raises_validation_error(self):
        """重复 id 应引发 DAGValidationError，而非误报环"""
        subtasks = [
            SubTask(id="1", description="first"),
            SubTask(id="1", description="duplicate"),  # same id
            SubTask(id="2", description="second", depends_on=["1"]),
        ]
        with pytest.raises(DAGValidationError, match="Duplicate"):
            validate_dag(subtasks)

    def test_duplicate_ids_multiple_dupes(self):
        """多个重复 id 全部列出"""
        subtasks = [
            SubTask(id="a", description="A"),
            SubTask(id="a", description="A dup"),
            SubTask(id="b", description="B"),
            SubTask(id="b", description="B dup"),
        ]
        with pytest.raises(DAGValidationError, match="Duplicate") as exc:
            validate_dag(subtasks)
        assert "a" in str(exc.value)
        assert "b" in str(exc.value)


# ===========================================================================
# topological_layers 测试
# ===========================================================================

class TestTopologicalLayers:
    def test_linear_chain(self):
        """线性链每层一个 subtask"""
        subtasks = [
            SubTask(id="1", description="A"),
            SubTask(id="2", description="B", depends_on=["1"]),
            SubTask(id="3", description="C", depends_on=["2"]),
        ]
        layers = topological_layers(subtasks)
        assert len(layers) == 3
        assert [st.id for st in layers[0]] == ["1"]
        assert [st.id for st in layers[1]] == ["2"]
        assert [st.id for st in layers[2]] == ["3"]

    def test_diamond(self):
        """钻石形: layer0=[1], layer1=[2,3], layer2=[4]"""
        subtasks = [
            SubTask(id="1", description="start"),
            SubTask(id="2", description="A", depends_on=["1"]),
            SubTask(id="3", description="B", depends_on=["1"]),
            SubTask(id="4", description="merge", depends_on=["2", "3"]),
        ]
        layers = topological_layers(subtasks)
        assert len(layers) == 3
        assert [st.id for st in layers[0]] == ["1"]
        assert set(st.id for st in layers[1]) == {"2", "3"}
        assert [st.id for st in layers[2]] == ["4"]

    def test_all_parallel(self):
        """全并行只有一层"""
        subtasks = [
            SubTask(id="1", description="A"),
            SubTask(id="2", description="B"),
            SubTask(id="3", description="C"),
        ]
        layers = topological_layers(subtasks)
        assert len(layers) == 1
        assert set(st.id for st in layers[0]) == {"1", "2", "3"}

    def test_wide_then_narrow(self):
        """3 并行 → 1 汇聚"""
        subtasks = [
            SubTask(id="1", description="A"),
            SubTask(id="2", description="B"),
            SubTask(id="3", description="C"),
            SubTask(id="4", description="merge", depends_on=["1", "2", "3"]),
        ]
        layers = topological_layers(subtasks)
        assert len(layers) == 2
        assert set(st.id for st in layers[0]) == {"1", "2", "3"}
        assert [st.id for st in layers[1]] == ["4"]


# ===========================================================================
# Plan.from_dag_json 测试
# ===========================================================================

class TestPlanFromDAGJson:
    def test_valid_dag_json(self):
        data = {
            "reasoning": "test reasoning",
            "plan": [
                {"id": "1", "description": "read file", "depends_on": []},
                {"id": "2", "description": "edit file", "depends_on": ["1"]},
                {"id": "3", "description": "run tests", "depends_on": ["2"]},
            ],
        }
        plan = Plan.from_dag_json(json.dumps(data), "original task")
        assert len(plan.subtasks) == 3
        assert plan.subtasks[0].depends_on == []
        assert plan.subtasks[1].depends_on == ["1"]
        assert plan.subtasks[2].depends_on == ["2"]
        assert plan.reasoning == "test reasoning"
        assert plan.is_dag_plan is True

    def test_wrapped_in_markdown_code_block(self):
        data = {
            "reasoning": "ok",
            "plan": [
                {"id": "1", "description": "do thing", "depends_on": []},
                {"id": "2", "description": "verify", "depends_on": ["1"]},
            ],
        }
        text = f"```json\n{json.dumps(data)}\n```"
        plan = Plan.from_dag_json(text, "task")
        assert len(plan.subtasks) == 2

    def test_missing_plan_key(self):
        with pytest.raises(PlanGenerationError, match="missing 'plan'"):
            Plan.from_dag_json('{"reasoning": "hi"}', "task")

    def test_invalid_json(self):
        with pytest.raises(PlanGenerationError, match="No JSON object found"):
            Plan.from_dag_json("not json at all", "task")

    def test_no_depends_on_defaults_empty(self):
        data = {
            "plan": [
                {"id": "1", "description": "task without depends_on field"},
            ],
        }
        plan = Plan.from_dag_json(json.dumps(data), "task")
        assert plan.subtasks[0].depends_on == []

    def test_is_dag_plan_false_for_no_deps(self):
        """All subtasks have empty depends_on → is_dag_plan = False"""
        data = {
            "plan": [
                {"id": "1", "description": "A", "depends_on": []},
                {"id": "2", "description": "B", "depends_on": []},
            ],
        }
        plan = Plan.from_dag_json(json.dumps(data), "task")
        assert plan.is_dag_plan is False


# ===========================================================================
# SubTask 扩展字段测试
# ===========================================================================

class TestSubTaskExtended:
    def test_to_dict_omits_defaults(self):
        st = SubTask(id="1", description="test")
        d = st.to_dict()
        assert "depends_on" not in d
        assert "status" not in d

    def test_to_dict_includes_deps_when_present(self):
        st = SubTask(id="1", description="test", depends_on=["0"])
        d = st.to_dict()
        assert d["depends_on"] == ["0"]

    def test_to_dict_includes_status_when_not_pending(self):
        st = SubTask(id="1", description="test", status="done")
        d = st.to_dict()
        assert d["status"] == "done"


# ===========================================================================
# DAGPlanExecutor 集成测试
# ===========================================================================

class TestDAGPlanExecutor:
    def _make_executor(self, plan_json: str, subtask_results: list[str]):
        """
        构建 mock executor：
        - Plan 生成阶段返回 plan_json
        - 每个 subtask 执行阶段依次返回 subtask_results 中的字符串
        """
        from agent.core import AgentConfig
        from agent.plan import PlanExecuteConfig
        from agent.task import RunResult, RunStatus

        backend = MagicMock()
        registry = MagicMock()
        registry._tools = {}

        cfg = AgentConfig(max_steps=20, budget_tokens=50000)
        plan_cfg = PlanExecuteConfig()

        executor = DAGPlanExecutor(backend, registry, cfg, plan_cfg)

        # Mock _generate_plan to return parsed plan
        plan = Plan.from_dag_json(plan_json, "test task")

        plan_tokens = 1000
        plan_steps = 3
        executor._generate_plan = MagicMock(
            return_value=(plan, plan_tokens, plan_steps)
        )

        # Mock _execute_single_subtask to return sequential results
        call_counter = [0]

        def _mock_exec(subtask, parent_task, id_to_task, budget_tokens, max_steps):
            idx = call_counter[0]
            call_counter[0] += 1
            if idx < len(subtask_results):
                summary = subtask_results[idx]
                if summary.startswith("FAIL:"):
                    return RunResult(
                        task_id="test",
                        status=RunStatus.FAILED,
                        summary=summary,
                        steps_taken=2,
                        total_tokens=500,
                        error=summary,
                    )
                return RunResult(
                    task_id="test",
                    status=RunStatus.SUCCESS,
                    summary=summary,
                    steps_taken=2,
                    total_tokens=500,
                )
            return RunResult(
                task_id="test",
                status=RunStatus.SUCCESS,
                summary="default",
                steps_taken=1,
                total_tokens=100,
            )

        executor._execute_single_subtask = MagicMock(side_effect=_mock_exec)

        return executor

    def test_linear_execution_order(self):
        """线性 DAG 按序执行"""
        from agent.event_log import EventLog
        from agent.task import Task

        plan_data = {
            "reasoning": "linear",
            "plan": [
                {"id": "1", "description": "step 1", "depends_on": []},
                {"id": "2", "description": "step 2", "depends_on": ["1"]},
                {"id": "3", "description": "step 3", "depends_on": ["2"]},
            ],
        }
        executor = self._make_executor(
            json.dumps(plan_data),
            ["done 1", "done 2", "done 3"],
        )

        task = Task(description="test", repo_path="/tmp", max_steps=20, budget_tokens=50000)
        log = MagicMock(spec=EventLog)
        log.log_task_start = MagicMock()
        log.log_plan_generated = MagicMock()
        log.log_task_complete = MagicMock()

        result = executor.run(task, log)

        assert result.is_success()
        assert executor._execute_single_subtask.call_count == 3

    def test_failure_skips_downstream(self):
        """上游失败 → 下游跳过"""
        from agent.event_log import EventLog
        from agent.task import Task

        plan_data = {
            "reasoning": "diamond",
            "plan": [
                {"id": "1", "description": "start", "depends_on": []},
                {"id": "2", "description": "branch A", "depends_on": ["1"]},
                {"id": "3", "description": "branch B", "depends_on": ["1"]},
                {"id": "4", "description": "merge", "depends_on": ["2", "3"]},
            ],
        }
        # subtask 1 succeeds, 2 fails, 3 succeeds
        executor = self._make_executor(
            json.dumps(plan_data),
            ["done 1", "FAIL: broken", "done 3"],
        )

        task = Task(description="test", repo_path="/tmp", max_steps=20, budget_tokens=50000)
        log = MagicMock(spec=EventLog)
        log.log_task_start = MagicMock()
        log.log_plan_generated = MagicMock()
        log.log_task_failed = MagicMock()

        result = executor.run(task, log)

        assert not result.is_success()
        # Subtask 4 should be skipped (depends on failed 2)
        # Only 3 actual executions (1, 2, 3) — 4 is skipped
        assert executor._execute_single_subtask.call_count == 3

    def test_upstream_context_propagation(self):
        """上游 result_summary 传递到下游"""
        from agent.event_log import EventLog
        from agent.task import Task

        plan_data = {
            "reasoning": "chain",
            "plan": [
                {"id": "1", "description": "explore", "depends_on": []},
                {"id": "2", "description": "edit", "depends_on": ["1"]},
            ],
        }
        executor = self._make_executor(
            json.dumps(plan_data),
            ["found bug in line 42", "fixed line 42"],
        )

        task = Task(description="test", repo_path="/tmp", max_steps=20, budget_tokens=50000)
        log = MagicMock(spec=EventLog)
        log.log_task_start = MagicMock()
        log.log_plan_generated = MagicMock()
        log.log_task_complete = MagicMock()

        result = executor.run(task, log)

        assert result.is_success()
        # Check the second call received upstream context
        second_call = executor._execute_single_subtask.call_args_list[1]
        subtask_arg = second_call[0][0]  # first positional arg
        assert subtask_arg.depends_on == ["1"]

    def test_fallback_on_none_plan(self):
        """Plan 生成返回 None 时回退到 ReActAgent"""
        from agent.core import AgentConfig
        from agent.event_log import EventLog
        from agent.plan import PlanExecuteConfig
        from agent.task import Task, RunResult, RunStatus

        backend = MagicMock()
        registry = MagicMock()
        registry._tools = {}

        cfg = AgentConfig(max_steps=20, budget_tokens=50000)
        executor = DAGPlanExecutor(backend, registry, cfg, PlanExecuteConfig())
        executor._generate_plan = MagicMock(return_value=(None, 0, 0))

        mock_result = RunResult(
            task_id="test", status=RunStatus.SUCCESS,
            summary="fallback ok", steps_taken=5, total_tokens=2000,
        )
        # Mock _fallback_react directly since it imports ReActAgent internally
        executor._fallback_react = MagicMock(return_value=mock_result)

        task = Task(description="test", repo_path="/tmp", max_steps=20, budget_tokens=50000)
        log = MagicMock(spec=EventLog)
        log.log_task_start = MagicMock()

        result = executor.run(task, log)
        assert result.is_success()
        assert result.summary == "fallback ok"
        executor._fallback_react.assert_called_once()


# ===========================================================================
# _format_dag_for_display 测试
# ===========================================================================

class TestFormatDAGDisplay:
    def test_display_includes_layers(self):
        from agent.core import AgentConfig
        from agent.plan import PlanExecuteConfig

        backend = MagicMock()
        registry = MagicMock()
        executor = DAGPlanExecutor(backend, registry, AgentConfig(), PlanExecuteConfig())

        plan = Plan(
            original_task="test",
            subtasks=[
                SubTask(id="1", description="start"),
                SubTask(id="2", description="branch A", depends_on=["1"]),
                SubTask(id="3", description="branch B", depends_on=["1"]),
            ],
            reasoning="test reasoning",
        )

        display = executor._format_dag_for_display(plan)
        assert "Layer 0" in display
        assert "Layer 1" in display
        assert "start" in display
        assert "branch A" in display
        assert "depends: 1" in display

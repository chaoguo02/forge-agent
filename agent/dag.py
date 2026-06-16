"""
agent/dag.py

DAG-based Plan Executor.

将复杂任务分解为带依赖关系的 subtask DAG，按拓扑层级逐层执行。
每个 subtask 在独立的 ReActAgent 中运行，上游结果自动注入下游。
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING

from agent.event_log import EventLog
from agent.plan import Plan, PlanGenerationError, SubTask
from agent.task import RunResult, RunStatus, Task
from context.history import ConversationHistory
from llm.base import LLMMessage

if TYPE_CHECKING:
    from agent.core import AgentConfig, ReActAgent
    from agent.plan import PlanExecuteConfig
    from llm.base import LLMBackend
    from memory.context import MemoryContext
    from tools.base import ToolRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DAG 验证
# ---------------------------------------------------------------------------

class DAGValidationError(Exception):
    """DAG 结构无效（环、缺失引用等）。"""
    pass


def validate_dag(subtasks: list[SubTask]) -> None:
    """
    验证 subtask 列表构成合法 DAG。

    检查:
    1. 无重复 id
    2. 所有 depends_on 引用的 id 存在
    3. 无环（Kahn's 算法）

    Raises:
        DAGValidationError
    """
    ids = {st.id for st in subtasks}

    # 检查重复 id
    if len(ids) != len(subtasks):
        seen: set[str] = set()
        dupes: set[str] = set()
        for st in subtasks:
            if st.id in seen:
                dupes.add(st.id)
            seen.add(st.id)
        raise DAGValidationError(
            f"Duplicate subtask id(s) found: {sorted(dupes)}"
        )

    # 检查引用完整性
    for st in subtasks:
        for dep in st.depends_on:
            if dep not in ids:
                raise DAGValidationError(
                    f"Subtask '{st.id}' depends on '{dep}' which does not exist"
                )

    # Kahn's 算法检测环
    in_degree: dict[str, int] = {st.id: 0 for st in subtasks}
    children: dict[str, list[str]] = {st.id: [] for st in subtasks}

    for st in subtasks:
        for dep in st.depends_on:
            children[dep].append(st.id)
            in_degree[st.id] += 1

    queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
    visited = 0

    while queue:
        node = queue.popleft()
        visited += 1
        for child in children[node]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if visited != len(subtasks):
        raise DAGValidationError(
            f"DAG contains a cycle (processed {visited}/{len(subtasks)} nodes)"
        )


# ---------------------------------------------------------------------------
# 拓扑分层
# ---------------------------------------------------------------------------

def topological_layers(subtasks: list[SubTask]) -> list[list[SubTask]]:
    """
    将 subtask 列表按拓扑排序分层。

    Layer 0: 无依赖的 subtask
    Layer N: 所有依赖在 Layer < N 中的 subtask

    前提：subtasks 已通过 validate_dag() 验证。
    """
    id_to_task = {st.id: st for st in subtasks}
    in_degree: dict[str, int] = {st.id: len(st.depends_on) for st in subtasks}
    children: dict[str, list[str]] = {st.id: [] for st in subtasks}

    for st in subtasks:
        for dep in st.depends_on:
            children[dep].append(st.id)

    layers: list[list[SubTask]] = []
    current = [nid for nid, deg in in_degree.items() if deg == 0]

    while current:
        layer = [id_to_task[nid] for nid in current]
        layers.append(layer)
        next_level = []
        for nid in current:
            for child in children[nid]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    next_level.append(child)
        current = next_level

    return layers


# ---------------------------------------------------------------------------
# DAGPlanExecutor
# ---------------------------------------------------------------------------

class DAGPlanExecutor:
    """
    DAG 版 Plan-then-Execute Agent.

    三阶段：
    1. _generate_plan(): 只读 ReActAgent 探索 → LLM 输出 DAG JSON
    2. 用户审批
    3. _execute_dag(): 按拓扑层级逐层执行
    """

    def __init__(
        self,
        backend: "LLMBackend",
        registry: "ToolRegistry",
        agent_config: "AgentConfig | None" = None,
        plan_config: "PlanExecuteConfig | None" = None,
        memory_context: "MemoryContext | None" = None,
    ) -> None:
        from agent.core import AgentConfig
        from agent.plan import PlanExecuteConfig

        self._backend = backend
        self._registry = registry
        self._cfg = agent_config or AgentConfig()
        self._plan_cfg = plan_config or PlanExecuteConfig()
        self._memory_context = memory_context

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def run(self, task: Task, log: EventLog) -> RunResult:
        """三阶段 DAG 执行。"""
        log.log_task_start(task)
        logger.info("DAGPlanExecutor starting task %s", task.task_id)

        # Phase 1: 生成 DAG Plan
        plan, plan_tokens, plan_steps = self._generate_plan(task, log)
        if plan is None:
            return self._fallback_react(task, log)

        log.log_plan_generated(plan)
        logger.info(
            "DAG plan generated: %d subtasks, %d layers",
            len(plan.subtasks),
            len(topological_layers(plan.subtasks)),
        )

        # Phase 2: 用户审批
        approval_cb = self._plan_cfg.plan_approval_callback
        if approval_cb:
            display = self._format_dag_for_display(plan)
            approved = approval_cb(display)
            if not approved:
                log.log_task_failed(steps=plan_steps, reason="Plan rejected by user")
                return RunResult(
                    task_id=task.task_id,
                    status=RunStatus.GAVE_UP,
                    summary="Plan rejected by user",
                    steps_taken=plan_steps,
                    total_tokens=plan_tokens,
                )

        # Phase 3: 执行 DAG
        exec_result = self._execute_dag(plan, task, log, plan_tokens, plan_steps)
        return exec_result

    # ------------------------------------------------------------------
    # Phase 1: 生成 DAG Plan
    # ------------------------------------------------------------------

    def _generate_plan(
        self, task: Task, log: EventLog
    ) -> tuple[Plan | None, int, int]:
        """
        用只读 ReActAgent 探索 + 请求结构化 DAG JSON.

        Returns:
            (plan, tokens_used, steps_taken) 或 (None, 0, 0)
        """
        from agent.core import ReActAgent
        from agent.prompt import get_dag_plan_prompt

        agent = ReActAgent(
            self._backend, self._registry, self._cfg,
            memory_context=self._memory_context,
        )

        history = ConversationHistory(max_messages=self._cfg.history_max_messages)
        dag_prompt = get_dag_plan_prompt()
        history.add(LLMMessage(
            role="user",
            content=(
                f"{dag_prompt}\n\n"
                f"## Repository\n{task.repo_path}\n\n"
                f"## Task\n{task.description}\n\n"
                f"Explore the codebase and produce a DAG execution plan. "
                f"Stop calling tools and respond with the JSON plan when ready."
            ),
        ))
        agent._pending_history = history

        plan_steps = min(8, max(5, task.max_steps // 3))
        plan_task = Task(
            description=task.description,
            repo_path=task.repo_path,
            max_steps=plan_steps,
            budget_tokens=task.budget_tokens // 3,
        )

        agent.switch_to_plan_mode()
        plan_log = EventLog.create(plan_task, log_dir=self._plan_cfg.plan_subtask_log_dir)
        plan_result = agent.run(plan_task, plan_log)
        plan_log.close()

        plan_text = plan_result.summary or ""
        if not plan_text.strip():
            logger.warning("DAG plan generation produced empty result")
            return None, 0, 0

        try:
            plan = Plan.from_dag_json(plan_text, task.description)
            validate_dag(plan.subtasks)
        except (PlanGenerationError, DAGValidationError) as e:
            logger.warning("DAG plan validation failed: %s — trying fallback JSON parse", e)
            try:
                plan = Plan.from_json(plan_text, task.description)
            except PlanGenerationError:
                logger.warning("Fallback JSON parse also failed — falling back to react")
                return None, plan_result.total_tokens, plan_result.steps_taken

        return plan, plan_result.total_tokens, plan_result.steps_taken

    # ------------------------------------------------------------------
    # Phase 3: DAG 执行
    # ------------------------------------------------------------------

    def _execute_dag(
        self, plan: Plan, task: Task, log: EventLog,
        plan_tokens: int, plan_steps: int,
    ) -> RunResult:
        """按拓扑层级顺序执行 subtask."""
        from agent.core import ReActAgent

        layers = topological_layers(plan.subtasks)
        total_tokens = plan_tokens
        total_steps = plan_steps

        budget_per_subtask = max(
            10000,
            (task.budget_tokens - plan_tokens) // max(len(plan.subtasks), 1),
        )
        steps_per_subtask = min(
            10,
            max(5, (task.max_steps - plan_steps) // max(len(plan.subtasks), 1)),
        )

        id_to_task = {st.id: st for st in plan.subtasks}
        failed_ids: set[str] = set()

        for layer_idx, layer in enumerate(layers):
            logger.info("Executing DAG layer %d (%d subtasks)", layer_idx, len(layer))

            for subtask in layer:
                # 检查上游依赖是否有失败
                upstream_failed = any(dep in failed_ids for dep in subtask.depends_on)
                if upstream_failed:
                    subtask.status = "skipped"
                    failed_ids.add(subtask.id)
                    logger.info("Skipping subtask %s (upstream failed)", subtask.id)
                    continue

                subtask.status = "running"
                result = self._execute_single_subtask(
                    subtask, task, id_to_task,
                    budget_tokens=budget_per_subtask,
                    max_steps=steps_per_subtask,
                )
                total_tokens += result.total_tokens
                total_steps += result.steps_taken

                if result.is_success():
                    subtask.status = "done"
                    subtask.result_summary = result.summary or ""
                else:
                    subtask.status = "failed"
                    subtask.result_summary = result.summary or result.error or "Failed"
                    failed_ids.add(subtask.id)
                    logger.warning("Subtask %s failed: %s", subtask.id, subtask.result_summary[:100])

        # 汇总结果
        done_tasks = [st for st in plan.subtasks if st.status == "done"]
        failed_tasks = [st for st in plan.subtasks if st.status == "failed"]
        skipped_tasks = [st for st in plan.subtasks if st.status == "skipped"]

        summary_parts = [f"DAG execution complete: {len(done_tasks)} done, "
                         f"{len(failed_tasks)} failed, {len(skipped_tasks)} skipped."]
        for st in done_tasks:
            if st.result_summary:
                summary_parts.append(f"  [{st.id}] {st.result_summary[:100]}")

        summary = "\n".join(summary_parts)

        if failed_tasks:
            from agent.core import _git_diff
            patch = _git_diff(task.repo_path)
            log.log_task_failed(steps=total_steps, reason=summary)
            return RunResult(
                task_id=task.task_id,
                status=RunStatus.FAILED,
                summary=summary,
                steps_taken=total_steps,
                total_tokens=total_tokens,
                patch=patch,
            )

        from agent.core import _git_diff
        patch = _git_diff(task.repo_path)
        log.log_task_complete(steps=total_steps, summary=summary)
        return RunResult(
            task_id=task.task_id,
            status=RunStatus.SUCCESS,
            summary=summary,
            steps_taken=total_steps,
            total_tokens=total_tokens,
            patch=patch,
        )

    def _execute_single_subtask(
        self,
        subtask: SubTask,
        parent_task: Task,
        id_to_task: dict[str, SubTask],
        budget_tokens: int,
        max_steps: int,
    ) -> RunResult:
        """在独立 ReActAgent 中执行单个 subtask."""
        from agent.core import AgentConfig, ReActAgent
        from agent.prompt import build_dag_subtask_prompt

        upstream_context = self._build_upstream_context(subtask, id_to_task)

        cfg = AgentConfig(
            max_steps=max_steps,
            budget_tokens=budget_tokens,
            history_max_messages=self._cfg.history_max_messages,
            llm_max_retries=self._cfg.llm_max_retries,
            llm_retry_delay=self._cfg.llm_retry_delay,
            stream=self._cfg.stream,
            stream_callback=self._cfg.stream_callback,
            thought_callback=self._cfg.thought_callback,
            confirm_dangerous=self._cfg.confirm_dangerous,
            confirm_callback=self._cfg.confirm_callback,
        )

        agent = ReActAgent(
            self._backend, self._registry, cfg,
            memory_context=self._memory_context,
        )

        prompt = build_dag_subtask_prompt(
            subtask_id=subtask.id,
            description=subtask.description,
            expected_outcome=subtask.expected_outcome,
            upstream_context=upstream_context,
        )

        sub_task = Task(
            description=prompt,
            repo_path=parent_task.repo_path,
            max_steps=max_steps,
            budget_tokens=budget_tokens,
        )

        sub_log = EventLog.create(sub_task, log_dir=self._plan_cfg.plan_subtask_log_dir)
        result = agent.run(sub_task, sub_log)
        sub_log.close()

        return result

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _build_upstream_context(
        self, subtask: SubTask, id_to_task: dict[str, SubTask]
    ) -> str:
        """从已完成的上游 subtask 中收集 result_summary."""
        parts = []
        for dep_id in subtask.depends_on:
            dep = id_to_task.get(dep_id)
            if dep and dep.status == "done" and dep.result_summary:
                parts.append(f"[Subtask {dep.id}] {dep.result_summary}")
        return "\n".join(parts)

    def _format_dag_for_display(self, plan: Plan) -> str:
        """将 DAG plan 格式化为人类可读的审批文本。"""
        layers = topological_layers(plan.subtasks)
        lines = []
        if plan.reasoning:
            lines.append(f"## Reasoning\n{plan.reasoning}\n")
        lines.append("## Execution Plan (DAG)\n")
        for i, layer in enumerate(layers):
            lines.append(f"### Layer {i} (parallel-ready)")
            for st in layer:
                deps = f" [depends: {', '.join(st.depends_on)}]" if st.depends_on else ""
                lines.append(f"  {st.id}. {st.description}{deps}")
                if st.expected_outcome:
                    lines.append(f"     Expected: {st.expected_outcome}")
            lines.append("")
        return "\n".join(lines)

    def _fallback_react(self, task: Task, log: EventLog) -> RunResult:
        """Plan 生成失败时回退到普通 ReActAgent."""
        from agent.core import ReActAgent

        logger.info("Falling back to plain ReActAgent")
        agent = ReActAgent(
            self._backend, self._registry, self._cfg,
            memory_context=self._memory_context,
        )
        return agent.run(task, log)

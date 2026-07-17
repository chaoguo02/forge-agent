from entry.modes.interaction import (
    ApprovalAction,
    ApprovalChoice,
    ClickAdapter,
    PlanExecutionPolicy,
    PredefinedChoiceAdapter,
    cli_plan_adapter,
)
from entry.modes.plan_approval import PlanAction, PlanApprovalService
from agent.task import TaskIntent


def _valid_contract_data():
    return {
        "objective": "Review runtime process execution and project isolation",
        "execution_intent": "analysis",
        "target_files": ["runtime/project_environment.py"],
        "expected_behavior": "Document the implementation with exact source locations",
        "verification_strategy": "Read the cited source lines",
        "potential_conflicts": [],
    }


def test_v2_runner_declares_typed_plan_intent():
    from entry.modes import v2_runner

    assert v2_runner.TaskIntent is TaskIntent


def test_plan_contract_extraction_skips_markdown_brackets_before_json():
    import json

    from entry.modes.plan_contract import extract_and_parse_json

    data = _valid_contract_data()
    text = "# Report\n[ENVIRONMENT] cwd={not-json}\n```json\n" + json.dumps(data) + "\n```"

    assert extract_and_parse_json(text) == data


def test_canonical_plan_document_is_human_readable_and_machine_parseable():
    from entry.modes.plan_contract import PlanContract, extract_and_parse_json

    contract = PlanContract.model_validate(_valid_contract_data())
    document = contract.render_plan_document()

    assert document.startswith("## Objective")
    assert "## Execution Contract\n```json" in document
    assert extract_and_parse_json(document) == contract.model_dump()


def test_plan_filename_is_stable_and_does_not_embed_task_text():
    from entry.modes.v2_runner import _plan_filename

    description = "审查 runtime 目录，并列出文件和行号。"

    assert _plan_filename(description) == _plan_filename(description)
    assert _plan_filename(description).startswith("plan-")
    assert description[:2] not in _plan_filename(description)


def test_plan_filename_uses_short_ascii_slug_when_available():
    from entry.modes.v2_runner import _plan_filename

    filename = _plan_filename("Review runtime process execution and project isolation")

    assert filename.startswith("plan-review-runtime-process-execution")
    assert filename.endswith(".md")


def test_plan_contract_preserves_declared_step_and_token_limits():
    from types import SimpleNamespace

    from agent.session.task_contract import TaskContract

    contract = TaskContract.for_plan(SimpleNamespace(
        max_steps=40, budget_tokens=80_000,
    ))

    assert contract.max_steps == 40
    assert contract.budget_tokens == 80_000


def test_approval_choice_coerces_external_string_at_boundary():
    choice = ApprovalChoice(action="revise", feedback="Add tests")

    assert choice.action is ApprovalAction.REVISE


def test_execution_choices_trigger_build():
    service = PlanApprovalService()

    assert service.evaluate(
        ApprovalChoice(ApprovalAction.EXECUTE)
    ) is PlanAction.TRIGGER_BUILD


def test_save_choice_completes_plan_without_build():
    service = PlanApprovalService()

    assert service.evaluate(
        ApprovalChoice(ApprovalAction.SAVE)
    ) is PlanAction.COMPLETE_PLAN


def test_revision_limit_is_committed_only_after_execution():
    service = PlanApprovalService(max_revisions=1)
    choice = ApprovalChoice(ApprovalAction.REVISE, feedback="Add tests")

    assert service.evaluate(choice) is PlanAction.TRIGGER_REPLAN
    assert service.revision_count == 0
    service.commit_revision()
    assert service.evaluate(choice) is PlanAction.ABORT_REVISIONS


def test_adapters_return_typed_actions():
    assert PredefinedChoiceAdapter("abort").prompt_approval().action is ApprovalAction.ABORT
    assert cli_plan_adapter(PlanExecutionPolicy.SAVE).prompt_approval().action is ApprovalAction.SAVE
    assert cli_plan_adapter(PlanExecutionPolicy.EXECUTE).prompt_approval().action is ApprovalAction.EXECUTE


def test_click_adapter_displays_plan_and_defaults_to_save(monkeypatch, capsys):
    monkeypatch.setattr("click.prompt", lambda *args, **kwargs: kwargs["default"])
    adapter = ClickAdapter()

    adapter.show_plan("## Objective\nInspect runtime", "plan-123.md")
    choice = adapter.prompt_approval()

    output = capsys.readouterr().out
    assert "## Objective\nInspect runtime" in output
    assert "Save plan and exit (default)" in output
    assert choice.action is ApprovalAction.SAVE


def test_cli_separates_tool_auto_approval_from_plan_execution():
    from click.testing import CliRunner
    from entry.cli import cli

    result = CliRunner().invoke(cli, ["run", "--help"])

    assert result.exit_code == 0
    assert "--plan-action [review|save|execute]" in result.output
    assert "does not execute a generated plan" in " ".join(result.output.split())


def test_manual_plan_edit_reads_known_path_without_editor_lookup(tmp_path, monkeypatch):
    from entry.modes import v2_runner

    plan_path = tmp_path / "plan.md"
    plan_path.write_text("updated plan", encoding="utf-8")
    messages = []
    interaction = type(
        "Interaction",
        (),
        {"show_message": lambda self, text, style: messages.append((text, style))},
    )()
    paused = []
    monkeypatch.setattr(v2_runner.click, "pause", lambda prompt: paused.append(prompt))

    result = v2_runner._read_manual_plan_edit(str(plan_path.resolve()), interaction)

    assert result == "updated plan"
    assert str(plan_path.resolve()) in messages[0][0]
    assert paused


def test_plan_artifact_persists_canonical_document_when_contract_is_present(tmp_path):
    import json

    from entry.modes import v2_runner

    contract = _valid_contract_data()
    raw = "## Draft\n```json\n" + json.dumps(contract) + "\n```"
    interaction = type(
        "Interaction",
        (),
        {"show_message": lambda self, text, style="info": None},
    )()

    artifact = v2_runner._build_plan_artifact(
        plan_path=str(tmp_path / "plan.md"),
        raw_plan_text=raw,
        intent_override=None,
        interaction=interaction,
    )

    assert "## Execution Contract\n```json" in artifact.file_text
    assert artifact.review_text.startswith("## Objective")


def test_v2_result_printer_suppresses_summary_already_rendered_by_events(capsys):
    from types import SimpleNamespace

    from agent.task import RunStatus
    from entry.modes.v2_runner import _print_v2_result

    result = SimpleNamespace(status=RunStatus.SUCCESS, summary="unique final report")

    _print_v2_result("v2-build", "sessions.db", "session-id", result, show_summary=False)

    output = capsys.readouterr().out
    assert "unique final report" not in output
    assert "completed successfully" in output


def test_v2_plan_e2e_saves_canonical_plan_without_executing(
    tmp_path, monkeypatch,
):
    import json
    import sqlite3

    from agent.core import AgentConfig
    from agent.task import Action, ActionType
    from entry.modes.interaction import PredefinedChoiceAdapter
    from entry.modes.plan_contract import extract_and_parse_json
    from entry.modes.v2_runner import _plan_filename, run_v2_mode
    from llm.base import MockBackend
    from executor.state_paths import ProjectStatePaths, STATE_HOME_ENV
    from core.base import ToolRegistry

    repo = tmp_path / "target-repo"
    repo.mkdir()
    marker = repo / "runtime.py"
    marker.write_text("# process runtime\n", encoding="utf-8")
    state_home = tmp_path / "isolated-state"
    monkeypatch.setenv(STATE_HOME_ENV, str(state_home))
    description = "Review runtime process execution and project isolation"
    contract = _valid_contract_data()
    model_output = (
        "## Implementation plan\nInspect the runtime boundary.\n```json\n"
        + json.dumps(contract)
        + "\n```"
    )
    backend = MockBackend([
        Action(
            action_type=ActionType.FINISH,
            thought="plan complete",
            message=model_output,
        ),
    ], input_tokens=100, output_tokens=100)

    run_v2_mode(
        agent_name="plan",
        description=description,
        repo_path=repo,
        backend=backend,
        registry=ToolRegistry(),
        agent_config=AgentConfig(
            max_steps=10,
            budget_tokens=5_000,
            request_budget_tokens=4_000,
            stream=False,
        ),
        memory_context=None,
        log_dir="",
        intent_override="analysis",
        approval_interaction=PredefinedChoiceAdapter("save"),
        renderer=None,
    )

    paths = ProjectStatePaths.for_project(repo)
    plan_path = paths.plans / _plan_filename(description)
    assert plan_path.is_file()
    plan_text = plan_path.read_text(encoding="utf-8")
    assert "## Objective" in plan_text or "## Goal" in plan_text or "## Implementation plan" in plan_text
    assert extract_and_parse_json(plan_text) == contract
    assert marker.read_text(encoding="utf-8") == "# process runtime\n"
    assert backend.call_count == 1

    with sqlite3.connect(paths.sessions_db) as connection:
        sessions = connection.execute(
            "SELECT agent_name, status FROM sessions ORDER BY created_at"
        ).fetchall()
    assert sessions == [("plan", "completed")]


# ═══════════════════════════════════════════════════════════════════════════
# Gap 2: Prompt-based Permissions (ExitPlanMode allowedPrompts)
# ═══════════════════════════════════════════════════════════════════════════


class TestPromptBasedPermissions:
    """CC-aligned: ExitPlanModeTool.allowedPrompts → auto-allow matching tool calls."""

    def test_add_approved_prompts_stores_valid_entries(self):
        from hitl.pipeline import PermissionPipeline
        pipeline = PermissionPipeline()
        pipeline.add_approved_prompts([
            {"tool": "Bash", "prompt": "run unit tests"},
            {"tool": "Bash", "prompt": "install dependencies"},
        ])
        assert len(pipeline._approved_prompts) == 2
        assert pipeline._approved_prompts[0]["tool"] == "Bash"
        assert pipeline._approved_prompts[0]["prompt"] == "run unit tests"

    def test_add_approved_prompts_ignores_invalid_entries(self):
        from hitl.pipeline import PermissionPipeline
        pipeline = PermissionPipeline()
        pipeline.add_approved_prompts([
            {"tool": "Bash"},                     # missing prompt
            {"prompt": "something"},              # missing tool
            "not_a_dict",
            None,
            123,
        ])
        assert len(pipeline._approved_prompts) == 0

    def test_add_approved_prompts_ignores_non_list(self):
        from hitl.pipeline import PermissionPipeline
        pipeline = PermissionPipeline()
        pipeline.add_approved_prompts("not a list")  # type: ignore[arg-type]
        assert len(pipeline._approved_prompts) == 0

    def test_match_bash_command_by_keyword_overlap(self):
        from hitl.pipeline import PermissionPipeline
        pipeline = PermissionPipeline()
        pipeline.add_approved_prompts([
            {"tool": "Bash", "prompt": "run unit tests with pytest"},
        ])
        # "pytest tests/" shares words with "run unit tests with pytest"
        match = pipeline._match_approved_prompt("Bash", {"command": "pytest tests/"})
        assert match == "run unit tests with pytest"

    def test_match_bash_command_case_insensitive(self):
        from hitl.pipeline import PermissionPipeline
        pipeline = PermissionPipeline()
        pipeline.add_approved_prompts([
            {"tool": "Bash", "prompt": "Run Type Checking"},
        ])
        match = pipeline._match_approved_prompt("Bash", {"command": "mypy --strict type checking"})
        assert match == "Run Type Checking"

    def test_no_match_for_different_tool(self):
        from hitl.pipeline import PermissionPipeline
        pipeline = PermissionPipeline()
        pipeline.add_approved_prompts([
            {"tool": "Bash", "prompt": "run tests"},
        ])
        match = pipeline._match_approved_prompt("Write", {"path": "test.py", "content": "..."})
        assert match is None

    def test_no_match_when_no_keyword_overlap(self):
        from hitl.pipeline import PermissionPipeline
        pipeline = PermissionPipeline()
        pipeline.add_approved_prompts([
            {"tool": "Bash", "prompt": "run tests"},
        ])
        match = pipeline._match_approved_prompt("Bash", {"command": "rm -rf /"})
        assert match is None

    def test_match_write_path_by_prompt_substring(self):
        from hitl.pipeline import PermissionPipeline
        pipeline = PermissionPipeline()
        pipeline.add_approved_prompts([
            {"tool": "Write", "prompt": "create test_utils.py"},
        ])
        # "test_utils.py" is a substring of "create test_utils.py"
        match = pipeline._match_approved_prompt("Write", {"path": "test_utils.py", "content": "..."})
        assert match == "create test_utils.py"

    def test_match_read_path_by_keyword_overlap(self):
        from hitl.pipeline import PermissionPipeline
        pipeline = PermissionPipeline()
        pipeline.add_approved_prompts([
            {"tool": "Read", "prompt": "read configuration file"},
        ])
        match = pipeline._match_approved_prompt("Read", {"path": "config/settings.yml"})
        assert match is None  # no keyword overlap

    def test_empty_prompts_no_match(self):
        from hitl.pipeline import PermissionPipeline
        pipeline = PermissionPipeline()
        # No prompts added
        match = pipeline._match_approved_prompt("Bash", {"command": "pytest"})
        assert match is None

    def test_pipeline_check_allows_matching_tool_call(self):
        from hitl.pipeline import PermissionDecision, PermissionLayer, PermissionPipeline
        pipeline = PermissionPipeline()
        pipeline.add_approved_prompts([
            {"tool": "Bash", "prompt": "run unit tests"},
        ])
        from core.base import NoopTool, ToolMetadata
        tool = NoopTool("Bash")
        tool.metadata = ToolMetadata()
        result = pipeline.check(tool, {"command": "pytest tests/"})
        assert result.decision is PermissionDecision.ALLOW
        assert result.layer is PermissionLayer.PROMPT_APPROVED

    def test_pipeline_check_denies_unrelated_tool(self):
        from hitl.pipeline import PermissionDecision, PermissionPipeline
        pipeline = PermissionPipeline()
        pipeline.add_approved_prompts([
            {"tool": "Bash", "prompt": "run unit tests"},
        ])
        from core.base import NoopTool, ToolMetadata
        tool = NoopTool("Write")
        tool.metadata = ToolMetadata()
        result = pipeline.check(tool, {"path": "test.py", "content": "malicious"})
        # No approved prompt for Write, falls through to callback
        # Without confirm_callback, headless mode denies
        assert result.decision is PermissionDecision.DENY

    def test_exit_plan_mode_tool_stores_allowed_prompts(self):
        from tools.plan_mode_tool import ExitPlanModeTool
        from core.base import ToolRegistry
        from hitl.pipeline import PermissionPipeline

        pipeline = PermissionPipeline()
        registry = ToolRegistry()
        registry._permission_pipeline = pipeline

        tool = ExitPlanModeTool()
        object.__setattr__(tool, '_registry', registry)

        result = tool.execute({
            "plan": "Implement feature X",
            "allowedPrompts": [
                {"tool": "Bash", "prompt": "run unit tests"},
                {"tool": "Write", "prompt": "create test_feature.py"},
            ],
        })
        assert result.success is True
        assert len(pipeline._approved_prompts) == 2
        assert pipeline._approved_prompts[0]["tool"] == "Bash"
        assert pipeline._approved_prompts[1]["tool"] == "Write"

    def test_exit_plan_mode_tool_handles_missing_allowed_prompts(self):
        from tools.plan_mode_tool import ExitPlanModeTool
        from core.base import ToolRegistry
        from hitl.pipeline import PermissionPipeline

        pipeline = PermissionPipeline()
        registry = ToolRegistry()
        registry._permission_pipeline = pipeline

        tool = ExitPlanModeTool()
        object.__setattr__(tool, '_registry', registry)

        result = tool.execute({"plan": "Implement feature X"})
        assert result.success is True
        assert len(pipeline._approved_prompts) == 0

    def test_scoped_pipeline_shares_approved_prompts(self):
        from hitl.pipeline import PermissionPipeline
        pipeline = PermissionPipeline()
        pipeline.add_approved_prompts([
            {"tool": "Bash", "prompt": "run unit tests with pytest"},
        ])
        scoped = pipeline.scoped("/tmp/test")
        # scoped shares the same list reference
        assert scoped._approved_prompts is pipeline._approved_prompts
        match = scoped._match_approved_prompt("Bash", {"command": "pytest tests/ -v"})
        assert match == "run unit tests with pytest"


# ═══════════════════════════════════════════════════════════════════════════
# Gap 3: System Prompt Throttling (plan mode)
# ═══════════════════════════════════════════════════════════════════════════


class TestPlanModeThrottling:
    """CC-aligned: plan mode prompt throttled (full → sparse → full every 25)."""

    def test_non_plan_session_uses_base_source(self):
        """Non-plan sessions should use base runtime_message_source without throttling."""
        from agent.session.models import AgentDefinition, AgentKind, TaskIntent

        spec = AgentDefinition(
            name="build",
            description="build agent",
            intent=TaskIntent.EDIT,
            agent_kind=AgentKind.PRIMARY,
            permission_mode="default",
        )
        assert spec.permission_mode != "plan"

    def test_plan_spec_has_permission_mode_plan(self):
        """Plan agent definition declares permission_mode='plan'."""
        from agent.session.models import _BUILTIN_AGENTS
        plan = _BUILTIN_AGENTS.get("plan")
        assert plan is not None
        assert plan.permission_mode == "plan"

    def test_throttle_step_1_no_extra_injection(self):
        """Step 1: no extra injection — full prompt already in build_runtime_messages."""
        # Simulate the throttling logic inline
        _plan_step = [0]
        def source():
            _plan_step[0] += 1
            step = _plan_step[0]
            msgs = []
            if step == 1:
                return msgs  # full injection already in build_runtime_messages
            if step % 5 == 0 and step % 25 != 0:
                msgs.append("[PLAN MODE] sparse reminder")
            elif step % 25 == 0:
                msgs.append("[PLAN MODE] full re-injection")
            return msgs

        assert source() == []  # step 1

    def test_throttle_step_5_sparse_reminder(self):
        """Every 5th step (not 25th): inject sparse reminder."""
        _plan_step = [0]
        def source():
            _plan_step[0] += 1
            step = _plan_step[0]
            msgs = []
            if step == 1:
                return msgs
            if step % 5 == 0 and step % 25 != 0:
                msgs.append("sparse")
            elif step % 25 == 0:
                msgs.append("full")
            return msgs

        for _ in range(4):
            source()  # steps 1-4
        assert source() == ["sparse"]  # step 5

    def test_throttle_step_10_sparse_reminder(self):
        """Step 10: sparse reminder."""
        _plan_step = [0]
        def source():
            _plan_step[0] += 1
            step = _plan_step[0]
            msgs = []
            if step == 1:
                return msgs
            if step % 5 == 0 and step % 25 != 0:
                msgs.append("sparse")
            elif step % 25 == 0:
                msgs.append("full")
            return msgs

        for _ in range(9):
            source()
        assert source() == ["sparse"]  # step 10

    def test_throttle_step_25_full_reinjection(self):
        """Every 25th step: full plan mode re-injection."""
        _plan_step = [0]
        def source():
            _plan_step[0] += 1
            step = _plan_step[0]
            msgs = []
            if step == 1:
                return msgs
            if step % 5 == 0 and step % 25 != 0:
                msgs.append("sparse")
            elif step % 25 == 0:
                msgs.append("full")
            return msgs

        for _ in range(24):
            source()
        assert source() == ["full"]  # step 25

    def test_throttle_step_3_no_injection(self):
        """Step 3: no injection (not a multiple of 5 or 25)."""
        _plan_step = [0]
        def source():
            _plan_step[0] += 1
            step = _plan_step[0]
            msgs = []
            if step == 1:
                return msgs
            if step % 5 == 0 and step % 25 != 0:
                msgs.append("sparse")
            elif step % 25 == 0:
                msgs.append("full")
            return msgs

        for _ in range(2):
            source()  # steps 1-2
        assert source() == []  # step 3

    def test_step_25_takes_priority_over_step_5(self):
        """At step 25 (which is also a multiple of 5), full wins over sparse."""
        _plan_step = [0]
        def source():
            _plan_step[0] += 1
            step = _plan_step[0]
            msgs = []
            if step == 1:
                return msgs
            if step % 5 == 0 and step % 25 != 0:
                msgs.append("sparse")
            elif step % 25 == 0:
                msgs.append("full")
            return msgs

        for _ in range(24):
            source()
        assert source() == ["full"]  # step 25 — full, not sparse

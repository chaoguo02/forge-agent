"""
tests/test_compaction.py

测试 ConversationCompactor：对话压缩逻辑。
"""

from __future__ import annotations

import pytest

from context.compaction import ConversationCompactor
from context.token_budget import TokenBudget


def _make_assistant_msg(thought="I think...", tool="shell", params=None):
    """构造 assistant 消息（forge-agent 的纯文本格式）。"""
    content = f"Thought: {thought}"
    if tool:
        import json
        content += f"\nAction: {tool}\nParams: {json.dumps(params or {'cmd': 'ls'})}"
    return {"role": "assistant", "content": content}


def _make_observation_msg(tool="shell", status="SUCCESS", output="some output"):
    """构造 tool result 消息（forge-agent 的纯文本格式）。"""
    return {"role": "user", "content": f"[Tool: {tool} | {status}]\n{output}"}


def _make_user_msg(content="user message"):
    return {"role": "user", "content": content}


# ---------------------------------------------------------------------------
# ShouldCompact
# ---------------------------------------------------------------------------

class TestShouldCompact:
    def test_compact_not_needed_when_short(self):
        compactor = ConversationCompactor()
        history = [
            _make_user_msg("task"),
            _make_assistant_msg("step 1"),
            _make_observation_msg(),
        ]
        budget = TokenBudget(total=80_000)
        assert not compactor.should_compact(history, budget)

    def test_compact_needed_when_large(self):
        compactor = ConversationCompactor(
            trigger_ratio=0.10,  # 10% 就触发，方便测试
        )
        history = [
            _make_user_msg("task"),
        ]
        # 加 50 条大消息
        for i in range(50):
            history.append(_make_assistant_msg(f"step {i}", "shell", {"cmd": "x" * 500}))
            history.append(_make_observation_msg(output="x" * 2000))

        budget = TokenBudget(total=80_000)
        # 50 轮工具调用应该远超预算
        assert compactor.should_compact(history, budget)

    def test_not_compact_too_few_messages(self):
        compactor = ConversationCompactor(min_history=10)
        history = [_make_user_msg("task"), _make_assistant_msg("hi"), _make_observation_msg()]
        budget = TokenBudget(total=80_000)
        # 少于 min_history
        assert not compactor.should_compact(history, budget)


# ---------------------------------------------------------------------------
# CompactHistory
# ---------------------------------------------------------------------------

class TestCompactHistory:
    def test_compact_reduces_message_count(self):
        compactor = ConversationCompactor()
        history = [_make_user_msg("task")]
        for i in range(10):
            history.append(_make_assistant_msg(f"step {i}"))
            history.append(_make_observation_msg(output=f"result {i}"))

        result = compactor.compact_history(history)
        # 应该显著减少消息数
        assert len(result) < len(history)
        # 首条保留
        assert result[0]["content"] == "task"

    def test_compact_single_message(self):
        compactor = ConversationCompactor()
        history = [_make_user_msg("task")]
        result = compactor.compact_history(history)
        assert len(result) == 1
        assert result[0]["content"] == "task"

    def test_compact_empty(self):
        compactor = ConversationCompactor()
        assert compactor.compact_history([]) == []


# ---------------------------------------------------------------------------
# BuildCompactBlockForHistory
# ---------------------------------------------------------------------------

class TestBuildCompactBlock:
    def test_build_block_returns_summary(self):
        compactor = ConversationCompactor()
        history = [
            _make_user_msg("Fix the login bug"),
            _make_assistant_msg("Looking at auth.py", "read", {"path": "src/auth.py"}),
            _make_observation_msg(output="def login(): pass"),
            _make_assistant_msg("Found the issue", "edit", {"path": "src/auth.py", "old": "bug", "new": "fix"}),
            _make_observation_msg(output="File updated."),
        ]

        block = compactor.build_compact_block_for_history(history)
        assert block["role"] == "user"
        assert "Fix the login bug" in block["content"]
        assert "[Conversation compacted" in block["content"]

    def test_build_block_empty(self):
        compactor = ConversationCompactor()
        block = compactor.build_compact_block_for_history([])
        assert "empty" in block["content"].lower()


# ---------------------------------------------------------------------------
# ExtractFromAssistant
# ---------------------------------------------------------------------------

class TestExtractFromAssistant:
    def test_extract_thought_and_tool(self):
        compactor = ConversationCompactor()
        content = "Thought: Let me check the file\nAction: read\nParams: {\"path\": \"test.py\"}"
        result = compactor._extract_from_assistant(content)
        assert result is not None
        assert "Let me check" in result
        assert "read" in result

    def test_extract_empty(self):
        compactor = ConversationCompactor()
        assert compactor._extract_from_assistant("") is None

    def test_skip_compaction_block(self):
        compactor = ConversationCompactor()
        assert compactor._extract_from_assistant("[Earlier conversation summarized") is None


# ---------------------------------------------------------------------------
# ExtractFromObservation
# ---------------------------------------------------------------------------

class TestExtractFromObservation:
    def test_extract_success(self):
        compactor = ConversationCompactor()
        content = "[Tool: read | SUCCESS]\ndef foo(): pass\nclass Bar: pass"
        result = compactor._extract_from_observation(content)
        assert result is not None
        assert "✓" in result
        assert "read" in result

    def test_extract_error(self):
        compactor = ConversationCompactor()
        content = "[Tool: test | ERROR]\nFAILED test_foo"
        result = compactor._extract_from_observation(content)
        assert result is not None
        assert "✗" in result
        assert "FAILED" in result

    def test_skip_compaction_block(self):
        compactor = ConversationCompactor()
        assert compactor._extract_from_observation("[Conversation compacted") is None

    def test_no_match(self):
        compactor = ConversationCompactor()
        assert compactor._extract_from_observation("just a regular message") is None


# ---------------------------------------------------------------------------
# ExtractKeyOutput
# ---------------------------------------------------------------------------

class TestExtractKeyOutput:
    def test_short_output(self):
        compactor = ConversationCompactor()
        assert compactor._extract_key_output("Hello World") == "Hello World"

    def test_multiline_output(self):
        compactor = ConversationCompactor()
        output = "line1\nline2\nline3\nline4\nline5"
        result = compactor._extract_key_output(output)
        assert "line1" in result
        assert "line5" not in result  # 只保留前 3 行
        assert "..." in result

    def test_skip_separator_lines(self):
        compactor = ConversationCompactor()
        output = "───\nresult\n───"
        result = compactor._extract_key_output(output)
        assert "───" not in result
        assert "result" in result

    def test_empty_output(self):
        compactor = ConversationCompactor()
        assert compactor._extract_key_output("") == ""

from __future__ import annotations

import asyncio

from runtime.context_compression import (
    AutoCompactTrackingState,
    apply_tool_result_budget,
    compress_messages,
)


def _tool_result_message(content: str, *, tool_name: str = "read") -> dict:
    return {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "t1",
                "tool_name": tool_name,
                "content": content,
            }
        ],
    }


def test_apply_tool_result_budget_truncates_large_tool_result():
    messages = [_tool_result_message("x" * 100)]

    compacted, freed = apply_tool_result_budget(messages, max_chars=50, preview_chars=10)

    content = compacted[0]["content"][0]["content"]
    assert content.startswith("x" * 10)
    assert "truncated 90 chars" in content
    assert freed > 0


def test_compress_messages_reports_budget_layer():
    async def scenario():
        result = await compress_messages(
            [_tool_result_message("x" * 60_000)],
            enable_snip=False,
            enable_microcompact=False,
            enable_collapse=False,
            enable_autocompact=False,
        )

        assert "budget" in result.layers_applied
        assert result.tokens_freed > 0

    asyncio.run(scenario())


def test_compress_messages_reports_blocking_limit():
    async def scenario():
        result = await compress_messages(
            [{"role": "user", "content": "x" * 100}],
            context_window=10,
            enable_budget=False,
            enable_snip=False,
            enable_microcompact=False,
            enable_collapse=False,
            enable_autocompact=False,
        )

        assert "blocking_limit" in result.layers_applied

    asyncio.run(scenario())


def test_autocompact_failure_circuit_breaker_stops_retrying():
    async def scenario():
        tracking = AutoCompactTrackingState()
        calls = 0

        async def fail_summary(_messages):
            nonlocal calls
            calls += 1
            raise RuntimeError("summary failed")

        messages = [{"role": "user", "content": "x" * 120}]
        for _ in range(4):
            await compress_messages(
                messages,
                context_window=40,
                call_model_for_summary=fail_summary,
                autocompact_tracking=tracking,
                enable_budget=False,
                enable_snip=False,
                enable_microcompact=False,
                enable_collapse=False,
                enable_autocompact=True,
            )

        assert tracking.consecutive_failures == 3
        assert calls == 3

    asyncio.run(scenario())

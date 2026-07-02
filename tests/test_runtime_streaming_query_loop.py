from __future__ import annotations

import asyncio

from runtime.query_loop import LoopExitReason, LoopTerminalEvent, ToolResultEvent, query_loop
from runtime.tool import ToolExecutionResult, ToolResult


def test_streaming_query_loop_executes_tool_use_and_continues():
    async def scenario():
        calls = 0

        async def call_model(messages):
            nonlocal calls
            calls += 1
            if calls == 1:
                yield {"type": "text_delta", "text": "checking"}
                yield {"type": "tool_use", "id": "t1", "name": "read", "input": {}}
            else:
                assert any(
                    isinstance(message, dict)
                    and message.get("content", [{}])[0].get("type") == "tool_result"
                    for message in messages
                    if isinstance(message.get("content", None), list)
                )
                yield {"type": "text_delta", "text": "done"}

        async def execute_tool(tool_call):
            return ToolExecutionResult(
                call_id=tool_call["id"],
                tool_name=tool_call["name"],
                result=ToolResult(output="file content"),
            )

        events = []
        async for event in query_loop(
            [{"role": "user", "content": "read file"}],
            call_model=call_model,
            execute_tool=execute_tool,
            get_concurrency_safe=lambda _tool_call: True,
            max_turns=3,
        ):
            events.append(event)

        assert any(isinstance(event, ToolResultEvent) and event.output == "file content" for event in events)
        assert isinstance(events[-1], LoopTerminalEvent)
        assert events[-1].reason == LoopExitReason.COMPLETED
        assert calls == 2

    asyncio.run(scenario())


def test_streaming_query_loop_returns_blocking_limit_when_compression_fails():
    async def scenario():
        async def call_model(messages):
            yield {"type": "text_delta", "text": "should not run"}

        async def execute_tool(_tool_call):
            raise AssertionError("tool should not run")

        events = []
        async for event in query_loop(
            [{"role": "user", "content": "x" * 100}],
            call_model=call_model,
            execute_tool=execute_tool,
            get_concurrency_safe=lambda _tool_call: True,
            context_window=10,
        ):
            events.append(event)

        assert events == [LoopTerminalEvent(reason=LoopExitReason.BLOCKING_LIMIT)]

    asyncio.run(scenario())

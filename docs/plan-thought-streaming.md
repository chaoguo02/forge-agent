# Plan: Thought Streaming for Web Mode

## Context

CLI streams LLM thought tokens in real-time via `stream_callback → InlineRenderer`.
Web waits for the full thought to complete, then pushes it as a single `WsThought` event.
Users see nothing during the LLM's thinking phase (5-30 seconds of blank screen).

## Current State

**LLM backend** (agent/core.py:2512-2513): already streams, but callback is None for Web:
```python
if self._cfg.stream_callback:
    self._cfg.stream_callback(event.text)
```

**CLI stream_callback** (entry/chat.py:194-206): writes to terminal in real-time.

**Web agent config** (agent_factory.py:236-237): stream=True but stream_callback=None.

## Implementation

Single batch, 3 files:
1. `server/events.py` — add WsThoughtDelta dataclass
2. `agent/session/runtime.py` or `server/services/agent_service.py` — wire stream_callback to EventBus
3. `web/src/types/events.ts` — add WsThoughtDelta interface
4. `web/src/stores/chatStore.ts` — handle thought_delta events

### Event type
```python
@dataclass
class WsThoughtDelta:
    type: Literal["thought_delta"] = "thought_delta"
    text: str = ""
    step: int = 0
    child_session_id: str = ""
    timestamp: str = ""
```

### Stream callback (in agent_service.py _run_and_notify)
```python
def _stream_callback(text: str) -> None:
    if self._event_bus is not None:
        self._event_bus.publish_typed(session_id, WsThoughtDelta(
            text=text, step=0,  # step unknown during streaming
        ))
```

# Plan: Auto-Compaction for Web Agent Loop

## Context

Web mode's agent loop logs a budget warning but never triggers actual compaction. The CLI ChatSession has `_maybe_auto_compact_after_round()` that fires after every round. We need the equivalent inside the agent loop so Web agents self-heal when budget is exceeded.

## Current State

**agent/core.py:939-949** — Budget warning only:
```python
if step > 3 and _budget_pct > 80:
    logger.warning("Token budget at %.0f%% — consider /compact")
    history.add(LLMMessage(role="user", content="[SYSTEM] Context window usage..."))
```

**agent/core.py:1088-1114** — Reactive compaction on error (reference pattern):
```python
# Tier 1: drain — zero-cost SnipCompact + MicroCompact
_drained += _snip_history(history)
_drained += _micro_compact(history)
# Tier 2: full LLM compact
self.compactor.compact(history, total_tokens)
```

**entry/chat.py:390-405** — CLI auto-compact reference:
```python
# Gated by: config.auto_compact_after_round, result status, round_count interval, token threshold
self.compact(focus=prompt)
```

## Target State

Add auto-compaction in the agent loop, triggered when budget exceeds 100%:

```python
if step > 3 and _budget_pct > 100:
    if not _already_compacted_this_run:
        # Tier 1: drain
        _drained = _snip_history(history)
        _drained += _micro_compact(history)
        if _drained > 0:
            logger.info("Auto-compact drain freed ~%d tokens", _drained)
            # Recalculate budget
            continue
        # Tier 2: full LLM compact (only if drain wasn't enough)
        if _budget_pct > 100:
            self.compactor.compact(history, total_tokens)
            _already_compacted_this_run = True
            logger.info("Auto-compact: full compact triggered")
```

Key design decisions:
- Throttle: `_already_compacted_this_run` flag prevents re-compaction within same run
- Trigger: budget > 100% (not 80% — only warn at 80%, compact at 100%)
- Method: same 3-tier waterfall as reactive compaction
- Location: right after existing budget warning, before ContextCollapse

## Implementation

Single batch, 1 file: `agent/core.py`

### Change: Add auto-compaction after budget warning

In the agent loop, right after the `if step > 3 and _budget_pct > 80:` block (line 949), add:

```python
# ── Auto-compact: trigger actual compaction when budget exceeded ──
# CC-aligned: SnipCompact → MicroCompact → full AutoCompact waterfall
if step > 3 and _budget_pct > 100 and self.compactor is not None:
    if not getattr(self, '_auto_compacted', False):
        import logging
        _compaction_logger = logging.getLogger(__name__)
        _compaction_logger.warning(
            "Auto-compact triggered at %.0f%% budget (%d/%d)",
            _budget_pct, total_tokens, _budget_total,
        )
        # Tier 1: zero-cost drain (SnipCompact + MicroCompact)
        _drained = 0
        try:
            from agent.context_trimming import _snip_history, _micro_compact
            _drained += _snip_history(history)
            _drained += _micro_compact(history)
            if _drained > 0:
                _compaction_logger.info(
                    "Auto-compact drain freed ~%d tokens", _drained,
                )
                # Recompute budget after drain
                _new_total = sum(
                    getattr(m, "token_count", 0) or 0
                    for m in history._messages
                )
                total_tokens = _new_total  # update budget tracker
                continue  # retry with compacted history
        except Exception as _dexc:
            _compaction_logger.debug("Auto-compact drain failed: %s", _dexc)
        # Tier 2: full LLM compact
        try:
            self.compactor.compact(history, total_tokens)
            self._auto_compacted = True
            _compaction_logger.info("Auto-compact: full LLM compact completed")
            continue  # retry with compacted history
        except Exception as _cexc:
            _compaction_logger.warning(
                "Auto-compact full compact failed: %s", _cexc,
            )
```

This is the minimal change — no new files, no config changes, no server-layer modifications. The auto-compaction uses the existing `ConversationCompactor` that's already available in the agent loop.

## Verification

1. Start server, send a long-running task that accumulates many tokens
2. Watch logs for "Auto-compact triggered at >100% budget"
3. After compaction, agent should continue without hitting "prompt too long" error
4. The compaction should be throttled (only one full compact per run)

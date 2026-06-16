"""
pytest conftest — auto-apply markers based on file name.

Usage:
    pytest -m core          # agent loop, task model, event log
    pytest -m llm           # backends, routing, native tool use
    pytest -m tools         # file/shell/git/memory tools
    pytest -m context       # token budget, history, compaction
    pytest -m multi         # multi-agent, DAG, plan
    pytest -m entry         # CLI, chat, renderer, config
    pytest                  # all tests (default)
"""
import pytest

_FILE_TO_MARKER = {
    "test_day1": "core",
    "test_day2": "core",
    "test_day7": "core",
    "test_factory": "core",
    "test_day4": "llm",
    "test_native_tool_use": "llm",
    "test_day3": "tools",
    "test_confirm": "tools",
    "test_sandbox": "tools",
    "test_web_tool": "tools",
    "test_memory_tool": "tools",
    "test_memory_store": "tools",
    "test_memory_system": "tools",
    "test_rag_memory": "tools",
    "test_code_chunker": "context",
    "test_day5": "context",
    "test_compaction": "context",
    "test_multi_agent": "multi",
    "test_dag": "multi",
    "test_plan": "multi",
    "test_day6": "entry",
    "test_chat": "entry",
    "test_renderer": "entry",
    "test_stream": "entry",
}


def pytest_collection_modifyitems(items):
    for item in items:
        stem = item.module.__name__.rsplit(".", 1)[-1]
        marker_name = _FILE_TO_MARKER.get(stem)
        if marker_name:
            item.add_marker(getattr(pytest.mark, marker_name))

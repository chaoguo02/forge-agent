from __future__ import annotations

import sys
from types import SimpleNamespace

from tools.web_tool import SearchResult, WebFetchTool, WebSearchTool


def test_web_fetch_schema_does_not_advertise_unused_prompt():
    tool = WebFetchTool()

    assert set(tool.parameters_schema["properties"]) == {"url"}
    assert "prompt" not in tool.description
    assert tool.metadata.required_permissions == frozenset({"network:fetch"})


def test_web_search_declares_network_search_permission():
    assert WebSearchTool().metadata.required_permissions == frozenset(
        {"network:search"},
    )


def test_web_search_returns_structured_data_with_compatibility_output(
    monkeypatch,
):
    class _DDGS:
        def text(self, query, max_results):
            return [
                {
                    "title": "Example",
                    "href": "https://example.test/docs",
                    "body": "A useful snippet",
                },
            ]

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=_DDGS))

    result = WebSearchTool().execute({"query": "example"})

    assert result.success
    assert result.output.startswith("Web search results for: example")
    assert result.data == (
        SearchResult(
            title="Example",
            url="https://example.test/docs",
            snippet="A useful snippet",
        ),
    )

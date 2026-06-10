"""
tests/test_memory_tool.py

测试记忆读写工具。
"""

from __future__ import annotations

import os
import tempfile

import pytest

from memory.models import Memory, MemoryMetadata, MemorySummary
from memory.store import MemoryStore
from tools.memory_tool import (
    MemoryReadTool, MemoryWriteTool, MemoryListTool, MemoryDeleteTool,
)


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield MemoryStore(
            repo_path="/tmp/test-repo",
            memory_dir=os.path.join(tmpdir, "memory"),
        )


@pytest.fixture
def read_tool(store):
    return MemoryReadTool(store)


@pytest.fixture
def write_tool(store):
    return MemoryWriteTool(store)


@pytest.fixture
def list_tool(store):
    return MemoryListTool(store)


@pytest.fixture
def delete_tool(store):
    return MemoryDeleteTool(store)


# ---------------------------------------------------------------------------
# MemoryReadTool
# ---------------------------------------------------------------------------

class TestMemoryReadTool:
    def test_read_existing(self, store, read_tool):
        store.write_memory(Memory(
            name="hello", description="Greeting", content="Hello World",
        ))
        result = read_tool.execute({"name": "hello"})
        assert result.success
        assert "Hello World" in result.output

    def test_read_nonexistent(self, read_tool):
        result = read_tool.execute({"name": "ghost"})
        assert not result.success
        assert "not found" in result.error.lower()

    def test_read_requires_name(self, read_tool):
        result = read_tool.execute({"name": ""})
        assert not result.success
        assert "required" in result.error.lower()

    def test_schema_requires_name(self, read_tool):
        schema = read_tool.to_llm_schema()
        assert schema.name == "memory_read"
        assert "name" in schema.parameters["required"]


# ---------------------------------------------------------------------------
# MemoryWriteTool
# ---------------------------------------------------------------------------

class TestMemoryWriteTool:
    def test_write_basic(self, store, write_tool, read_tool):
        result = write_tool.execute({
            "name": "build-cmd",
            "description": "Build commands",
            "type": "project",
            "content": "## Build\nnpm run build",
        })
        assert result.success
        assert "saved" in result.output.lower()

        # 验证写入
        read_result = read_tool.execute({"name": "build-cmd"})
        assert read_result.success
        assert "npm run build" in read_result.output

    def test_write_overwrite(self, store, write_tool, read_tool):
        write_tool.execute({"name": "x", "description": "v1", "type": "project", "content": "one"})
        result = write_tool.execute({"name": "x", "description": "v2", "type": "project", "content": "two"})
        assert result.success

        read_result = read_tool.execute({"name": "x"})
        assert "two" in read_result.output

    def test_write_requires_name(self, write_tool):
        result = write_tool.execute({
            "name": "", "description": "desc", "type": "project", "content": "body",
        })
        assert not result.success

    def test_write_requires_description(self, write_tool):
        result = write_tool.execute({
            "name": "test", "description": "", "type": "project", "content": "body",
        })
        assert not result.success

    def test_write_requires_content(self, write_tool):
        result = write_tool.execute({
            "name": "test", "description": "desc", "type": "project", "content": "",
        })
        assert not result.success

    def test_write_invalid_type(self, write_tool):
        result = write_tool.execute({
            "name": "test", "description": "desc", "type": "invalid", "content": "body",
        })
        assert not result.success

    def test_write_updates_index(self, store, write_tool, list_tool):
        write_tool.execute({
            "name": "my-mem", "description": "My memory",
            "type": "reference", "content": "Hello",
        })
        summaries = store.list_memories()
        assert any(s.name == "my-mem" for s in summaries)

    def test_schema_requires_correct_fields(self, write_tool):
        schema = write_tool.to_llm_schema()
        assert schema.name == "memory_write"
        assert "name" in schema.parameters["required"]
        assert "description" in schema.parameters["required"]
        assert "type" in schema.parameters["required"]
        assert "content" in schema.parameters["required"]


# ---------------------------------------------------------------------------
# MemoryListTool
# ---------------------------------------------------------------------------

class TestMemoryListTool:
    def test_list_empty(self, list_tool):
        result = list_tool.execute({})
        assert result.success
        assert "No memories" in result.output

    def test_list_with_memories(self, store, write_tool, list_tool):
        write_tool.execute({"name": "a", "description": "First", "type": "project", "content": "A"})
        write_tool.execute({"name": "b", "description": "Second", "type": "reference", "content": "B"})

        result = list_tool.execute({})
        assert result.success
        assert "a" in result.output
        assert "b" in result.output
        assert "First" in result.output
        assert "Second" in result.output

    def test_list_filter_by_type(self, store, write_tool, list_tool):
        write_tool.execute({"name": "a", "description": "Proj", "type": "project", "content": "A"})
        write_tool.execute({"name": "b", "description": "Ref", "type": "reference", "content": "B"})

        result = list_tool.execute({"type": "project"})
        assert result.success
        assert "a" in result.output
        assert "b" not in result.output

    def test_list_no_matching_type(self, list_tool):
        result = list_tool.execute({"type": "user"})
        assert result.success
        assert "No memories" in result.output

    def test_list_invalid_type(self, list_tool):
        result = list_tool.execute({"type": "bogus"})
        assert not result.success

    def test_schema(self, list_tool):
        schema = list_tool.to_llm_schema()
        assert schema.name == "memory_list"


# ---------------------------------------------------------------------------
# MemoryDeleteTool
# ---------------------------------------------------------------------------

class TestMemoryDeleteTool:
    def test_delete_existing(self, store, write_tool, delete_tool, read_tool):
        write_tool.execute({"name": "x", "description": "X", "type": "project", "content": "body"})
        assert read_tool.execute({"name": "x"}).success

        result = delete_tool.execute({"name": "x"})
        assert result.success
        assert "deleted" in result.output.lower()

        assert not read_tool.execute({"name": "x"}).success

    def test_delete_nonexistent(self, delete_tool):
        result = delete_tool.execute({"name": "ghost"})
        assert result.success  # 不存在返回成功

    def test_delete_requires_name(self, delete_tool):
        result = delete_tool.execute({"name": ""})
        assert not result.success

    def test_delete_updates_index(self, store, write_tool, delete_tool):
        write_tool.execute({"name": "x", "description": "X", "type": "project", "content": "body"})
        assert len(store.list_memories()) == 1

        delete_tool.execute({"name": "x"})
        assert len(store.list_memories()) == 0

    def test_schema_requires_name(self, delete_tool):
        schema = delete_tool.to_llm_schema()
        assert schema.name == "memory_delete"
        assert "name" in schema.parameters["required"]

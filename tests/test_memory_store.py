"""
tests/test_memory_store.py

测试 MemoryStore 的 CRUD 操作和 MEMORY.md 索引管理。
"""

from __future__ import annotations

import os
import tempfile

import pytest
import yaml

from memory.models import Memory, MemoryMetadata, MemorySummary
from memory.store import MemoryStore, _parse_frontmatter, _build_frontmatter


# ---------------------------------------------------------------------------
# 辅助：临时目录 fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_store():
    """创建一个使用临时目录的 MemoryStore。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = MemoryStore(
            repo_path="/tmp/test-repo",
            memory_dir=os.path.join(tmpdir, "memory"),
        )
        yield store


# ---------------------------------------------------------------------------
# 前/后 frontmatter 测试
# ---------------------------------------------------------------------------

class TestFrontmatter:
    def test_parse_frontmatter_basic(self):
        text = """---
name: build-cmd
description: Build commands
metadata:
  type: project
---

Content body here.
"""
        fm, body = _parse_frontmatter(text)
        assert fm["name"] == "build-cmd"
        assert fm["description"] == "Build commands"
        assert fm["metadata"]["type"] == "project"
        assert body == "Content body here."

    def test_parse_no_frontmatter(self):
        text = "Just content, no frontmatter."
        fm, body = _parse_frontmatter(text)
        assert fm == {}
        assert body == "Just content, no frontmatter."

    def test_parse_empty_body(self):
        text = """---
name: test
description: test
---
"""
        fm, body = _parse_frontmatter(text)
        assert fm["name"] == "test"
        assert body == ""

    def test_build_frontmatter(self):
        memory = Memory(
            name="test-memory",
            description="A test memory",
            content="Test content",
            metadata=MemoryMetadata(type="project"),
        )
        fm_str = _build_frontmatter(memory)
        parsed = yaml.safe_load(fm_str)
        assert parsed["name"] == "test-memory"
        assert parsed["description"] == "A test memory"
        assert parsed["metadata"]["type"] == "project"


# ---------------------------------------------------------------------------
# MemoryStore CRUD
# ---------------------------------------------------------------------------

class TestMemoryStore:
    def test_write_and_read(self, tmp_store):
        mem = Memory(
            name="build-commands",
            description="Build, test, and lint commands",
            content="## Build\nnpm run build",
            metadata=MemoryMetadata(type="project"),
        )
        assert tmp_store.write_memory(mem)

        read = tmp_store.read_memory("build-commands")
        assert read is not None
        assert read.name == "build-commands"
        assert read.description == "Build, test, and lint commands"
        assert "## Build" in read.content
        assert "npm run build" in read.content
        assert read.metadata.type == "project"

    def test_read_nonexistent(self, tmp_store):
        mem = tmp_store.read_memory("nonexistent")
        assert mem is None

    def test_write_overwrite(self, tmp_store):
        mem1 = Memory(
            name="test", description="v1", content="version 1",
        )
        mem2 = Memory(
            name="test", description="v2", content="version 2",
        )
        tmp_store.write_memory(mem1)
        tmp_store.write_memory(mem2)

        read = tmp_store.read_memory("test")
        assert read.content == "version 2"

    def test_delete(self, tmp_store):
        mem = Memory(name="todelete", description="delete me", content="bye")
        tmp_store.write_memory(mem)
        assert tmp_store.read_memory("todelete") is not None

        assert tmp_store.delete_memory("todelete")
        assert tmp_store.read_memory("todelete") is None

    def test_delete_nonexistent(self, tmp_store):
        """删除不存在的记忆应返回 True。"""
        assert tmp_store.delete_memory("ghost")

    def test_list_memories(self, tmp_store):
        mems = [
            Memory(name="a", description="First", content="A", metadata=MemoryMetadata(type="project")),
            Memory(name="b", description="Second", content="B", metadata=MemoryMetadata(type="reference")),
        ]
        for m in mems:
            tmp_store.write_memory(m)

        summaries = tmp_store.list_memories()
        names = [s.name for s in summaries]
        assert "a" in names
        assert "b" in names
        assert len(summaries) == 2

    def test_list_empty_store(self, tmp_store):
        summaries = tmp_store.list_memories()
        assert summaries == []

    def test_index_auto_rebuilt(self, tmp_store):
        """写入后 MEMORY.md 应该自动重建。"""
        mem = Memory(name="my-mem", description="My memory", content="Hello")
        tmp_store.write_memory(mem)

        assert tmp_store.index_path.exists()
        index_text = tmp_store.index_path.read_text(encoding="utf-8")
        assert "my-mem" in index_text
        assert "My memory" in index_text

    def test_get_index_content(self, tmp_store):
        mem = Memory(name="hello", description="Greeting", content="Hi")
        tmp_store.write_memory(mem)

        content = tmp_store.get_index_content()
        assert "hello" in content
        assert "Greeting" in content

    def test_get_index_content_empty(self, tmp_store):
        content = tmp_store.get_index_content()
        assert content == ""

    def test_store_dir_created(self, tmp_store):
        """目录在写入前应自动创建。"""
        assert tmp_store.store_dir.exists()

    def test_multiple_memories(self, tmp_store):
        names = ["alpha", "beta", "gamma"]
        for n in names:
            tmp_store.write_memory(Memory(name=n, description=n.upper(), content=n * 3))

        assert len(tmp_store.list_memories()) == 3
        for n in names:
            assert tmp_store.read_memory(n) is not None

    def test_index_parses_correctly(self, tmp_store):
        """list_memories 读取 MEMORY.md 后应返回正确的摘要。"""
        mem = Memory(
            name="big-memory",
            description="A large memory",
            content="x" * 1000,
            metadata=MemoryMetadata(type="reference"),
        )
        tmp_store.write_memory(mem)

        summaries = tmp_store.list_memories()
        assert len(summaries) == 1
        assert summaries[0].name == "big-memory"
        assert summaries[0].description == "A large memory"

"""
tests/test_external_memory_store.py

测试 ExternalMemoryStore：SQLite 持久化 + 语义搜索。
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from memory.external_store import ExternalMemoryStore


@pytest.fixture
def tmp_db() -> str:
    """临时数据库路径。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def store(tmp_db: str) -> ExternalMemoryStore:
    """带有临时数据库的 ExternalMemoryStore 实例。"""
    s = ExternalMemoryStore(db_path=tmp_db)
    yield s
    s.close()


class TestExternalMemoryStore:
    def test_add_and_get(self, store: ExternalMemoryStore):
        store.add_memory("login-bug", "The login bug was caused by a null pointer in auth.py")
        mem = store.get_memory("login-bug")
        assert mem is not None
        assert mem["name"] == "login-bug"
        assert "null pointer" in mem["content"]
        assert "created_at" in mem
        assert "updated_at" in mem

    def test_get_nonexistent(self, store: ExternalMemoryStore):
        mem = store.get_memory("nonexistent")
        assert mem is None

    def test_add_with_metadata(self, store: ExternalMemoryStore):
        store.add_memory("test-meta", "content", metadata={"type": "project", "priority": "high"})
        mem = store.get_memory("test-meta")
        assert mem["metadata"]["type"] == "project"
        assert mem["metadata"]["priority"] == "high"

    def test_overwrite_updates(self, store: ExternalMemoryStore):
        store.add_memory("key", "original content")
        store.add_memory("key", "updated content")
        mem = store.get_memory("key")
        assert mem["content"] == "updated content"

    def test_delete(self, store: ExternalMemoryStore):
        store.add_memory("to-delete", "delete me")
        assert store.get_memory("to-delete") is not None
        store.delete_memory("to-delete")
        assert store.get_memory("to-delete") is None

    def test_delete_nonexistent(self, store: ExternalMemoryStore):
        assert store.delete_memory("nothing") is True

    def test_list(self, store: ExternalMemoryStore):
        store.add_memory("a", "content a")
        store.add_memory("b", "content b")
        mems = store.list_memories()
        assert len(mems) == 2
        names = [m["name"] for m in mems]
        assert "a" in names
        assert "b" in names

    def test_list_empty(self, store: ExternalMemoryStore):
        assert store.list_memories() == []

    def test_persistence(self, tmp_db: str):
        """写入后重建 store，确认数据还在。"""
        store1 = ExternalMemoryStore(db_path=tmp_db)
        store1.add_memory("persist-test", "hello world")
        store1.close()

        store2 = ExternalMemoryStore(db_path=tmp_db)
        mem = store2.get_memory("persist-test")
        store2.close()
        assert mem is not None
        assert mem["content"] == "hello world"

    def test_search_similarity(self, store: ExternalMemoryStore):
        """添加两条语义不同的记忆，搜索应返回匹配度更高的那条。"""
        store.add_memory("python", "Python is a programming language with dynamic typing and garbage collection.")
        store.add_memory("coffee", "Coffee is a brewed drink made from roasted coffee beans.")

        results = store.search("programming languages", top_k=5)
        assert len(results) >= 1

        # Python 记忆的相关度应该高于 Coffee 记忆
        python_result = next(r for r in results if r["name"] == "python")
        coffee_result = next(r for r in results if r["name"] == "coffee")
        assert python_result["score"] > coffee_result["score"]

    def test_search_empty_store(self, store: ExternalMemoryStore):
        results = store.search("anything")
        assert results == []

    def test_search_returns_top_k(self, store: ExternalMemoryStore):
        for i in range(10):
            store.add_memory(f"note-{i}", f"This is note number {i} about various topics.")
        results = store.search("note", top_k=3)
        assert len(results) == 3

    def test_search_empty_query(self, store: ExternalMemoryStore):
        store.add_memory("test", "content")
        assert store.search("") == []
        assert store.search("   ") == []

    def test_context_manager(self, tmp_db: str):
        with ExternalMemoryStore(db_path=tmp_db) as store:
            store.add_memory("ctx-test", "context manager test")
            assert store.get_memory("ctx-test") is not None
        # 退出后 store 已关闭
        with ExternalMemoryStore(db_path=tmp_db) as store2:
            assert store2.get_memory("ctx-test") is not None


class TestMemorySearchTool:
    """集成测试：MemorySearchTool + ExternalMemoryStore。"""

    def test_tool_search(self, store: ExternalMemoryStore):
        from tools.memory_tool import MemorySearchTool

        store.add_memory("api-doc", "The REST API uses JWT tokens for authentication.")
        tool = MemorySearchTool(external_store=store)

        result = tool.execute({"query": "authentication"})
        assert result.success
        assert "api-doc" in result.output
        assert "JWT" in result.output or "REST" in result.output

    def test_tool_no_store(self):
        from tools.memory_tool import MemorySearchTool

        tool = MemorySearchTool(external_store=None)
        result = tool.execute({"query": "test"})
        assert not result.success
        assert "not available" in result.error.lower()

    def test_tool_empty_query(self, store: ExternalMemoryStore):
        from tools.memory_tool import MemorySearchTool

        tool = MemorySearchTool(external_store=store)
        result = tool.execute({"query": ""})
        assert not result.success
        assert "query is required" in result.error.lower()

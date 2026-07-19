"""Tests for SQLite and file memory backends."""
import os
import sqlite3
import tempfile

from memory.sqlite_backend import SqliteMemoryBackend
from memory.models import Memory, MemoryMetadata, MemorySummary


def _setup_db(db_path: str):
    """Create memory_entries and memory_anchors tables."""
    with sqlite3.connect(db_path) as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS memory_entries ("
            "name TEXT PRIMARY KEY, description TEXT, content TEXT, "
            "type TEXT, status TEXT, scope TEXT, confidence REAL, "
            "access_count INT DEFAULT 0, source TEXT DEFAULT '', "
            "source_session_id TEXT DEFAULT '', created_at TEXT, updated_at TEXT)"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS memory_anchors ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, memory_name TEXT, "
            "kind TEXT, path TEXT, symbol_name TEXT, task_value TEXT, content_hash TEXT)"
        )


def _make_mem(name, desc="test", content="# Test", type_="project",
              status="active", scope="project", confidence=0.7):
    return Memory(
        name=name, description=desc, content=content,
        metadata=MemoryMetadata(type=type_, status=status, scope=scope, confidence=confidence),
    )


class TestSqliteMemoryBackend:
    db_path: str = ""

    @classmethod
    def setup_method(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), f"test_mem_{os.getpid()}.db")
        _setup_db(cls.db_path)
        cls.b = SqliteMemoryBackend(cls.db_path)

    @classmethod
    def teardown_method(cls):
        try:
            os.unlink(cls.db_path)
        except OSError:
            pass

    def test_write_and_read(self):
        mem = _make_mem("test-write", content="# Hello")
        assert self.b.write_memory(mem), "write failed"
        read = self.b.read_memory("test-write")
        assert read is not None, "read returned None"
        assert read.name == "test-write"
        assert read.content == "# Hello"

    def test_delete(self):
        self.b.write_memory(_make_mem("test-del"))
        assert self.b.delete_memory("test-del"), "delete failed"
        assert self.b.read_memory("test-del") is None

    def test_delete_nonexistent(self):
        assert self.b.delete_memory("no-such-mem"), "delete should return True for missing"

    def test_list_memories(self):
        self.b.write_memory(_make_mem("mem-a"))
        self.b.write_memory(_make_mem("mem-b"))
        lst = self.b.list_memories()
        names = {s.name for s in lst}
        assert "mem-a" in names
        assert "mem-b" in names

    def test_count_by_type(self):
        self.b.write_memory(_make_mem("p1", type_="project"))
        self.b.write_memory(_make_mem("p2", type_="project"))
        self.b.write_memory(_make_mem("f1", type_="feedback"))
        ct = self.b.count_by_type()
        total = sum(ct.values())
        assert total >= 4, f"Expected >=4 total, got {total}"
        assert ct.get("project", 0) >= 2
        assert ct.get("feedback", 0) >= 1

    def test_record_access(self):
        self.b.write_memory(_make_mem("access-test"))
        assert self.b.record_access("access-test"), "record_access failed"
        mem = self.b.read_memory("access-test")
        assert mem is not None
        assert mem.metadata.access_count >= 1

    def test_list_by_scope(self):
        self.b.write_memory(_make_mem("g1", scope="global"))
        self.b.write_memory(_make_mem("p1", scope="project"))
        result = self.b.list_by_scope("global")
        assert len(result) == 1
        assert result[0].name == "g1"

    def test_get_index_content(self):
        self.b.write_memory(_make_mem("idx-a", desc="Index A"))
        content = self.b.get_index_content()
        assert "# Memory Index" in content
        assert "idx-a" in content


if __name__ == "__main__":
    t = TestSqliteMemoryBackend()
    t.setup_method()
    try:
        t.test_write_and_read()
        print("OK: test_write_and_read")
        t.test_delete()
        print("OK: test_delete")
        t.test_delete_nonexistent()
        print("OK: test_delete_nonexistent")
        t.test_list_memories()
        print("OK: test_list_memories")
        t.test_count_by_type()
        print("OK: test_count_by_type")
        t.test_record_access()
        print("OK: test_record_access")
        t.test_list_by_scope()
        print("OK: test_list_by_scope")
        t.test_get_index_content()
        print("OK: test_get_index_content")
        print("ALL 7 TESTS PASSED")
    finally:
        t.teardown_method()

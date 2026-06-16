"""
context/code_indexer.py

代码向量索引器。

扫描仓库代码文件 → AST 分块 → fastembed 向量化 → 存入 SQLite。
支持增量扫描（按 mtime 跳过未更改文件）和 .gitignore 感知。

与 memory/indexer.py（记忆向量索引）独立：
- memory/indexer.py: 索引用户记忆文档
- context/code_indexer.py: 索引代码库源文件

用法：
    indexer = CodeIndexer(db_path=".forge-agent/code_index.db")
    stats = indexer.scan_and_index("/path/to/repo")
    # stats = {"files_scanned": 42, "chunks_indexed": 156, "skipped": 10}
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from context.code_chunker import (
    CodeChunk,
    chunk_file,
    is_code_file,
    should_skip_path,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

DEFAULT_DB_NAME = "code_index.db"
BATCH_SIZE = 32  # embedding batch size
MAX_WORKERS = 4  # 并行解析文件数


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class IndexStats:
    files_scanned: int = 0
    chunks_indexed: int = 0
    files_skipped: int = 0
    errors: int = 0
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# CodeIndexer
# ---------------------------------------------------------------------------

class CodeIndexer:
    """
    代码向量索引器。

    独立 SQLite 数据库存储代码 chunk + embedding，
    与 external_memory.db 完全隔离。
    """

    def __init__(
        self,
        db_path: str | None = None,
        repo_path: str | None = None,
        model_name: str | None = None,
    ) -> None:
        if db_path is None and repo_path:
            db_path = str(Path(repo_path) / ".forge-agent" / DEFAULT_DB_NAME)
        elif db_path is None:
            db_path = str(Path.cwd() / ".forge-agent" / DEFAULT_DB_NAME)

        self._db_path = db_path
        self._model_name = model_name
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """初始化 SQLite schema。"""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS code_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                symbol_name TEXT NOT NULL,
                symbol_kind TEXT NOT NULL,
                content TEXT NOT NULL,
                docstring TEXT DEFAULT '',
                language TEXT DEFAULT '',
                embedding BLOB,
                metadata TEXT DEFAULT '{}',
                indexed_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS file_index (
                file_path TEXT PRIMARY KEY,
                mtime REAL NOT NULL,
                chunk_count INTEGER DEFAULT 0,
                indexed_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_code_chunks_file
                ON code_chunks(file_path);
            CREATE INDEX IF NOT EXISTS idx_code_chunks_symbol
                ON code_chunks(symbol_name);
        """)

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # 扫描 + 索引
    # ------------------------------------------------------------------

    def scan_and_index(self, repo_path: str | Path) -> IndexStats:
        """
        扫描仓库并索引所有代码文件。

        增量：按 mtime 跳过未更改的文件。
        """
        t0 = time.time()
        repo = Path(repo_path).resolve()
        stats = IndexStats()

        # 收集需要索引的文件
        files_to_index: list[tuple[Path, str]] = []

        try:
            all_paths = sorted(repo.rglob("*"))
        except OSError:
            return stats

        for path in all_paths:
            if should_skip_path(path):
                continue
            try:
                if not path.is_file():
                    continue
                if not is_code_file(path):
                    continue
            except OSError:
                continue

            rel_path = str(path.relative_to(repo))
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue

            # 增量检查
            if self._is_up_to_date(rel_path, mtime):
                stats.files_skipped += 1
                continue

            files_to_index.append((path, rel_path))

        # 并行解析文件
        all_chunks: list[tuple[str, list[CodeChunk]]] = []

        def _parse_file(item: tuple[Path, str]) -> tuple[str, list[CodeChunk]]:
            path, rel = item
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                chunks = chunk_file(rel, content)
                return (rel, chunks)
            except Exception as e:
                logger.debug("Failed to chunk %s: %s", rel, e)
                return (rel, [])

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(_parse_file, f): f for f in files_to_index}
            for future in as_completed(futures):
                try:
                    result = future.result()
                    all_chunks.append(result)
                    stats.files_scanned += 1
                except Exception:
                    stats.errors += 1

        # 批量向量化 + 写入
        for rel_path, chunks in all_chunks:
            if not chunks:
                self._update_file_index(rel_path, 0)
                continue

            try:
                self._index_chunks(rel_path, chunks)
                stats.chunks_indexed += len(chunks)
            except Exception as e:
                logger.warning("Failed to index %s: %s", rel_path, e)
                stats.errors += 1

        stats.elapsed_seconds = time.time() - t0
        logger.info(
            "Code indexing complete: %d files, %d chunks, %.1fs",
            stats.files_scanned, stats.chunks_indexed, stats.elapsed_seconds,
        )
        return stats

    def _is_up_to_date(self, rel_path: str, mtime: float) -> bool:
        """检查文件是否已索引且未更改。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT mtime FROM file_index WHERE file_path = ?",
            (rel_path,),
        ).fetchone()
        if row and row[0] >= mtime:
            return True
        return False

    def _index_chunks(self, rel_path: str, chunks: list[CodeChunk]) -> None:
        """向量化并写入单个文件的所有 chunk。"""
        # 批量 embedding
        embed_texts = [c.embed_text for c in chunks]
        embeddings = self._encode_batch(embed_texts)

        now = time.time()
        conn = self._get_conn()

        with self._lock:
            # 删旧
            conn.execute("DELETE FROM code_chunks WHERE file_path = ?", (rel_path,))

            # 插新
            rows = []
            for i, chunk in enumerate(chunks):
                emb_bytes = embeddings[i] if i < len(embeddings) else None
                meta = json.dumps({
                    "language": chunk.language,
                    "docstring": chunk.docstring[:200] if chunk.docstring else "",
                })
                rows.append((
                    chunk.file_path,
                    chunk.start_line,
                    chunk.end_line,
                    chunk.symbol_name,
                    chunk.symbol_kind,
                    chunk.content,
                    chunk.docstring or "",
                    chunk.language,
                    emb_bytes,
                    meta,
                    now,
                ))

            conn.executemany(
                """INSERT INTO code_chunks
                   (file_path, start_line, end_line, symbol_name, symbol_kind,
                    content, docstring, language, embedding, metadata, indexed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )

            self._update_file_index(rel_path, len(chunks))
            conn.commit()

    def _update_file_index(self, rel_path: str, chunk_count: int) -> None:
        """更新 file_index 表。"""
        conn = self._get_conn()
        now = time.time()
        conn.execute(
            """INSERT OR REPLACE INTO file_index (file_path, mtime, chunk_count, indexed_at)
               VALUES (?, ?, ?, ?)""",
            (rel_path, now, chunk_count, now),
        )

    def _encode_batch(self, texts: list[str]) -> list[bytes | None]:
        """批量 embedding，返回 bytes 列表。无 fastembed 时返回 None 列表。"""
        try:
            from memory.external_store import _encode_batch, _embedding_to_bytes
        except ImportError:
            return [None] * len(texts)

        try:
            vectors = _encode_batch(texts, self._model_name)
            return [_embedding_to_bytes(v) for v in vectors]
        except Exception as e:
            logger.warning("Embedding failed: %s", e)
            return [None] * len(texts)

    # ------------------------------------------------------------------
    # 查询接口（供 CodeRetriever 使用）
    # ------------------------------------------------------------------

    def search(
        self,
        query_embedding: Any,
        top_k: int = 10,
        min_score: float = 0.3,
        file_pattern: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        向量相似度搜索代码 chunk。

        Args:
            query_embedding: numpy array（归一化的 query embedding）
            top_k: 返回前 N 个结果
            min_score: 最低相似度
            file_pattern: 可选文件路径 glob 过滤

        Returns:
            [{file_path, start_line, end_line, symbol_name, symbol_kind, content, score}, ...]
        """
        import numpy as np
        from memory.external_store import _bytes_to_embedding

        conn = self._get_conn()

        query_str = "SELECT file_path, start_line, end_line, symbol_name, symbol_kind, content, docstring, embedding FROM code_chunks"
        params: list[Any] = []

        if file_pattern:
            query_str += " WHERE file_path LIKE ?"
            # 将 glob 转为 SQL LIKE
            like_pattern = file_pattern.replace("*", "%").replace("?", "_")
            params.append(like_pattern)

        rows = conn.execute(query_str, params).fetchall()
        if not rows:
            return []

        scored: list[tuple[float, dict]] = []
        for row in rows:
            emb_bytes = row[7]
            if not emb_bytes:
                continue

            emb = _bytes_to_embedding(emb_bytes)
            score = float(np.dot(query_embedding, emb))

            if score < min_score:
                continue

            scored.append((score, {
                "file_path": row[0],
                "start_line": row[1],
                "end_line": row[2],
                "symbol_name": row[3],
                "symbol_kind": row[4],
                "content": row[5],
                "docstring": row[6],
                "score": score,
            }))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:top_k]]

    def get_stats(self) -> dict[str, int]:
        """获取索引统计。"""
        conn = self._get_conn()
        files = conn.execute("SELECT COUNT(*) FROM file_index").fetchone()[0]
        chunks = conn.execute("SELECT COUNT(*) FROM code_chunks").fetchone()[0]
        return {"files": files, "chunks": chunks}

"""
context/code_retriever.py

代码语义检索器。

将自然语言查询转为 embedding，在 code_index 中检索相关代码片段。
结果附带文件路径 + 行号 + 符号名，可直接被 LLM 用于定位代码。

与 memory/retriever.py（记忆检索）互补：
- memory/retriever.py: 从记忆库中检索相关上下文
- context/code_retriever.py: 从代码库中检索相关代码片段
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CodeRetriever:
    """
    代码语义检索器。

    用法：
        retriever = CodeRetriever(indexer)
        results = retriever.search("handle user login authentication")
        # → [{"file_path": "auth/login.py", "symbol_name": "login_handler", ...}, ...]
    """

    def __init__(
        self,
        indexer: Any,
        top_k: int = 10,
        min_score: float = 0.3,
    ) -> None:
        self._indexer = indexer
        self._top_k = top_k
        self._min_score = min_score

    def search(
        self,
        query: str,
        top_k: int | None = None,
        file_pattern: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        自然语言搜索代码片段。

        Args:
            query: 自然语言查询
            top_k: 返回数量（覆盖默认值）
            file_pattern: 文件路径 glob 过滤（如 "*.py", "src/**"）

        Returns:
            按相关度排序的代码片段列表
        """
        if not query.strip():
            return []

        top_k = top_k or self._top_k

        try:
            query_embedding = self._encode_query(query)
        except Exception as e:
            logger.warning("Failed to encode query: %s", e)
            return []

        results = self._indexer.search(
            query_embedding=query_embedding,
            top_k=top_k,
            min_score=self._min_score,
            file_pattern=file_pattern,
        )

        return results

    def search_by_symbol(self, symbol_name: str) -> list[dict[str, Any]]:
        """按符号名搜索（精确或模糊匹配）。"""
        return self.search(f"function {symbol_name}")

    def format_results(self, results: list[dict[str, Any]]) -> str:
        """
        将搜索结果格式化为 LLM 可读的文本。

        用于注入到 agent prompt 中。
        """
        if not results:
            return ""

        lines = ["## Code Search Results\n"]
        for i, r in enumerate(results, 1):
            score = r.get("score", 0)
            lines.append(
                f"### [{i}] {r['file_path']}:{r['start_line']}-{r['end_line']} "
                f"({r['symbol_kind']} `{r['symbol_name']}`, score: {score:.2f})"
            )
            if r.get("docstring"):
                lines.append(f"  Docstring: {r['docstring'][:100]}")
            # 截取代码预览（前 20 行）
            content = r.get("content", "")
            preview_lines = content.splitlines()[:20]
            if len(content.splitlines()) > 20:
                preview_lines.append("  ... (truncated)")
            lines.append("```")
            lines.extend(preview_lines)
            lines.append("```\n")

        return "\n".join(lines)

    def _encode_query(self, query: str):
        """将查询文本编码为 embedding 向量。"""
        from memory.external_store import _encode
        return _encode(query)

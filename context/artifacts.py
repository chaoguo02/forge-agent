"""
context/artifacts.py

Artifact Store — 大型工具输出的外部化存储。

设计原理：
- 工具输出超过 token 阈值时，原始内容存入内存中的 ArtifactStore
- 对话历史中只保留短摘要引用（artifact_id + 首 N 行 + 统计信息）
- LLM 可通过 artifact_id 请求完整内容（未来扩展）
- 支持 LRU 淘汰，避免内存无限增长

与 Claude Code 的 artifact 思路一致：
- 大输出不塞进 prompt，保持 context window 精简
- 摘要保留足够信息让 LLM 决定是否需要完整内容

接入点：
- agent/core.py 的 _build_tool_result_content() 调用 maybe_store()
- 返回 (应放入历史的文本, 是否被artifact化)
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from context.token_budget import estimate_tokens


@dataclass
class Artifact:
    """存储的单个 artifact。"""
    artifact_id: str
    tool_name: str
    full_content: str
    summary: str
    token_count: int
    char_count: int
    line_count: int
    created_at: float = field(default_factory=time.time)

    def reference_text(self) -> str:
        """生成放入历史的引用文本。"""
        return (
            f"[Artifact {self.artifact_id} | {self.tool_name} | "
            f"{self.line_count} lines, ~{self.token_count} tokens]\n"
            f"{self.summary}"
        )


class ArtifactStore:
    """
    内存中的 artifact 存储。LRU 淘汰策略。

    用法：
        store = ArtifactStore(threshold_tokens=2000, max_artifacts=50)
        text_for_history, was_stored = store.maybe_store(tool_name, output)
    """

    def __init__(
        self,
        threshold_tokens: int = 2000,
        max_artifacts: int = 50,
        summary_lines: int = 15,
        summary_tail_lines: int = 5,
    ) -> None:
        self._threshold_tokens = threshold_tokens
        self._max_artifacts = max_artifacts
        self._summary_lines = summary_lines
        self._summary_tail_lines = summary_tail_lines
        self._store: OrderedDict[str, Artifact] = OrderedDict()

    @property
    def threshold_tokens(self) -> int:
        return self._threshold_tokens

    def maybe_store(self, tool_name: str, output: str) -> tuple[str, bool]:
        """
        检查输出是否需要 artifact 化。

        Args:
            tool_name: 产生此输出的工具名
            output: 工具原始输出

        Returns:
            (text_for_history, was_artifacted)
            - was_artifacted=False: 返回原始 output，不做处理
            - was_artifacted=True: 返回摘要引用文本
        """
        if not output:
            return output, False

        token_count = estimate_tokens(output)
        if token_count <= self._threshold_tokens:
            return output, False

        artifact = self._create_artifact(tool_name, output, token_count)
        self._add(artifact)
        return artifact.reference_text(), True

    def get(self, artifact_id: str) -> Artifact | None:
        """按 ID 获取 artifact，LRU 更新访问顺序。"""
        if artifact_id not in self._store:
            return None
        self._store.move_to_end(artifact_id)
        return self._store[artifact_id]

    def get_full_content(self, artifact_id: str) -> str | None:
        """获取 artifact 的完整内容。"""
        art = self.get(artifact_id)
        return art.full_content if art else None

    def list_artifacts(self) -> list[tuple[str, str, int]]:
        """返回 [(artifact_id, tool_name, token_count), ...]"""
        return [
            (art.artifact_id, art.tool_name, art.token_count)
            for art in self._store.values()
        ]

    @property
    def count(self) -> int:
        return len(self._store)

    @property
    def total_tokens_stored(self) -> int:
        return sum(a.token_count for a in self._store.values())

    def _create_artifact(self, tool_name: str, output: str, token_count: int) -> Artifact:
        """从原始输出创建 Artifact，生成摘要。"""
        lines = output.splitlines()
        line_count = len(lines)

        summary = self._build_summary(lines, tool_name, token_count, line_count)

        content_hash = hashlib.sha256(output[:1000].encode(errors="replace")).hexdigest()[:8]
        artifact_id = f"art_{content_hash}"

        return Artifact(
            artifact_id=artifact_id,
            tool_name=tool_name,
            full_content=output,
            summary=summary,
            token_count=token_count,
            char_count=len(output),
            line_count=line_count,
        )

    def _build_summary(
        self, lines: list[str], tool_name: str, token_count: int, line_count: int
    ) -> str:
        """构建 artifact 摘要：保留首 N 行 + 尾 M 行 + 统计信息。"""
        head_n = self._summary_lines
        tail_n = self._summary_tail_lines
        max_summary_chars = 2000

        if line_count <= head_n + tail_n:
            joined = "\n".join(lines)
            if len(joined) <= max_summary_chars:
                return joined
            # Few lines but very long — char-level truncation
            return (
                joined[:max_summary_chars // 2]
                + f"\n... [{len(joined) - max_summary_chars} chars omitted, ~{token_count} tokens total] ...\n"
                + joined[-max_summary_chars // 4:]
            )

        head = lines[:head_n]
        tail = lines[-tail_n:] if tail_n > 0 else []
        omitted = line_count - head_n - tail_n

        parts = []
        parts.extend(head)
        parts.append(f"... [{omitted} lines omitted, ~{token_count} tokens total] ...")
        if tail:
            parts.extend(tail)

        return "\n".join(parts)

    def _add(self, artifact: Artifact) -> None:
        """添加 artifact，执行 LRU 淘汰。"""
        if artifact.artifact_id in self._store:
            self._store.move_to_end(artifact.artifact_id)
            self._store[artifact.artifact_id] = artifact
        else:
            self._store[artifact.artifact_id] = artifact

        while len(self._store) > self._max_artifacts:
            self._store.popitem(last=False)

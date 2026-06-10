"""
context/compaction.py

客户端对话压缩（Compaction）。

当对话历史接近 token 预算上限时，把工具调用记录压缩成结构化摘要，
保留关键信息，丢弃完整的工具输出。

使用场景：
- 自动：_build_messages() 检测到历史 token 超预算时触发
- 手动：用户输入 /compact 命令时触发

压缩策略（不调 LLM）：
- 从 tool call + observation 中提取：做了什么工具、关键结果
- 从 assistant 消息中提取：推理结论
- 格式化为紧凑的结构化块
"""

from __future__ import annotations

import re
import logging
from typing import Any

from context.token_budget import estimate_tokens, TokenBudget

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_COMPACTION_TRIGGER_RATIO = 0.80  # 历史 token 超过预算的 80% 时触发
_COMPACTION_BLOCK_TOKEN_BUDGET = 2000  # compaction 块的目标 token 数
_MIN_HISTORY_BEFORE_COMPACT = 6  # 少于 N 条消息时不做 compaction

# 正则：匹配 forge-agent 的纯文本格式
# assistant: "Thought: ...\nAction: tool_name\nParams: {...}"
# user: "[Tool: tool_name | SUCCESS]\noutput..."
_RE_THOUGHT = re.compile(r"Thought:\s*(.+?)(?:\n|$)", re.DOTALL)
_RE_ACTION = re.compile(r"Action:\s*(\S+)")
_RE_PARAMS = re.compile(r"Params:\s*(\{.*\})", re.DOTALL)
_RE_OBSERVATION = re.compile(
    r"\[Tool:\s*(\S+)\s*\|\s*(\w+)\]\s*\n?(.*)",
    re.DOTALL,
)
_RE_TRUNCATED = re.compile(r"\[(\d+) earlier messages were truncated")


# ---------------------------------------------------------------------------
# ConversationCompactor
# ---------------------------------------------------------------------------

class ConversationCompactor:
    """
    对话历史压缩器。

    把工具调用+结果+推理的消息序列压缩成一段结构化摘要，
    替换原始历史中的多条消息。
    """

    def __init__(
        self,
        trigger_ratio: float = _COMPACTION_TRIGGER_RATIO,
        compact_budget: int = _COMPACTION_BLOCK_TOKEN_BUDGET,
        min_history: int = _MIN_HISTORY_BEFORE_COMPACT,
    ) -> None:
        self._trigger_ratio = trigger_ratio
        self._compact_budget = compact_budget
        self._min_history = min_history

    # ------------------------------------------------------------------
    # 判断是否需要 compaction
    # ------------------------------------------------------------------

    def should_compact(
        self,
        history_dicts: list[dict],
        token_budget: TokenBudget,
    ) -> bool:
        """
        判断是否需要 compaction。

        Args:
            history_dicts: history.to_dicts() 的输出
            token_budget:  TokenBudget 实例

        Returns:
            True 表示需要 compaction
        """
        if len(history_dicts) < self._min_history:
            return False

        plan = token_budget.default_plan()
        total_tokens = sum(
            estimate_tokens(m.get("content", "")) for m in history_dicts
        )
        threshold = int(plan.history * self._trigger_ratio)
        return total_tokens > threshold

    # ------------------------------------------------------------------
    # 执行 compaction
    # ------------------------------------------------------------------

    def compact_history(
        self,
        history_dicts: list[dict],
        max_tokens: int | None = None,
    ) -> list[dict]:
        """
        压缩对话历史。

        保留首条消息（任务描述），其余消息压缩成一段 compact 摘要块。

        Args:
            history_dicts: history.to_dicts() 的输出
            max_tokens:   compaction 块的目标 token 数

        Returns:
            压缩后的历史 dict 列表：[保留的首条, compact 块, 最后几轮原始]
        """
        if not history_dicts:
            return history_dicts

        budget = max_tokens or self._compact_budget
        first = history_dicts[0]  # 保留首条任务描述
        rest = history_dicts[1:]  # 其余消息

        if not rest:
            return [first]

        # 1. 从 rest 中提取最后几轮（保留最近 2-3 轮原始消息）
        keep_recent = self._extract_recent_rounds(rest, n_rounds=2)

        # 2. 压缩剩余的老消息
        compact_targets = rest[:max(0, len(rest) - len(keep_recent))]

        if compact_targets:
            compact_block = self._build_compact_block(compact_targets, budget)
            result = [first, compact_block] + keep_recent
        else:
            result = [first] + keep_recent

        return result

    def build_compact_block_for_history(
        self,
        history_dicts: list[dict],
        max_tokens: int | None = None,
    ) -> dict:
        """
        为完整历史生成一段 compaction 块（/compact 命令用）。

        保留首条，压缩剩余全部。

        Returns:
            {"role": "user", "content": compact_text}
        """
        if not history_dicts:
            return {"role": "user", "content": "(empty conversation)"}

        budget = max_tokens or self._compact_budget
        first = history_dicts[0]
        rest = history_dicts[1:]

        compact_text = self._summarize_messages(rest, budget)

        return {
            "role": "user",
            "content": f"[Conversation compacted — earlier messages summarized]\n\n"
                       f"Original task: {first.get('content', '')[:200]}\n\n"
                       f"{compact_text}\n\n"
                       f"[End of compaction summary. Resume conversation.]",
        }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _extract_recent_rounds(
        self,
        messages: list[dict],
        n_rounds: int = 2,
    ) -> list[dict]:
        """
        从消息列表中提取最近 N 轮（assistant + user 对）。
        从后往前找，保留最后的 N 个配对。
        """
        if not messages:
            return []

        # 从后往前遍历，找 assistant + user 对
        rounds: list[list[dict]] = []
        current_round: list[dict] = []

        for msg in reversed(messages):
            current_round.insert(0, msg)
            if msg.get("role") == "assistant" and current_round:
                rounds.insert(0, current_round)
                current_round = []
                if len(rounds) >= n_rounds:
                    break
            elif msg.get("role") == "user":
                # user 消息可能是上一轮的 tool result
                # 如果 current_round 以 user 开头，它属于上一轮
                if current_round and current_round[0].get("role") == "user":
                    rounds.insert(0, current_round)
                    current_round = [msg]
                    if len(rounds) >= n_rounds:
                        break
                else:
                    current_round = [msg]

        # 把选中的轮次展开回列表
        selected = []
        for rnd in rounds:
            selected.extend(rnd)

        # 确定有多少条消息被保留了，返回对应的原始消息
        count = len(selected)
        return messages[-count:] if count > 0 else []

    def _build_compact_block(
        self,
        messages: list[dict],
        max_tokens: int,
    ) -> dict:
        """把一批消息压缩成一段 compact 块。"""
        text = self._summarize_messages(messages, max_tokens)

        return {
            "role": "user",
            "content": (
                f"[Earlier conversation summarized — {len(messages)} messages "
                f"compacted]\n\n{text}\n\n"
                f"[Continue below with the most recent exchanges.]"
            ),
        }

    def _summarize_messages(
        self,
        messages: list[dict],
        max_tokens: int,
    ) -> str:
        """
        把消息列表压缩成紧凑摘要。

        提取：
        - 每个 assistant 消息的 thought
        - 每个 tool 调用的名称 + 关键参数
        - 每个 tool result 的关键输出（截断）
        """
        entries: list[str] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "assistant":
                extracted = self._extract_from_assistant(content)
                if extracted:
                    entries.append(extracted)

            elif role == "user":
                extracted = self._extract_from_observation(content)
                if extracted:
                    entries.append(extracted)

        summary = "\n".join(entries)

        # 裁剪到 max_tokens
        if estimate_tokens(summary) > max_tokens:
            chars = max_tokens * 4
            summary = summary[:chars]
            summary += f"\n... (truncated to fit budget)"

        return summary

    def _extract_from_assistant(self, content: str) -> str | None:
        """从 assistant 消息提取 thought + tool call 摘要。"""
        if not content.strip():
            return None

        # 检查 compaction 块自身（避免递归）
        if content.startswith("[Earlier conversation summarized") or \
           content.startswith("[Conversation compacted"):
            return None

        # 提取 thought（第一行，或 Thought: 后的内容）
        thought_match = _RE_THOUGHT.search(content)
        action_match = _RE_ACTION.search(content)
        params_match = _RE_PARAMS.search(content)

        parts = []

        if thought_match:
            thought = thought_match.group(1).strip()[:200]
            if thought:
                parts.append(f"→ {thought}")

        if action_match:
            tool_name = action_match.group(1)
            param_info = ""
            if params_match:
                try:
                    import json
                    params = json.loads(params_match.group(1))
                    # 提取关键参数（路径、命令等）
                    key_params = []
                    for k in ("cmd", "path", "file_path", "pattern", "name"):
                        if k in params:
                            key_params.append(f"{k}={params[k]}")
                    if key_params:
                        param_info = " (" + ", ".join(key_params) + ")"
                except (json.JSONDecodeError, ValueError):
                    pass
            parts.append(f"  🛠 {tool_name}{param_info}")

        return "\n".join(parts) if parts else None

    def _extract_from_observation(self, content: str) -> str | None:
        """从 user/observation 消息提取工具结果摘要。"""
        if not content.strip():
            return None

        # 跳过 compaction 块自身
        if content.startswith("[Earlier conversation summarized") or \
           content.startswith("[Conversation compacted"):
            return None

        # 匹配 [Tool: name | STATUS]
        obs_match = _RE_OBSERVATION.match(content.strip())
        if not obs_match:
            return None

        tool_name = obs_match.group(1)
        status = obs_match.group(2)
        output = obs_match.group(3).strip()

        # 提取输出的关键信息
        key_info = self._extract_key_output(output)
        status_icon = "✓" if status == "SUCCESS" else "✗"

        result = f"  {status_icon} [{tool_name}]"
        if key_info:
            result += f": {key_info}"
        return result

    def _extract_key_output(self, output: str) -> str:
        """
        从工具输出中提取关键信息。

        策略：
        1. 取第一行有实质内容的（跳过空行/分隔符）
        2. 如果包含关键信息（test results, error, file paths），保留
        3. 截断到 150 字符
        """
        if not output:
            return ""

        lines = output.splitlines()
        meaningful = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            # 跳过装饰性分隔符行
            if all(c in "─━═-*_— " for c in stripped):
                continue
            # 跳过纯数字行
            if stripped.isdigit():
                continue

            meaningful.append(stripped)

        if not meaningful:
            return ""

        # 取前 N 行
        preview = meaningful[:3]
        text = "; ".join(preview)

        if len(meaningful) > 3:
            text += f" ... ({len(meaningful) - 3} more lines)"

        # 截断到 150 字
        if len(text) > 150:
            text = text[:147] + "..."

        return text


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

def create_compactor(
    trigger_ratio: float = _COMPACTION_TRIGGER_RATIO,
) -> ConversationCompactor:
    """创建默认配置的 ConversationCompactor。"""
    return ConversationCompactor(trigger_ratio=trigger_ratio)

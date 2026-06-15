"""
context/token_budget.py

Token 预算管理：给 prompt 各部分分配 token 配额，超出时按优先级裁剪。

算法：配合模型实际 max_context_window，按已消耗 token 量衰减历史配额。

各部分优先级（高→低，裁剪时从低优先级开始）：
  1. system_core   系统指令，永不裁剪
  2. task          任务描述，永不裁剪
  3. repo_map      repo 摘要，超出时缩减
  4. recent_obs    最近 observation，永不裁剪
  5. history       历史对话，从最旧开始裁剪
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Token 计数：优先 tiktoken，失败时字符估算 fallback
# ---------------------------------------------------------------------------

_tiktoken_enc = None
_tiktoken_available = False

def _init_tiktoken() -> None:
    global _tiktoken_enc, _tiktoken_available
    if _tiktoken_available or _tiktoken_enc is not None:
        return
    try:
        import tiktoken
        _tiktoken_enc = tiktoken.get_encoding("cl100k_base")
        _tiktoken_available = True
    except Exception:
        # 网络不通 / 未安装，降级为字符估算
        _tiktoken_available = False


def estimate_tokens(text: str) -> int:
    """
    估算文本的 token 数。
    优先使用 tiktoken（精确），不可用时用字符数 // 4（误差 <15%）。
    """
    if not _tiktoken_available:
        _init_tiktoken()

    if _tiktoken_available and _tiktoken_enc is not None:
        try:
            return max(1, len(_tiktoken_enc.encode(text)))
        except Exception:
            pass

    # 字符估算 fallback
    return max(1, len(text) // 4)


def estimate_chars(tokens: int) -> int:
    """把 token 数转换为字符预算（估算）。"""
    return tokens * 4


def is_tiktoken_available() -> bool:
    """返回 tiktoken 是否可用，供诊断脚本使用。"""
    _init_tiktoken()
    return _tiktoken_available


# ---------------------------------------------------------------------------
# BudgetPlan
# ---------------------------------------------------------------------------

@dataclass
class BudgetPlan:
    """各部分的 token 配额计划。"""
    total: int
    system_core: int
    repo_map: int
    history: int
    observation: int
    reserve: int                     # 保留向后兼容，新代码为 0

    @property
    def available(self) -> int:
        return self.total - self.reserve


# ---------------------------------------------------------------------------
# TokenBudget
# ---------------------------------------------------------------------------

# 给 model response 预留的 token 空间（代替旧的 15% reserve）
_OUTPUT_ROOM = 4096

# 衰减公式分母系数：consumed 达到 effective × DENOM 时 decay=0.67
_DECAY_DENOM = 3

# 衰减下限，防止历史配额收缩到不可用
_DECAY_FLOOR = 0.30


class TokenBudget:
    """
    Token 预算管理器——消费感知的动态分配。

    用法：
        budget = TokenBudget(total=80_000)
        plan = budget.compute_plan(consumed_tokens=0, max_context_window=200_000)
        trimmed = budget.trim_to(text, plan.repo_map)
        trimmed_history = budget.trim_history(msgs, plan.history)
    """

    def __init__(self, total: int = 80_000) -> None:
        self._total = total

    def compute_plan(
        self,
        consumed_tokens: int = 0,
        max_context_window: int | None = None,
    ) -> BudgetPlan:
        """
        根据已消耗 token 数和模型上下文窗口，计算本轮配额。

        Args:
            consumed_tokens:  本轮之前已消耗的 token 总数（input + output）
            max_context_window: 模型的最大上下文窗口，None 时用 self._total

        Returns:
            BudgetPlan，其中 history 随 consumed_tokens 增大而衰减
        """
        effective = self._total
        if max_context_window is not None:
            effective = min(self._total, max_context_window)

        available = effective - _OUTPUT_ROOM

        if available <= 0:
            # 极端情况：上下文窗口太小，给保底配额
            return BudgetPlan(
                total=effective,
                reserve=0,
                system_core=max(500, effective // 4),
                repo_map=0,
                history=max(500, effective // 4),
                observation=0,
            )

        # 衰减系数：consumed_tokens 越大，历史配给越紧
        decay = _DECAY_FLOOR
        if consumed_tokens == 0:
            decay = 1.0
        else:
            decay = max(
                _DECAY_FLOOR,
                1.0 - consumed_tokens / (effective * _DECAY_DENOM),
            )

        # 固定开销组件（上限保护）
        system_core = max(2000, int(available * 0.12))
        repo_map = min(int(available * 0.12), 12_000)
        observation = max(1000, int(available * 0.10))

        # 历史 = 剩余空间 × 衰减
        base_history = available - system_core - repo_map - observation
        if base_history <= 0:
            base_history = available // 2

        if consumed_tokens == 0:
            history = base_history
        else:
            history = max(2000, int(base_history * decay))

        return BudgetPlan(
            total=effective,
            reserve=0,
            system_core=system_core,
            repo_map=repo_map,
            history=history,
            observation=observation,
        )

    def default_plan(self) -> BudgetPlan:
        """
        向后兼容的默认计划，等价于 compute_plan(0)。
        """
        return self.compute_plan(consumed_tokens=0, max_context_window=None)

    def trim_to(self, text: str, token_limit: int) -> str:
        """裁剪文本到 token_limit 以内，超出时保留开头。"""
        if estimate_tokens(text) <= token_limit:
            return text
        # 二分逼近：找到合适的字符截断点
        char_limit = token_limit * 4
        candidate = text[:char_limit]
        while estimate_tokens(candidate) > token_limit and len(candidate) > 0:
            candidate = candidate[:int(len(candidate) * 0.9)]
        omitted = estimate_tokens(text[len(candidate):])
        return candidate + f"\n... [{omitted} tokens truncated]"

    def trim_history(
        self,
        messages: list[dict],
        token_limit: int,
    ) -> list[dict]:
        """
        裁剪历史消息列表到 token_limit 以内。
        保留第一条（任务描述）+ 尽量多的最近消息。

        分级策略（从轻到重，均从后往前保留最近的消息）：
        1. 保留 tool_use，丢弃 tool_result（旧工具输出）
        2. 丢弃旧 tool_use 记录，保留 thought
        3. 仅保留最后 N 轮
        """
        if not messages:
            return messages

        token_counts = [estimate_tokens(m.get("content", "")) for m in messages]
        total = sum(token_counts)

        if total <= token_limit:
            return messages

        # ── 第 1 级：尝试丢弃旧 observation（tool result） ────────────
        result = self._trim_results_only(messages, token_counts, token_limit)
        if result is not None:
            return result

        # ── 第 2 级：尝试丢弃旧 tool_use，保留推理 ───────────────────
        result = self._trim_tool_calls(messages, token_counts, token_limit)
        if result is not None:
            return result

        # ── 第 3 级：回退到原始简单策略 ────────────────────────────
        return self._trim_simple(messages, token_counts, token_limit)

    @staticmethod
    def _trim_results_only(
        messages: list[dict],
        token_counts: list[int],
        token_limit: int,
    ) -> list[dict] | None:
        """
        第 1 级：丢弃旧的 observation（[Tool: ...] user 消息），
        保留对应的 assistant 消息。
        从后往前处理，保留最近的消息。
        """
        first = messages[0]
        first_tokens = token_counts[0]

        # 从后往前选消息
        selected: list[dict] = []
        budget_left = token_limit - first_tokens
        dropped_results = 0
        tool_result_count = 0

        for i in range(len(messages) - 1, 0, -1):
            msg = messages[i]
            tokens = token_counts[i]

            # 判断是否为 tool result（user 消息且以 [Tool: 开头）
            is_result = (
                msg.get("role") == "user"
                and msg.get("content", "").strip().startswith("[Tool:")
            )

            if is_result:
                tool_result_count += 1
                # 尝试丢弃：先检查如果丢弃后是否能腾出空间
                if budget_left >= tokens:
                    selected.append(msg)
                    budget_left -= tokens
                else:
                    dropped_results += 1
            else:
                if budget_left >= tokens:
                    selected.append(msg)
                    budget_left -= tokens
                else:
                    dropped_results += 1

        if dropped_results == 0 or tool_result_count == 0:
            return None

        # 恢复正序
        selected.reverse()
        result = [first]
        if dropped_results > 0:
            result.append({
                "role": "user",
                "content": (
                    f"[{dropped_results} tool results were removed "
                    f"to free context space]"
                ),
            })
        result.extend(selected)

        # 验证 token 预算
        if sum(estimate_tokens(m.get("content", "")) for m in result) <= token_limit:
            return result
        return None

    @staticmethod
    def _trim_tool_calls(
        messages: list[dict],
        token_counts: list[int],
        token_limit: int,
    ) -> list[dict] | None:
        """
        第 2 级：丢弃旧的 tool_use（assistant 消息含 Action:），
        仅保留 thought 部分。
        从后往前处理，保留最近的消息。
        """
        first = messages[0]
        first_tokens = token_counts[0]

        selected: list[dict] = []
        budget_left = token_limit - first_tokens
        dropped_calls = 0

        for i in range(len(messages) - 1, 0, -1):
            msg = messages[i]
            tokens = token_counts[i]
            content = msg.get("content", "")

            # 判断是否为 tool call（assistant 消息且含 Action:）
            is_tool_call = (
                msg.get("role") == "assistant"
                and "Action:" in content
            )

            if is_tool_call and budget_left < tokens:
                # 尝试只保留 thought（Action: 之前的内容）
                thought = TokenBudget._extract_thought(content)
                if thought:
                    thought_tokens = estimate_tokens(thought)
                    if budget_left >= thought_tokens:
                        selected.append({"role": "assistant", "content": thought})
                        budget_left -= thought_tokens
                        dropped_calls += 1
                        continue

            if budget_left >= tokens:
                selected.append(msg)
                budget_left -= tokens
            else:
                dropped_calls += 1

        if dropped_calls == 0:
            return None

        # 检查是否真的有 tool call 被压缩了
        # （不要因为纯 user 消息被丢弃就返回 success，那应该走 fallback）
        tool_call_condensed = any(
            msg.get("role") == "assistant" and "Action:" in msg.get("content", "")
            for msg in selected
        )
        if not tool_call_condensed:
            return None

        selected.reverse()
        result = [first]
        result.extend(selected)

        if sum(estimate_tokens(m.get("content", "")) for m in result) <= token_limit:
            return result
        return None

    @staticmethod
    def _trim_drop_all_but_last(
        messages: list[dict],
        token_limit: int,
        keep: int = 3,
    ) -> list[dict]:
        """
        第 3 级：兜底策略。保留首条 + 最后 keep 条消息。
        """
        first = messages[0]
        first_tokens = estimate_tokens(first.get("content", ""))
        last_keep = messages[-keep:] if len(messages) > keep + 1 else messages[1:]

        placeholder = {
            "role": "user",
            "content": (
                f"[{len(messages) - 1 - len(last_keep)} earlier messages "
                f"were truncated to fit context window]"
            ),
        }
        placeholder_tokens = estimate_tokens(placeholder["content"])

        result = [first, placeholder]
        budget_left = token_limit - first_tokens - placeholder_tokens

        for msg in last_keep:
            tokens = estimate_tokens(msg.get("content", ""))
            if budget_left >= tokens:
                result.append(msg)
                budget_left -= tokens
            else:
                break

        return result

    @staticmethod
    def _trim_simple(
        messages: list[dict],
        token_counts: list[int],
        token_limit: int,
    ) -> list[dict]:
        """回退策略：和原始实现一致，保留首条 + 尽量多最近消息。"""
        if not messages:
            return messages

        result = [messages[0]]
        remaining_budget = token_limit - token_counts[0]
        dropped = 0
        selected: list[dict] = []

        for msg, tokens in zip(reversed(messages[1:]), reversed(token_counts[1:])):
            if remaining_budget - tokens >= 0:
                selected.append(msg)
                remaining_budget -= tokens
            else:
                dropped += 1

        selected.reverse()
        if dropped > 0:
            result.append({
                "role": "user",
                "content": f"[{dropped} earlier messages were truncated to fit context window]",
            })
        result.extend(selected)
        return result

    @staticmethod
    def _extract_thought(content: str) -> str | None:
        """从 assistant 消息中提取 thought 部分（Action: 之前的内容）。"""
        idx = content.find("Action:")
        if idx == -1:
            thought = content
        else:
            thought = content[:idx].strip()
        if thought and not thought.startswith("[Earlier"):
            return thought
        return None

    def usage_report(
        self,
        system_text: str,
        repo_map_text: str,
        history: list[dict],
        observation_text: str,
        consumed_tokens: int = 0,
        max_context_window: int | None = None,
    ) -> dict[str, int]:
        plan = self.compute_plan(consumed_tokens, max_context_window)
        history_tokens = sum(
            estimate_tokens(m.get("content", "")) for m in history
        )
        return {
            "system":      estimate_tokens(system_text),
            "repo_map":    estimate_tokens(repo_map_text),
            "history":     history_tokens,
            "observation": estimate_tokens(observation_text),
            "total": (
                estimate_tokens(system_text)
                + estimate_tokens(repo_map_text)
                + history_tokens
                + estimate_tokens(observation_text)
            ),
            "budget":        self._total,
            "tiktoken_used": is_tiktoken_available(),
        }
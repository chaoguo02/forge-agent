"""
context/task_router.py

Task Relationship Router — 判断用户新消息与当前会话上下文的关系。

分类结果：
- same_task: 继续当前任务（追问、补充细节）
- related_task: 新任务但与前一个任务相关（同一模块、相关功能）
- unrelated_task: 全新独立任务
- quick_question: 简单问题，不需要重上下文

用途：
- same_task → 保留全部上下文，不压缩
- related_task → 保留相关文件上下文，轻度裁剪
- unrelated_task → 触发 compaction，生成 TaskSummary 并清理
- quick_question → 最小上下文，跳过 repo_map 等重型注入

分类策略：
1. 启发式规则（快速、无 LLM 调用）
2. 回退到 LLM 分类（仅在规则不确定时）
"""

from __future__ import annotations

import re
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context.session import SessionState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 分类结果
# ---------------------------------------------------------------------------

SAME_TASK = "same_task"
RELATED_TASK = "related_task"
UNRELATED_TASK = "unrelated_task"
QUICK_QUESTION = "quick_question"

# ---------------------------------------------------------------------------
# 启发式信号
# ---------------------------------------------------------------------------

# 表示继续当前任务的信号词（短消息开头）
_CONTINUATION_SIGNALS = re.compile(
    r"^(also|and |then |next |ok |good|great|perfect|yes|"
    r"还有|另外|然后|接着|继续|好的)",
    re.IGNORECASE,
)

# 表示新任务的信号词
_NEW_TASK_SIGNALS = re.compile(
    r"^(switch to|let'?s move|let'?s work on|new task|different topic|unrelated|"
    r"now let'?s|now work on|"
    r"换个|切换|新的任务|另一个问题|现在来做)",
    re.IGNORECASE,
)

# 表示简单问题的模式
_QUICK_QUESTION_PATTERNS = re.compile(
    r"^(what is|what'?s|how do|how does|how to|where is|which|can you explain|"
    r"explain |tell me about |"
    r"什么是|怎么|哪个|在哪|能解释一下)\s",
    re.IGNORECASE,
)

# 短消息阈值（字符数）——很短的消息更可能是 follow-up 或 quick_question
_SHORT_MESSAGE_CHARS = 50

# 文件路径模式
_FILE_PATH_RE = re.compile(
    r"(?:[\w/\\.-]+\.(?:py|js|ts|tsx|jsx|go|rs|java|c|h|cpp|rb|md|yaml|yml|json|toml))"
)


def classify_task_relationship(
    user_input: str,
    session_state: "SessionState",
) -> str:
    """
    启发式分类用户输入与当前 session 的关系。

    快速规则判断，不调用 LLM，延迟 < 1ms。

    Args:
        user_input: 用户新消息
        session_state: 当前 session 状态

    Returns:
        one of: same_task, related_task, unrelated_task, quick_question
    """
    text = user_input.strip()

    # 首轮消息或没有已完成任务 → 总是 unrelated_task
    if not session_state.completed_tasks:
        return UNRELATED_TASK

    # 检查显式切换信号
    if _NEW_TASK_SIGNALS.search(text):
        return UNRELATED_TASK

    # 短消息 + 继续信号 → same_task
    if len(text) < _SHORT_MESSAGE_CHARS and _CONTINUATION_SIGNALS.search(text):
        return SAME_TASK

    # 简单问题模式
    if _QUICK_QUESTION_PATTERNS.search(text) and len(text) < 200:
        # 检查是否引用了当前任务的文件
        mentioned_files = set(_FILE_PATH_RE.findall(text))
        last_task = session_state.completed_tasks[-1]
        if mentioned_files and mentioned_files.intersection(last_task.changed_files):
            return SAME_TASK  # 问的是刚改过的文件
        return QUICK_QUESTION

    # 文件重叠检测
    mentioned_files = set(_FILE_PATH_RE.findall(text))
    if mentioned_files:
        last_task = session_state.completed_tasks[-1]
        overlap = mentioned_files.intersection(
            set(last_task.changed_files + last_task.read_files)
        )
        if overlap:
            return RELATED_TASK

    # 目标重叠检测（关键词）
    last_goal_words = set(
        session_state.completed_tasks[-1].user_goal.lower().split()
    )
    current_words = set(text.lower().split())
    # 去除常见停用词和短词
    stopwords = {"the", "a", "an", "is", "to", "in", "for", "of", "and", "on", "it",
                 "i", "can", "you", "this", "that", "with", "from", "do", "be", "not",
                 "fix", "add", "update", "change", "make", "set", "get", "new",
                 "我", "你", "的", "了", "是", "在", "把", "对", "这个", "那个",
                 "修复", "添加", "修改", "设置"}
    meaningful_last = {w for w in last_goal_words - stopwords if len(w) > 2}
    meaningful_current = {w for w in current_words - stopwords if len(w) > 2}
    meaningful_overlap = meaningful_last & meaningful_current
    if len(meaningful_overlap) >= 2:
        return RELATED_TASK

    # 如果提及了文件但没有和上一任务重叠 → 新任务
    if mentioned_files:
        return UNRELATED_TASK

    # 消息长度启发：长消息（>300 chars）更可能是新任务
    if len(text) > 300:
        return UNRELATED_TASK

    # 默认：related_task（保守选择，保留一些上下文）
    return RELATED_TASK


def get_compaction_strategy(relationship: str) -> dict:
    """
    根据任务关系返回 compaction 策略参数。

    Returns:
        dict with keys:
        - should_compact: bool
        - keep_recent_rounds: int
        - inject_session_summary: bool
    """
    if relationship == SAME_TASK:
        return {
            "should_compact": False,
            "keep_recent_rounds": 99,
            "inject_session_summary": False,
        }
    elif relationship == RELATED_TASK:
        return {
            "should_compact": False,
            "keep_recent_rounds": 5,
            "inject_session_summary": True,
        }
    elif relationship == QUICK_QUESTION:
        return {
            "should_compact": False,
            "keep_recent_rounds": 2,
            "inject_session_summary": False,
        }
    else:  # UNRELATED_TASK
        return {
            "should_compact": True,
            "keep_recent_rounds": 2,
            "inject_session_summary": True,
        }

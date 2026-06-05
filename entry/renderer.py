"""
entry/renderer.py

输出渲染抽象层。支持多形态切换：
- InlineRenderer：rich 库的内联流式 TUI（默认）
- PlainRenderer：纯 ANSI 转义码（非终端 / CI 降级）

用法：
    renderer = get_renderer("inline", model="deepseek-chat", mode="react")
    renderer.stream_text("hello")
    renderer.on_tool_call(1, "shell", {"cmd": "ls"})
"""

from __future__ import annotations

import sys
import time
from abc import ABC, abstractmethod
from typing import Any


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------

class Renderer(ABC):
    """输出渲染器抽象基类。ChatSession 通过此接口输出，不感知底层实现。"""

    @abstractmethod
    def on_round_start(self, user_input: str) -> None:
        """一轮对话开始。"""
        ...

    @abstractmethod
    def stream_text(self, token: str) -> None:
        """最终回答的流式 token。"""
        ...

    @abstractmethod
    def stream_thought(self, token: str) -> None:
        """推理过程的流式 token（仅推理模型）。"""
        ...

    @abstractmethod
    def on_tool_call(self, step: int, name: str, params: dict[str, Any]) -> None:
        """工具调用。"""
        ...

    @abstractmethod
    def on_observation(
        self, step: int, tool_name: str, status: str,
        output: str, error: str | None,
    ) -> None:
        """工具执行结果。"""
        ...

    @abstractmethod
    def on_reflection(self, reason: str) -> None:
        """触发 Reflection。"""
        ...

    @abstractmethod
    def on_finish(self, step: int, message: str) -> None:
        """任务完成。"""
        ...

    @abstractmethod
    def on_give_up(self, step: int, message: str) -> None:
        """Agent 主动放弃。"""
        ...

    @abstractmethod
    def on_round_end(
        self, round_num: int, steps: int, tokens: int, elapsed: float,
    ) -> None:
        """一轮结束，显示统计。"""
        ...

    @abstractmethod
    def on_error(self, message: str) -> None:
        """错误信息。"""
        ...

    @abstractmethod
    def on_stats(
        self, rounds: int, total_steps: int, total_tokens: int,
    ) -> None:
        """会话统计（/stats 命令）。"""
        ...


# ---------------------------------------------------------------------------
# 辅助：ANSI 颜色（PlainRenderer 和 InlineRenderer 共用）
# ---------------------------------------------------------------------------

def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text

def _green(t: str) -> str:  return _c(t, "32")
def _yellow(t: str) -> str: return _c(t, "33")
def _red(t: str) -> str:    return _c(t, "31")
def _cyan(t: str) -> str:   return _c(t, "36")
def _bold(t: str) -> str:   return _c(t, "1")
def _dim(t: str) -> str:    return _c(t, "2")


# ---------------------------------------------------------------------------
# PlainRenderer — 纯 ANSI，无新依赖
# ---------------------------------------------------------------------------

class PlainRenderer(Renderer):
    """
    纯 ANSI escape 渲染器。与当前 chat.py 的行为完全一致。
    CLI run 模式和 CI 环境使用此渲染器。
    """

    def on_round_start(self, user_input: str) -> None:
        pass  # 用户输入已由 readline 提供，不重复打印

    def stream_text(self, token: str) -> None:
        sys.stdout.write(token)
        sys.stdout.flush()

    def stream_thought(self, token: str) -> None:
        sys.stdout.write(_dim(token))
        sys.stdout.flush()

    def on_tool_call(self, step: int, name: str, params: dict[str, Any]) -> None:
        key_param = ""
        for k in ("cmd", "path", "pattern", "symbol", "message"):
            if k in params:
                key_param = str(params[k])[:60]
                break
        if key_param:
            suffix = "..." if len(str(params.get(k, ""))) > 60 else ""
            print(_cyan(f"  [{step}] {name}  {key_param}{suffix}"))
        else:
            print(_cyan(f"  [{step}] {name}"))

    def on_observation(
        self, step: int, tool_name: str, status: str,
        output: str, error: str | None,
    ) -> None:
        silent = tool_name in {
            "file_read", "file_view", "file_write", "find_files", "find_symbol",
        }
        if status == "success":
            if silent:
                print(_green("  ✓"))
            else:
                lines = output.splitlines()[:20]
                preview = "\n".join(f"    {l}" for l in lines)
                if lines:
                    print(_green("  ✓") + _dim(f"\n{preview}"))
                    if len(output.splitlines()) > 20:
                        print(_dim(f"    ... ({len(output.splitlines()) - 20} more lines)"))
                else:
                    print(_green("  ✓"))
        else:
            print(_red(f"  ✗ {error or output[:120]}"))

    def on_reflection(self, reason: str) -> None:
        print(_yellow(f"\n  ⟳ Reflection ({reason}) — reconsidering...\n"))

    def on_finish(self, step: int, message: str) -> None:
        print(_green(f"\n  [{step}] ✓ finish"))
        if message:
            print(message)

    def on_give_up(self, step: int, message: str) -> None:
        print(_red(f"\n  [{step}] ✗ give_up"))

    def on_round_end(
        self, round_num: int, steps: int, tokens: int, elapsed: float,
    ) -> None:
        print(_dim(
            f"  ─── Round {round_num} · "
            f"{steps} steps · {tokens:,} tokens · {elapsed:.1f}s ───"
        ))

    def on_error(self, message: str) -> None:
        print(_red(f"\n  ❌ Error: {message}"))

    def on_stats(self, rounds: int, total_steps: int, total_tokens: int) -> None:
        print(_bold(f"\n{'─' * 50}"))
        print("  Session stats:")
        print(f"    Rounds : {rounds}")
        print(f"    Steps  : {total_steps}")
        print(f"    Tokens : {total_tokens:,}")
        print(_bold(f"{'─' * 50}\n"))


# ---------------------------------------------------------------------------
# InlineRenderer — rich 内联流式 TUI
# ---------------------------------------------------------------------------

class InlineRenderer(Renderer):
    """
    使用 rich 的内联流式 TUI 渲染器（Claude Code 风格）。

    特性：
    - 主区域显示流式输出
    - 底部状态栏（模型 / 模式 / token 用量 / 步数 / 耗时）
    - 工具调用紧凑显示
    - diff 语法高亮
    - 非 TTY 环境自动降级为 PlainRenderer
    """

    def __init__(
        self,
        model: str = "?",
        mode: str = "react",
    ) -> None:
        self._model = model
        self._mode = mode
        self._current_step = 0
        self._total_steps = 0
        self._total_tokens = 0
        self._start_time = 0.0
        self._output_lines: list[str] = []
        # 流式缓冲区
        self._text_buf: list[str] = []
        self._thought_buf: list[str] = []
        self._streaming_thought = False

        # 检查 rich 是否可用
        try:
            from rich.live import Live
            from rich.layout import Layout
            from rich.panel import Panel
            from rich.syntax import Syntax
            from rich.text import Text
            from rich.console import Console
            self._live_cls = Live
            self._layout_cls = Layout
            self._panel_cls = Panel
            self._syntax_cls = Syntax
            self._text_cls = Text
            self._console = Console()
            self._rich_ok = True
        except ImportError:
            self._rich_ok = False

    # ------------------------------------------------------------------
    # Renderer 接口
    # ------------------------------------------------------------------

    def on_round_start(self, user_input: str) -> None:
        self._start_time = time.time()
        self._current_step = 0
        self._text_buf.clear()
        self._thought_buf.clear()
        self._output_lines.clear()
        self._streaming_thought = False

        if self._rich_ok:
            self._output_lines.append(_bold(f"\n  ▶ {user_input[:100]}"))
        else:
            pass  # Plain 不做特殊处理

    def stream_text(self, token: str) -> None:
        if self._streaming_thought:
            # 从 thought 切换到 text，先换行分隔
            self._output_lines.append("")
            self._streaming_thought = False
        self._text_buf.append(token)
        sys.stdout.write(token)
        sys.stdout.flush()

    def stream_thought(self, token: str) -> None:
        self._streaming_thought = True
        self._thought_buf.append(token)
        sys.stdout.write(_dim(token))
        sys.stdout.flush()

    def on_tool_call(self, step: int, name: str, params: dict[str, Any]) -> None:
        self._current_step = step
        key = ""
        for k in ("cmd", "path", "pattern", "symbol", "message"):
            if k in params:
                key = f" {str(params[k])[:60]}"
                break
        self._output_lines.append(
            _cyan(f"  [{step}] {name}{key}")
        )

    def on_observation(
        self, step: int, tool_name: str, status: str,
        output: str, error: str | None,
    ) -> None:
        silent = tool_name in {
            "file_read", "file_view", "file_write", "find_files", "find_symbol",
        }
        if status == "success":
            if silent:
                self._output_lines.append(_green("  ✓"))
            else:
                lines = output.splitlines()[:20]
                preview = "\n".join(f"    {l}" for l in lines)
                self._output_lines.append(_green("  ✓"))
                if preview:
                    self._output_lines.append(_dim(preview))
                    if len(output.splitlines()) > 20:
                        self._output_lines.append(
                            _dim(f"    ... ({len(output.splitlines()) - 20} more lines)")
                        )
        else:
            self._output_lines.append(_red(f"  ✗ {error or output[:120]}"))

        # 尝试 diff 高亮
        if tool_name in ("shell",) and output.startswith("diff "):
            self._output_lines.append(self._highlight_diff(output))

    def on_reflection(self, reason: str) -> None:
        self._output_lines.append(
            _yellow(f"  ⟳ Reflection ({reason})")
        )

    def on_finish(self, step: int, message: str) -> None:
        self._output_lines.append(_green(f"  [{step}] ✓ finish"))

    def on_give_up(self, step: int, message: str) -> None:
        self._output_lines.append(_red(f"  [{step}] ✗ give_up"))

    def on_round_end(
        self, round_num: int, steps: int, tokens: int, elapsed: float,
    ) -> None:
        self._total_steps += steps
        self._total_tokens += tokens
        self._output_lines.append(
            _dim(
                f"  ─── Round {round_num} · "
                f"{steps} steps · {tokens:,} tokens · {elapsed:.1f}s ───"
            )
        )
        # 打印所有收集的行
        for line in self._output_lines:
            print(line)

    def on_error(self, message: str) -> None:
        print(_red(f"\n  ❌ Error: {message}"))

    def on_stats(self, rounds: int, total_steps: int, total_tokens: int) -> None:
        print(_bold(f"\n{'─' * 50}"))
        print("  Session stats:")
        print(f"    Rounds : {rounds}")
        print(f"    Steps  : {total_steps}")
        print(f"    Tokens : {total_tokens:,}")
        print(f"    Model  : {self._model}")
        print(f"    Mode   : {self._mode}")
        print(_bold(f"{'─' * 50}\n"))

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _highlight_diff(self, text: str) -> str:
        """给 diff 输出加颜色。"""
        try:
            from rich.syntax import Syntax
            from rich.console import Console as RichConsole
            import io
            buf = io.StringIO()
            console = RichConsole(file=buf, force_terminal=True, width=120)
            syntax = Syntax(text, "diff", theme="monokai")
            console.print(syntax)
            return buf.getvalue().rstrip()
        except Exception:
            return text


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------

def get_renderer(name: str, **kwargs) -> Renderer:
    """
    根据名称创建 Renderer。

    Args:
        name: "inline" | "plain"
        kwargs: InlineRenderer 的构造参数（model, mode）

    Returns:
        Renderer 实例
    """
    if name == "plain":
        return PlainRenderer()
    if name == "inline":
        # 非 TTY 自动降级
        if not sys.stdout.isatty():
            return PlainRenderer()
        return InlineRenderer(**kwargs)
    raise ValueError(f"Unknown renderer: {name!r}, expected 'inline' or 'plain'")

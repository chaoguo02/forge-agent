"""
entry/renderer.py

统一输出渲染器。ChatSession 所有输出通过此模块，
不直接 sys.stdout.write 或 click.echo。

具备：
- 流式 thought（暗色）/ text（亮色）差异化输出
- 工具调用紧凑展示
- diff 语法高亮（rich 可用时）
- 非 TTY 自动关闭颜色
"""

from __future__ import annotations

import sys
import time
from typing import Any


# ---------------------------------------------------------------------------
# ANSI 颜色
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
# Renderer
# ---------------------------------------------------------------------------

class Renderer:
    """
    统一渲染器。即时输出，无缓冲。

    model / mode 仅用于 on_stats 展示，其余方法不依赖它们。
    """

    def __init__(self, model: str = "?", mode: str = "react") -> None:
        self.model = model
        self.mode = mode
        self._total_steps = 0
        self._total_tokens = 0

    # ── 流式回调 ──────────────────────────────────────────────────

    def stream_text(self, token: str) -> None:
        """最终回答的流式 token。"""
        sys.stdout.write(token)
        sys.stdout.flush()

    def stream_thought(self, token: str) -> None:
        """推理过程的流式 token（推理模型专用，dim 暗色）。"""
        sys.stdout.write(_dim(token))
        sys.stdout.flush()

    # ── 事件回调 ──────────────────────────────────────────────────

    def on_tool_call(self, step: int, name: str, params: dict[str, Any]) -> None:
        key = ""
        for k in ("cmd", "path", "pattern", "symbol", "message"):
            if k in params:
                key = f" {str(params[k])[:60]}"
                break
        print(_cyan(f"  [{step}] {name}{key}"))

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
                        print(_dim(
                            f"    ... ({len(output.splitlines()) - 20} more lines)"
                        ))
                else:
                    print(_green("  ✓"))
            # diff 高亮
            if output.startswith("diff "):
                print(_highlight_diff(output))
        else:
            print(_red(f"  ✗ {error or output[:120]}"))

    def on_reflection(self, reason: str) -> None:
        print(_yellow(f"\n  ⟳ Reflection ({reason}) — reconsidering...\n"))

    def on_finish(self, step: int, message: str) -> None:
        print(_green(f"\n  [{step}] ✓ finish"))

    def on_give_up(self, step: int, message: str) -> None:
        print(_red(f"\n  [{step}] ✗ give_up"))
        if message:
            print(_red(f"  {message}"))

    def on_error(self, message: str) -> None:
        print(_red(f"\n  ❌ Error: {message}"))

    # ── 统计 ──────────────────────────────────────────────────────

    def on_round_end(
        self, round_num: int, steps: int, tokens: int, elapsed: float,
    ) -> None:
        self._total_steps += steps
        self._total_tokens += tokens
        print(_dim(
            f"  ─── Round {round_num} · "
            f"{steps} steps · {tokens:,} tokens · {elapsed:.1f}s ───"
        ))

    def on_stats(self, rounds: int, total_steps: int, total_tokens: int) -> None:
        print(_bold(f"\n{'─' * 50}"))
        print("  Session stats:")
        print(f"    Rounds : {rounds}")
        print(f"    Steps  : {total_steps}")
        print(f"    Tokens : {total_tokens:,}")
        print(f"    Model  : {self.model}")
        print(f"    Mode   : {self.mode}")
        print(_bold(f"{'─' * 50}\n"))


# ---------------------------------------------------------------------------
# diff 高亮（rich 可用时）
# ---------------------------------------------------------------------------

def _highlight_diff(text: str) -> str:
    """给 diff 文本加 ANSI 颜色。rich 不可用时静默降级。"""
    try:
        from rich.syntax import Syntax
        from rich.console import Console
        import io
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        syntax = Syntax(text, "diff", theme="monokai")
        console.print(syntax)
        return buf.getvalue().rstrip()
    except Exception:
        return text

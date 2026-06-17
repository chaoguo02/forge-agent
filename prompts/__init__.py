"""
prompts/ — Prompt 分层架构。

本目录既是 Python 包，也是内置 prompt .md 文件的存放位置。

核心组件：
- PromptAssembler: 三层覆盖的 Prompt 文件加载与渲染
"""

from prompts.assembler import PromptAssembler

__all__ = ["PromptAssembler"]

"""
tests/test_code_chunker.py

AST 代码分块器测试：多语言解析、正则 fallback、元数据完整性。
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch

from context.code_chunker import (
    CodeChunk,
    chunk_file,
    is_code_file,
    should_skip_path,
    _chunk_with_regex,
    _chunk_sliding_window,
)


# ===========================================================================
# Python 文件分块测试
# ===========================================================================

PYTHON_SAMPLE = '''\
"""Module docstring."""

import os
from pathlib import Path


def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}!"


def goodbye(name: str) -> str:
    return f"Goodbye, {name}!"


class Greeter:
    """A greeter class."""

    def __init__(self, prefix: str):
        self.prefix = prefix

    def greet(self, name: str) -> str:
        """Greet someone."""
        return f"{self.prefix} {name}"

    def farewell(self, name: str) -> str:
        return f"Farewell, {name}"
'''


class TestPythonChunking:
    def test_chunk_python_file(self):
        chunks = chunk_file("test.py", PYTHON_SAMPLE)
        assert len(chunks) > 0

        # 应该找到函数和类
        names = [c.symbol_name for c in chunks]
        # 至少能找到 hello, goodbye（无论 AST 还是 regex）
        assert any("hello" in n for n in names)
        assert any("goodbye" in n for n in names)

    def test_chunk_metadata(self):
        chunks = chunk_file("src/utils.py", PYTHON_SAMPLE)
        for chunk in chunks:
            assert chunk.file_path == "src/utils.py"
            assert chunk.start_line >= 1
            assert chunk.end_line >= chunk.start_line
            assert chunk.symbol_kind in ("function", "class", "method", "module")
            assert chunk.language == "python"

    def test_embed_text_includes_path(self):
        chunks = chunk_file("src/hello.py", PYTHON_SAMPLE)
        for chunk in chunks:
            assert "src/hello.py" in chunk.embed_text

    def test_empty_file_returns_empty(self):
        chunks = chunk_file("empty.py", "")
        assert chunks == []

    def test_whitespace_only_returns_empty(self):
        chunks = chunk_file("blank.py", "   \n  \n")
        assert chunks == []


# ===========================================================================
# JavaScript 文件分块测试
# ===========================================================================

JS_SAMPLE = '''\
// Utility functions

function add(a, b) {
    return a + b;
}

function multiply(a, b) {
    return a * b;
}

class Calculator {
    constructor() {
        this.result = 0;
    }

    add(value) {
        this.result += value;
        return this;
    }
}

export default Calculator;
'''


class TestJavaScriptChunking:
    def test_chunk_js_functions(self):
        chunks = chunk_file("math.js", JS_SAMPLE)
        assert len(chunks) > 0
        names = [c.symbol_name for c in chunks]
        assert any("add" in n for n in names)
        assert any("multiply" in n for n in names)

    def test_js_language_tag(self):
        chunks = chunk_file("index.js", JS_SAMPLE)
        for chunk in chunks:
            assert chunk.language == "javascript"


# ===========================================================================
# Go 文件分块测试
# ===========================================================================

GO_SAMPLE = '''\
package main

import "fmt"

func Hello(name string) string {
    return fmt.Sprintf("Hello, %s!", name)
}

func Goodbye(name string) string {
    return fmt.Sprintf("Goodbye, %s!", name)
}

func main() {
    fmt.Println(Hello("World"))
}
'''


class TestGoChunking:
    def test_chunk_go_functions(self):
        chunks = chunk_file("main.go", GO_SAMPLE)
        assert len(chunks) > 0
        names = [c.symbol_name for c in chunks]
        assert any("Hello" in n for n in names)
        assert any("main" in n for n in names)

    def test_go_language_tag(self):
        chunks = chunk_file("main.go", GO_SAMPLE)
        for chunk in chunks:
            assert chunk.language == "go"


# ===========================================================================
# 正则 fallback 测试
# ===========================================================================

class TestRegexFallback:
    def test_regex_finds_python_defs(self):
        chunks = _chunk_with_regex("test.py", PYTHON_SAMPLE, "python")
        assert len(chunks) > 0
        names = [c.symbol_name for c in chunks]
        assert "hello" in names
        assert "goodbye" in names

    def test_regex_finds_class(self):
        chunks = _chunk_with_regex("test.py", PYTHON_SAMPLE, "python")
        class_chunks = [c for c in chunks if c.symbol_kind == "class"]
        assert len(class_chunks) >= 1

    def test_regex_on_unknown_language(self):
        code = "func main() {\n    println(\"hi\")\n}\n"
        chunks = _chunk_with_regex("main.go", code, "go")
        assert len(chunks) >= 1
        assert chunks[0].symbol_name == "main"


# ===========================================================================
# 滑动窗口 fallback 测试
# ===========================================================================

class TestSlidingWindow:
    def test_short_file_single_chunk(self):
        content = "\n".join(f"line {i}" for i in range(10))
        chunks = _chunk_sliding_window("data.txt", content, "unknown")
        assert len(chunks) == 1

    def test_long_file_multiple_chunks(self):
        content = "\n".join(f"line {i}: " + "x" * 50 for i in range(200))
        chunks = _chunk_sliding_window("big.txt", content, "unknown")
        assert len(chunks) > 1

    def test_preserves_file_path(self):
        content = "\n".join(f"line {i}" for i in range(10))
        chunks = _chunk_sliding_window("src/data.txt", content, "unknown")
        assert all(c.file_path == "src/data.txt" for c in chunks)


# ===========================================================================
# 工具函数测试
# ===========================================================================

class TestUtilityFunctions:
    def test_is_code_file(self):
        assert is_code_file(Path("test.py")) is True
        assert is_code_file(Path("main.go")) is True
        assert is_code_file(Path("app.js")) is True
        assert is_code_file(Path("style.css")) is False
        assert is_code_file(Path("readme.md")) is False
        assert is_code_file(Path("data.json")) is False

    def test_should_skip_path(self):
        assert should_skip_path(Path(".git/config")) is True
        assert should_skip_path(Path("node_modules/lodash/index.js")) is True
        assert should_skip_path(Path("__pycache__/mod.cpython-311.pyc")) is True
        assert should_skip_path(Path("src/main.py")) is False
        assert should_skip_path(Path("tests/test_foo.py")) is False


# ===========================================================================
# CodeChunk 数据类测试
# ===========================================================================

class TestCodeChunk:
    def test_line_count(self):
        chunk = CodeChunk(
            file_path="test.py", start_line=10, end_line=25,
            symbol_name="foo", symbol_kind="function",
            content="...", language="python",
        )
        assert chunk.line_count == 16

    def test_embed_text_with_docstring(self):
        chunk = CodeChunk(
            file_path="test.py", start_line=1, end_line=5,
            symbol_name="hello", symbol_kind="function",
            content="def hello():\n    pass",
            docstring="Says hello",
            language="python",
        )
        assert "Says hello" in chunk.embed_text
        assert "test.py" in chunk.embed_text

    def test_embed_text_without_docstring(self):
        chunk = CodeChunk(
            file_path="test.py", start_line=1, end_line=5,
            symbol_name="hello", symbol_kind="function",
            content="def hello():\n    pass",
            language="python",
        )
        assert "test.py" in chunk.embed_text
        assert "function hello" in chunk.embed_text


# ===========================================================================
# 边界情况
# ===========================================================================

class TestEdgeCases:
    def test_single_function_file(self):
        code = "def only_func():\n    x = 1\n    return x + 42\n"
        chunks = chunk_file("single.py", code)
        assert len(chunks) >= 1

    def test_file_with_only_imports(self):
        code = "import os\nimport sys\nfrom pathlib import Path\n"
        chunks = chunk_file("imports.py", code)
        # May return empty or a module chunk — both are valid
        assert isinstance(chunks, list)

    def test_large_file_skipped(self):
        content = "x" * 600_000
        chunks = chunk_file("huge.py", content)
        assert chunks == []

    def test_binary_like_content(self):
        content = "\x00\x01\x02" * 100
        chunks = chunk_file("binary.py", content)
        assert isinstance(chunks, list)

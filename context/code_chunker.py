"""
context/code_chunker.py

AST-aware 代码分块器。

基于 tree-sitter 按函数/类/方法边界分块代码文件，生成适合向量索引的 CodeChunk。
与 memory/chunker.py（文本记忆分块）互补：这个专门处理代码文件。

分块策略（三级回退）：
1. tree-sitter AST：按 function_definition / class_definition / method_definition 边界
2. 正则 fallback：按 def/class/function/func/fn 关键字行切分
3. 滑动窗口 fallback：纯文本按行切分（最后兜底）

每个 chunk 附带丰富的元数据：
- file_path, start_line, end_line
- symbol_name, symbol_kind (function/class/method/module)
- docstring（如果有）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from context.repo_map import (
    _CLASS_NODES,
    _FUNC_NODES,
    _LANG_REGISTRY,
    _SKIP_DIRS,
    _get_language,
)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

MAX_CHUNK_LINES = 100
MIN_CHUNK_LINES = 2
MAX_FILE_SIZE = 500_000  # 500KB 以上跳过

# 正则：匹配函数/类定义行（多语言）
_DEF_RE = re.compile(
    r"^([ \t]*)(def|class|async def|function|func|fn|pub fn|pub\(crate\) fn"
    r"|export function|export default function|export async function"
    r"|async function)\s+(\w+)",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class CodeChunk:
    """一个代码分块，对应一个函数/类/方法或文件片段。"""
    file_path: str
    start_line: int
    end_line: int
    symbol_name: str
    symbol_kind: str           # "function" | "class" | "method" | "module"
    content: str               # 源码文本
    docstring: str = ""        # 提取到的 docstring
    language: str = ""         # 编程语言标识
    metadata: dict = field(default_factory=dict)

    @property
    def embed_text(self) -> str:
        """用于 embedding 的文本：包含文件路径 + 符号名 + 内容。"""
        header = f"{self.file_path}:{self.symbol_kind} {self.symbol_name}"
        if self.docstring:
            return f"{header}\n{self.docstring}\n\n{self.content}"
        return f"{header}\n\n{self.content}"

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def chunk_file(file_path: str | Path, content: str | None = None) -> list[CodeChunk]:
    """
    对单个代码文件进行 AST-aware 分块。

    Args:
        file_path: 文件路径（相对或绝对）
        content: 文件内容（None 时从磁盘读取）

    Returns:
        CodeChunk 列表，每个对应一个函数/类/方法
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    if content is None:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

    if not content.strip():
        return []

    if len(content) > MAX_FILE_SIZE:
        return []

    file_str = str(file_path)
    language = _ext_to_language(ext)

    # 尝试 tree-sitter AST 分块
    lang = _get_language(ext)
    if lang is not None:
        chunks = _chunk_with_treesitter(file_str, content, lang, language)
        if chunks:
            return chunks

    # 正则 fallback
    chunks = _chunk_with_regex(file_str, content, language)
    if chunks:
        return chunks

    # 滑动窗口 fallback
    return _chunk_sliding_window(file_str, content, language)


def is_code_file(path: Path) -> bool:
    """判断是否为支持的代码文件。"""
    ext = path.suffix.lower()
    return ext in _CODE_EXTENSIONS


def should_skip_path(path: Path) -> bool:
    """判断路径是否应跳过（.git, node_modules 等）。"""
    return any(part in _SKIP_DIRS for part in path.parts)


# ---------------------------------------------------------------------------
# 支持的代码文件扩展名
# ---------------------------------------------------------------------------

_CODE_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java", ".cpp", ".c", ".h", ".hpp",
    ".rb", ".php", ".cs", ".swift", ".kt", ".scala",
    ".lua", ".sh", ".bash", ".zsh",
})

_EXT_TO_LANG: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".jsx": "javascript",
    ".go": "go", ".rs": "rust", ".java": "java",
    ".cpp": "cpp", ".c": "c", ".h": "c", ".hpp": "cpp",
    ".rb": "ruby", ".php": "php", ".cs": "csharp",
    ".swift": "swift", ".kt": "kotlin", ".scala": "scala",
    ".lua": "lua", ".sh": "shell", ".bash": "shell", ".zsh": "shell",
}


def _ext_to_language(ext: str) -> str:
    return _EXT_TO_LANG.get(ext, "unknown")


# ---------------------------------------------------------------------------
# tree-sitter 分块
# ---------------------------------------------------------------------------

def _chunk_with_treesitter(
    file_path: str, content: str, lang, language: str
) -> list[CodeChunk]:
    """用 tree-sitter 解析 AST，按函数/类边界分块。"""
    try:
        from tree_sitter import Parser
        parser = Parser(lang)
        tree = parser.parse(content.encode("utf-8", errors="replace"))
    except Exception:
        return []

    lines = content.splitlines()
    chunks: list[CodeChunk] = []

    # 收集顶层和类内的函数/类定义
    _collect_chunks_from_node(tree.root_node, file_path, lines, language, chunks)

    # 过滤太短的 chunk
    chunks = [c for c in chunks if c.line_count >= MIN_CHUNK_LINES]

    # 如果 AST 解析没找到任何符号，返回空让 fallback 接管
    if not chunks:
        return []

    # 处理文件头部（模块 docstring / import 区域）
    if chunks:
        first_start = chunks[0].start_line
        if first_start > MIN_CHUNK_LINES:
            header_content = "\n".join(lines[:first_start - 1])
            if header_content.strip():
                header_chunk = CodeChunk(
                    file_path=file_path,
                    start_line=1,
                    end_line=first_start - 1,
                    symbol_name="<module>",
                    symbol_kind="module",
                    content=header_content,
                    language=language,
                )
                chunks.insert(0, header_chunk)

    return chunks


def _collect_chunks_from_node(
    node, file_path: str, lines: list[str], language: str,
    chunks: list[CodeChunk], parent_class: str = "",
) -> None:
    """递归遍历 AST 节点，收集函数/类定义为 chunk。"""
    ntype = node.type

    if ntype in _FUNC_NODES and ntype != "arrow_function":
        name_node = node.child_by_field_name("name")
        if name_node:
            name = name_node.text.decode("utf-8", errors="replace")
            start = node.start_point[0]  # 0-based
            end = node.end_point[0]

            # 限制 chunk 最大行数
            if end - start + 1 > MAX_CHUNK_LINES:
                end = start + MAX_CHUNK_LINES - 1

            content = "\n".join(lines[start:end + 1])
            indent = node.start_point[1]
            kind = "method" if indent > 0 or parent_class else "function"
            symbol_name = f"{parent_class}.{name}" if parent_class else name

            docstring = _extract_docstring(node, lines)

            chunks.append(CodeChunk(
                file_path=file_path,
                start_line=start + 1,
                end_line=end + 1,
                symbol_name=symbol_name,
                symbol_kind=kind,
                content=content,
                docstring=docstring,
                language=language,
            ))
            return  # 不递归进入函数体

    elif ntype in _CLASS_NODES:
        name_node = node.child_by_field_name("name")
        if name_node:
            class_name = name_node.text.decode("utf-8", errors="replace")
            start = node.start_point[0]
            end = node.end_point[0]

            # 类级别 chunk（含类签名 + docstring，不含方法体）
            class_header_end = min(start + 5, end)  # 类签名通常前几行
            for child in node.children:
                if child.type in _FUNC_NODES:
                    class_header_end = child.start_point[0] - 1
                    break

            if class_header_end > start:
                header_content = "\n".join(lines[start:class_header_end + 1])
                docstring = _extract_docstring(node, lines)
                chunks.append(CodeChunk(
                    file_path=file_path,
                    start_line=start + 1,
                    end_line=class_header_end + 1,
                    symbol_name=class_name,
                    symbol_kind="class",
                    content=header_content,
                    docstring=docstring,
                    language=language,
                ))

            # 递归处理类内方法
            for child in node.children:
                _collect_chunks_from_node(
                    child, file_path, lines, language, chunks,
                    parent_class=class_name,
                )
            return

    # 非函数/类节点：递归子节点
    for child in node.children:
        _collect_chunks_from_node(child, file_path, lines, language, chunks, parent_class)


def _extract_docstring(node, lines: list[str]) -> str:
    """尝试从 AST 节点提取 docstring。"""
    # Python: 函数/类体的第一个 expression_statement > string
    body = node.child_by_field_name("body")
    if body is None:
        return ""

    for child in body.children:
        if child.type == "expression_statement":
            for subchild in child.children:
                if subchild.type == "string":
                    text = subchild.text.decode("utf-8", errors="replace")
                    # 去除引号
                    text = text.strip("\"'").strip()
                    if text:
                        return text[:200]  # 限制长度
            break
        elif child.type == "comment":
            text = child.text.decode("utf-8", errors="replace").lstrip("/#").strip()
            if text:
                return text[:200]
            break
        elif child.type not in ("newline", "indent", "NEWLINE"):
            break

    return ""


# ---------------------------------------------------------------------------
# 正则 fallback
# ---------------------------------------------------------------------------

def _chunk_with_regex(file_path: str, content: str, language: str) -> list[CodeChunk]:
    """用正则按函数/类定义行切分代码。"""
    lines = content.splitlines()
    if not lines:
        return []

    # 找所有定义行位置
    boundaries: list[tuple[int, str, str]] = []  # (line_idx, name, kind)
    for m in _DEF_RE.finditer(content):
        indent = m.group(1)
        keyword = m.group(2)
        name = m.group(3)

        line_num = content[:m.start()].count("\n")
        kind = "class" if "class" in keyword else (
            "method" if len(indent) > 0 else "function"
        )
        boundaries.append((line_num, name, kind))

    if not boundaries:
        return []

    chunks: list[CodeChunk] = []

    # 文件头部（第一个定义之前）
    if boundaries[0][0] > MIN_CHUNK_LINES:
        header_end = boundaries[0][0] - 1
        header = "\n".join(lines[:header_end + 1])
        if header.strip():
            chunks.append(CodeChunk(
                file_path=file_path,
                start_line=1,
                end_line=header_end + 1,
                symbol_name="<module>",
                symbol_kind="module",
                content=header,
                language=language,
            ))

    # 每个定义 → 下一个定义之前（或文件末尾）
    for i, (line_idx, name, kind) in enumerate(boundaries):
        if i + 1 < len(boundaries):
            end_idx = boundaries[i + 1][0] - 1
        else:
            end_idx = len(lines) - 1

        # 限制最大行数
        if end_idx - line_idx + 1 > MAX_CHUNK_LINES:
            end_idx = line_idx + MAX_CHUNK_LINES - 1

        chunk_content = "\n".join(lines[line_idx:end_idx + 1])
        if not chunk_content.strip():
            continue

        chunks.append(CodeChunk(
            file_path=file_path,
            start_line=line_idx + 1,
            end_line=end_idx + 1,
            symbol_name=name,
            symbol_kind=kind,
            content=chunk_content,
            language=language,
        ))

    return [c for c in chunks if c.line_count >= MIN_CHUNK_LINES]


# ---------------------------------------------------------------------------
# 滑动窗口 fallback
# ---------------------------------------------------------------------------

def _chunk_sliding_window(
    file_path: str, content: str, language: str
) -> list[CodeChunk]:
    """纯行数滑动窗口切分（最后兜底）。"""
    lines = content.splitlines()
    if len(lines) < MIN_CHUNK_LINES:
        return []

    chunks: list[CodeChunk] = []
    window = MAX_CHUNK_LINES
    overlap = 10
    start = 0

    while start < len(lines):
        end = min(start + window - 1, len(lines) - 1)
        chunk_content = "\n".join(lines[start:end + 1])

        if chunk_content.strip():
            chunks.append(CodeChunk(
                file_path=file_path,
                start_line=start + 1,
                end_line=end + 1,
                symbol_name=f"<chunk:{start + 1}-{end + 1}>",
                symbol_kind="module",
                content=chunk_content,
                language=language,
            ))

        start = end + 1 - overlap
        if start <= chunks[-1].start_line - 1 if chunks else 0:
            break

    return chunks

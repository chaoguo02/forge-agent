"""
skills/registry.py

SkillRegistry — 技能发现、加载、渲染。

发现流程：
1. 扫描 skills_dir 下的子目录
2. 每个子目录中查找 SKILL.md
3. 解析 YAML frontmatter 提取 metadata
4. 调用时才读取 body 并执行 $ARGUMENTS 替换
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SkillMetadata:
    """技能元数据（启动时加载，低成本）。"""
    name: str           # 目录名，也是调用名（/name）
    display_name: str   # frontmatter 中的 name 字段
    description: str    # frontmatter 中的 description
    dir_path: str       # 技能目录的绝对路径


class SkillRegistry:
    """
    技能注册表。负责发现、索引、加载和渲染技能。

    用法：
        registry = SkillRegistry("/path/to/.forge-agent/skills")
        skills = registry.list_skills()
        rendered = registry.load_and_render("code-review", "fix the auth bug")
    """

    def __init__(self, skills_dir: str) -> None:
        self._skills_dir = skills_dir
        self._metadata: dict[str, SkillMetadata] = {}
        self._discover()

    def _discover(self) -> None:
        """扫描 skills_dir，解析每个 SKILL.md 的 frontmatter。"""
        skills_path = Path(self._skills_dir)
        if not skills_path.is_dir():
            logger.debug("Skills directory does not exist: %s", self._skills_dir)
            return

        for entry in sorted(skills_path.iterdir()):
            if not entry.is_dir():
                continue
            skill_file = entry / "SKILL.md"
            if not skill_file.is_file():
                continue

            try:
                metadata = self._parse_frontmatter(skill_file, entry.name)
                if metadata:
                    self._metadata[metadata.name] = metadata
                    logger.debug("Discovered skill: %s", metadata.name)
            except Exception as e:
                logger.warning("Failed to parse skill %s: %s", entry.name, e)

        logger.info("Discovered %d skills in %s", len(self._metadata), self._skills_dir)

    def _parse_frontmatter(self, skill_file: Path, dir_name: str) -> SkillMetadata | None:
        """解析 SKILL.md 的 YAML frontmatter。"""
        content = skill_file.read_text(encoding="utf-8")
        frontmatter, _ = self._split_frontmatter(content)

        if not frontmatter:
            return SkillMetadata(
                name=dir_name,
                display_name=dir_name,
                description="",
                dir_path=str(skill_file.parent),
            )

        # 简单 YAML 解析（不依赖 pyyaml，只解析 key: value）
        fm_dict = self._simple_yaml_parse(frontmatter)

        return SkillMetadata(
            name=dir_name,
            display_name=fm_dict.get("name", dir_name),
            description=fm_dict.get("description", ""),
            dir_path=str(skill_file.parent),
        )

    def _split_frontmatter(self, content: str) -> tuple[str, str]:
        """分割 frontmatter 和 body。返回 (frontmatter_text, body_text)。"""
        if not content.startswith("---"):
            return "", content

        # 找第二个 ---
        end_idx = content.find("---", 3)
        if end_idx == -1:
            return "", content

        frontmatter = content[3:end_idx].strip()
        body = content[end_idx + 3:].strip()
        return frontmatter, body

    def _simple_yaml_parse(self, text: str) -> dict[str, str]:
        """极简 YAML 解析器（只处理顶层 key: value 字符串对）。"""
        result: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    result[key] = value
        return result

    def list_skills(self) -> list[SkillMetadata]:
        """返回所有已发现的 skill metadata。"""
        return list(self._metadata.values())

    def has_skill(self, name: str) -> bool:
        """检查是否存在指定名称的 skill。"""
        return name in self._metadata

    def load_and_render(self, name: str, arguments: str = "") -> str | None:
        """
        加载并渲染 skill。

        1. 查找 metadata
        2. 读取 SKILL.md body
        3. $ARGUMENTS 替换
        4. 返回渲染后的完整内容

        Returns:
            渲染后的 skill 内容，或 None（skill 不存在）
        """
        if name not in self._metadata:
            return None

        metadata = self._metadata[name]
        skill_file = Path(metadata.dir_path) / "SKILL.md"

        if not skill_file.is_file():
            logger.warning("Skill file missing: %s", skill_file)
            return None

        content = skill_file.read_text(encoding="utf-8")
        _, body = self._split_frontmatter(content)

        if not body:
            return None

        # $ARGUMENTS 替换
        rendered = body.replace("$ARGUMENTS", arguments)

        return rendered

    def format_for_prompt(self) -> str:
        """
        格式化 skill 列表，用于注入 system prompt。

        返回格式：
            ## Available Skills
            Use the `use_skill` tool to invoke these skills:
            - code-review: Review code changes for bugs...
            - explain-error: Explain an error message...
        """
        if not self._metadata:
            return ""

        lines = [
            "## Available Skills",
            "Use the `use_skill` tool to invoke these skills, or the user can type /skill-name directly:",
        ]
        for meta in self._metadata.values():
            desc = meta.description or "(no description)"
            lines.append(f"- **{meta.name}**: {desc}")

        return "\n".join(lines)

    def refresh(self) -> None:
        """重新扫描 skills 目录（用于运行时热加载）。"""
        self._metadata.clear()
        self._discover()

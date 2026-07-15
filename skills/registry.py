"""
skills/registry.py

SkillRegistry — 技能发现、加载、渲染。

发现流程：
1. 扫描多个 skills 目录（内置 + 项目级）
2. 每个子目录中查找 SKILL.md
3. 解析 YAML frontmatter 提取 metadata（name, description）
4. 调用时才读取 body 并执行 $ARGUMENTS 替换

Aligned with Claude Code: no keyword-based triggers; LLM matches skills
via description semantic similarity in the system prompt listing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# 内置 skills 目录（随代码分发）
BUILTIN_SKILLS_DIR = str(Path(__file__).parent / "builtin")


@dataclass
class SkillMetadata:
    """技能元数据 — aligned with Claude Code Skill frontmatter reference.

    https://code.claude.com/docs/en/skills#frontmatter-reference

    Core:
      name:        directory name, also the invocation command /name
      display_name: frontmatter 'name' field (human-readable label in listings)
      description: frontmatter 'description' (LLM uses this to decide when to load)
      when_to_use: frontmatter 'when_to_use' — extra context for LLM auto-load
      dir_path:    absolute path to the skill directory

    Invocation control:
      disable_model_invocation:  true → only user /name can invoke, LLM cannot auto-load
      user_invocable:            false → hidden from / menu, only LLM can invoke

    Execution:
      model:   model override when skill is active ("" = inherit)
      effort:  effort level override ("" = inherit): low|medium|high|xhigh|max
      context: "" | "fork" — run in forked subagent context
      agent:   subagent type when context=fork

    Activation scope:
      paths: glob patterns limiting auto-activation to matching files

    Tool control:
      allowed_tools:    tools granted without per-use approval while active
      disallowed_tools: tools removed from available pool while active
    """
    name: str              # 目录名，也是调用名（/name）
    display_name: str      # frontmatter 中的 name 字段
    description: str       # frontmatter 中的 description
    dir_path: str = ""     # 技能目录的绝对路径
    when_to_use: str = ""  # frontmatter 中的 when_to_use

    # ── Invocation control ──
    disable_model_invocation: bool = False
    user_invocable: bool = True

    # ── Execution overrides ──
    model: str = ""    # "" = inherit session model
    effort: str = ""   # "" = inherit session effort
    context: str = ""  # "" | "fork"
    agent: str = ""    # subagent type when context=fork

    # ── Activation scope ──
    paths: tuple[str, ...] = ()

    # ── Tool control ──
    allowed_tools: frozenset[str] = frozenset()
    disallowed_tools: frozenset[str] = frozenset()

    # ── Derived helpers ──

    @property
    def model_invocable(self) -> bool:
        """Can the LLM auto-invoke this skill? Inverse of disable_model_invocation."""
        return not self.disable_model_invocation

    @property
    def user_can_invoke(self) -> bool:
        """Can the user type /name to invoke this skill?"""
        return self.user_invocable

    def matches_path(self, file_path: str) -> bool:
        """Check whether this skill should activate for the given file path.

        Uses pathlib.PurePosixPath.match() which supports ** (recursive)
        unlike fnmatch.fnmatch() on Python < 3.13.
        """
        if not self.paths:
            return True
        p = file_path.replace("\\", "/")
        pp = Path(p)
        return any(pp.match(pat) for pat in self.paths)


class SkillRegistry:
    """
    技能注册表。负责发现、索引、加载和渲染技能。

    支持多目录发现：
    - 内置 skills/builtin/（随代码提交）
    - 项目级 .forge-agent/skills/（用户自定义）

    用法：
        registry = SkillRegistry("/path/to/.forge-agent/skills")
        skills = registry.list_skills()
        rendered = registry.load_and_render("code-review", "auth module")
    """

    def __init__(self, skills_dir: str, extra_dirs: list[str] | None = None, include_builtin: bool = True) -> None:
        self._skills_dirs: list[str] = []
        # 内置目录（可选，测试时可关闭）
        if include_builtin:
            self._skills_dirs.append(BUILTIN_SKILLS_DIR)
        # 项目级目录
        if skills_dir:
            self._skills_dirs.append(skills_dir)
        # 额外目录（如用户级 ~/.forge-agent/skills/）
        if extra_dirs:
            self._skills_dirs.extend(extra_dirs)

        self._metadata: dict[str, SkillMetadata] = {}
        self._discover()

    def _discover(self) -> None:
        """扫描所有 skills 目录，解析每个 SKILL.md 的 frontmatter。"""
        for skills_dir in self._skills_dirs:
            skills_path = Path(skills_dir)
            if not skills_path.is_dir():
                logger.debug("Skills directory does not exist: %s", skills_dir)
                continue

            for entry in sorted(skills_path.iterdir()):
                if not entry.is_dir():
                    continue
                skill_file = entry / "SKILL.md"
                if not skill_file.is_file():
                    continue

                try:
                    metadata = self._parse_frontmatter(skill_file, entry.name)
                    if metadata:
                        # 项目级覆盖内置（后扫描的目录覆盖先扫描的）
                        self._metadata[metadata.name] = metadata
                        logger.debug("Discovered skill: %s (from %s)", metadata.name, skills_dir)
                except Exception as e:
                    logger.warning("Failed to parse skill %s: %s", entry.name, e)

        logger.info("Discovered %d skills total", len(self._metadata))

    def _parse_frontmatter(self, skill_file: Path, dir_name: str) -> SkillMetadata | None:
        """Parse SKILL.md YAML frontmatter.

        Supported fields (aligned with Claude Code):
          name, description, when_to_use, model, effort,
          disable-model-invocation, user-invocable, allowed-tools,
          disallowed-tools, context, agent, paths, arguments

        Note: 'triggers' has been removed — Claude Code uses LLM semantic
        matching via description, not keyword-based substring matching.
        """
        content = skill_file.read_text(encoding="utf-8")
        frontmatter, _ = self._split_frontmatter(content)

        if not frontmatter:
            return SkillMetadata(
                name=dir_name,
                display_name=dir_name,
                description="",
                dir_path=str(skill_file.parent),
            )

        try:
            fm_dict: dict = yaml.safe_load(frontmatter) or {}
        except yaml.YAMLError:
            fm_dict = {}

        # ── Parse paths: string, comma/space-separated, or YAML list ──
        raw_paths = fm_dict.get("paths", ())
        if isinstance(raw_paths, str):
            paths = tuple(
                p.strip() for p in raw_paths.replace(",", " ").split()
                if p.strip()
            )
        elif isinstance(raw_paths, list):
            paths = tuple(str(p).strip() for p in raw_paths if str(p).strip())
        else:
            paths = ()

        # ── Parse allowed/disallowed tools ──
        def _parse_tool_set(raw) -> frozenset[str]:
            if isinstance(raw, str):
                return frozenset(t.strip() for t in raw.replace(",", " ").split() if t.strip())
            if isinstance(raw, list):
                return frozenset(str(t).strip() for t in raw if str(t).strip())
            return frozenset()

        return SkillMetadata(
            name=dir_name,
            display_name=str(fm_dict.get("name", dir_name)),
            description=str(fm_dict.get("description", "")),
            when_to_use=str(fm_dict.get("when_to_use", "")),
            dir_path=str(skill_file.parent),
            disable_model_invocation=bool(fm_dict.get("disable-model-invocation", False)),
            user_invocable=bool(fm_dict.get("user-invocable", True)),
            model=str(fm_dict.get("model", "")),
            effort=str(fm_dict.get("effort", "")),
            context=str(fm_dict.get("context", "")),
            agent=str(fm_dict.get("agent", "")),
            paths=paths,
            allowed_tools=_parse_tool_set(fm_dict.get("allowed-tools", [])),
            disallowed_tools=_parse_tool_set(fm_dict.get("disallowed-tools", [])),
        )

    @staticmethod
    def _split_frontmatter(content: str) -> tuple[str, str]:
        """Split frontmatter and body using the shared utility."""
        from utils.frontmatter import split_frontmatter
        return split_frontmatter(content)

    def list_skills(self) -> list[SkillMetadata]:
        """返回所有已发现的 skill metadata。"""
        return list(self._metadata.values())

    def has_skill(self, name: str) -> bool:
        """检查是否存在指定名称的 skill。"""
        return name in self._metadata

    def get_skill_detail(self, name: str) -> str | None:
        """返回 skill 的完整 body 内容（未做 $ARGUMENTS 替换）。供 /skill show 使用。"""
        if name not in self._metadata:
            return None
        metadata = self._metadata[name]
        skill_file = Path(metadata.dir_path) / "SKILL.md"
        if not skill_file.is_file():
            return None
        content = skill_file.read_text(encoding="utf-8")
        _, body = self._split_frontmatter(content)
        return body or None

    def load_and_render(self, name: str, arguments: str = "") -> str | None:
        """
        加载并渲染 skill。

        1. 查找 metadata
        2. 读取 SKILL.md body
        3. $ARGUMENTS 替换
        4. 返回渲染后的完整内容
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

        rendered = body.replace("$ARGUMENTS", arguments)
        return rendered

    def format_for_prompt(self, *, llm_invocable_only: bool = True) -> str:
        """
        Format skill list for system prompt injection.

        Aligned with Claude Code frontmatter:
        - Skills with disable_model_invocation=true are hidden from LLM listing.
          The user can still invoke them via /name, but the LLM won't auto-load.
        - user-invocable=false skills are still listed (LLM can auto-load them).
        - when_to_use is appended to description for semantic matching.

        Args:
            llm_invocable_only: if True (default), exclude skills that set
                               disable-model-invocation: true.
        """
        if not self._metadata:
            return ""

        user_skills = [m for m in self._metadata.values() if m.user_can_invoke]
        model_skills = [m for m in self._metadata.values() if m.model_invocable]

        lines = [
            "## Available Skills",
        ]

        # Skills the user can invoke via /name
        if user_skills:
            names = ", ".join(f"/{m.name}" for m in user_skills)
            lines.append(f"User-invocable: {names}")

        # Skills the LLM can auto-load (respects disable_model_invocation)
        visible = model_skills if llm_invocable_only else list(self._metadata.values())

        if visible:
            lines.append("Use the `Skill` tool to load a skill, or type /skill-name directly:")
            for meta in visible:
                desc = meta.description or "(no description)"
                if meta.when_to_use:
                    desc += f" (Use when: {meta.when_to_use})"
                lines.append(f"- **/{meta.name}**: {desc}")

        return "\n".join(lines)

    def refresh(self) -> None:
        """重新扫描 skills 目录（用于运行时热加载）。"""
        self._metadata.clear()
        self._discover()

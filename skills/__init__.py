"""
skills/

Skill 系统 — filesystem-based 可复用技能模块。

设计借鉴 Claude Code 的 Skill 架构：
- 技能定义存放在 .forge-agent/skills/<name>/SKILL.md
- YAML frontmatter 描述 metadata（name, description）
- Markdown body 是技能内容（在调用时注入 agent 上下文）
- 支持 $ARGUMENTS 参数替换
"""

from skills.registry import SkillRegistry, SkillMetadata
from skills.tool import SkillTool

__all__ = ["SkillRegistry", "SkillMetadata", "SkillTool"]

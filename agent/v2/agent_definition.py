"""Load agent definitions from .md YAML frontmatter files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from agent.task import TaskIntent
from agent.v2.models import (
    AgentDefinition,
    AgentIsolation,
    AgentVisibility,
    DelegationScope,
)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class AgentDefinitionError(ValueError):
    """A discovered agent file exists but cannot define a trustworthy agent."""

    def __init__(self, path: str | Path, detail: str) -> None:
        self.path = Path(path).expanduser().resolve()
        self.detail = detail
        super().__init__(f"Invalid agent definition {self.path}: {detail}")


def _invalid(path: Path, detail: str) -> AgentDefinitionError:
    return AgentDefinitionError(path, detail)


def load_agent_definitions(
    project_dir: str | Path | None = None,
    user_dir: str | Path | None = None,
) -> dict[str, AgentDefinition]:
    """Load agent definitions from user, project, and built-in scopes.

    Priority: project > user > built-in.
    """
    merged: dict[str, AgentDefinition] = {}

    # Built-in (lowest priority)
    from agent.v2.models import _BUILTIN_AGENTS
    merged.update(_BUILTIN_AGENTS)

    # User (~/.forge-agent/agents/)
    user_agents_dir = Path(user_dir) if user_dir else Path.home() / ".forge-agent" / "agents"
    for definition in _load_from_dir(user_agents_dir):
        merged[definition.name] = definition

    # Project (.forge-agent/agents/).  Project discovery is opt-in: callers
    # must provide the Runtime-owned project root instead of inheriting the
    # host process CWD.
    if project_dir is not None:
        project_root = Path(project_dir).expanduser().resolve()
        project_agents_dir = project_root / ".forge-agent" / "agents"
        for definition in _load_from_dir(project_agents_dir):
            merged[definition.name] = definition

    return merged


def _load_from_dir(directory: Path) -> list[AgentDefinition]:
    if not directory.is_dir():
        return []
    definitions: list[AgentDefinition] = []
    names: dict[str, Path] = {}
    for path in sorted(directory.glob("*.md")):
        definition = _parse_definition(path)
        previous = names.get(definition.name)
        if previous is not None:
            raise _invalid(
                path,
                f"duplicate agent name {definition.name!r} in the same scope; "
                f"already declared by {previous.resolve()}",
            )
        names[definition.name] = path
        definitions.append(definition)
    return definitions


def _parse_definition(path: Path) -> AgentDefinition:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise _invalid(path, f"unable to read UTF-8 content: {exc}") from exc

    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise _invalid(path, "missing YAML frontmatter")

    try:
        frontmatter: dict[str, Any] = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise _invalid(path, f"invalid YAML frontmatter: {exc}") from exc

    if not isinstance(frontmatter, dict):
        raise _invalid(path, "YAML frontmatter must be a mapping")

    name = frontmatter.get("name", path.stem)
    body = text[match.end():].strip()

    tools_raw = frontmatter.get("tools", "")
    disallowed_raw = frontmatter.get("disallowedTools", frontmatter.get("disallowed_tools", ""))
    allowed_subagents_raw = frontmatter.get("allowedSubagents", frontmatter.get("allowed_subagents", None))
    intent_raw = frontmatter.get("intent")
    if intent_raw is None:
        raise _invalid(path, "missing required field 'intent'")
    try:
        intent = TaskIntent(intent_raw)
    except ValueError as exc:
        raise _invalid(path, f"field 'intent' has invalid value {intent_raw!r}") from exc
    isolation_raw = frontmatter.get("isolation", AgentIsolation.FORK.value)
    try:
        isolation = AgentIsolation(isolation_raw)
    except ValueError as exc:
        raise _invalid(
            path, f"field 'isolation' has invalid value {isolation_raw!r}"
        ) from exc
    if "background" in frontmatter:
        raise _invalid(path, "unsupported field 'background'")
    if "hidden" in frontmatter:
        raise _invalid(path, "removed field 'hidden'; use 'visibility'")
    visibility_raw = frontmatter.get("visibility", AgentVisibility.PUBLIC.value)
    try:
        visibility = AgentVisibility(visibility_raw)
    except ValueError as exc:
        raise _invalid(
            path, f"field 'visibility' has invalid value {visibility_raw!r}"
        ) from exc
    delegation_scope_raw = frontmatter.get(
        "delegationScope", frontmatter.get("delegation_scope")
    )
    try:
        delegation_scope = (
            DelegationScope(delegation_scope_raw)
            if delegation_scope_raw is not None
            else None
        )
    except ValueError as exc:
        raise _invalid(
            path,
            f"field 'delegationScope' has invalid value {delegation_scope_raw!r}",
        ) from exc
    try:
        max_turns = int(frontmatter.get("maxTurns", frontmatter.get("max_turns", 50)))
        max_tokens_raw = frontmatter.get(
            "maxTokens", frontmatter.get("max_tokens")
        )
        max_tokens = int(max_tokens_raw) if max_tokens_raw is not None else None
        if max_turns < 1 or (max_tokens is not None and max_tokens < 1):
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise _invalid(
            path, "fields 'maxTurns' and 'maxTokens' must be positive integers"
        ) from exc

    return AgentDefinition(
        name=str(name),
        description=str(frontmatter.get("description", "")),
        intent=intent,
        tools=_parse_tool_list(tools_raw),
        disallowed_tools=_parse_tool_list(disallowed_raw),
        allowed_subagents=_parse_optional_list(allowed_subagents_raw),
        delegation_scope=delegation_scope,
        model=str(frontmatter.get("model", "inherit")),
        isolation=isolation,
        visibility=visibility,
        max_turns=max_turns,
        max_tokens=max_tokens,
        system_prompt=body or str(frontmatter.get("instructions", "")),
    )


def _parse_tool_list(value: Any) -> frozenset[str]:
    if isinstance(value, str):
        return frozenset(
            name.strip()
            for name in value.replace(",", " ").split()
            if name.strip()
        )
    if isinstance(value, list):
        return frozenset(str(item).strip() for item in value if str(item).strip())
    return frozenset()


def _parse_optional_list(value: Any) -> frozenset[str] | None:
    if value is None:
        return None
    return _parse_tool_list(value)

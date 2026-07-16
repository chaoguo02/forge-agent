# Skills 系统 CC 对齐 — 实现计划

> 依据: CC 官方文档 + 源码 (skills.mdx, Tool.ts, QueryEngine.ts, SkillTool.ts)
> 参考: https://code.claude.com/docs/en/skills

---

## 批次数

| 批次 | 主题 | 文件数 | 核心改动 |
|------|------|--------|---------|
| S1 | SkillTool contextModifier + V2 注册 + allowed-tools | 8 | ToolResult 携带权限修改、注册 Skill 到 V2、SK-05/06 生效 |
| S2 | context: fork + model/effort 覆盖 | 5 | Fork 模式独立执行、模型切换、推理力度 |
| S3 | hooks + paths + 两阶段加载 | 5 | 技能 hooks 注册/清理、路径动态激活、前加载优化 |

---

## Batch S1: SkillTool contextModifier + V2 注册 + allowed-tools

### 1.1 SkillTool 返回 contextModifier

**CC 依据**: SkillTool 返回的 `ToolResult` 携带 `contextModifier` 闭包, 包含:
- `allowedTools → appState.toolPermissionContext.alwaysAllowRules.command`
- `model → resolveSkillModelOverride()`
- `effort → getAppState().effortValue`

**改动**: `skills/tool.py` — SkillTool.execute() 新增 contextModifier 机制:

```python
@dataclass
class SkillContextModifier:
    allowed_tools: frozenset[str] = frozenset()
    disallowed_tools: frozenset[str] = frozenset()
    model: str = ""
    effort: str = ""

class SkillTool(BaseTool):
    def execute(self, params):
        ...
        metadata = self._registry.get_skill_meta(skill_name)  # 新增方法
        modifier = SkillContextModifier(
            allowed_tools=metadata.allowed_tools if metadata else frozenset(),
            disallowed_tools=metadata.disallowed_tools if metadata else frozenset(),
            model=metadata.model if metadata else "",
            effort=metadata.effort if metadata else "",
        )
        # 通过 ToolResult.metadata 传递 modifier
        result = ToolResult(success=True, output=..., metadata={"skill_modifier": modifier})
        # 在 registry 层消费 modifier
        if modifier.allowed_tools or modifier.disallowed_tools:
            registry = getattr(self, "_registry", None)
            if registry and hasattr(registry, "with_skill_restrictions"):
                registry = registry.with_skill_restrictions(metadata)
        return result
```

### 1.2 SkillMetadata 添加 hooks 字段 + get_skill_meta 公开方法

**改动**: `skills/registry.py`
- `SkillMetadata` 新增 `hooks: tuple[dict, ...] = ()`
- `_parse_frontmatter` 解析 `hooks` 字段
- `get_skill_meta()` 改为公开方法

### 1.3 registry_factory.py 注册 SkillTool

**CC 依据**: Skill 工具对所有 agent 类型可用, 非仅 chat 模式。

**改动**: `entry/bootstrap/registry_factory.py`
```python
from skills.tool import SkillTool
from skills.registry import SkillRegistry
skills_dir = str(Path(repo_path) / ".forge-agent" / "skills") if repo_path else ""
skill_registry = SkillRegistry(skills_dir)
if skill_registry.list_skills():
    registry.register(SkillTool(skill_registry))
```

### 1.4 V2 系统提示注入 Available Skills 列表

**CC 依据**: Phase 1 加载: name+description 注入系统提示 (~100 tokens/个)。

**改动**: `agent/v2/runtime_prompt_builder.py`
```python
# 在 build_runtime_messages() 末尾添加
if skill_registry is not None:
    skill_listing = skill_registry.format_for_prompt(llm_invocable_only=True)
    if skill_listing:
        messages.append(LLMMessage(role="user", content=skill_listing))
```

需要传递 `skill_registry` 参数到 `build_runtime_messages()`。

### 1.5 ToolResult 支持 metadata 传递

**CC 依据**: tool 结果可携带 `contextModifier` 元数据改变后续状态。

**改动**: `tools/base.py` — ToolResult 新增 `metadata` 字段:
```python
@dataclass
class ToolResult:
    success: bool
    output: str = ""
    error: str = ""
    cached: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 1.6 PolicyAwareToolRegistry 消费 skill modifier

**CC 依据**: contextModifier 在工具返回后立即应用。

**改动**: `agent/policy_registry.py`
```python
def execute_tool(self, name, params, thought=""):
    result = super().execute_tool(name, params, thought=thought)
    # 消费 skill modifier
    if result.success and result.metadata.get("skill_modifier"):
        modifier = result.metadata["skill_modifier"]
        if modifier.allowed_tools or modifier.disallowed_tools:
            fake_skill = type("Skill", (), {
                "allowed_tools": modifier.allowed_tools,
                "disallowed_tools": modifier.disallowed_tools,
            })()
            self = self.with_skill_restrictions(fake_skill)
    return result
```

### 1.7 with_skill_restrictions 支持 skill 去激活

**CC 依据**: 技能结束后恢复原始权限。

**改动**: `agent/policy_registry.py` — 保存原始 PhasePolicy 快照, 技能结束时恢复。

### 涉及文件 (8 个)
1. `skills/tool.py` — contextModifier + get_skill_meta
2. `skills/registry.py` — hooks 字段 + 公开 get_skill_meta
3. `entry/bootstrap/registry_factory.py` — 注册 SkillTool
4. `agent/v2/runtime_prompt_builder.py` — 注入技能列表
5. `agent/v2/runtime.py` — 传递 skill_registry
6. `tools/base.py` — ToolResult.metadata
7. `agent/policy_registry.py` — 消费 modifier + with_skill_restrictions
8. `agent/policy.py` — PhasePolicy 支持 skill 去激活

---

## Batch S2: context: fork + model/effort 覆盖

### 2.1 context: fork 执行路径

**CC 依据**: `context: fork` 时, 技能在隔离子代理中执行, 有独立 token budget。

**改动**: `skills/tool.py` — 检测 context, fork 时调用 Agent 工具:
```python
if metadata.context == "fork":
    agent_type = metadata.agent or "general-purpose"
    # 通过 Agent tool 派发子代理执行技能内容
    return self._execute_forked(agent_type, rendered, metadata)
```

### 2.2 model/effort 覆盖

**CC 依据**: 技能 frontmatter 的 model/effort 在技能激活期间覆盖主会话配置。

**改动**: 在 contextModifier 中已携带 model/effort, PolicyAwareToolRegistry 消费时传递给 AgentConfig。

### 涉及文件 (5 个)
1. `skills/tool.py` — fork 执行路径
2. `agent/core.py` — AgentConfig.effort 已存在
3. `agent/policy_registry.py` — model/effort 覆盖
4. `agent/v2/runtime.py` — subagent skill 执行
5. `agent/v2/agent_factory.py` — 传递 skill model/effort

---

## Batch S3: hooks + paths + 两阶段加载

### 3.1 技能 hooks 注册/清理

**CC 依据**: 技能调用时注册 hooks, 技能结束时清理。

### 3.2 paths 动态激活

**CC 依据**: paths 条件技能仅在文件匹配时浮现。

### 3.3 两阶段加载 (Phase 1 frontmatter only)

**CC 依据**: 启动只读 frontmatter (~100 tokens/个), body 在调用时才加载。

### 涉及文件 (5 个)
1. `skills/registry.py` — hooks 注册/清理、paths 动态激活、两阶段加载
2. `skills/tool.py` — hooks 生命周期
3. `agent/v2/runtime.py` — 清理 hooks

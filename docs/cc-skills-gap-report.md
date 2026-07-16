# Skills 系统 — CC 对齐差距报告

> 依据: CC 官方文档 + 源码分析 (skills.mdx, sub-agents.md, permissions.md)
> 调研: 2026-07-16

---

## ✅ 已正确实现

| # | 特性 | 位置 | 说明 |
|---|------|------|------|
| 1 | Skill 工具名 "Skill", 别名 "use_skill" | `skills/tool.py:50-54` | CC-aligned |
| 2 | SKILL.md + YAML frontmatter 格式 | `skills/registry.py:201-273` | 完整解析 |
| 3 | 基本字段: name, description, when_to_use | `skills/registry.py:61-65` | 已解析 |
| 4 | Invocation control: disable_model_invocation, user_invocable | `skills/registry.py:68-69` | 已解析 |
| 5 | model, effort 字段解析 | `skills/registry.py:72-73` | 已解析 |
| 6 | context: "fork" 字段解析 | `skills/registry.py:74` | 已解析存值 |
| 7 | agent 字段 (fork 模式代理类型) | `skills/registry.py:75` | 已解析 |
| 8 | paths 条件激活 glob | `skills/registry.py:78` | `matches_path()` 方法可用 |
| 9 | arguments 命名参数 | `skills/registry.py:79` | 已解析 |
| 10 | allowed-tools / disallowed-tools 解析 | `skills/registry.py:82-83` | 已解析为 frozenset |
| 11 | $ARGUMENTS 全部替换 | `skills/registry.py:501` | 完整替换 |
| 12 | $ARGUMENTS[N], $N | `skills/registry.py:477-482` | 定位替换 |
| 13 | $name 命名参数替换 (SK-12) | `skills/registry.py:485-488` | frontmatter 映射 |
| 14 | ${CLAUDE_SESSION_ID}, ${CLAUDE_PROJECT_DIR} | `skills/registry.py:492-494` | 环境变量替换 |
| 15 | ${CLAUDE_SKILL_DIR}, ${CLAUDE_EFFORT} | `skills/registry.py:496-498` | 环境变量替换 |
| 16 | 多目录发现 (内置 + 项目) | `skills/registry.py:124-131` | 优先级可控 |
| 17 | 嵌套 skill 发现 (SK-19) | `skills/registry.py:162-175` | 3 层深度 |
| 18 | mtime 增量刷新 (SK-18) | `skills/registry.py:569-591` | 无变化不重扫 |
| 19 | 支持文件索引 (SK-17) | `skills/registry.py:364-384` | 运行时自动附加 |
| 20 | !`cmd` 和 ```! 内联命令 (SK-09) | `skills/registry.py:389-450` | 预处理阶段执行 |
| 21 | SkillContextBuffer 上下文管理 | `skills/buffer.py` | LRU 淘汰 |

---

## ❌ 未实现（需新增）

### 1. allowed-tools/disallowed-tools 未接入 PermissionPipeline

**CC 行为**: 技能调用时, `contextModifier` 将 `allowed-tools` 合并到 `alwaysAllowRules.command`, 持续到技能生命周期结束。disallowed-tools 从工具池中移除。

**我们的现状**: `SkillTool.execute()` 只返回文本, 不修改任何运行时权限状态。`PolicyAwareToolRegistry.with_skill_restrictions()` 存在但从未被调用。

**影响**: skills 的 `allowed-tools: [Read, Grep]` 在技能激活时**没有任何效果**——模型仍能看到所有工具。SK-05/SK-06 未实现。

### 2. model/effort 覆盖未生效

**CC 行为**: 技能 frontmatter 的 `model: sonnet` 在技能激活期间覆盖主会话模型。

**我们的现状**: 字段已解析到 `SkillMetadata.model`, 但从未传递到 `LLMBackend` 或 `AgentConfig`。

### 3. context: fork 未实现

**CC 行为**: `context: fork` 时, 技能在独立子代理中执行 (`prepareForkedCommandContext()` → `runAgent()`), 有自己的 token budget 和工具池。

**我们的现状**: 无论 `context` 字段是什么, 始终内联渲染后返回文本。fork 模式完全缺失。

### 4. 系统提示中无 "Available Skills" 列表 (V2 模式)

**CC 行为**: 启动时两阶段加载: Phase 1 将所有技能的 name+description 注入系统提示 (~100 tokens/个), 模型知悉所有可用技能。

**我们的现状**: `SkillRegistry.format_for_prompt()` 存在但只在 chat 模式的 help 中显示。V2 agent 的系统提示 (`runtime_prompt_builder.py`) 完全不包含 skill 列表。模型甚至不知道技能的存在。

### 5. hooks 字段未解析

**CC 行为**: 技能 frontmatter 可声明 `hooks`, 调用时注册、结束时清理。

**我们的现状**: `SkillMetadata` 没有 hooks 字段, `_parse_frontmatter` 不解析 hooks。技能调用也没涉及 hook 注册/清理。

### 6. paths 条件激活未使用

**CC 行为**: 声明 `paths: packages/database/**` 的技能, 仅在模型访问匹配文件时动态浮现。

**我们的现状**: `matches_path()` 已实现但从未被调用。所有技能始终可见。

### 7. 两阶段加载未实现

**CC 行为**: Phase 1 只加载 frontmatter (~100 tokens), Phase 2 在调用时加载完整 body + 资源。

**我们的现状**: `SkillRegistry.__init__()` 一次性读取所有 SKILL.md, 在启动时 parse frontmatter 和 body。不是正确性问题, 但启动时 token/cpu 开销更高。

---

## ⚠️ 已实现但错误

### 1. SkillTool 只返回文本, 不修改 agent 运行时状态 ← 最严重的架构差距

**问题**: `skills/tool.py:104-107`
```python
return ToolResult(
    success=True,
    output=f"[Skill: {skill_name}]\n\n{rendered}",
)
```

**CC 的做法**: Skill 工具返回带有 `contextModifier` 的结果对象:
```typescript
return {
    type: ToolResultType.REPROMPT,
    contextModifier: {
        toolPermissionContext: {
            alwaysAllowRules: {
                command: [{ toolName: "Read" }, ...]  // allowed-tools
            }
        },
        mainLoopModel: "sonnet",         // model override
        getAppState().effortValue: "high" // effort override
    },
    output: rendered_content
};
```

**影响**: 由于只返回纯文本, 以下 CC-aligned 功能全部失效:
- allowed-tools 不会 auto-approve 指定工具
- disallowed-tools 不会移除指定工具
- model 不会切换模型
- effort 不会调整推理力度

### 2. V2 模式下 Skill 工具不可见

**问题**: `entry/cli.py:689-691`
```python
if skill_registry.list_skills():
    from skills.tool import SkillTool
    registry.register(SkillTool(skill_registry))
```
SkillTool 只注册到 chat 模式的 registry, 而在 V2 run mode (`entry/bootstrap/registry_factory.py`) 中从未注册。V2 build agent 根本没有 Skill 工具可用。

### 3. format_for_prompt() 未注入 V2 系统提示

**问题**: `runtime_prompt_builder.py` 没有调用 `skill_registry.format_for_prompt()`。Agent 运行时提示中不包含 "Available Skills" 列表。

### 4. `\$_` 转义处理在替换顺序中可能出错

**问题**: `skills/registry.py:505-509`
```python
for key in sorted(subs.keys(), key=len, reverse=True):
    result = result.replace(key, subs[key])
result = result.replace("\\$", "$")  # 后处理转义
```
如果 content 中有 `\$ARGUMENTS`, `$ARGUMENTS` 先被替换成实际参数, 然后 `\$` 被转义为 `$`, 导致 `\$ARGUMENTS` 变成 `$actual_args` 而非保留为 `\$ARGUMENTS`。

---

## 总结

| 类别 | 数量 | 关键项 |
|------|------|--------|
| ✅ 已正确实现 | 21 项 | frontmatter 解析、参数替换、发现机制、内联命令 |
| ❌ 未实现 | 7 项 | allowed-tools 接入 pipeline、model/effort 覆盖、fork 执行、系统提示列表、hooks、动态 paths、两阶段加载 |
| ⚠️ 已实现但错误 | 4 项 | SkillTool 无 contextModifier、V2 模型无 Skill 工具、无技能列表提示、转义处理顺序 |

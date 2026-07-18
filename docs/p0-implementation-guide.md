# P0 实施指导：模型切换 / 上下文压缩 / Skills / 文件附件

> 基于 2026-07-19 Claude Code 逆向工程研究 + 官方文档 + 社区分析
> 所有实现建议均标注来源 URL 和对应代码位置

---

## 目录

1. [P0-1: 模型切换](#p01-模型切换)
2. [P0-2: 上下文自动压缩](#p02-上下文自动压缩)
3. [P0-3: Skills 系统](#p03-skills-系统)
4. [P0-4: 文件附件 (@mentions)](#p04-文件附件-mentions)

---

## P0-1: 模型切换

### 目标

允许用户在会话内切换 LLM 模型（如 DeepSeek → GPT），且下一轮生效，上下文历史保留。

### CC 的实现方式

CC 的 `/model` 命令是 **harness/model 分离架构**的体现：

- **`/model <alias>`** 在当前会话切换模型，下一轮生效
- **`--model <id>`** 在启动时设置
- **`ANTHROPIC_MODEL`** 环境变量设置默认模型
- 社区通过反向代理 (claude-code-router) 实现跨 provider 路由
- 上下文**保留**（历史不丢失），但 prompt cache 失效

> **来源:** [Claude Code model configuration](https://support.claude.com/en/articles/11940350-claude-code-model-configuration), [claude-code-router](https://github.com/GoldVelen/claude-model-router)

### 我们的现状

- [server/services/agent_service.py:102-115](server/services/agent_service.py#L102-L115) — LLM backend 在 `__init__` 中创建，之后不可变
- [server/services/agent_service.py:190-202](server/services/agent_service.py#L190-L202) — `_apply_cli_overrides` 仅在初始化时应用
- [web/src/components/ChatView.tsx:26-30](web/src/components/ChatView.tsx#L26-L30) — `MODEL_OPTIONS` 定义了前端列表，但未接入后端
- 后端 `create_backend_from_config()` 接收 model/provider 参数，具备重建能力

### 实施步骤

**Step 1: 后端 — 添加模型切换 API**

新增端点 `POST /api/sessions/{session_id}/model`:

```python
# server/routers/sessions.py
@router.post("/{session_id}/model")
async def switch_model(session_id: str, body: ModelSwitchBody, service=Depends(get_service)):
    """Switch the LLM model for an active session. Takes effect on the next message."""
    rec = service.session_service.get_session(session_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Session not found")
    # Store pending model switch in session metadata
    service.session_service.update_metadata(session_id, {
        "pending_model": body.model,
        "pending_provider": body.provider,
    })
    return {"switched": True, "model": body.model, "session_id": session_id}
```

**Step 2: 后端 — `run_chat_async` 在构建 backend 前检查 pending model**

修改 [server/services/agent_service.py:444-460](server/services/agent_service.py#L444-L460):

```python
def _run_and_notify():
    # 检查是否有 pending model switch
    meta = self.session_service.get_session(session_id).metadata
    pending_model = meta.get("pending_model")
    if pending_model:
        # 重建 backend
        self._backend = create_backend_from_config({
            "provider": meta.get("pending_provider", self._config.llm.provider),
            "model": pending_model,
            "api_key": self._config.llm.api_key or None,
            "base_url": self._config.llm.base_url or None,
            "max_tokens": self._config.llm.max_tokens,
            "timeout_seconds": self._config.llm.timeout_seconds,
        })
        # 清除 pending flag
        service.session_service.update_metadata(session_id, {"pending_model": None})
    ...
```

**关键约束**: 切换模型后，prompt cache 会失效。如果使用 Anthropic API 的 prompt caching，需要在切换后的第一条消息中接受 cache miss 的开销。

**Step 3: 前端 — 模型选择器**

在 [web/src/components/ChatView.tsx](web/src/components/ChatView.tsx) 的 composer 区域添加模型下拉框：

```tsx
// 已有 MODEL_OPTIONS 定义 (line 26-30)，只需接入
<select value={currentModel} onChange={async (e) => {
    setCurrentModel(e.target.value);
    await fetch(`/api/sessions/${sid}/model`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: e.target.value }),
    });
}}>
    {MODEL_OPTIONS.map(m => <option key={m.key} value={m.key}>{m.family}: {m.note}</option>)}
</select>
```

**Step 4: 前端 — chatStore 添加 currentModel 状态**

[web/src/stores/chatStore.ts](web/src/stores/chatStore.ts) 已有 `currentMode`，同理添加 `currentModel`:

```typescript
currentModel: string;
setModel: (model: string) => void;
```

### 行为准则

1. **模型切换仅在下一轮生效** — 当前正在执行的 agent 不受影响
2. **上下文历史保留** — 切换后不丢失对话
3. **Provider 切换可选** — 默认保持当前 provider，仅切换 model 名
4. **前端列表中仅显示已配置的 provider 支持的模型** — 从 `config.llm` 读取

### 涉及文件

| 文件 | 改动 |
|------|------|
| `server/routers/sessions.py` | 新增 `POST /{id}/model` 端点 |
| `server/services/agent_service.py` | `_run_and_notify` 检查 pending model |
| `server/services/session_service.py` | 可能需要 `update_metadata` 方法 |
| `web/src/components/ChatView.tsx` | 模型选择器 UI |
| `web/src/stores/chatStore.ts` | `currentModel` 状态 |

---

## P0-2: 上下文自动压缩

### 目标

当 token 使用量接近上下文窗口上限时，自动触发压缩，防止 agent 因上下文溢出而失败。

### CC 的实现方式

CC 使用**四层渐进式压缩流水线**，每层成本从零到高递进：

| 层级 | 粒度 | 成本 | 机制 |
|------|------|------|------|
| **Snip** | 整个轮次 | 零 | `Array.filter()` 移除空结果/被拒轮次 |
| **MicroCompact** | tool_result 内容 | 零 API 调用 | cache_edits / 时间衰减清理旧工具输出 |
| **Context Collapse** | 多轮范围 | 低 (LLM 摘要) | 读时投影，创建虚拟视图 |
| **AutoCompact** | 整个会话 | 1 次 API 调用 | 9 段式结构化摘要 + 重注入关键上下文 |

触发条件: `token_count > effective_context_window - 13000` (~80% 窗口)。

关键设计细节:
- **Session Memory 优先**: 后台维护的会话内存可复用时跳过 LLM 摘要
- **电路断路器**: 连续 3 次压缩失败后禁用
- **层间协作**: Snip 释放的 token 数传递给 AutoCompact，Collapse 与 AutoCompact 互斥
- **压缩后恢复**: 重新注入最近 5 个文件 (每文件 5K token)、技能 (每技能 5K)、CLAUDE.md

> **来源:** [wuwangzhang1216 deep analysis](https://github.com/wuwangzhang1216/claude-code-source-all-in-one/blob/main/claude-code-deep-analysis/07-context-window.en.md), [Claude Code compaction docs](https://github.com/claude-code-best/claude-code/blob/main/docs/context/compaction.mdx), [CSDN 分析](https://blog.csdn.net/monsion/article/details/159698713), [Tencent Cloud 分析](https://cloud.tencent.com.cn/developer/article/2653153)

### 我们的现状

- [agent/core.py:555](agent/core.py#L555) — `token_budget = TokenBudget(total=...)` 已追踪 token 使用
- [server/routers/sessions.py:432-454](server/routers/sessions.py#L432-L454) — `POST /{id}/compact` 手动压缩端点
- [server/services/agent_service.py:499-530](server/services/agent_service.py#L499-L530) — `compact_session_async` 后台压缩
- **缺失**: 自动触发逻辑、渐进式压缩层级、压缩后恢复

### 实施策略

我们不需要一步到位实现全部四层。建议分两个阶段：

#### 阶段 A: 自动触发 + 简单压缩 (Batch P0-2a)

**Step 1: Token 监控**

在 [agent/core.py:765](agent/core.py#L765) ReAct 主循环中添加 token 检查：

```python
for step in range(1, task.max_steps + 1):
    # 每个 step 结束后检查 token 用量
    if token_budget.used > token_budget.total * 0.8:  # 80% 阈值
        logger.warning("Token budget at %.0f%% — triggering auto-compact",
                       token_budget.used / token_budget.total * 100)
        _should_compact = True
        break
```

**Step 2: 自动压缩触发**

在 `_run_body` 的 finish 逻辑之前，检查是否需要压缩：

```python
if _should_compact:
    from server.services.agent_service import compact_session
    compact_result = compact_session(session_id)
    # 将压缩摘要注入对话历史
    history.add(LLMMessage(role="user", content=(
        f"[AUTOCOMPACT] Previous conversation has been summarized. "
        f"Continue from this summary:\n\n{compact_result}"
    )))
    continue  # 继续 agent 循环
```

**Step 3: 压缩后恢复关键上下文**

在 [agent/core.py](agent/core.py) 中添加恢复逻辑：

```python
def _reinject_after_compact(history, task):
    """After compaction, re-inject essential context."""
    # 1. 重新注入 CLAUDE.md
    claude_md = _read_claude_md(task.repo_path)
    if claude_md:
        history.add(LLMMessage(role="user", content=claude_md))
    # 2. 重新注入最近修改的文件 (最多 5 个)
    recent_files = _get_recently_modified_files(task.repo_path, limit=5)
    for f in recent_files:
        content = _read_file_safe(f, max_lines=100)
        if content:
            history.add(LLMMessage(role="user", content=f"[FILE RESTORE] {f}:\n{content}"))
```

#### 阶段 B: 渐进式压缩 (Batch P0-2b, 后续)

| 子任务 | 说明 |
|--------|------|
| Snip | 过滤空结果轮次 — 简单 `list.remove()` |
| MicroCompact | 清理旧工具输出 (替换为 `[Old output cleared]`) |
| Context Collapse | 创建 `projectView()` 虚拟视图 |
| Session Memory | 后台维护可复用的会话笔记 |

### 行为准则

1. **自动触发阈值**: token > 80% context window → 触发压缩
2. **压缩不丢失关键信息**: 恢复 CLAUDE.md、最近文件、活跃技能
3. **电路断路器**: 连续 3 次压缩失败 → 禁用自动压缩，转为警告
4. **手动压缩优先**: 如果用户已手动 `/compact`，重置自动压缩计数器
5. **压缩后提示**: 注入简短的系统消息告知用户压缩已发生

### 涉及文件

| 文件 | 改动 |
|------|------|
| `agent/core.py` | Token 监控 + 自动触发 + 恢复逻辑 |
| `server/services/agent_service.py` | `compact_session_async` 增强 |
| `agent/completion_guard.py` | 可能添加压缩后的完成条件调整 |

---

## P0-3: Skills 系统

### 目标

支持可复用的 Skills 系统：模型根据任务描述自动匹配并调用 Skill，Skill 内容渐进式加载。

### CC 的实现方式

CC 的 Skills 系统使用**三层渐进式加载**：

| 阶段 | 内容 | Token 成本 | 加载时机 |
|------|------|-----------|----------|
| **Discovery** | `name` + `description` from YAML frontmatter | ~30-50 tokens/skill | 启动时始终加载 |
| **Activation** | 完整 `SKILL.md` 正文 | < 2000 tokens | 当 skill 描述匹配当前任务时 |
| **Execution** | 捆绑资源 (`references/`, `scripts/`) | 按需 | 仅当工作流需要时 |

**SKILL.md 结构:**
```
my-skill/
├── SKILL.md           # 主指令 (必需)
│   # frontmatter: name, description, when_to_use, allowed-tools,
│   #   context (fork/inline), model, effort, paths, ...
├── reference.md       # 详细参考 (按需加载)
├── examples/
│   └── sample.md
└── scripts/
    └── validate.sh
```

**触发方式:**
1. **自动**: 模型根据 `description` 语义匹配
2. **手动**: 用户输入 `/<skill-name>`
3. **条件激活**: 通过 `paths` glob 匹配，仅当操作匹配文件时激活

**执行方式:**
- **Inline**: 注入到主对话流
- **Fork** (`context: fork`): 在隔离子代理中运行

> **来源:** [Claude Code Skills docs](https://code.claude.com/docs/en/skills), [Anthropic engineering blog](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills), [Skywork ultimate guide](https://skywork.ai/blog/ai-bot/claude-code-skills-ultimate-guide-3/), [Steve Kinney analysis](https://stevekinney.com/writing/agent-skills)

### 我们的现状

- [server/routers/sessions.py](server/routers/sessions.py) — 无 Skill 相关端点
- [entry/bootstrap/registry_factory.py:105-120](entry/bootstrap/registry_factory.py#L105-L120) — 已有 `SkillRegistry` 和 `SkillTool` 的引用代码，但可能未完整实现
- [web/src/components/ChatView.tsx:43-48](web/src/components/ChatView.tsx#L43-L48) — `SLASH_COMMANDS` 列表定义了前端 slash 命令，但未接入后端

### 实施步骤

**Step 1: Skill 文件结构 + 加载器**

创建 `skills/` 模块:

```python
# skills/loader.py
class SkillLoader:
    """Load SKILL.md files from .forge-agent/skills/ and ~/.forge-agent/skills/"""

    def load_all(self, project_root: str) -> list[Skill]:
        """返回所有已安装的 skill 元数据 (name + description only)"""
        skills = []
        for skills_dir in [
            Path.home() / ".forge-agent" / "skills",
            Path(project_root) / ".forge-agent" / "skills",
        ]:
            if skills_dir.exists():
                for skill_dir in skills_dir.iterdir():
                    if skill_dir.is_dir():
                        skill_md = skill_dir / "SKILL.md"
                        if skill_md.exists():
                            skills.append(self._parse_skill(skill_md))
        return skills

    def _parse_skill(self, path: Path) -> Skill:
        """Parse YAML frontmatter + markdown body"""
        content = path.read_text(encoding="utf-8")
        frontmatter, body = _split_frontmatter(content)
        return Skill(
            name=frontmatter.get("name", path.parent.name),
            description=frontmatter.get("description", ""),
            body=body,
            allowed_tools=frontmatter.get("allowed-tools", []),
            context=frontmatter.get("context", "inline"),
            model=frontmatter.get("model"),
        )
```

**Step 2: Discovery — 注入到 System Prompt**

在 [agent/core.py](agent/core.py) 系统消息构建处，添加上下文:

```python
# 在 system prompt 末尾添加 skill 目录 (仅 name + description)
skills = skill_loader.load_all(task.repo_path)
if skills:
    skill_list = "\n".join(
        f"- `/{s.name}`: {s.description[:200]}"
        for s in skills
    )
    system_prompt += (
        f"\n\n## Available Skills\n"
        f"When a task matches a skill's description, "
        f"use the `Skill` tool to invoke it.\n\n{skill_list}"
    )
```

**Step 3: SkillTool — 模型调用入口**

创建 [tools/skill_tool.py](tools/skill_tool.py):

```python
class SkillTool(BaseTool):
    name = "Skill"
    description = "Invoke a skill to get specialized instructions for a task."

    parameters_schema = {
        "type": "object",
        "properties": {
            "skill": {"type": "string", "description": "Skill name to invoke"},
            "args": {"type": "string", "description": "Optional arguments for the skill"},
        },
        "required": ["skill"],
    }

    def execute(self, params):
        skill_name = params["skill"]
        skill = self._registry.get(skill_name)
        if skill is None:
            return ToolResult(success=False, error=f"Unknown skill: {skill_name}")
        # 注入完整 SKILL.md 正文到对话
        return ToolResult(
            success=True,
            output=skill.body,
            metadata={"skill_name": skill_name, "context": skill.context},
        )
```

**Step 4: 注册 Skill 工具**

在 [entry/bootstrap/registry_factory.py:105-120](entry/bootstrap/registry_factory.py#L105-L120) 中完成 SkillTool 注册（已有 SkillRegistry 引用，补充完整）。

**Step 5: 前端 Slash 命令接入**

[web/src/components/ChatView.tsx:43-48](web/src/components/ChatView.tsx#L43-L48) 的 `SLASH_COMMANDS` 改为从后端 API 动态加载:

```typescript
// web/src/api/config.ts (已存在)
export async function listSkills(): Promise<Skill[]> {
    const r = await fetch("/api/skills");
    return r.json();
}
```

### 行为准则

1. **渐进式加载**: 启动时仅注入 name + description (~30-50 tokens/skill)
2. **语义匹配**: 模型自主决定何时调用 Skill（基于 description 匹配）
3. **按需加载正文**: 仅当 Skill 被调用时才注入完整 SKILL.md
4. **条件激活**: 支持 `paths` glob 条件激活（skill 仅在匹配文件时可见）
5. **Skill 热重载**: 文件变更后自动检测（可选 file watcher）
6. **上下文隔离**: `context: fork` 的 skill 在子代理中运行，不污染主对话

### 涉及文件

| 文件 | 改动 |
|------|------|
| `skills/loader.py` | **NEW** — Skill 文件加载 + frontmatter 解析 |
| `skills/registry.py` | 可能已有 — 验证并补充 |
| `tools/skill_tool.py` | **NEW** 或补充 — `SkillTool` 实现 |
| `entry/bootstrap/registry_factory.py` | 注册 SkillTool |
| `agent/core.py` | System prompt 注入 skill 目录 |
| `server/routers/skills.py` | **NEW** — `GET /api/skills` 端点 |
| `web/src/components/ChatView.tsx` | Slash 命令动态加载 |

---

## P0-4: 文件附件 (@mentions)

### 目标

支持 `@file_path` 语法将文件内容注入上下文，支持拖拽图片和剪贴板粘贴。

### CC 的实现方式

CC 的 `@mention` 系统是上下文注入的主要机制：

- 输入 `@path/to/file` → 预处理管线提取路径 → 并行读取文件内容 → 注入为 `AttachmentMessage`
- 支持文件、目录（列出）、glob 模式、MCP 资源、子代理
- 图片通过拖拽/粘贴 → 预处理 `maybeResizeAndDownsampleImageBlock()` → metadata 收集
- IDE 扩展自动注入当前文件和选区

预处理管线分 6 个阶段，其中:
- **Stage 3 (Input Processing)**: 提取 `@` 路径、MCP 引用、IDE 选区
- **Stage 5 (Attachment Injection)**: ~25 种附件类型并行计算，1 秒超时

> **来源:** [Claude Code preprocessing pipeline](https://augustinchan.dev/posts/2026-04-04-claude-code-preprocessing-pipeline), [@mentions guide](https://dev.to/rajeshroyal/-mentions-the-2-character-shortcut-that-10x-your-ai-coding-speed-3jej), [Context Assembly Chapter 10](https://openedclaude.github.io/claude-reviews-claude/chapters/10-context-assembly)

### 我们的现状

- [web/src/components/ChatView.tsx:32-41](web/src/components/ChatView.tsx#L32-L41) — `PROJECT_FILE_SUGGESTIONS` 静态文件建议列表
- [web/src/components/SlashMenu.tsx](web/src/components/SlashMenu.tsx) — Slash 菜单组件
- **缺失**: 后端附件解析、前端 `@` 触发自动补全、图片支持

### 实施步骤

**Step 1: 后端 — 附件解析端点**

新增 `POST /api/attachments/resolve`:

```python
# server/routers/attachments.py (已存在文件，补充)
@router.post("/api/attachments/resolve")
async def resolve_attachment(body: AttachmentResolveBody, service=Depends(get_service)):
    """解析 @mention 引用为文件内容"""
    path = body.path
    repo = service.repo_path
    full_path = Path(repo) / path

    # 安全检查: 路径必须在 repo 内
    if not str(full_path.resolve()).startswith(str(Path(repo).resolve())):
        raise HTTPException(status_code=403, detail="Path outside repository")

    if full_path.is_file():
        content = full_path.read_text(encoding="utf-8")
        return {
            "type": "file",
            "path": path,
            "content": content[:10000],  # 限制 10K 字符
            "lines": content.count("\n") + 1,
        }
    elif full_path.is_dir():
        files = [str(p.relative_to(full_path)) for p in full_path.iterdir() if not p.name.startswith(".")]
        return {"type": "directory", "path": path, "files": files[:50]}
    else:
        # 尝试 glob 匹配
        matches = list(Path(repo).glob(path))
        if matches:
            return {"type": "glob", "path": path, "matches": [str(m.relative_to(repo)) for m in matches[:20]]}
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
```

**Step 2: 后端 — 附件注入到对话上下文**

在 [server/services/agent_service.py:_run_and_notify](server/services/agent_service.py#L444) 中，处理附件列表:

```python
def _run_and_notify():
    # 解析附件 (从 prompt 中提取 @mentions)
    attachments = _extract_attachments(prompt)
    attachment_context = ""
    for att in attachments:
        resolved = _resolve_attachment(att, self.repo_path)
        if resolved:
            attachment_context += f"\n[FILE: {att}]\n{resolved}\n[/FILE]\n"

    if attachment_context:
        prompt = attachment_context + "\n" + prompt
    ...
```

**Step 3: 后端 — `_extract_attachments` 工具函数**

```python
import re

_ATTACHMENT_RE = re.compile(r"@(\S+)")

def _extract_attachments(prompt: str) -> list[str]:
    """从用户输入中提取 @file_path 引用"""
    return [m.group(1) for m in _ATTACHMENT_RE.finditer(prompt)]
```

**Step 4: 前端 — `@` 触发自动补全**

在 [web/src/components/ChatView.tsx](web/src/components/ChatView.tsx) composer textarea 中添加 `@` 监听:

```tsx
const [showSuggestions, setShowSuggestions] = useState(false);
const [suggestionQuery, setSuggestionQuery] = useState("");

function handleInput(value: string) {
    const lastAt = value.lastIndexOf("@");
    if (lastAt >= 0 && (lastAt === 0 || value[lastAt - 1] === " ")) {
        setSuggestionQuery(value.slice(lastAt + 1));
        setShowSuggestions(true);
    } else {
        setShowSuggestions(false);
    }
}

// 已有 PROJECT_FILE_SUGGESTIONS (line 32-41) 可复用
// 另加 API 调用 /api/files?query=... 动态搜索
```

**Step 5: 前端 — SlashMenu 扩展**

已有的 [web/src/components/SlashMenu.tsx](web/src/components/SlashMenu.tsx) 扩展支持 `@`:

- `@file.ts` → 文件内容预览
- `@dir/` → 目录列表
- `@*.py` → glob 匹配结果

**Step 6: 后端 — 图片支持 (后续)**

```python
# 需要前端先将图片转为 base64/URL，后端存入临时目录
# 在 system prompt 中添加图片 URL (如果模型支持多模态)
```

### 行为准则

1. **路径安全**: 所有 `@path` 必须在 repo 根目录内
2. **内容限制**: 单文件最多注入 10,000 字符（大文件分段）
3. **并行解析**: 多个 `@mention` 并行读取
4. **不覆盖 prompt**: 附件作为附加上下文注入，不替代用户消息
5. **前端预览**: 用户可以看到即将注入的文件内容（展开/折叠）
6. **敏感文件保护**: `.git/`、`.forge-agent/settings.json` 等不可通过 `@mention` 访问

### 涉及文件

| 文件 | 改动 |
|------|------|
| `server/routers/attachments.py` | 补充 `POST /api/attachments/resolve` |
| `server/services/agent_service.py` | `_extract_attachments` + 上下文注入 |
| `web/src/components/ChatView.tsx` | `@` 触发自动补全 |
| `web/src/components/SlashMenu.tsx` | 扩展支持 `@` 文件引用 |
| `web/src/api/config.ts` 或新文件 | `resolveAttachment()` API 调用 |

---

## 实施顺序建议

```
Batch P0-1a: 模型切换 — 后端 API + backend 重建逻辑
Batch P0-1b: 模型切换 — 前端选择器 UI

Batch P0-4a: 文件附件 — 后端解析端点 + @mention 提取
Batch P0-4b: 文件附件 — 前端自动补全 + SlashMenu 扩展

Batch P0-3a: Skills — SkillLoader + Skill 解析
Batch P0-3b: Skills — SkillTool + System Prompt 注入
Batch P0-3c: Skills — 前端 Slash 命令动态加载

Batch P0-2a: 上下文压缩 — Token 监控 + 自动触发
Batch P0-2b: 上下文压缩 — 恢复逻辑 (CLAUDE.md + 最近文件)
Batch P0-2c: 上下文压缩 — 渐进式 (Snip → MicroCompact → Collapse)
```

每批 ≤5 个文件，commit 后全局反思。

---

## 参考来源汇总

- [Claude Code official docs — settings](https://code.claude.com/docs/en/settings)
- [Claude Code official docs — permission modes](https://code.claude.com/docs/en/permission-modes)
- [Claude Code official docs — commands](https://code.claude.com/docs/en/commands)
- [Claude Code official docs — skills](https://code.claude.com/docs/en/skills)
- [Claude Code official docs — context window](https://code.claude.com/docs/en/context-window)
- [Claude Code official docs — how Claude Code works](https://code.claude.com/docs/en/how-claude-code-works)
- [Claude Code model configuration](https://support.claude.com/en/articles/11940350-claude-code-model-configuration)
- [Claude Code model router (GoldVelen)](https://github.com/GoldVelen/claude-model-router)
- [Claude Code source analysis — context window](https://github.com/wuwangzhang1216/claude-code-source-all-in-one/blob/main/claude-code-deep-analysis/07-context-window.en.md)
- [Claude Code source analysis — permission system](https://github.com/wuwangzhang1216/claude-code-source-all-in-one/blob/main/claude-code-deep-analysis/05-permission-system.en.md)
- [Claude Code preprocessing pipeline](https://augustinchan.dev/posts/2026-04-04-claude-code-preprocessing-pipeline)
- [Claude Code context assembly (Chapter 10)](https://openedclaude.github.io/claude-reviews-claude/chapters/10-context-assembly)
- [Anthropic Agent Skills engineering blog](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Skywork Skills ultimate guide](https://skywork.ai/blog/ai-bot/claude-code-skills-ultimate-guide-3/)
- [Steve Kinney Skills analysis](https://stevekinney.com/writing/agent-skills)
- [Tencent Cloud — AutoCompact analysis](https://cloud.tencent.com.cn/developer/article/2653153)
- [CSDN — Context compression pipeline](https://blog.csdn.net/monsion/article/details/159698713)
- [GitHub issue #17772 — Programmatic model switching](https://github.com/anthropics/claude-code/issues/17772)
- [GitHub issue #44976 — Auto model routing](https://github.com/anthropics/claude-code/issues/44976)
- [GitHub issue #25410 — Per-prompt model override](https://github.com/anthropics/claude-code/issues/25410)

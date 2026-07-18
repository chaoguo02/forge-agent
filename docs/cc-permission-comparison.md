# Claude Code vs Forge Agent — 权限系统完整对比

> 基于 2026-07-18 代码审计 + Claude Code 逆向工程研究

---

## 一、我们的实现：完整链路追踪

### 架构总览：双线程模型

```
主线程 (asyncio event loop)              后台线程 (daemon thread)
  HTTP handlers 运行于此                    Agent (ReActAgent) 运行于此
  EventBus drain task 运行于此              PermissionPipeline.check() 阻塞于此
  WebSocket I/O 发生于此                    工具执行发生于此
```

### 完整审批流程（11 个阶段）

#### Stage 0: 订阅建立

| 步骤 | 文件 | 行号 | 说明 |
|------|------|------|------|
| WebSocket 连接 | `web/src/stores/chatStore.ts:connectWs()` | 234-268 | 浏览器打开 `wss://host/api/ws/sessions/{id}` |
| 用户发送消息 | `web/src/stores/chatStore.ts:sendChat()` | 195-208 | POST `/api/sessions/{id}/messages` |
| HTTP 处理器 | `server/routers/sessions.py:create_message()` | 287-355 | 返回 202，启动后台线程 |

#### Stage 1: 后台线程初始化

| 步骤 | 文件 | 行号 | 说明 |
|------|------|------|------|
| 构建 Web 回调 | `server/services/agent_service.py:_build_web_confirm_callback()` | 254-312 | 创建 ApprovalBroker + 闭包 |
| 存储回调 | `agent/session/runtime.py:set_web_confirm_callback()` | 1747-1755 | `_web_confirm_callbacks[sid] = callback` |
| 启动 daemon 线程 | `server/services/agent_service.py:_run_and_notify()` | 481-483 | `threading.Thread(target=..., daemon=True)` |
| 注入到 Pipeline | `agent/session/runtime.py:run_session()` | 637-654 | pop callback + rules + mode |

#### Stage 2: ReAct 主循环

| 步骤 | 文件 | 行号 | 说明 |
|------|------|------|------|
| Agent 主循环 | `agent/core.py:_run_body()` | 765 | `for step in range(1, max_steps+1):` |
| LLM 调用 | `agent/core.py` | 955-1064 | 流式/非流式 |
| 工具分发 | `agent/core.py` | 1475-1765 | TOOL_CALL → execute_tool |

#### Stage 3: 权限门控

| 步骤 | 文件 | 行号 | 说明 |
|------|------|------|------|
| 权限检查入口 | `core/base.py:execute_tool()` | 589-603 | `pipeline.check(tool, params, thought)` |
| 工具执行 | `core/base.py` | 624-625 | `tool.execute(actual_params)` |

#### Stage 4: 六层权限管线

##### Layer 1: validateInput — 绝对安全底线

**文件:** `hitl/pipeline.py:472-484`

- 调用 `tool.permission_denial_reason(params)`
- 返回 DENY 时不可覆盖
- **线程:** 后台线程，同步，非阻塞

##### Layer 2: PreToolUse Hooks

**文件:** `hitl/pipeline.py:487-526`

- 三种结果: `BLOCK→DENY`, `APPROVE→ALLOW`, `CONTINUE→pass`
- 可修改 input (stash 在 `_pending_hook_updates`)
- **线程:** 后台线程

##### Layer 3: Permission Rules

**文件:** `hitl/pipeline.py:530-567`

优先级: `deny > session_allow > allow > ask`

- `DENY` → 短路拒绝，计入熔断计数
- `ALLOW` → 短路通过（规则或 session 规则）
- `ASK` → **直接跳到 Layer 6**，传 `force_interactive=True`
- `None` → 继续到 Layer 4

##### PermissionRule.matches()

**文件:** `hitl/permission_rule.py:78-91`

1. 比较 `self.tool_name` 与 `tool_name.lower()`
2. 检查别名映射 (`bash→shell`)
3. 提取匹配目标: `_extract_match_target()` → glob 匹配
4. Glob 语法: 尾部 ` *` = 前缀匹配, 中间 `*` = 单 token, 无 `*` = 精确匹配

##### Layer 4: Permission Mode

**文件:** `hitl/pipeline.py:590-684`

| 模式 | 行为 |
|------|------|
| `bypassPermissions` | 全部 ALLOW（除了 `rm -rf /` / `rm -rf ~`） |
| `acceptEdits` | Write/Edit + mkdir/touch/mv/cp 自动通过 |
| `plan` | Write/Edit/Bash 全部 DENY |
| `dontAsk` | 只读工具 ALLOW，其余 DENY（不到 Layer 6） |
| `default`/空 | 返回 None → Layer 5 → Layer 6 |

##### Layer 4.5: Prompt-based Permissions

**文件:** `hitl/pipeline.py:708-731`

- CC ExitPlanMode 模式
- Token 化模糊匹配

##### Layer 5: Path Sandbox

**文件:** `hitl/pipeline.py:837-862`

- 仅当 `path_access=WRITE` 且设置了 `project_root` 时生效
- 检查目标路径在项目根目录内

##### Layer 6: Interactive Callback — 阻塞点

**文件:** `hitl/pipeline.py:735-788`

```
Path A: approval_mode=AUTO + force_interactive=False → ALLOW (不阻塞)
Path B: Web callback → _web_confirm_callback(request) → BLOCKS
Path C: TTY callback → 阻塞 stdin
Path D: 无 callback → DENY (fail closed)
```

`_apply_decision()` (lines 789-833):
- `ALWAYS_ALLOW`: 持久化规则到 `settings.json`
- `ALLOW_ONCE`: 仅本次通过
- `DENY`: 拒绝

#### Stage 5: ApprovalBroker — 同步阻塞

**文件:** `server/services/approval_broker.py:85-149`

```python
req_id = uuid.uuid4().hex[:12]           # 生成 12 位请求 ID
self._pending[req_id] = pending           # 存储待审批
on_pending(req_id)                        # 推送 WS 事件
signaled = pending.event.wait(timeout=60) # ← 阻塞于此 (threading.Event)
return pending.decision                   # 返回决策
```

WS 事件推送路径:
- `push_event()` → `EventBus.publish_raw()` → `SessionSubscriber.publish()` → `loop.call_soon_threadsafe()` → `_drain()` → `ws.send_json()`

#### Stage 6: 用户点击 Allow

**文件:** `web/src/components/ToolApprovalCard.tsx:84`

→ `chatStore.resolveToolApproval()` → `fetch(POST /api/sessions/{id}/tool-approve)` → **乐观移除卡片**

#### Stage 7: HTTP 处理器唤醒后台线程

**文件:** `server/routers/sessions.py:543-569`

```python
broker = service._runtime.get_approval_broker(session_id)
decision = PromptDecision(action=ALLOW_ONCE, ...)
broker.resolve(body.request_id, decision)  # → Event.set()
```

**文件:** `server/services/approval_broker.py:153-169`

```python
pending.decision = decision
pending.event.set()  # ← 唤醒后台线程
```

#### Stage 8: 后台线程恢复 → 工具执行

1. `wait_for_decision()` 返回 `PromptDecision`
2. `_layer6_callback()` → `_apply_decision()` → `PermissionResult(ALLOW)`
3. `pipeline.check()` 返回 ALLOW
4. `ToolRegistry.execute_tool()` 执行 `tool.execute(params)`
5. 工具执行（如 `FileEditTool.execute()` → Read-before-Edit 检查 → 写文件）
6. 结果记录到 EventLog → WS 事件推送到前端

#### Stage 9: 完成守卫

**文件:** `agent/completion_guard.py:162-242`

- EDIT 意图 + git repo: 验证 `git.diff(baseline)` 有实际变更
- 3-strike 限制: 同一原因连续阻塞 3 次 → force GIVE_UP
- 验证 agent 文件出现在 git diff 中

---

## 二、Claude Code 的真实实现

> 以下内容来自 Claude Code 官方文档、社区逆向工程分析（source map）、GitHub issues。

### 2.1 核心架构

#### 关键源码文件（社区从 source map 逆向）

| 文件 | 功能 | 大小 |
|------|------|------|
| `src/utils/permissions/permissions.ts` | 核心管线 `hasPermissionsToUseToolInner()` | ~1486 行 |
| `src/utils/permissions/denialTracking.ts` | 拒绝熔断追踪 | — |
| `src/utils/shellRuleMatching.ts` | Shell 规则匹配 | — |
| `src/utils/permissions/dangerousPatterns.ts` | 危险模式检查 | ~80 行 |
| `src/utils/permissions/yoloClassifier.ts` | Auto 模式分类器 | ~1495 行 |

> **来源:** `@anthropic-ai/claude-code` npm 包中的 57MB `cli.js.map` 文件被安全研究员 Chaofan Shou 于 2026-03-31 披露
> - [GitHub: wuwangzhang1216/claude-code-source-all-in-one](https://github.com/wuwangzhang1216/claude-code-source-all-in-one/blob/main/claude-code-deep-analysis/05-permission-system.en.md)
> - [openedclaude.github.io Chapter 7](https://openedclaude.github.io/claude-reviews-claude/chapters/07-permission-pipeline)

### 2.2 决策管线: `hasPermissionsToUseToolInner()`

**Phase 1 — 硬安全门 (bypass 免疫):**

| 步骤 | 检查 | 可否覆盖 |
|------|------|----------|
| 0 | Abort 信号检查 | 否 |
| 1a | 工具级 deny 规则 (8 个来源全部检查) | **否 — deny 永远优先** |
| 1b | 工具级 ask 规则 (如 `"alwaysAsk": ["Bash"]`) | 否 |
| 1c | `tool.checkPermissions()` — 工具自身的内容感知逻辑 | N/A |
| 1d | 工具自身返回 `deny` | 否 |
| 1e | `requiresUserInteraction()` | 否 |
| 1f | 内容特定 ask 规则 (如 `Bash(npm publish:*)`) | 否 |
| 1g | 内置安全检查: `.git/`, `.claude/`, `.vscode/`, shell 配置文件 | **否 — 连 `--dangerously-skip-permissions` 也无法覆盖** |

**Phase 2 — 模式和 Allow 规则快速路径:**

| 步骤 | 检查 |
|------|------|
| 2a | `bypassPermissions` 模式 → `allow` (type: `mode`) |
| 2b | 工具级 allow 规则 → `allow` (type: `rule`) |

**Phase 3 — 默认回退:**

| 步骤 | 检查 |
|------|------|
| 3 | `passthrough` → `ask` — 默认提示用户 |

> **来源:** [wuwangzhang1216 deep analysis](https://github.com/wuwangzhang1216/claude-code-source-all-in-one/blob/main/claude-code-deep-analysis/05-permission-system.en.md) (社区逆向)

### 2.3 Headless 模式协议: NDJSON over stdio

**启动命令:**
```bash
claude --print --output-format stream-json --input-format stream-json \
       --verbose --permission-prompt-tool stdio
```

**`control_request` (Agent → Host):**
```json
{
  "type": "control_request",
  "request_id": "req_abc123",
  "request": {
    "subtype": "can_use_tool",
    "tool_name": "Bash",
    "input": { "command": "git add -A", "description": "Stage all changes" },
    "decision_reason": "Command not in allowlist",
    "tool_use_id": "toolu_xyz"
  }
}
```

**`control_response` (Host → Agent) — Allow:**
```json
{
  "type": "control_response",
  "response": {
    "subtype": "success",
    "request_id": "req_abc123",
    "response": {
      "behavior": "allow",
      "updatedInput": { "command": "git add -A", "description": "Stage all changes" },
      "updatedPermissions": []
    }
  }
}
```

**`control_response` (Host → Agent) — Deny:**
```json
{
  "type": "control_response",
  "response": {
    "subtype": "success",
    "request_id": "req_abc123",
    "response": {
      "behavior": "deny",
      "message": "User denied this action"
    }
  }
}
```

> **来源:** [Runloop AI docs — Claude Code SDK Protocol Specification](https://docs.runloop.ai/docs/axons/broker/claude-protocol) (第三方 SDK 文档)
> [DeepWiki: Structured I/O](https://deepwiki.com/farion1231/claude-code/13.2-structured-and-remote-io)

**协议规则:**
1. `request_id` 必须匹配用于关联
2. CLI 阻塞等待响应（默认 ~60s 超时）
3. 多个请求可并发
4. Host 追踪 `tool_use_id` 防止重复执行

### 2.4 六种权限模式

| 模式 | CLI 标签 | 行为 |
|------|----------|------|
| `default` | Manual | 每次文件编辑/shell/网络请求都需要审批 |
| `acceptEdits` | Accept Edits | 自动批准文件编辑 + 常用文件系统命令 (mkdir/touch/rm/rmdir/mv/cp/sed) |
| `plan` | Plan Mode | 只读分析。文件编辑永不自动批准 |
| `bypassPermissions` | Bypass | 跳过所有非 bypass-immune 检查。需要 `--dangerously-skip-permissions` |
| `dontAsk` | Don't Ask | 将所有 `ask` 转为 `deny`。仅匹配 `permissions.allow` 的执行。永不调用 callback |
| `auto` | Auto | 使用独立 LLM 分类器决策（`TRANSCRIPT_CLASSIFIER` feature flag） |

**两种内部模式（社区逆向发现）:**

| 模式 | 用途 |
|------|------|
| `auto` | LLM 分类器自动决策 |
| `bubble` | 子代理权限冒泡到父终端 |

> **来源:** [Official Claude Code docs — permission modes](https://code.claude.com/docs/en/permission-modes) (官方文档)
> [wuwangzhang1216 deep analysis](https://github.com/wuwangzhang1216/claude-code-source-all-in-one/blob/main/claude-code-deep-analysis/05-permission-system.en.md)

**模式切换方式:**
- **会话内:** `Shift+Tab` 循环 `default → acceptEdits → plan`
- **启动时:** `claude --permission-mode acceptEdits`
- **持久化:** `.claude/settings.json` 中设置 `permissions.defaultMode`

### 2.5 Auto 模式 (YOLO Classifier)

CC 的 `auto` 模式使用**独立 LLM 调用**（非主对话模型）:

| 阶段 | 模型 | max_tokens | 说明 |
|------|------|------------|------|
| Stage 1 (Fast) | Sonnet | 64 | 仅输出 yes/no，~80% 情况 |
| Stage 2 (Deep) | Sonnet | 4096 | Chain-of-thought，可覆盖 Stage 1 的 block |

关键设计:
- 助手的文本回复**排除**在分类器转录之外（被视为对抗内容）
- CLAUDE.md 内容注入到 `<user_claude_md>` 标签
- 每 5 轮注入行为提示

> **来源:** [Tencent Cloud developer article](https://cloud.tencent.cn/developer/article/2653444) (社区逆向)
> [The Block Beats](https://en.theblockbeats.news/flash/338093) (蚂蚁集团工程师分析)

### 2.6 8 源规则层级

CC 从 8 个来源加载规则（优先级从低到高）:

| 优先级 | 来源 Key | 文件/来源 |
|--------|----------|-----------|
| 1 (最低) | `userSettings` | `~/.claude/settings.json` |
| 2 | `projectSettings` | `.claude/settings.json` |
| 3 | `localSettings` | `.claude/settings.local.json` |
| 4 | `flagSettings` | `--settings` CLI 参数 |
| 5 | `policySettings` | 企业托管配置 |
| 6 | `cliArg` | `--allow` / `--deny` CLI 参数 |
| 7 | `command` | Skill tool `allowedTools` |
| 8 (最高) | `session` | 会话内 "Always allow" |

> **来源:** [wuwangzhang1216 deep analysis](https://github.com/wuwangzhang1216/claude-code-source-all-in-one/blob/main/claude-code-deep-analysis/05-permission-system.en.md)

### 2.7 拒绝熔断 (Denial Tracking)

**文件:** `src/utils/permissions/denialTracking.ts`

| 限制 | 值 | 触发行为 |
|------|-----|----------|
| `maxConsecutive` | 3 | 同一工具连续拒绝 3 次 → 断路器跳闸 |
| `maxTotal` | 20 | 会话内总计 20 次拒绝 → 断路器跳闸 |

断路器跳闸后:
1. 注入消息给 AI: "Your previous tool call was rejected..."
2. 如果分类器不可用: fail-closed (立即拒绝) 或 fail-open (降级为交互式)
3. Headless 模式: 直接终止 agent

> **来源:** [GitHub: claude-code-best permission-model doc](https://github.com/claude-code-best/claude-code/blob/main/docs/safety/permission-model.mdx)

### 2.8 子代理权限继承 (已知 Bug)

CC 官方文档声称:
> "如果父进程使用 bypassPermissions 或 acceptEdits，这将优先且不可覆盖"

**实际情况:** 多个 GitHub issues 确认子代理不继承父权限:

| 不继承的设置 | Issue |
|-------------|-------|
| Tool allow rules (`.claude/settings.json`) | [#37730](https://github.com/anthropics/claude-code/issues/37730) |
| Tool allow rules (`~/.claude/settings.json`) | [#37730](https://github.com/anthropics/claude-code/issues/37730) |
| Permission modes (`bypassPermissions`, `acceptEdits`) | [#37442](https://github.com/anthropics/claude-code/issues/37442), [#57118](https://github.com/anthropics/claude-code/issues/57118) |
| `settings.local.json` permissions | [#67481](https://github.com/anthropics/claude-code/issues/67481) |
| PreToolUse hooks + deny rules | [#27661](https://github.com/anthropics/claude-code/issues/27661) |
| "Allow Always" selections | [#37442](https://github.com/anthropics/claude-code/issues/37442) |
| `--dangerously-skip-permissions` flag | [#37442](https://github.com/anthropics/claude-code/issues/37442) |

**影响:** 用户报告每次 pipeline 运行需要 10-40+ 次手动审批，多代理编排基本不可用。截至 v2.1.198+ 仍未修复。

### 2.9 Always Allow 持久化 (已知 Bug)

多个 GitHub issues 报告 "Always allow" 不持久化:
- 选择后无文件写入: [#16762](https://github.com/anthropics/claude-code/issues/16762), [#11172](https://github.com/anthropics/claude-code/issues/11172)
- 符号链接目录不持久化: [#27720](https://github.com/anthropics/claude-code/issues/27720)
- 精确字符串匹配对复合命令无效
- 目录访问不持久化: [#17507](https://github.com/anthropics/claude-code/issues/17507)

**解决方法:** 手动编辑 settings 文件，语法如下:
```json
{
  "permissions": {
    "allow": ["Bash(git *)", "Read(**/*.ts)", "Edit(src/**)"]
  }
}
```

> **来源:** [Official permissions docs](https://code.claude.com/docs/en/permissions)


---

## 三、差距对比表

### 3.1 权限管线架构

| 维度 | Claude Code | Forge Agent | 差距评估 |
|------|-------------|-------------|----------|
| 管线入口 | `hasPermissionsToUseToolInner()` (~1486 行) | `PermissionPipeline.check()` (~140 行) | 🟡 功能覆盖 80% |
| 硬安全门 (bypass-immune) | 7 步检查 (deny rules, ask rules, tool checkPermissions, requiresUserInteraction, 内置路径保护) | 2 步 (validateInput, deny rules) | 🔴 缺失: `.git/.claude/` 路径保护、`requiresUserInteraction` |
| Hook 位置 | Phase 1 末尾 (可覆盖后续规则) | Layer 2 (正确位置) | ✅ 对齐 |
| Deny 规则 | 8 个来源全部检查，优先级最高 | 从 settings.json 加载，优先级最高 | ✅ 对齐 |
| Allow 规则 | 在 deny 之后、ask 之前 (Phase 2b) | 在 deny 之后、ask 之前 (Layer 3) | ✅ 对齐 (已修复) |
| Ask 规则 | 在 deny 之后 (Phase 1b) | 在 allow 之后 (Layer 3) | 🔴 倒置 — CC 是 deny→ask→allow |
| 默认回退 | `passthrough→ask` | `None→Layer 4→Layer 6` | ✅ 等价 |

> 注: 我们将 ASK 放在 allow 之后是因为 Ask 规则匹配时直接跳 Layer 6 `force_interactive=True`，用户有最终决定权。CC 将 ask 放在 Phase 1 (bypass-immune)，allow 放在 Phase 2 (可被 bypass)。两种设计语义不同但都可达到安全目的。

### 3.2 权限模式

| 模式 | Claude Code | Forge Agent | 差距 |
|------|-------------|-------------|------|
| `default` / Manual | ✅ 每次需要审批 | ✅ `_layer4_permission_mode` 返回 None → Layer 6 弹卡 | ✅ |
| `acceptEdits` | ✅ Write/Edit + mkdir/touch/rm/rmdir/mv/cp/sed | ✅ Write/Edit + mkdir/touch/mv/cp (缺 rm/rmdir/sed) | 🟡 缺失部分安全命令 |
| `plan` | ✅ 只读，Write/Edit/Bash 拒绝 | ✅ 相同行为 | ✅ |
| `bypassPermissions` | ✅ 跳过所有非 bypass-immune 检查，`rm -rf /` 仍提示 | ✅ 相同行为 (含 root/home rm 断路器) | ✅ |
| `dontAsk` | ✅ 将 ask→deny，仅 allow 规则和只读通过 | ✅ 相同行为 | ✅ |
| `auto` (YOLO) | ✅ 独立 LLM 分类器 (两阶段 Sonnet) | ❌ 未实现 | 🔴 重大缺失 |
| `bubble` (internal) | ✅ 子代理冒泡到父终端 | ❌ 未实现 | 🟡 内部模式 — 暂不需要 |

### 3.3 Headless 协议

| 维度 | Claude Code | Forge Agent | 差距 |
|------|-------------|-------------|------|
| 传输协议 | NDJSON over stdio | WebSocket + HTTP | ✅ 等价 (传输不同，模式相同) |
| 请求格式 | `control_request` with `request_id`, `subtype`, `tool_name`, `input`, `decision_reason`, `tool_use_id` | WS `approval_required` with `request_id`, `tool_name`, `params`, `thought` | 🟡 缺少 `decision_reason`、`tool_use_id` |
| 响应格式 (Allow) | `control_response` with `updatedInput` (必填) | HTTP POST with `decision`, `updated_input` (可选) | 🟡 CC 的 `updatedInput` 是必填 (即使不变) |
| 响应格式 (Deny) | `control_response` with `message` (必填) | HTTP POST with `decision: deny`, `note` | ✅ 对齐 |
| 超时 | ~60s | 60s (可配置) | ✅ |
| 并发请求 | ✅ 支持多个并发 | ✅ `toolApprovals: Record<requestId>` | ✅ |
| 去重保护 | Host 追踪 `tool_use_id` | 无 | 🟡 轻量缺失 |
| 客户端库 | `claude-wrap` (npm), `turboclaude-protocol` (Rust) | 无外部客户端库 | 🟡 暂不需要 |

### 3.4 拒绝熔断

| 维度 | Claude Code | Forge Agent | 差距 |
|------|-------------|-------------|------|
| 连续拒绝 | 3 次同一工具 → 跳闸 | 3 次同一工具 → 升级消息 | ✅ |
| 总计拒绝 | 20 次 → 跳闸 | 20 次 → 拒绝并注入消息 | ✅ |
| 跳闸行为 | 注入消息 + fail-closed/fail-open + headless 终止 | 注入消息 + (仅在 check() 中 block) | 🟡 CC headless 直接终止 agent |
| 成功重置 | `recordSuccess()` 重置连续计数 | 无显式重置 | 🟡 工具成功后连续拒绝计数不会重置 |

### 3.5 规则系统

| 维度 | Claude Code | Forge Agent | 差距 |
|------|-------------|-------------|------|
| 来源数量 | 8 (userSettings→session) | 3 (builtin + user/project/local settings) | 🔴 缺少 policySettings、flagSettings、cliArg、command |
| Glob 语法 | `Bash(npm test *)` 前缀匹配，`Edit(src/**)` 递归通配 | `Bash(npm test *)` 前缀匹配，无 `**` | 🟡 缺少 `**` 递归通配 |
| 别名处理 | 内置 aliases | `_TOOL_ALIAS_MAP` (手动映射) | ✅ 功能等价 |
| Always Allow 持久化 | `persistPermissionUpdates()` → settings 文件 | `save_rule_to_settings()` | ✅ |
| 不过滤规则持久化 Bug | 🔴 多个 GitHub issues 确认不工作 | ✅ 待验证 | 🟡 |

### 3.6 子代理继承

| 维度 | Claude Code | Forge Agent | 差距 |
|------|-------------|-------------|------|
| Deny 规则继承 | 文档说继承，实际不工作 (Bug) | ✅ `apply_inherited_state()` | ✅ 我们的实现更可靠 |
| Allow 规则继承 | 文档说继承，实际不工作 (Bug) | ✅ 继承 allow_rules | ✅ |
| Session 规则继承 | 不继承 (Bug) | ✅ 继承 session_rules | ✅ |
| Permission Mode 继承 | bypassPermissions/plan 强制传递 | ✅ `_resolve_child_permission_mode()` | ✅ |

### 3.7 完成守卫

| 维度 | Claude Code | Forge Agent | 差距 |
|------|-------------|-------------|------|
| Git diff 验证 | ✅ workspace revision delta | ✅ `TaskCompletionGuard` + `_refresh_git_state` | ✅ |
| 完成条件可配置 | 未知 | ❌ 硬编码 EDIT/ANALYSIS 判断 | 🟡 缺少外部完成条件注入 |
| 完成阻断重试限制 | 未知 | ✅ 3-strike 同原因 → give_up | ✅ 防御性改进 |

### 3.8 整体评估

| 模块 | 对齐度 | 状态 |
|------|--------|------|
| 6 层管线结构 | 85% | 🟡 缺硬安全门部分检查 |
| 权限模式 | 80% | 🔴 缺 auto/YOLO 模式 |
| Headless 协议 | 90% | 🟡 缺 decision_reason/tool_use_id |
| 拒绝熔断 | 85% | 🟡 缺成功重置 + headless 终止 |
| 规则系统 | 70% | 🔴 缺 5 个规则来源 + ** 递归通配 |
| 子代理继承 | 95% | ✅ 比 CC 当前版本更可靠 |
| 完成守卫 | 90% | 🟡 缺外部条件注入 |


---

## 四、动态运行时设置 — CC 做法与我们的差距

### 4.1 模型切换

| 维度 | Claude Code | Forge Agent | 差距 |
|------|-------------|-------------|------|
| 会话内切换 | `/model` 命令 → 下一轮生效 | ❌ 无 | 🔴 |
| 默认模型 | `ANTHROPIC_MODEL` 环境变量 / `--model` / settings | `config.llm.model` (启动时写死) | 🔴 不支持切换 |
| 上下文保持 | 切换后历史保留，cache 失效 | N/A | 🟡 |

> **来源:** [Claude Code model configuration](https://support.claude.com/en/articles/11940350-claude-code-model-configuration)

### 4.2 思考模式

| 维度 | Claude Code | Forge Agent | 差距 |
|------|-------------|-------------|------|
| 思考可见性 | `Alt+T` 切换显示/隐藏 | ❌ 无 | 🔴 |
| 推理力度 | `/effort [low\|medium\|high\|xhigh\|max]` | ❌ 无 | 🔴 |
| 配置持久化 | `alwaysThinkingEnabled=true` in settings | ❌ 无 | 🔴 |

> **来源:** [Claude Code commands docs](https://code.claude.com/docs/en/commands)

### 4.3 MCP

| 维度 | Claude Code | Forge Agent | 差距 |
|------|-------------|-------------|------|
| 服务器配置 | `~/.claude.json` / `.mcp.json` / `claude mcp add` | ❌ 无 MCP 支持 | 🔴 |
| 工具发现 | 启动时连接，按需加载 schema | N/A | 🔴 |
| requiresUserInteraction | ✅ 始终提示用户，bypass-immune | ❌ | 🔴 |
| 权限模式 | `mcp__<server>__<tool>` 格式 | N/A | 🔴 |
| 热重载 | `/mcp reconnect/enable/disable` | N/A | 🟡 |

> **来源:** [Claude Code MCP docs](https://code.claude.com/docs/en/mcp)

### 4.4 Skills / Slash Commands

| 维度 | Claude Code | Forge Agent | 差距 |
|------|-------------|-------------|------|
| Skills 加载 | 渐进式 (启动时仅 name+description，按需注入 body) | ❌ | 🔴 |
| Skills 调用 | 模型自主语义匹配 → `Skill` tool | ❌ | 🔴 |
| Slash Commands | 用户显式 `/command` 触发 | ❌ 前端有 SLASH_COMMANDS 列表但未接入后端 | 🔴 |
| Hot-reload | ✅ v2.1.0+ skills 自动检测变更 | N/A | 🟡 |
| Runtime 访问 | Skills 有完全 bash 权限 | N/A | 🟡 |

> **来源:** [Claude Code commands docs](https://code.claude.com/docs/en/commands), [GitHub issue #14851](https://github.com/anthropics/claude-code/issues/14851)

### 4.5 上下文压缩

| 维度 | Claude Code | Forge Agent | 差距 |
|------|-------------|-------------|------|
| 四层架构 | Snip → MicroCompact → Context Collapse → AutoCompact | ❌ 有 `/compact` API 但无自动压缩 | 🔴 |
| Cache-aware | ✅ MicroCompact 感知 Anthropic prompt cache | N/A | 🔴 |
| 自动触发 | Token > 80% context window → 自动压缩 | ❌ | 🔴 |
| 手动压缩 | `/compact [focus instructions]` | ✅ `POST /{id}/compact` | ✅ |
| 错误恢复 | prompt_too_long → Collapse drain → Reactive Compact → give_up | ❌ | 🔴 |
| 压缩后恢复 | 重新注入 CLAUDE.md/rules/skills (有上限) | ❌ | 🔴 |

> **来源:** [Claude Code context window docs](https://code.claude.com/docs/en/context-window), [source analysis](https://github.com/wuwangzhang1216/claude-code-source-all-in-one/blob/main/claude-code-deep-analysis/07-context-window.en.md)

### 4.6 文件附件

| 维度 | Claude Code | Forge Agent | 差距 |
|------|-------------|-------------|------|
| @ file mentions | ✅ `@path/to/file.js` → 注入全文 | ❌ 前端有 PROJECT_FILE_SUGGESTIONS 但无附件系统 | 🔴 |
| IDE 自动注入 | ✅ 当前文件 + 选区自动注入 | ❌ | 🔴 |
| 拖拽 | ✅ 拖拽自动插入路径 | ❌ | 🔴 |
| 图片 | ✅ PNG/JPG | ❌ | 🔴 |

> **来源:** [Steve Kinney: Referencing files in Claude Code](https://stevekinney.com/courses/ai-development/referencing-files-in-claude-code)

### 4.7 IDE 集成

| 维度 | Claude Code | Forge Agent | 差距 |
|------|-------------|-------------|------|
| 协议 | MCP over local WebSocket/SSE + JSON-RPC 2.0 | WebSocket (我们的自定义协议) | 🟡 |
| 工具暴露 | 仅 2 个 MCP 工具给模型 | N/A | 不适用 |
| 选区同步 | 实时 `selection_changed` 通知 | ❌ | 🔴 |

> **来源:** [DeepWiki: IDE integration](https://deepwiki.com/ChinaSiro/claude-code-sourcemap/13.1-ide-integration-and-lsp)

### 4.8 Settings Hot-Reload

| 维度 | Claude Code | Forge Agent | 差距 |
|------|-------------|-------------|------|
| 官方声称 | v1.0.90+ "settings 变更立即生效" | ❌ 所有设置启动时加载 | 🔴 |
| 实际情况 | 权限/MCP/Hooks **不可靠** (多个 Bug) | ❌ | 🟡 CC 自己也有问题 |
| 模式切换 | ✅ `Shift+Tab` 立即生效 | ❌ | 🔴 |

> **来源:** [Claude Code settings docs](https://code.claude.com/docs/en/settings), [GitHub issues #6499, #53538, #66765](https://github.com/anthropics/claude-code/issues/6499)


---

## 五、实施指导：优先级排序

### 🔴 P0 — 核心功能缺失 (应尽快实现)

| 序号 | 功能 | CC 实现 | 我们缺什么 | 预计改动 |
|------|------|---------|------------|----------|
| 1 | **模型切换** | `/model` 命令 | 前端无切换 UI，后端 `config.llm.model` 启动时写死 | `agent_service.py` + frontend model selector |
| 2 | **上下文自动压缩** | 四层渐进压缩 | 仅手动 `/compact`，无自动触发 | `agent/core.py` 增加 token 监控 + 自动压缩 |
| 3 | **Skills 系统** | 渐进式加载 + 模型自主调用 | 无 Skills 基础设施 | Skills registry + SkillTool + 前端 |
| 4 | **文件附件 (@mentions)** | `@path/file` + IDE 自动注入 | 前端有建议列表但无附件注入 | 后端附件解析 + 上下文注入 |

### 🟡 P1 — 权限管线增强

| 序号 | 功能 | CC 实现 | 我们缺什么 | 预计改动 |
|------|------|---------|------------|----------|
| 5 | **硬安全门路径保护** | `.git/`, `.claude/`, `.vscode/` 硬编码 | 无 | `hitl/pipeline.py` Layer 1 增加 |
| 6 | **`requiresUserInteraction`** | MCP 工具标记 | 无概念 | ToolMetadata 增加字段 + pipeline 检查 |
| 7 | **`decision_reason` + `tool_use_id`** | 每个 control_request 携带 | 缺少 | `approval_broker.py` + WS 消息格式 |
| 8 | **`**` 递归通配** | `Edit(src/**)` | 仅 `*` (单 segment) | `hitl/permission_rule.py` `_pattern_to_regex` |
| 9 | **拒绝计数重置** | `recordSuccess()` | 无 | `hitl/pipeline.py` `_apply_tool_check` |

### 🟢 P2 — 体验增强

| 序号 | 功能 | CC 实现 | 我们缺什么 | 预计改动 |
|------|------|---------|------------|----------|
| 10 | **思考模式切换** | `/effort` + `Alt+T` | 无 | 前端 toggle + 后端 effort 参数 |
| 11 | **权限模式热切换** | `Shift+Tab` 循环 | 只能在启动时设置 | WS 消息触发 `set_permission_mode()` |
| 12 | **Settings hot-reload** | 部分可用 (有 Bug) | 完全不可 | File watcher + pipeline 更新 |
| 13 | **IDE 选区同步** | 实时 `selection_changed` | 无 | 需要 VS Code 扩展 |
| 14 | **MCP 支持** | 完整 MCP 客户端 | 无 | 独立项目级别的工作 |

### ⚪ P3 — 暂不实现

| 功能 | 原因 |
|------|------|
| `auto` (YOLO) 模式 | 需要独立 LLM 调用基础设施 + 实现复杂 |
| `bubble` 子代理模式 | 我们有自己的继承机制，且 CC 的 bubble 已证实不可靠 |
| 企业策略设置 (policySettings) | 非当前阶段需求 |
| 8 源规则层级 (全部) | 当前 user/project/local 三层已覆盖主要场景 |

### 建议实施顺序

```
Batch 12: 模型切换 (P0-1)
Batch 13: 权限模式热切换 + decision_reason (P1-7 + P2-11)
Batch 14: 硬安全门路径保护 + requiresUserInteraction (P1-5 + P1-6)
Batch 15: ** 递归通配 + 拒绝计数重置 (P1-8 + P1-9)
Batch 16: 文件附件 @mentions (P0-4)
Batch 17: 思考模式切换 (P2-10)
--- 以下需要更长时间的设计 ---
Batch 18+: Skills 系统 (P0-3)
Batch 19+: 上下文自动压缩 (P0-2)
Batch 20+: Settings hot-reload (P2-12)
```

---

## 六、反思

### 我们做得比 CC 好的地方

1. **子代理权限继承**: CC 的继承机制已被多个 GitHub issue 证实在 v2.1.198+ 仍不可靠。我们的 `apply_inherited_state()` + `_resolve_child_permission_mode()` 设计更可靠。

2. **完成守卫的 3-strike 限制**: CC 没有文档化的重试限制机制，我们的 `_block_tracker` 能防止完成检查死循环。

3. **`force_interactive` 机制**: 我们区分了 ASK 规则的 `force_interactive=True` 和普通 Layer 6 的 `approval_mode=auto`，CC 将 ask 放在 Phase 1 (bypass-immune) 达到类似效果但实现更复杂。

4. **双线程 Event 模型**: 我们的 `threading.Event` + `loop.call_soon_threadsafe` 模式比 CC 的 stdin 阻塞更灵活（支持 HTTP API 集成）。

### 我们的关键差距

1. **缺少 Auto/YOLO 模式**: CC 的独立 LLM 分类器是最复杂的权限组件，目前没有等价实现。
2. **缺少动态设置**: 模型切换、Skills、MCP、上下文压缩等核心功能未接入主链路。
3. **规则来源太少**: 仅 3 层 (builtin + project + local) vs CC 的 8 层。
4. **Headless 协议字段不完整**: 缺少 `decision_reason`、`tool_use_id`。

### 下一步建议

先实现 P0 (模型切换 + 上下文压缩 + Skills + 文件附件)，然后补 P1 的权限增强。保持现在"每批 ≤5 文件"的节奏，每批 commit + 全局反思。

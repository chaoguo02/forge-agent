# 上下文压缩与短期记忆 — CC 对齐差距报告

> 调研来源: CC 官方文档 + compaction.mdx 源码分析
> 对比目标: forge-agent context/compaction.py + agent/core.py

---

## 一、参数对比

| 参数 | CC 值 | forge-agent 值 | 差距 |
|------|-------|---------------|------|
| 会话 budget_tokens | 无硬上限 | **160,000** | ✅ 合理 |
| 请求上下文预算 | 200,000 (模型上限) | **70,000** | ❌ 严重偏低 |
| 历史最大消息数 | 无限制 | **40** | ❌ 过低 |
| 触发 compaction 阈值 | 接近模型上限时自动 | 80% × 70K = **56,000 tokens** | ❌ 过早触发 |
| 压缩后重注入预算 | 50,000 tokens | **无** | ❌ 缺失 |
| 恢复文件数 | 5 个, 每个 ≤5K | **无** | ❌ 缺失 |
| Skill 保留预算 | 25,000 tokens | **无** | ❌ 缺失 |
| thrashing 保护 | 无显式 | 3 次上限 + 3 步冷却 | ✅ 额外保护 |
| 最小历史触发 | 无显式 | 6 条 | ✅ 保守 |

### 核心问题：`request_budget_tokens = 70,000`

DeepSeek v4 的上下文窗口是 **128K tokens**。我们的 `request_budget_tokens` 设为 70K，仅用了 55% 的容量。这意味着：

1. Compaction 在 56K tokens 时就触发 → 模型还有 70K+ 的空余容量被浪费
2. 40 条消息上限 → 即使每条消息平均 500 tokens，也仅 20K，远未到 128K
3. 压缩后没有恢复机制 → 关键上下文（已读文件、激活的 Skill）丢失

**应改为**: `request_budget_tokens = 110_000`，`history_max_messages = 200`

---

## 二、压缩策略对比

### CC 的三层体系

| 层 | 名称 | API调用 | 触发条件 | 行为 |
|----|------|--------|---------|------|
| 1 | MicroCompact | 无 | 单工具输出过长 | 清除旧输出内容，保留消息框架 |
| 2 | Session Memory | 无 | 有已提取的会话记忆 | 用已有 Memory 作摘要，零 API 成本 |
| 3 | API Summary | 有 | 手动/自动 fallback | LLM 生成结构化摘要 |

### forge-agent 的现状

**只有一层**：LLM API Summary。无 MicroCompact，无 Session Memory Compact。

```
✅ 已实现: API Summary (结构化摘要: Discoveries/Changes Made/Remaining Work)
❌ 未实现: MicroCompact (单工具输出过长时的轻量清理)
❌ 未实现: Session Memory Compact (用已有 memory 作摘要)
```

---

## 三、压缩后恢复机制对比

### CC 的重注入预算 (50,000 tokens)

压缩后重新注入：
- 最近读取的**5 个文件内容** (每个 ≤5K tokens)
- 激活的 **Skill 指令** (总预算 25K tokens)
- **CLAUDE.md** 内容
- **MCP 工具发现结果**
- **任务锚点** (目标、约束)

### forge-agent 的现状

**无任何恢复机制。** 压缩后模型丢失：
- 已读文件的内容 → 需要重新 Read
- 激活的 Skill 指令 → 需要重新加载
- 工作目录结构认知 → 需要重新 Glob

---

## 四、完整性保护对比

| 保护机制 | CC | forge-agent |
|---------|-----|-------------|
| 工具调用对完整性 | ✅ `adjustIndexToPreserveAPIInvariants()` | ❌ 无 |
| Compact Boundary 标记 | ✅ `SystemCompactBoundaryMessage` + metadata | ⚠️ 部分 (R3 加了 kind 字段) |
| PTL 应急降级 | ✅ Reactive Compact + Truncation Head | ❌ 无 |
| Hook 注入 | ✅ Pre/Post compact hooks | ❌ 无 |
| 保留最近消息 | ✅ `minTokens=10,000` + `minTextBlockMessages=5` | ✅ 第一条 + 最近几条 |

---

## 五、短期记忆对比

| 方面 | CC | forge-agent |
|------|-----|-------------|
| 自动记忆 | MEMORY.md 自动写入 | ⚠️ memory/ 目录有 18 个文件但整合松散 |
| 长期记忆 | CLAUDE.md + auto-memory + /memory | ⚠️ MemoryContext 存在但 agent 消费浅 |
| 跨会话记忆 | Agent-scoped memory (user/project/local) | ✅ AgentDefinition.memory 字段已支持 |
| 记忆注入 | 首次 200 行/25KB 注入 | ✅ _load_agent_memory 支持 |

---

## 六、总结

### ✅ 匹配的地方

1. 基本 API Summary 框架（结构化摘要、增量压缩、thrashing 保护）
2. AgentDefinition.memory 字段支持
3. 记忆内容加载到 agent 提示中

### ❌ 缺少的地方

1. **MicroCompact 层** — 单工具输出过长时的无 API 轻量清理
2. **Session Memory Compact 层** — 用已有记忆作摘要
3. **压缩后恢复机制** — 文件/Skill/CLAUDE.md 重新注入
4. **工具调用对完整性** — 不把配对的 tool_use/tool_result 切开
5. **PTL 应急降级** — 压缩失败时的降级策略
6. **Compact Boundary 标记** — 类型化的边界标记 + metadata
7. **request_budget_tokens 偏低** — 70K 远低于 128K 模型上限

### ⚠️ 走错的地方

1. **`request_budget_tokens = 70,000`** — 仅用 55% 容量，导致过早触发压缩
2. **`history_max_messages = 40`** — 5 轮子代理调用就可能超过
3. **压缩后无恢复** — 模型压缩后丢失关键上下文需要重新读取

### 🔧 修复优先级

| 优先级 | 修改 | 影响 |
|--------|------|------|
| P0 | `request_budget_tokens` 70K→110K, `history_max_messages` 40→200 | 立即减少不必要压缩 |
| P1 | 压缩后恢复：最近文件 + 激活 Skill 重新注入 | 压缩后 agent 可用性 |
| P1 | 工具调用对完整性保护 | 避免压缩破坏 tool_use/tool_result 配对 |
| P2 | MicroCompact 层 | 单工具大输出场景 |
| P2 | Compact Boundary 标记完善 | 类型化 metadata |
| P3 | Session Memory Compact | 零 API 成本压缩 |

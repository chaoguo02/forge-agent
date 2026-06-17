# forge-agent 开发任务清单

> 更新日期：2026-06-17

---

## 当前状态 v1.1

| 能力 | 状态 |
|------|------|
| 核心 ReAct 循环 | ✅ |
| Plan-and-Execute + DAG | ✅ |
| 三层记忆系统 (短/长/向量) + 主动记忆 | ✅ |
| RAG (AST code chunker + fastembed) | ✅ |
| Multi-Agent 协作 (Coordinator + 3 tiers) | ✅ |
| MCP 协议核心 (stdio + 工具代理) | ✅ |
| Web 工具 + SSRF 防护 | ✅ |
| TUI 渲染器 (InlineRenderer) | ✅ |
| 多模型 + 运行时切换 | ✅ |
| Skill 系统 (MVP: 发现/加载/渲染/SkillTool) | ✅ |
| Shell 确认 + Docker 沙箱 | ✅ |
| **HITL 完整系统** | 🟡 部分（仅 Shell confirm） |
| **长上下文工程 + Prompt Caching** | 🟡 部分 |
| **结构化上下文** | 🟡 部分 |

测试：**509 passed**（17 文件，精简后）

---

## 🎯 今日开发计划（2026-06-17）

**核心主题**：HITL（Human-in-the-Loop）+ 长上下文工程 + Prompt Caching

---

### 一、HITL 系统设计

#### 1.1 什么情况下 Agent 应该主动暂停并请求人工确认

**判断标准（分层策略）**：

| 层级 | 场景 | 判断依据 | 当前状态 |
|------|------|---------|---------|
| L0 硬拦截 | 危险命令 (`rm -rf /`, `mkfs`) | 正则黑名单 | ✅ 已有 |
| L1 确认 | 文件写入/删除/Shell 执行 | `needs_confirm()` 函数 | ✅ 已有 |
| L2 语义 | 不可逆操作（发邮件/PR/部署/付费 API） | 工具 metadata `irreversible: true` | ❌ 待实现 |
| L3 自信度 | Agent 不确定该怎么做 | LLM 输出 `[NEED_HUMAN]` 标记 | ❌ 待实现 |
| L4 代价 | 长任务中间检查点（累计步数 > N） | `step_count % checkpoint_interval == 0` | ❌ 待实现 |

**设计决策**：
- L0/L1 同步阻塞（当前已有）
- L2/L3/L4 走异步确认队列（新增）
- 每个确认节点有超时（默认 5min → 自动 deny）

#### 1.2 HITL 中断与恢复机制

**状态持久化**：

```
.forge-agent/hitl/
├── pending/           ← 待确认请求队列
│   └── <request_id>.json
├── decisions/         ← 已做决定（审计用）
│   └── <request_id>.json
└── policies/          ← 用户策略（记住偏好）
    └── policy.yaml
```

**请求状态机**：
```
created → pending → approved / denied / timeout
                 ↘ deferred (用户稍后决定)
```

**恢复机制**：
- Agent 暂停时将当前 step 序列化为 checkpoint
- Checkpoint 包含：`(task_id, step_num, history_snapshot, pending_action)`
- 恢复时从 checkpoint 重建 Agent 状态
- 对于 `timeout` 的请求：默认 deny + 记录审计

#### 1.3 如何设计确认节点不影响异步执行

**方案：Future-based 确认**

```python
class HitlRequest:
    id: str
    action: str          # 待确认的操作描述
    tool_name: str       # 触发工具
    params: dict         # 工具参数
    context: str         # Agent 当时的推理
    urgency: str         # "blocking" | "advisory"
    timeout_s: int       # 超时秒数
    created_at: float

class HitlManager:
    def request_approval(self, req: HitlRequest) -> Awaitable[bool]:
        """非阻塞提交确认请求，返回 Future"""
        
    def get_pending(self) -> list[HitlRequest]:
        """TUI 渲染待确认列表"""
        
    def decide(self, request_id: str, approved: bool, note: str = ""):
        """用户做出决定"""
```

**对异步执行的影响**：
- `urgency: "blocking"` → Agent 等待（当前模式）
- `urgency: "advisory"` → Agent 继续执行，决定异步到达后影响下一步
- Multi-Agent 场景：子 Agent 的确认请求上报给 Coordinator，Coordinator 决定是否升级给用户

#### 1.4 人工反馈如何被 Agent 吸收

**反馈注入机制**：
1. 用户 approve/deny 时可附带 `note` 文本
2. `note` 作为 `system` message 注入下一轮 LLM 对话
3. 格式：`[Human feedback on {tool_name}]: {note}`
4. 长期模式识别：连续 deny 同类操作 → 自动学习为 policy（主动记忆触发）
5. Policy 持久化到 `policies/policy.yaml`，下次自动应用

**反馈影响链**：
```
用户 deny + note "不要修改测试文件"
  → 注入当前对话 history
  → ProactiveMemory 检测到修正模式
  → 保存为 policy: {pattern: "file_write", path_regex: "tests/.*", action: "deny"}
  → 后续自动应用（无需再次确认）
```

#### 1.5 HITL 对系统吞吐量和延迟的影响

| 指标 | 无 HITL | 有 HITL (blocking) | 有 HITL (advisory) |
|------|---------|-------------------|-------------------|
| 单轮延迟 | ~3-8s | +人工等待时间 | ~3-8s（无增加） |
| 吞吐量 | 1x | 0.3x~0.8x | 0.9x~1.0x |
| 中断恢复开销 | 0 | checkpoint 写入 ~10ms | 0 |

**衡量方法**：
- 在 `EventLog` 中记录 `hitl_wait_ms` 字段
- `RunResult` 新增 `hitl_stats: {total_requests, approvals, denials, avg_wait_ms}`
- `/stats` 命令展示 HITL 统计
- 阈值告警：单次等待 > 5min 时提示用户 "任务暂停中"

---

### 二、结构化上下文设计

#### 2.1 当前问题

- system prompt 是一个巨大的字符串拼接，难以管理
- 缺少 "哪些内容是稳定的（可缓存）" vs "哪些是动态的（每轮变化）" 的区分
- token_budget 只做粗粒度截断，不做语义优先级排序

#### 2.2 结构化上下文分层

```
┌─────────────────────────────────────────────────┐
│ Layer 0: System Identity (极稳定, 可缓存)         │
│   - 角色定义、安全约束、输出格式规则              │
│   - 工具使用指南（不变的规则部分）                │
├─────────────────────────────────────────────────┤
│ Layer 1: Project Context (session 级稳定)        │
│   - RepoMap（文件结构 + 符号索引）               │
│   - Skills 列表                                  │
│   - Memory 上下文（相关记忆）                    │
├─────────────────────────────────────────────────┤
│ Layer 2: Task Context (轮次级变化)               │
│   - 当前任务描述                                 │
│   - 对话历史（滑动窗口）                         │
│   - Compaction 摘要                              │
├─────────────────────────────────────────────────┤
│ Layer 3: Ephemeral (单步级, 最短生命周期)         │
│   - 工具返回结果                                 │
│   - 诊断信息                                     │
│   - Skill body（使用后即丢弃）                   │
└─────────────────────────────────────────────────┘
```

**关键设计**：
- Layer 0 + Layer 1 = **Prompt Cache 稳定前缀**
- Layer 2 + Layer 3 = **动态后缀**（每轮重建）
- 预算分配：Layer 0/1 占 30%，Layer 2 占 50%，Layer 3 占 20%

#### 2.3 实现方案

```python
@dataclass
class ContextLayer:
    name: str
    priority: int       # 0 = 最高（system），3 = 最低（ephemeral）
    cacheable: bool     # 是否可进入 prompt cache
    content: str
    max_tokens: int     # 该层最大 token 预算

class StructuredContext:
    layers: list[ContextLayer]
    
    def build_messages(self) -> list[LLMMessage]:
        """按优先级组装 messages，cache 前缀在前"""
        
    def fits_budget(self, total_budget: int) -> bool:
        """检查是否超预算，必要时从 Layer 3 开始裁剪"""
```

---

### 三、Prompt Caching 原理与集成

#### 3.1 各厂商 Prompt Caching 机制

| 厂商 | 机制 | 触发方式 | 缓存粒度 | 价格优惠 |
|------|------|---------|---------|---------|
| **Anthropic** | 显式 `cache_control` | system 消息末尾加 `{"type": "ephemeral"}` breakpoint | 前缀匹配 | 缓存命中: input 价格 10% |
| **OpenAI** | 自动前缀匹配 | 无需显式声明，相同前缀自动命中 | 前缀匹配 (≥1024 tokens) | cached input 50% off |
| **DeepSeek** | 自动前缀匹配 | 无需操作，API 返回 `cached_tokens` | 前缀匹配 (≥64 tokens) | cached input: ¥0.1/M (原价 ¥1/M) |

#### 3.2 当前实现状态

**已有**（`llm/anthropic_backend.py`）：
- Anthropic system prompt 末尾插入 `cache_control` breakpoint
- 但仅在 system 消息层面，未覆盖多轮对话中的稳定前缀

**缺失**：
- OpenAI/DeepSeek 返回的 `cached_tokens` 未解析展示
- 没有"稳定前缀"的概念——每轮 system prompt 可能微调导致 cache miss
- 没有 cache hit rate 统计

#### 3.3 优化方案

**原则**：最大化稳定前缀长度 → 最大化 cache hit rate

1. **System prompt 分层稳定化**：
   - 固定部分（角色/规则/工具定义）放最前面，永不变
   - 动态部分（RepoMap/Memory/Task）放后面
   - → Anthropic cache_control 打在固定/动态分界处

2. **工具定义排序确定化**：
   - 工具列表按 name 字典序固定排列
   - 避免 tool registration order 不同导致 cache miss

3. **Token 用量 + Cache 统计**：
   ```
   [Round 3] 步数: 5 | tokens: 12,340 (cached: 8,200 = 66%) | 耗时: 4.2s
   ```

4. **多模型适配**：
   ```python
   class CacheStats:
       input_tokens: int
       cached_tokens: int        # Anthropic/DeepSeek 返回
       cache_hit_rate: float     # cached / input
       estimated_savings: float  # 金额节省
   ```

---

### 四、实现子任务清单

#### Phase 1: 结构化上下文 (今日)

- [ ] `context/structured.py` — ContextLayer + StructuredContext 类
- [ ] `agent/core.py` — `_build_system_prompt()` 重构为 StructuredContext
- [ ] Layer 0/1 与 Layer 2/3 明确分界
- [ ] 工具定义排序确定化（按 name 字典序）

#### Phase 2: Prompt Caching 增强 (今日)

- [ ] `llm/base.py` — `CacheStats` 数据类 + `LLMResponse` 新增 `cache_stats`
- [ ] `llm/anthropic_backend.py` — cache_control breakpoint 打在分层分界处
- [ ] `llm/openai_backend.py` — 解析 `usage.prompt_tokens_details.cached_tokens`
- [ ] `agent/core.py` — 每轮 RunResult 累计 cache_stats
- [ ] `entry/renderer.py` — 展示 cache hit rate

#### Phase 3: HITL 框架 (明日)

- [ ] `hitl/__init__.py` + `hitl/manager.py` — HitlManager 核心
- [ ] `hitl/request.py` — HitlRequest 数据模型
- [ ] `hitl/policy.py` — 策略引擎（自动 approve/deny 规则）
- [ ] `tools/base.py` — ToolRegistry.execute 接入 HitlManager
- [ ] 工具 metadata 新增 `irreversible` / `needs_approval` 标记
- [ ] `entry/chat.py` — `/approve` `/deny` 命令
- [ ] 反馈注入 + 策略学习（与 ProactiveMemory 联动）

#### Phase 4: HITL 高级 (后续)

- [ ] 状态持久化（checkpoint 序列化/恢复）
- [ ] Multi-Agent 场景下的确认请求上报
- [ ] 超时策略 + 降级执行
- [ ] HITL 统计面板

---

### 五、优先级排序

```
P0 (今日必须):
  ├── 结构化上下文 (ContextLayer + StructuredContext)
  └── Prompt Caching 统计 (CacheStats + 展示)

P1 (今日争取):
  └── 工具排序确定化 + Anthropic cache breakpoint 优化

P2 (明日):
  └── HITL 框架 Phase 3 (HitlManager + Policy)
```

---

## 已完成能力

| 期数 | 主题 | 状态 |
|------|------|------|
| 1 | 基础 ReAct + Tool Call | ✅ |
| 2 | Plan-and-Execute + DAG | ✅ |
| 3 | Memory + 上下文工程 | ✅ |
| 4 | RAG + 代码库理解 | ✅ |
| 5 | Multi-Agent 协作 | ✅ |
| 7 | 异步 + 并行工具 | ✅ |
| 8 | 多模型适配 + 运行时切换 | ✅ |
| 9 | 联网能力 + Web 工具 | ✅ |
| 10 | MCP 协议核心 | ✅ |
| 15 | Skill 系统 (MVP) | ✅ |
| 16 | TUI 界面 + 产品化 | ✅ |

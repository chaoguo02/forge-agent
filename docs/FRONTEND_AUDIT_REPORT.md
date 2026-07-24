# Frontend Audit Report

审计范围：
- `web/src/**`
- 前端 API Client 与页面级容器
- Plan / Review / SubAgent / Chat / Memory / Stats 关键路径
- 前后端交互与 E2E 可验证性

审计结论：
前端已经具备较完整的页面骨架、状态管理和部分 API 封装，但仍存在：
1. 少量裸 `fetch` 直接调用
2. AI 输出渲染不完全统一
3. 长内容截断与溢出处理不一致
4. Plan / Review / SubAgent 的产品化层级不足
5. E2E 验证对“请求真实发出 / 状态真实落库 / Markdown 正确渲染”的覆盖不足

---

## 🔴 P0 — 裸请求未全部收口到统一 Client

### 问题 1：ChatView 直接裸调模型配置接口
- 文件：`web/src/components/ChatView.tsx:194-199`
- 问题级别：P0
- 当前行为：直接使用 `fetch("/api/config/models", ...)`
- 问题说明：绕过统一 `web/src/api/client.ts`，无法统一处理错误、超时、拦截器、测试 mock。
- 复现步骤：
  1. 打开 Chat 页面
  2. 刷新页面
  3. 在 DevTools Network 观察 `/api/config/models` 请求由组件内直接发出
- 风险：
  - 与“所有 API 调用必须走统一 Client 层”冲突
  - 后续无法统一加埋点、重试、认证或错误规范化
- 备注：该请求应迁移到 `web/src/api/*` 下的新方法

### 问题 2：EventSidebar 直接裸调 storage stats
- 文件：`web/src/components/EventSidebar.tsx:64-69`
- 问题级别：P0
- 当前行为：直接 `fetch("/api/storage/stats", { signal })`
- 问题说明：同样绕过统一 Client 层。
- 复现步骤：
  1. 打开 Chat 页面右侧 Trace 面板
  2. 刷新页面
  3. 观察 Network 中 `/api/storage/stats`
- 风险：
  - 测试无法统一 mock
  - 错误处理与其他 API 不一致

### 问题 3：SubagentDetail 直接裸调 worktree action 接口
- 文件：`web/src/components/SubagentDetail.tsx:33-45`
- 问题级别：P0
- 当前行为：直接 `fetch("/api/sessions/.../worktrees/.../{action}", { method: "POST" })`
- 问题说明：绕过 `apiPost` / `api*` client 层，违背统一调用约束。
- 复现步骤：
  1. 打开某个有 subagent worktree 的 session
  2. 点击 Apply / Discard / Retain
  3. 观察 Network，接口为组件内裸调
- 风险：
  - 与统一 Client 层不一致
  - 后续无法集中处理 CSRF / headers / error mapping

---

## 🔴 P0 — Markdown 渲染未对所有 AI 输出字段统一收口

### 问题 4：Plan 视图仅以纯文本方式展示计划主体
- 文件：`web/src/components/PlanView.tsx:121-123`
- 问题级别：P0
- 当前行为：`<pre className="plan-pre">{planFile || planApproval.planText}</pre>`
- 问题说明：计划内容如果包含 markdown、代码块、表格、链接，会被当成纯文本显示。
- 复现步骤：
  1. 生成一个包含 markdown 的 plan
  2. 打开 Plan 视图
  3. 观察计划以纯文本显示，格式丢失
- 风险：
  - Plan 作为核心审批对象，阅读体验差
  - 无法体现结构化计划的层次

### 问题 5：Plan 批准区对 contract 只做截断展示
- 文件：`web/src/components/ChatView.tsx:902-905`
- 问题级别：P0
- 当前行为：只显示 `Goal:`，并对内容做 `slice(0, 120)`
- 问题说明：contract 信息被截断，且未做 markdown / 结构化渲染。
- 复现步骤：
  1. 触发 plan_ready
  2. 查看底部 plan approval 区
  3. 长 goal 或复杂 contract 会被截断
- 风险：
  - 用户无法完整审阅审批对象
  - 与“审批前可见完整 contract”目标不一致

### 问题 6：WsEventBlock 对 plan_ready / status / thought 仍以纯文本 detail 渲染
- 文件：`web/src/components/WsEventBlock.tsx:272-299`
- 问题级别：P0
- 当前行为：多数 detail 直接 `<div className="trace-body-copy">{detail}</div>` 或 `<pre>{detail}</pre>`
- 问题说明：AI 的执行计划、反思、状态摘要如果带 markdown，无法正确渲染。
- 复现步骤：
  1. 运行一个会输出 plan_ready 的 session
  2. 展开对应 trace event
  3. markdown 格式不可识别
- 风险：
  - trace 作为一等审计视图，信息损失严重

### 问题 7：ToolCallCard / ToolApprovalCard 对富文本参数显示不统一
- 文件：
  - `web/src/components/ToolCallCard.tsx:74-95`
  - `web/src/components/ToolApprovalCard.tsx:124-136`
- 问题级别：P1
- 当前行为：以 `pre` / `slice` / 字符串形式展示工具参数和 rationale
- 问题说明：这不是 markdown 问题本身，但属于 AI 输出与交互信息的非统一渲染。
- 复现步骤：
  1. 让模型发起含复杂参数的 tool_call
  2. 查看 ToolCallCard 与 ToolApprovalCard
  3. 长字段被压缩，层次不清晰
- 风险：
  - 复杂参数难以核对
  - 用户无法确认真实执行意图

---

## 🟠 P1 — 内容截断 / 溢出问题

### 问题 8：消息气泡中的 tool 输出被强制截断 500 字符
- 文件：`web/src/components/MessageBubble.tsx:26-28`
- 问题级别：P1
- 当前行为：`message.content.slice(0, 500)`
- 问题说明：tool output 可能包含关键错误栈、JSON、diff，但会被静默裁切。
- 复现步骤：
  1. 运行一个输出较长日志的 tool
  2. 查看消息气泡
  3. 后半段内容被裁掉
- 风险：
  - 调试信息丢失
  - 影响问题定位

### 问题 9：SessionSidebar 的 session preview 被截断到 42 字符
- 文件：`web/src/components/SessionSidebar.tsx:177-179`
- 问题级别：P1
- 当前行为：`(s.title || s.summary || s.id).slice(0, 42)`
- 问题说明：标题 / 摘要会被过早截断。
- 复现步骤：
  1. 打开侧边栏
  2. 选择长标题 session
  3. 预览信息不足
- 风险：
  - 可发现性差
  - 重要上下文丢失

### 问题 10：SubagentDetail 主体没有完整的展开/折叠策略
- 文件：`web/src/components/SubagentDetail.tsx:116-133`
- 问题级别：P1
- 当前行为：事件列表全量显示，缺少对长事件的统一展开策略
- 问题说明：子代理日志量大时可读性下降。
- 复现步骤：
  1. 打开有大量 subagent event 的会话
  2. 观察详情页
  3. 页面滚动和密度急剧上升
- 风险：
  - 信息过载
  - 手机/窄屏下体验差

### 问题 11：ChatView 中的 plan approval summary 使用固定高度并隐藏溢出
- 文件：`web/src/components/ChatView.tsx:903-905`
- 问题级别：P1
- 当前行为：`maxHeight: 80, overflow: "hidden"`
- 问题说明：审批区中重要 contract 内容被裁切。
- 复现步骤：
  1. 产生较长 contract
  2. 查看 plan waiting 区
  3. 内容被隐藏
- 风险：
  - 审批时信息不完整
  - 容易误判

### 问题 12：EventSidebar 事件摘要普遍采用 slice 截断
- 文件：`web/src/components/EventSidebar.tsx:109-115`
- 问题级别：P1
- 当前行为：对 content/name/output/error/message 一律 `slice(0, 72)`
- 问题说明：摘要卡片适合作为列表，但在某些事件中会丢失关键信息。
- 复现步骤：
  1. 运行长 thought / observation
  2. 查看右侧 event list
  3. 摘要过短
- 风险：
  - 影响 trace 审阅效率

---

## 🟡 P2 — UI 设计差距与产品化不足

### 问题 13：Plan View 结构偏审批卡，不是完整计划工作台
- 文件：`web/src/components/PlanView.tsx:25-242`
- 问题级别：P2
- 当前状态：
  - 已有审批动作
  - 但缺少结构化章节展示、差异视图、执行契约浏览器、失败 / 版本切换
- 复现步骤：
  1. 进入 Plan tab
  2. 查看计划展示
  3. 只能看到单一文本块和几个按钮
- 差距：
  - 缺少分层阅读体验
  - 缺少目标 / 风险 / 文件 / 验证分区
  - 缺少明确的“计划→执行”状态机视觉提示

### 问题 14：Review View 够用但不够强，缺少 diff 级别聚焦与批量处理
- 文件：`web/src/components/DiffReviewView.tsx:19-159`
- 问题级别：P2
- 当前状态：
  - 能列出 pending diffs
  - 能 approve / reject
  - 但没有更强的文件级导航、上下文摘要、批量操作回执
- 复现步骤：
  1. 进入 Reviews tab
  2. 查看多个 diff
  3. 只能线性浏览
- 差距：
  - 缺少“审核台”层级
  - 不利于大批量 diff 审阅

### 问题 15：Subagent 视图已经可用，但信息层级和错误态不足
- 文件：
  - `web/src/components/SessionTree.tsx:78-117`
  - `web/src/components/SubagentProgress.tsx:36-79`
  - `web/src/components/SubagentDetail.tsx:22-170`
- 问题级别：P2
- 当前状态：
  - 有树状导航
  - 有进度浮层
  - 有 detail overlay
  - 但缺少更清晰的 parent/child 关系视觉语义、失败回溯、重试入口统一风格
- 复现步骤：
  1. 运行多层 subagent
  2. 观察树和 overlay
  3. 层级语义较弱
- 差距：
  - 缺少“子任务面板”产品级体验
  - 对长链路任务不够友好

### 问题 16：ChatView 仍混有局部 inline style 与临时文案
- 文件：`web/src/components/ChatView.tsx:790-814`
- 问题级别：P2
- 当前状态：plan progress indicator 仍是 inline style 块
- 复现步骤：
  1. 处于 plan running
  2. 观察黄色提示条
  3. 与整体 UI 风格不完全一致
- 差距：
  - 说明布局系统尚未统一
  - 样式 token 使用不彻底

---

## 🟡 现有测试覆盖盲区

### 问题 17：缺少对前端 API 调用路径的自动化断言
- 文件范围：`web/src/components/**`
- 问题级别：P1
- 现状：
  - 有后端/集成测试
  - 但前端未验证某按钮是否真的触发了预期 API
- 复现步骤：
  1. 修改前端按钮或 handler
  2. 无前端测试拦截，容易回归
- 风险：
  - “看起来能用”但实际不发请求

### 问题 18：缺少 Markdown 渲染 E2E 断言
- 文件范围：`web/src/components/MessageBubble.tsx`, `PlanView.tsx`, `WsEventBlock.tsx`
- 问题级别：P0
- 现状：没有覆盖代码块 / 表格 / 链接渲染的端到端测试
- 复现步骤：
  1. AI 输出 markdown
  2. 页面显示为纯文本或半成品
  3. 无测试报错
- 风险：
  - 这是本次最需要补齐的回归面之一

### 问题 19：缺少“用户操作后状态真实落库”的 E2E 断言
- 文件范围：`server/routers/approvals.py`, `server/services/*`, `web/src/components/PlanView.tsx`
- 问题级别：P0
- 现状：前端按钮有，但未通过 E2E 验证 approve / reject / save / abort 是否真的改变后端状态
- 复现步骤：
  1. 点击按钮
  2. 前端状态变化了
  3. 但未验证后端持久化结果
- 风险：
  - UI 假成功

### 问题 20：缺少对长内容、表格、代码块、链接的可视化回归
- 文件范围：`MessageBubble`, `PlanView`, `WsEventBlock`, `MemoryView`
- 问题级别：P1
- 现状：没有视觉回归或截图证据
- 风险：
  - 布局轻微退化难以察觉
  - 在大屏 / 小屏上可能出现不同问题

---

## 总结

当前前端的主问题不是“没有功能”，而是：
1. **调用路径没有彻底收口**
2. **AI 富文本渲染没有统一抽象**
3. **Plan / Review / SubAgent 还停留在可用而非可审计、可验证、可扩展**
4. **缺少前端到后端状态真实一致性的自动化证据**

---

## 结论

建议按以下优先级推进：

1. **Batch 1**
   - 收口所有裸 `fetch`
   - 建立统一 `MarkdownRenderer`
   - 补齐 markdown E2E
2. **Batch 2**
   - 清理截断和布局溢出
3. **Batch 3**
   - 重做 Plan / Review / SubAgent UI
4. **Batch 4**
   - 完整 E2E 与回归证据链
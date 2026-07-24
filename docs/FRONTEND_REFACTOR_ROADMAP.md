# Frontend Refactor Roadmap

目标：
将前端从“功能可用”提升到“真实打通、可审计、可回归、生产级体验”。

总原则：
- 所有 API 调用必须通过统一 Client 层
- 所有 AI 输出必须通过统一 MarkdownRenderer 组件渲染
- 所有状态变更必须具备 loading / error / success 三态
- 每一批改动都必须配套 mock/test
- 每一批都要有可自动化验证的验收标准
- 若某批触发后端门禁失败，必须在该批内修复，不得后移

---

## Batch 1：API 真实打通 + Markdown 渲染统一

### 目标
1. 消除 `web/src/` 下所有裸 `fetch(` 调用
2. 建立并统一使用 `<MarkdownRenderer />`
3. 将 AI 输出字段统一切换到 MarkdownRenderer 渲染
4. 补齐针对 markdown / API 路径的 E2E 与 mock

### 改动文件清单
- `web/src/api/client.ts`
- `web/src/api/config.ts`（新增）
- `web/src/api/sessions.ts`
- `web/src/api/events.ts`（如需要，新增或拆分）
- `web/src/components/MarkdownRenderer.tsx`（新增）
- `web/src/components/MessageBubble.tsx`
- `web/src/components/PlanView.tsx`
- `web/src/components/WsEventBlock.tsx`
- `web/src/components/EventSidebar.tsx`
- `web/src/components/SubagentDetail.tsx`
- `web/src/components/ChatView.tsx`
- `web/src/components/ToolCallCard.tsx`（如需要统一预览格式）
- `web/src/components/ToolApprovalCard.tsx`（如需要统一预览格式）
- `web/src/components/MemoryView.tsx`（对齐 renderer 入口）
- `web/src/tests/**` 或 `web/e2e/**`（新增）
- `tests/**`（若需要联动后端验证）

### 预估工时
- 12~18 小时

### 主要实施项
1. 把 `ChatView`、`EventSidebar`、`SubagentDetail` 中的裸 `fetch` 改成 Client 层方法
2. 提炼 `MarkdownRenderer`，作为 AI 输出唯一渲染入口
3. 替换 MessageBubble / PlanView / WsEventBlock 中的 AI 文本渲染
4. 对 tool / approval / plan 的文本详情保留安全的 markdown 解析
5. 为新增 API 调用编写 mock 或测试替身
6. 为 markdown 输出补 E2E：代码块、表格、链接

### 验收标准（AC）
- `grep -r "fetch(" web/src/` 零命中
  - 允许例外：`web/src/api/client.ts` 本身与测试 mock
- 所有 AI 输出字段均通过 `<MarkdownRenderer />` 渲染
- E2E 至少覆盖以下三类 markdown：
  1. 代码块
  2. 表格
  3. 链接
- 相关 UI 的加载 / 错误 / 成功态可观察
- 后端 CMD-INJ / ENV_WHITELIST 相关测试无新增失败
- 批次内新增 API 调用均有 mock / test

### 回滚方案
- 保留旧渲染逻辑作为临时 fallback 分支
- 使用单个 feature flag 控制 MarkdownRenderer 切换
- 若 E2E 或 CI 失败，回滚本批新增组件与 API 封装改造，只保留安全的 client 抽象

---

## Batch 2：内容截断 / 布局修复 + 响应式适配

### 目标
1. 清理不必要的 `slice()` 截断
2. 改善长文本、diff、trace、tool output 的布局
3. 修复移动端 / 小屏下的溢出和重排问题
4. 提升整体信息密度与可读性

### 改动文件清单
- `web/src/components/MessageBubble.tsx`
- `web/src/components/ToolCallCard.tsx`
- `web/src/components/ToolApprovalCard.tsx`
- `web/src/components/PlanView.tsx`
- `web/src/components/WsEventBlock.tsx`
- `web/src/components/DiffBlock.tsx`
- `web/src/components/DiffReviewView.tsx`
- `web/src/components/SessionSidebar.tsx`
- `web/src/components/EventSidebar.tsx`
- `web/src/components/SubagentDetail.tsx`
- `web/src/components/StatsDashboard.tsx`
- `web/src/components/MemoryView.tsx`
- `web/src/styles.css`

### 预估工时
- 10~14 小时

### 主要实施项
1. 用统一的可展开文本容器替代静态 `slice`
2. diff、代码块、长输出加“默认可读、必要时展开”的交互
3. 调整 grid / flex / overflow / min-height / max-width 策略
4. 修复 sidebar / panel / drawer 在窄屏下的断裂
5. 优化 session 列表、trace 列表、plan 视图的层级

### 验收标准（AC）
- 不再出现关键 AI 输出的静默截断
- 长代码块、长 diff、长 plan 在 UI 中可展开查看完整内容
- 小屏（或窄窗口）下主布局不重叠、不溢出
- 相关页面通过截图回归或 E2E 视觉断言
- 无新增破坏性 CSS 回归

### 回滚方案
- 每个布局重构组件保留最小化 fallback 容器
- 样式改动独立于数据层，可单独回滚 CSS 文件
- 若出现广泛布局破坏，回退到 Batch 2 前的样式版本

---

## Batch 3：Plan / Review / SubAgent UI 重设计与实现

### 前置要求
必须先输出并确认：
- `docs/UI_DESIGN_SPEC.md`

### 目标
1. 将 Plan / Review / SubAgent 三大核心区域提升为“任务工作台”
2. 形成稳定的信息层级与操作流
3. 让用户能明确知道“当前在做什么、为什么、下一步是什么”
4. 强化多阶段任务的审阅、回溯和子任务观察

### 改动文件清单
- `docs/UI_DESIGN_SPEC.md`（新增）
- `web/src/components/PlanView.tsx`
- `web/src/components/DiffReviewView.tsx`
- `web/src/components/SubagentDetail.tsx`
- `web/src/components/SubagentProgress.tsx`
- `web/src/components/SessionTree.tsx`
- `web/src/components/WsEventBlock.tsx`
- `web/src/components/ChatView.tsx`
- `web/src/components/ToolApprovalCard.tsx`
- `web/src/components/ToolCallCard.tsx`
- `web/src/styles.css`

### 预估工时
- 14~20 小时

### 主要实施项
1. Plan 区：
   - 任务分解
   - contract 总览
   - 风险区
   - 验证策略
   - 目标文件浏览
2. Review 区：
   - diff 导航
   - 文件级摘要
   - 审核意见
   - 批次处理
3. SubAgent 区：
   - 任务树
   - 子任务卡
   - 状态流
   - worktree 结果面板
4. 将 Plan / Review / SubAgent 风格统一为同一套工作台体系

### 验收标准（AC）
- 三大区域都有明确的“正在做什么 / 为什么 / 下一步是什么”
- Plan / Review / SubAgent 不再依赖零散的小卡片拼装
- 用户能一眼判断状态、风险、审批点和回退点
- 子任务 / worktree 结果可追踪、可恢复、可回看
- E2E 可验证主要交互链路

### 回滚方案
- 保留现有视图结构作为 fallback
- 新 UI 通过单独的布局组件切换
- 若某一视图重构失败，可只回退该视图，不影响其他区域

---

## Batch 4：E2E 测试补全 + 回归验证

### 目标
1. 为前端关键交互建立端到端自动化验证
2. 证明请求真实发出、后端真实变更、UI 真正反映结果
3. 为 markdown / plan / review / subagent 建立回归证据链
4. 补充视觉证据（截图 / 录屏）

### 改动文件清单
- `web/e2e/**`（新增或扩展）
- `tests/test_e2e_smoke.py`
- `tests/test_cli_web_alignment.py`
- `tests/test_e2e_core.py`
- `tests/manual/**`（如需补充手工回归脚本）
- `web/playwright.config.*`（如适用，新增或调整）
- `web/package.json`（如需增加测试脚本）

### 预估工时
- 8~12 小时

### 主要实施项
1. Playwright 或 Cypress E2E：
   - 发送请求
   - 检查参数
   - 验证后端状态变化
   - 验证 UI 渲染
2. Markdown 回归：
   - 代码块
   - 表格
   - 链接
3. Plan / Review / SubAgent 回归：
   - plan_ready
   - approve / reject / save / abort
   - diff review
   - subagent 详情与 worktree action
4. 截图 / 录屏证据归档

### 验收标准（AC）
- 关键前端交互都有自动化 E2E 覆盖
- 至少有一条完整链路验证：
  - 用户操作
  - API 请求真实发出
  - 后端状态变化
  - UI 正确更新
- Markdown 渲染回归通过
- 相关回归测试可在 CI 中稳定运行
- 所有批次修改后无破坏性回归

### 回滚方案
- 保留测试用例以外的最小运行时改动
- 若 E2E 过于不稳定，可先保留单元 / 组件测试，E2E 独立回滚
- 截图回归失败时仅撤销测试配置，不回滚产品代码

---

## 统一门禁检查点

### Batch 1 前置 / 进行中门禁
- 统一 API Client 改造必须同步检查后端 `CMD-INJ` / `ENV_WHITELIST` 相关断言
- 若前端调用方式变化引起后端测试失败，必须在 Batch 1 内修复

### 批次推进门禁
- Batch 1 未达成验收标准，禁止进入 Batch 2
- Batch 2 未达成验收标准，禁止进入 Batch 3
- Batch 3 未达成验收标准，禁止进入 Batch 4

---

## 交付顺序

1. `docs/FRONTEND_AUDIT_REPORT.md`
2. `docs/FRONTEND_REFACTOR_ROADMAP.md`
3. Batch 1
4. Batch 2
5. Batch 3
6. Batch 4

---

## 当前建议
先由审阅者确认以上两份文档，随后开始 Batch 1：
- 收口裸 fetch
- 统一 MarkdownRenderer
- 补齐 E2E 验证
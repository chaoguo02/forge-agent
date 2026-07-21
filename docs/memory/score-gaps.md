# 记忆模块 — 分数差距分析

当前总分 5.5/10。目标 9/10。

---

## 1. 架构设计 — 8/10 → 目标 9/10

### 当前差距

| 问题 | 现状 | 目标 |
|------|------|------|
| `FileMemoryBackend` 是死代码 | 写了但无人调用 | 要么删掉，要么有实际用途 |
| `TwoTierMemoryStore` 参数过多 | 7 个构造参数，其中 `base_dir`/`memory_dir`/`global_dir` 在 SQLite 模式下全无效 | 简化参数或废弃 |
| `MemoryStore.store_dir` 属性在 SQLite 模式下返回不存在的路径 | `~/.grace/projects/...` 可能不存在 | 在 SQLite 模式下返回 None 或报错 |

### 具体动作

```
[P3] 删除 FileMemoryBackend 或给它一个实际入口（如 CLI export 命令）
[P4] 废弃 TwoTierMemoryStore 的 legacy 参数，改为只接受 repo_path + db_path
[P3] MemoryStore.store_dir 在 SQLite 模式下抛 AttributeError 或返回 None
```

### 达到 9/10 的标准
- 无死代码
- 所有公开 API 的参数都是必要的
- 没有"在某种模式下不工作"的属性

---

## 2. 后端 API — 7/10 → 目标 9/10

### 当前差距

| 缺口 | 现状 | 目标 |
|------|------|------|
| 缺少 session 上下文 | `source_session_id` 始终为空 | 在 router 中获取当前 session_id 并传入 |
| 没有批量详情 | `GET /api/memory` 只返回摘要 | 支持 `?expand=true` 返回完整内容 |
| 没有按 session 查询 | 无法查"这个 session 创建了哪些记忆" | `GET /api/memory?source_session_id=xxx` |
| Anchors 不能部分更新 | PATCH 不支持 anchors 字段 | PATCH 接受 anchors |
| 没有统计端点 | overview 只在列表时返回 | 独立 `GET /api/memory/stats` 端点 |
| 搜索结果的 content 截断 | `content[:500]` 硬编码 | 改为可配置长度或全文返回 |
| 没有版本/审计 | 无法知道谁在什么时候改了记忆 | 可选的变更日志 |

### 具体动作

```
[P2] router create/PATCH 中传入 `session_id` 作为 `source_session_id`
[P2] 列表端点支持 `_expand=true` 参数，返回完整 content
[P2] 列表端点支持 `source_session_id` 过滤
[P3] PATCH 支持 anchors 字段
[P3] 新增 `GET /api/memory/stats` 端点
[P4] search 端点 content 长度改为可配置
```

### 达到 9/10 的标准
- 所有写入路径都带 session 上下文
- 列表端点支持前端所需的所有过滤条件
- CRUD 完整，没有任何"只能通过 curl"的操作

---

## 3. 前端展示 — 4/10 → 目标 9/10

### 当前差距

| 缺口 | 现状 | 目标 |
|------|------|------|
| ❌ **没有新建入口** | 只能 curl 或 LLM 工具创建 | Memory tab 上有 "New Memory" 按钮 → 弹窗 → POST |
| ❌ **没有编辑功能** | 有 Delete 无 Edit | 详情面板可编辑 description/content/confidence → PATCH |
| ❌ **没有手动刷新** | 只在挂载时加载一次 | 按钮或下拉刷新 |
| ❌ **列表不显示创建时间** | 详情有但列表行没有 | catalog list 每行加 created_at |
| ❌ **锚点不可编辑** | 只能看不能改 | 详情锚点区可添加/删除锚点 |
| ❌ **搜索只搜 name+desc** | 不搜 content | 后端支持全文搜索或前端按需加载 |
| ❌ **类型过滤固定** | 只有 "all/user/feedback/project/reference" | 从 overview 动态生成过滤选项 |
| ❌ **无 Markdown 编辑** | 内容只读 | 编辑时用 textarea 编辑原始 Markdown |
| ❌ **空状态** | 列表为空时只显示文字 | 空状态卡片引导用户新建或写入 |
| ❌ **无确认弹窗** | `confirm()` 浏览器原生对话框 | 自定义 Modal 组件 |
| ❌ **无 Toast 通知** | 删除后无反馈 | 操作成功/失败的轻提示 |
| ❌ **侧栏分布图不是交互的** | 只是静态数值 | 点击分布图的类型可过滤列表 |

### 具体动作

```
[P1] 新增 "New Memory" 按钮 → Modal 表单 → POST /api/memory
[P1] 详情面板加 "Edit" 按钮 → 行内编辑 → PATCH
[P1] 加 "Refresh" 按钮
[P2] 目录列表每行显示 created_at
[P2] 锚点可删除/添加
[P2] 搜索改为搜 name + description + content（后端全文搜索或前端加载后搜索）
[P3] 类型过滤改为动态生成
[P3] 编辑内容用 textarea
[P2] 空状态引导卡片
[P2] 自定义 Modal 代替 confirm()
[P3] Toast 通知组件
[P3] 分布图点击可过滤
```

### 达到 9/10 的标准
- 完整的 CRUD 界面：建、看、改、删全部在前端可操作
- 数据变化后自动或一键刷新
- 所有后端字段都在前端有对应展示
- 没有浏览器原生弹窗

---

## 4. DB 存储 — 6/10 → 目标 9/10

### 当前差距

| 缺口 | 现状 | 目标 |
|------|------|------|
| 两张表建表代码重复 | `SqliteStorageBackend` 和 `SqliteMemoryBackend` 都建 memory_entries | 只在一个地方建表 |
| 无连接池 | `_conn()` 每次新建连接 | 连接复用（或明确声明不需要） |
| 无 `close()` 方法 | 连接靠 Python GC 关闭 | 显式 `close()` 方法 |
| 无 schema 版本 | `CREATE TABLE IF NOT EXISTS` 不会加新列 | schema 版本号 + 迁移脚本 |
| 无 WAL 文件清理 | WAL 日志无限增长 | 定期 `checkpoint` 或 PRAGMA wal_autocheckpoint |
| `memory_anchors` 无级联删除 | 外键定义了但不一定启用（PRAGMA foreign_keys） | 确保外键启用 |

### 具体动作

```
[P2] 删掉 SqliteStorageBackend._init_memory_tables()，只保留 SqliteMemoryBackend._init_tables()
[P3] 在 _init_tables 中执行 PRAGMA foreign_keys = ON
[P3] 加 close() 方法
[P3] 加 schema_version 表 + 迁移逻辑
[P3] PRAGMA wal_autocheckpoint=1000
```

### 达到 9/10 的标准
- 建表逻辑不重复
- 外键约束生效
- 连接可显式关闭
- schema 可迁移

---

## 5. 测试 — 3/10 → 目标 9/10

### 当前差距

| 缺口 | 现状 | 目标 |
|------|------|------|
| ❌ 无 API 集成测试 | 从未启动服务器验证端点 | 用 TestClient 测试 6 个端点 |
| ❌ 无前端组件测试 | MemoryView 所有交互未验证 | 至少测试渲染和数据加载 |
| ❌ 无后端→前端联调 | 前端 memory API 调用未验证 | 测试 getMemorySnapshot 的数据流 |
| ❌ 无数据迁移测试 | 文件→SQLite 路径从未验证 | 测试 sync_memory_from_files |
| ❌ 无错误路径测试 | 404/409/503 等未测试 | 每个错误场景有对应测试 |
| ❌ 无边界测试 | 空列表、大量数据、特殊字符 | 空 DB、1000 条记忆、Unicode content |

### 具体动作

```
[P1] 用 FastAPI TestClient 测试 6 个 memory API 端点
[P1] 测试 404（不存在）、409（重复创建）、503（store 不可用）
[P2] 测试 getMemorySnapshot() 成功/失败路径
[P2] 文件→SQLite 迁移测试
[P3] 1000 条记忆的列表性能
[P3] Unicode content（中文、日文、emoji）
```

### 达到 9/10 的标准
- API 每端点至少一个成功 + 一个失败测试
- 前端 API 调用层测试覆盖
- 迁移路径测试

---

## 6. 文档 — 5/10 → 目标 9/10

### 当前差距

| 缺口 | 现状 | 目标 |
|------|------|------|
| 文档分散 | 分布在 `docs/memory/`、`docs/architecture/`、`docs/` 三个目录 | 统一索引 |
| 无 API 文档自动生成 | 依赖代码注释 | 生成 OpenAPI/Swagger 文档 |
| 无前端组件文档 | MemoryView 的 props/state/effect 无文档 | 组件级文档 |
| 无数据流图 | 架构文档有文字描述无图 | 时序图展示写路径 |
| 无 quickstart | 新开发者不知如何创建第一条记忆 | "5 分钟上手"指南 |

### 具体动作

```
[P2] 在 docs/memory/ 下创建 README.md 作为统一入口
[P2] 数据流图（Mermaid 时序图）
[P3] 生成 Swagger 文档
[P3] 5 分钟快速入门（curl 创建 → 前端查看）
```

### 达到 9/10 的标准
- 所有记忆相关文档在一个目录下可索引
- 新开发者能在 5 分钟内创建→查看→删除一条记忆
- 有清晰的写路径时序图

---

## 优先级排序

| 等级 | 项 | 工作量 |
|------|----|--------|
| **P1 — 直接影响用户可用性** |
| | 前端新建记忆弹窗 | 半天 |
| | 前端编辑功能 | 半天 |
| | 前端刷新按钮 | 1 小时 |
| | API 集成测试 | 1 天 |
| | 空状态引导 | 2 小时 |
| **P2 — 提升完整度** |
| | source_session_id 传入 | 1 小时 |
| | 搜索支持 content | 半天 |
| | 列表显示 created_at | 1 小时 |
| | _expand 参数 | 2 小时 |
| | 自定义 Modal 代替 confirm() | 半天 |
| | Toast 通知 | 半天 |
| **P3 — 架构加固** |
| | 建表去重 | 1 小时 |
| | close() 方法 | 1 小时 |
| | z-anchors 部分更新 | 半天 |
| | stats 独立端点 | 半天 |
| | 性能 + Unicode 测试 | 1 天 |
| **P4 — 长期** |
| | schema 版本 + 迁移 | 1 天 |
| | 参数清理 | 半天 |
| | 自动生成文档 | 2 天 |

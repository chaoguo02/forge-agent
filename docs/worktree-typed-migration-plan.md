# 三项治本修复计划

> 先设计，后反思，再实现。

---

## Issue 1: 前端 worktree 乐观更新 (🔴)

### 当前错误流程

```
POST /worktrees/{child}/apply
  → 202 {accepted: true, status: "queued"}
  → 前端: r.ok → setDetail({worktree_resolved: "apply"})  ← 错! 只是入队
  → 按钮消失, 显示 "✓ Worktree apply"
  → Worker 线程: 还在队列中...
  → 甚至可能执行失败!
```

### 治本流程

```
POST /worktrees/{child}/apply
  → 202 {accepted: true, command_key: "...", status: "queued"}
  → 前端: setWorktreeAction("applying")  ← 显示 spinner
  → Worker: apply_worktree()
  → _worktree_completion_callback(parent_id, child_id, "apply", "applied")
  → publish_raw → WS: {type: "worktree_resolved", child_session_id, action, status}
  → chatStore.handleWsEvent:
      worktree_resolved → 更新 backgroundAgents[child_id].worktreeStatus
  → SubagentDetail: 订阅 worktreeStatus → show "✓ Applied" / "✗ Failed"
```

### 状态机

```
idle → applying → applied
     → applying → failed
     → discarding → discarded
     → retaining → retained
```

### 需要改动的文件

| 文件 | 改动 |
|------|------|
| `web/src/stores/chatStore.ts` | `backgroundAgents[id].worktreeStatus` 字段 |
| `web/src/components/SubagentDetail.tsx` | 移除乐观更新，订阅 worktreeStatus，三态渲染 |

### 反思验证

**问: 如果用户关闭 SubagentDetail 再打开，worktree 状态还在吗？**
答: `chatStore.backgroundAgents` 是内存状态，刷新丢失。SubagentDetail 的 `load()` 重新 fetch session detail → metadata 中有 `worktree_path`（来自后端 session record），但 `worktreeStatus` 需要从 worktree_results 或 WorktreeDisposition 重新读取。

**修复:** SubagentDetail 的 `load()` 不仅 fetch session detail，还 fetch worktree status (GET /worktrees 端点)。

**问: Worker 失败时，前端如何知道？**
答: `_worktree_completion_callback` 传入 `status="error"` → publish_raw → WS event → frontend 显示 "✗ Failed - retry?"。

**问: 用户点击 Apply 后刷新页面，按钮会回到初始状态吗？**
答: POST 返回的 `command_key` 不在 URL 中。刷新后前端重新 load → worktree 状态从 session record 读取 → 如果 worker 已完成，`WorktreeDisposition` 已变为 APPLIED。如果还在队列，仍为 PRESERVED。

---

## Issue 2: publish_raw 类型安全 (🟡)

### 当前问题

```python
# agent_service.py — 手工拼 dict
event_bus.publish_raw(session_id, {
    "type": "plan_ready",
    "plan_text": result.summary,
    ...
})

# server/events.py — 有 WsPlanReady dataclass 但没人用
```

`publish_raw` 接受 `dict` → 无编译时类型检查 → 字段名拼错要到运行时才发现。

### 治本方案

不改变 `publish_raw` 的签名（太多调用方）。而是：

**Step 1:** 在 `EventBus` 上新增 `publish_typed(session_id, event: WsEvent)`:
```python
def publish_typed(self, session_id: str, event: "WsEvent") -> None:
    self.publish_raw(session_id, event.to_dict())
```

**Step 2:** 在 `server/events.py` 的每个 dataclass 上标注 `_sent_via` 元数据（调试用途）。

**Step 3:** 迁移所有调用方（按优先级）:
- worktree callback → `WsWorktreeResolved`
- plan_ready → `WsPlanReady`
- approval_required → `WsApprovalRequired`
- status completed → `WsStatus`

**Step 4:** 标记 `publish_raw` 为 deprecated（但不删除）。

### 反思验证

**问: `publish_typed` 和 `publish_raw` 并存是否混乱？**
答: 过渡期是。长期目标是所有 `publish_raw` 调用方都迁移到 `publish_typed`。但 `publish_raw` 保留给第三方/插件使用。

**问: `WsEvent` union 类型能真正约束吗？**
答: Python 的 `|` 是类型标注，运行时不做检查。需要在 `publish_typed` 入口加 `assert isinstance(event, ...)` 或依赖 mypy/pyright 的静态检查。

**问: dataclass 的 `.to_dict()` 丢字段怎么办？**
答: 已验证 `_to_dict` 只跳过 `None`。所有字段都有合理的默认值（`""`, `[]`, `{}`）。`None` 不应该出现在 WS 事件中。

---

## Issue 3: PlanRevision JSON→SQLite 迁移 (🟡)

### 当前问题

`PlanRevisionService` 从 JSON 文件切换到了 SQLite，但旧数据永丢。

### 治本方案

**Step 1:** `PlanRevisionService.__init__` 中检测遗留 JSON 文件。

**Step 2:** 如果存在 `.forge-agent/plan-revisions/{session_id}.json` 且 SQLite 中无该 session 的记录 → 导入。

**Step 3:** 导入后写 `.forge-agent/plan-revisions/.migrated` 标记文件（记录已迁移的 session_id 列表）。

**Step 4:** 后续 `list_revisions` 只读 SQLite。

### 迁移伪代码

```python
def _migrate_json_if_needed(self):
    legacy_dir = Path(self._repo_path) / ".forge-agent" / "plan-revisions"
    if not legacy_dir.is_dir():
        return
    migrated_file = legacy_dir / ".migrated"
    migrated = set()
    if migrated_file.is_file():
        migrated = set(migrated_file.read_text().splitlines())
    
    for json_file in legacy_dir.glob("*.json"):
        session_id = json_file.stem
        if session_id in migrated or session_id.startswith("."):
            continue
        # Import
        revisions = json.loads(json_file.read_text())
        for rev in revisions:
            self._storage.insert_plan_revision(rev)
        migrated.add(session_id)
    
    migrated_file.write_text("\n".join(migrated))
```

### 反思验证

**问: 如果两个进程同时执行迁移怎么办？**
答: SQLite 有 WAL 锁。`INSERT OR REPLACE` 是幂等的。`.migrated` 文件写入不是原子的，但重复导入同一 session 不会产生重复数据（`id` 是 PRIMARY KEY）。

**问: 迁移后 JSON 文件要删除吗？**
答: 不删除。保留作为备份。`.migrated` 标记防止重复导入。

**问: `PlanRevisionService.__init__` 现在需要 `repo_path` 来访问旧 JSON 文件。但我们已经改成了 `(storage)` 签名。**
答: 需要同时传入 `repo_path` 和 `storage`。或者 `storage` 上挂一个 `repo_path` 属性。

---

## 实施顺序

```
Step 1: PlanRevisionService 添加 repo_path + 迁移逻辑
Step 2: EventBus 添加 publish_typed + 迁移 worktree callback
Step 3: 前端 worktree 三态渲染 (去掉乐观更新)
```

每步 commit。完成后反思。

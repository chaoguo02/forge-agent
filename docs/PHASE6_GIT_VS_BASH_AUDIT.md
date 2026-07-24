# Phase 6: Git Tool vs Bash Paradigm Audit

> 审计日期: 2026-07-23
> 目标: 判断专用 Git Tool 是否构成过度设计，输出带权重的三选一决策矩阵。

---

## 1. 代码事实提取

### 1.1 专用 Git Tool 清单

| Tool | 名称 | 行数 | 参数数 | CLI 映射 | 输出截断 | 超时 |
|------|------|------|--------|----------|---------|------|
| `GitStatusTool` | `git_status` | 49 | 1 (cwd) | `git status --short --branch` | 无 | 30s |
| `GitDiffTool` | `git_diff` | 79 | 3 (staged, path, cwd) | `git diff [--cached] [-- <path>]` | 8000 chars | 30s |
| `GitAddTool` | `git_add` | 63 | 2 (paths, cwd) | `git add <paths>` | 无 | 30s |
| `GitCommitTool` | `git_commit` | 68 | 2 (message, cwd) | `git commit -m <message>` | 无 | 30s |

- **总代码行数**: 341 行
- **外部依赖**: 仅 `subprocess` + `shutil` — 零第三方库，全部委托给 `git` CLI
- **共享辅助**: `_run_git()` (51 行) — 处理 Windows Git 路径发现 + Runtime 调用

### 1.2 Bash Tool 能力边界

| 维度 | 值 |
|------|-----|
| **名称** | `Bash`（注册在 `ShellTool`） |
| **行数** | 420 行 |
| **安全拦截模式** | `_BLOCKED_PATTERNS` — 16 个硬编码危险模式（rm -rf /, mkfs, dd if=, 等） |
| **只读命令白名单** | `_READ_ONLY_COMMANDS` — 78 个命令标记为并发安全（ls, grep, git status/log/diff/show/branch/..., Get-ChildItem, etc.） |
| **Git 只读前缀** | `_READ_ONLY_PREFIXES`: `git status`, `git log`, `git diff`, `git show`, `git branch`, `git tag`, `git remote`, `git config --get`, `git config --list`, `git ls-`, `git rev-` |
| **路径校验** | `_validate_workspace_paths()` — 阻止 `../` 逃逸 + 绝对路径越出 workspace |
| **输出截断** | 50,000 chars (`MAX_OUTPUT_CHARS`) |
| **超时** | 默认 30s，可配置 |
| **并发模式** | 根据命令动态判断 PARALLEL_SAFE / SERIAL |
| **当前对 Git 的限制** | Bash description **主动引导 LLM** 使用专用 Git Tool |

### 1.3 工具注册与默认可见性

| 代理类型 | 可见的 Git 工具 | 可见 Bash |
|---------|---------------|----------|
| `build` (primary) | `git_status`, `git_diff`, `git_add`, `git_commit` | ✅ |
| `plan` (read-only) | `git_status`, `git_diff` | ✅ |

**总共 ~26 个内置工具**注册在 [entry/bootstrap/registry_factory.py](entry/bootstrap/registry_factory.py)，其中 4 个是 Git Tool。

### 1.4 Bash Tool 描述中现存的 Git 引导

[tools/shell_tool.py:127-128](tools/shell_tool.py#L127-L128):
```
"For git operations (status, diff, add, commit), use the git_status,
git_diff, git_add, git_commit tools instead."
```

这已经是架构决策的体现：Bash 明确把 Git 操作让给了专用 Tool。

### 1.5 安全基础设施总览

| 安全层 | 实现 | 默认状态 |
|--------|------|---------|
| 命令模式拦截 | `_BLOCKED_PATTERNS` — 16 个硬编码模式 | ✅ 始终生效 |
| 工作区路径沙箱 | `_validate_workspace_paths()` | ✅ 始终生效 |
| 输出长度截断 | `MAX_OUTPUT_CHARS = 50,000` | ✅ 始终生效 |
| 执行超时 | 默认 30s | ✅ 始终生效 |
| Docker 沙箱 | `DockerRuntime` — overlay fs + no-new-privileges + CMD-INJ | ❌ 非默认，需 `--sandbox` flag |
| Git 凭证隔离 | 无 | ❌ Docker 模式下 bind mount 带有 `.git` 目录 |
| 本地进程隔离 | `LocalRuntime(local subprocess)` — 无 sandbox | ❌ 默认模式就是裸机 subprocess |

---

## 2. 六维决策矩阵

### 维度 1: LLM 能力匹配度 — 权重: **高**

| 专用 Git Tool 现状 | Bash + Git CLI 预期 | 判定 |
|-------------------|--------------------|------|
| `git_status` 固定参数 `--short --branch`，LLM 无法加 `--porcelain` / `--ignored` | `git status --porcelain=v2` 灵活组合 | 🟡 Bash 略优 |
| `git_diff` 只有 `staged` 和 `path` 参数，LLM 无法 `git diff HEAD~3..HEAD --stat` | `git diff --name-only --diff-filter=M` 精准控制 | 🟡 Bash 略优 |
| `git_add` 只有 `paths` 参数，LLM 无法 `git add -p`（交互式）或 `git add --update` | 完整 git CLI 表达力 | 🟡 Bash 略优 |
| `git_commit` 只有 `message`，无 `--amend` / `--no-verify` / `--signoff` | LLM 已知所有 commit 选项 | 🟡 Bash 略优 |
| 但：4 个 Tool 对 LLM 来说**完全透明**——schema 精准，无歧义 | Bash 需要 LLM 自行构建命令字符串，可能出错 | 🟢 Git Tool 略优 |

**得分**: Git Tool **3/10**, Bash **7/10** — LLM 被 Git Tool 的参数限制约束了已有的 Git 组合能力。专用 Tool 是能力退化。

> 引用: [tools/git_tool.py:122](tools/git_tool.py#L122) — `_run_git(["status", "--short", "--branch"])` 硬编码参数，LLM 无法加 `--porcelain`。

### 维度 2: Token 效率 — 权重: **高**

需要算账，不凭感觉：

**专用 Git Tool 的 Prompt 成本**（每条 Tool 的 JSON Schema）:

| Tool | Schema 字符数 | 估算 Token |
|------|-------------|-----------|
| `git_status` | ~250 chars | ~60 |
| `git_diff` | ~380 chars | ~95 |
| `git_add` | ~280 chars | ~70 |
| `git_commit` | ~260 chars | ~65 |
| **合计** | ~1,170 chars | **~290 tokens** |

**Bash Tool 的 Prompt 成本**:
- Bash schema: ~400 chars → ~100 tokens
- Bash description 中 2 行 git 引导: ~100 chars → ~25 tokens
- **合计**: ~125 tokens

**单次调用的运行时成本**（对比 `git status` 调用）:

| 路径 | 工具参数 Token | 输出 Token | 单次总成本 |
|------|-------------|-----------|----------|
| `git_status` 专用 Tool | `{"cwd": null}` → ~10 tokens | stdout → ~200 tokens | **~210** |
| `Bash: git status --short --branch` | `{"command":"git","args":["status","--short","--branch"]}` → ~30 tokens | stdout → ~200 tokens | **~230** |
| 差异 | +20 tokens | 相同 | **+10%** |

**但**：如果要执行 `git log --oneline -5 --graph --all`（专用 Tool 不支持的组合）：
- 专用 Tool: LLM 需要额外 turn 用 Bash 执行 → ~500 tokens 浪费
- Bash: 一次性完成 → ~230 tokens

**推论**: 对已有 Tool 覆盖的 4 个操作，专用 Tool 比 Bash 省 ~10%。但对**任何** Tool 不覆盖的操作，Bash 省 100%（一个 turn vs 两个 turn）。

**得分**: Git Tool **5/10**, Bash **5/10** — 高频场景打平，长尾场景 Bash 大胜。打成平手。

### 维度 3: 安全可控性 — 权重: 🔴 **关键**

这是真正的决策器。

**专用 Git Tool 的安全成本**:
- 4 个 Tool 的输入空间极小（cwd, paths, message）→ 攻击面窄 ✅
- `git_add` 信任 `paths` 参数，由 `PermissionPipeline` 的 Layer 5 路径沙箱保护 ✅
- `git_commit` 信任 `message` 参数，无注入风险（Shell tool 才有 `rm -rf` 注入风险） ✅
- **零额外代码**: 安全完全依赖 PermissionPipeline 的现有机制 ✅

**Bash 执行 Git 的安全成本**:
- `git` 本身不在 `_BLOCKED_PATTERNS` 中 → 通过 ✅
- 但 `git push --force origin main` / `git reset --hard HEAD~10` / `git rebase -i` **都不在拦截列表中** → ❌ 危险
- `git push` → 推送代码到远程 → 不可逆 ❌
- `git branch -D` → 删除分支 → 不可逆 ❌
- `git reset --hard` → 丢失未提交更改 → 不可逆 ❌
- Git 凭证通过 bind mount 暴露给容器 → 风险 ⚠️

**当前 Bash 防御层级**:

| 层级 | 对 Git 命令的覆盖 | 缺陷 |
|------|------------------|------|
| `_BLOCKED_PATTERNS` | 不覆盖任何 `git` 命令 | ❌ `git push --force` 无拦截 |
| `_READ_ONLY_PREFIXES` | 覆盖 11 个 git 只读操作 | ❌ `git push` / `git reset` / `git rebase` 均不在白名单中 |
| `PermissionPipeline` Layer 1-6 | 工具级别（Bash 作为一个整体） | ❌ 无法区分 `git log` vs `git push --force` |
| Docker overlay | 文件系统级 | ✅ `git push` 影响远程仓库，Docker 无法防护 |

**得分**: Git Tool **9/10**, Bash **3/10** — Bash 的 Git 安全完全靠 LLM 自律 + `_BLOCKED_PATTERNS` 的 16 个硬编码模式（不涵盖 `git push`）。专用 Tool 的窄接口天然免疫大批量 Git 破坏操作。

> ⚠️ **安全红线检查**: 如果现在开放 Bash 执行 `git push` / `git reset --hard`，当前的安全基础设施**不满足前提条件**。必须在 Bash Tool 中增加 Git 写操作白名单或额外确认层。

### 维度 4: 输出可解析性 — 权重: **中**

| 场景 | 专用 Git Tool | Bash + Git CLI | 判定 |
|------|------------|--------------|------|
| `git status` | 固定 `--short --branch`，输出格式稳定 | LLM 可能加 `--porcelain`，格式变化 | 🟢 Git Tool |
| `git diff` | 8000 chars 截断 + 结构化提示 "No staged changes." | 依赖 LLM 自行判断是否有 diff | 🟢 Git Tool |
| `git commit` | 返回明确 "Staged: ..." | 返回 git 原生输出，格式稳定 | 🟡 持平 |
| 结构化需求 | 前端 DiffBlock 可直接用 `git_diff` 结果 | 需要额外 output parser | 🟢 Git Tool |

**得分**: Git Tool **7/10**, Bash **4/10** — `git_diff` 的截断逻辑（[git_tool.py:201-204](tools/git_tool.py#L201-L204)）输出一致性优于原生 git CLI。

### 维度 5: 维护与扩展成本 — 权重: **中**

| 场景 | 专用 Git Tool | Bash + Git CLI |
|------|------------|--------------|
| 新增 `git stash` 支持 | 新写 1 个 Tool (~50 行) + 注册 + Prompt 更新 | 零代码，靠 LLM 知识 |
| 新增 `git cherry-pick` | 同上 | 零代码 |
| 修复 `git diff` 截断 bug | 改 `MAX_DIFF_CHARS` → 1 行 | 调整 Bash 的 `MAX_OUTPUT_CHARS` → 1 行 |
| 跨平台适配 | `_run_git()` 已处理 Windows Git 路径 | Bash 已处理跨平台 ✅ |
| 测试覆盖 | 每个 Tool 需要独立单元测试 | Bash 测试覆盖通用逻辑即可 |

**得分**: Git Tool **3/10**, Bash **8/10** — Git 操作有 150+ 子命令，专用 Tool 永远封装不完。Bash 的维护成本是 O(1)。

### 维度 6: 错误恢复能力 — 权重: **高**

| 场景 | 专用 Git Tool | Bash + Git CLI |
|------|------------|--------------|
| `git diff` 在非 git 目录 | `_run_git` → stderr 原文返回 → LLM 理解 | 相同 | 🟡 持平 |
| `git commit` 时无暂存 | `git` CLI 报错 → Tool 原样返回 | 相同 | 🟡 持平 |
| `git commit --amend` | Tool 不支持此参数 → schema validation reject | Bash 直接执行 | 🟢 Bash |
| 权限被拒（PermissionPipeline DENY） | Tool 不执行，返回 PermissionError | Bash 不执行，返回 PermissionError | 🟡 持平 |
| 自修正循环 | LLM 只能重试相同参数组合 | LLM 可加 `--verbose` / `--no-edit` 等调整 | 🟢 Bash |

**得分**: Git Tool **5/10**, Bash **7/10** — Bash 允许 LLM 自主调整命令重试（这是 ReAct 模式的核心优势）。

---

## 3. 综合得分

| 维度 | 权重 | Git Tool | Bash | 加权胜者 |
|------|------|----------|------|---------|
| LLM 能力匹配度 | 高 (×2) | 3 | 7 | **Bash (+8)** |
| Token 效率 | 高 (×2) | 5 | 5 | 持平 |
| 安全可控性 | 🔴 关键 (×3) | 9 | 3 | **Git Tool (+18)** |
| 输出可解析性 | 中 (×1) | 7 | 4 | Git Tool (+3) |
| 维护与扩展成本 | 中 (×1) | 3 | 8 | Bash (+5) |
| 错误恢复能力 | 高 (×2) | 5 | 7 | Bash (+4) |
| **加权总分** | | **63** | **60** | |

- Git Tool: 3×2 + 5×2 + 9×3 + 7×1 + 3×1 + 5×2 = 6 + 10 + 27 + 7 + 3 + 10 = **63**
- Bash: 7×2 + 5×2 + 3×3 + 4×1 + 8×1 + 7×2 = 14 + 10 + 9 + 4 + 8 + 14 = **59**

---

## 4. 安全红线检查（一票否决项）

| 安全检查 | 当前状态 | 判定 |
|---------|---------|------|
| Bash 是否有文件系统沙箱？ | Docker sandbox 存在但是 **非默认**；默认模式无沙箱 | ⚠️ 不满足默认路径 |
| 是否有危险 Git 命令拦截？ | `_BLOCKED_PATTERNS` 不含 `git push` / `git reset` / `git rebase` | ❌ 不满足 |
| 是否有输出长度截断？ | `MAX_OUTPUT_CHARS = 50,000` ✅ | ✅ |
| 是否有执行超时？ | 默认 30s ✅ | ✅ |
| 是否隔离了 Git 凭证/SSH Key？ | Docker bind mount 暴露完整 `.git` 目录 + SSH agent | ❌ 不满足 |

**红线结论**: 当前安全基础设施**不足以**直接开放 Bash 执行全部 Git 命令。必须补齐 Git 写操作的拦截能力。

---

## 5. 三选一决策

### 🟡 混合模式（推荐）

基于加权得分接近但安全维度决定性的事实：

#### 决策依据

1. **安全红线是真正的决策器**: 评分中 Git Tool 在安全维度以 9:3 大胜，且 Bash 在执行危险 Git 命令时缺少必要的拦截层。在补齐这些之前，全面迁移 Bash 不可行。

2. **但专用 Tool 限制太多**: 4 个 Tool 只覆盖 `status/diff/add/commit` 四个最基础操作。LLM 已知 150+ git 子命令，但被 Tool 可见性锁死。

3. **Bash 已经有 read-only git 前缀白名单**: [shell_tool.py:78-83](tools/shell_tool.py#L78-L83) 已为 11 种 git 只读操作标记为并发安全，这些操作本来就安全。

#### 拆分清单

| 分类 | 操作 | 归属 | 原因 |
|------|------|------|------|
| **保留专用 Tool** | `git_commit` | Git Tool | 🔴 写入 Git 历史，不可逆；必须有结构化 message 参数强制 |
| **保留专用 Tool** | `git_add` | Git Tool | 🟡 暂存是提交的前置步骤；与 `git_commit` 配合 |
| **迁移至 Bash** | `git_status` | 删除 Git Tool → Bash | 🟢 只读 + 已被 `_READ_ONLY_PREFIXES` 白名单覆盖 |
| **迁移至 Bash** | `git_diff` | 删除 Git Tool → Bash | 🟢 只读 + 白名单覆盖。LLM 可以自由加 `--stat` / `--name-only` |
| **Bash 新增白名单** | `git log`, `git stash list`, `git blame` | Bash（无需新 Tool） | 🟢 纯只读，已在白名单中 |
| **Bash 新增拦截** | `git push`, `git reset --hard`, `git rebase`, `git branch -D` | Bash 拦截层 | 🔴 必须在 `_BLOCKED_PATTERNS` 或 PermissionPipeline 层阻断 |

#### 实施步骤

**Step 1: Bash Tool 安全加固（前置依赖）**

```python
# tools/shell_tool.py — 新增 Git 写操作拦截
_GIT_BLOCKED_PATTERNS: tuple[str, ...] = (
    "git push --force",
    "git push -f",
    "git reset --hard",
    "git rebase",
    "git branch -D",
    "git branch --delete",
    "git clean -f",
    "git stash drop",
    "git stash clear",
    "git tag -d",
)

def _check_git_blocked(cmd: str) -> str | None:
    """Block destructive git operations when executed via Bash.
    These operations have dedicated tools or require explicit user consent.
    """
    for pattern in _GIT_BLOCKED_PATTERNS:
        if pattern in cmd.lower():
            return pattern
    return None
```

**Step 2: 从 Bash description 中移除 Git 引导**

```diff
- "For git operations (status, diff, add, commit), use the git_status,
-  git_diff, git_add, git_commit tools instead."
+ "For destructive git operations (commit, add, push, reset), use the
+  dedicated git_commit/git_add tools or request explicit approval."
```

**Step 3: 注册表调整 — 删除 `git_status` 和 `git_diff`**

[entry/bootstrap/registry_factory.py:86-87](entry/bootstrap/registry_factory.py#L86-L87) — 移除这两行注册。保留 `git_add` 和 `git_commit`。

**Step 4: Agent definition 更新**

```python
_DEFAULT_READONLY_TOOLS = frozenset({
    # git_status, git_diff removed — covered by Bash
    "Read", "Glob", "Grep", "file_view", "WebFetch", "WebSearch",
    "Bash", ...
})
_DEFAULT_GENERAL_TOOLS = frozenset({
    # git_status, git_diff removed — covered by Bash
    "git_add", "git_commit",  # kept — structured commit interface
    ...
})
```

**Step 5: 清理死代码**

- 删除 [tools/git_tool.py](tools/git_tool.py) 中的 `GitStatusTool` 和 `GitDiffTool` 类（约 130 行）
- 删除对应的 import 和注册
- 更新 [hitl/settings_loader.py:114-115](hitl/settings_loader.py#L114) 中的引用

#### 预期效果

| 指标 | 迁移前 | 迁移后 |
|------|--------|--------|
| Git Tool 数量 | 4 | 2 (`git_add`, `git_commit`) |
| LLM 可用 Git 操作 | 4 种固定组合 | 11 种只读 + 2 种结构写 + 任意组合 |
| Prompt Schema Token (Git 相关) | ~290 | ~135 (只有 add + commit) |
| 代码量 | 341 行 | ~195 行 |
| 危险 Git 操作防护 | 隐式（Tool 不支持=不能执行） | 显式拦截（`_GIT_BLOCKED_PATTERNS`） |
| 长尾 Git 操作支持 | ❌ 需新增 Tool | ✅ 零代码 |

---

## 6. 备选方案评审

### 🔴 如果选择「维持专用 Tool」

需要额外做的事情：
- 新增 `git_log` / `git_stash` / `git_cherry_pick` 等 8-12 个 Tool → 代码量 ×3
- 每次新增操作都需要：写 Tool 类 + 注册 + 测试 + 更新 agent definition
- Prompt 中 Tool 数量从 26 膨胀到 ~35 → 每次调用浪费 ~500 tokens

### 🟢 如果选择「全面迁移 Bash」

需要先补齐的安全前提（当前不满足）：
- Bash 必须能拦截 `git push` / `git reset --hard` / `git rebase` → 新增 `_GIT_BLOCKED_PATTERNS`
- Docker sandbox 应成为默认模式 → 或至少给出明确警告
- PermissionPipeline 需要增加「Git 写操作 confirm」层 → 工具级审批粒度不足

---

## 7. 结论

**混合模式**是最优解。4 个 Git Tool 中的 2 个（`git_status`, `git_diff`）是过度设计——它们是纯只读操作，Bash 已经为它们标记了并发安全 + 白名单前缀。2 个（`git_add`, `git_commit`）是合理的薄代理层——它们将高频写操作收敛到窄接口，用 PermissionPipeline 现有机制即可安全保护。

这个决策的核心逻辑：**不是「Git 专用 Tool 不好」，而是「Bash 已经有足够的 read-only Git 白名单，不需要为每个只读 git 操作重复造 Tool」**。

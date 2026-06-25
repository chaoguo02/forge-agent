# Langfuse CI 验证接入说明

## 1. 目标

这套 CI 方案解决三件事：

1. 自动执行 `langfuse-validate`，持续验证 Langfuse 观测链路是否可用。
2. 为每次运行产出结构化报告、基线快照和 Markdown 摘要。
3. 支持把当前运行结果与既有基线做回归比较，尽早发现成功率下降或 token 成本异常上升。

---

## 2. 本次新增内容

### 2.1 工作流

- [`.github/workflows/langfuse-validation.yml`](d:\StudyProjects\ProjectBench\forge-agent\.github\workflows\langfuse-validation.yml)

能力：

- 支持 `workflow_dispatch` 手动触发
- 支持定时调度（当前为 UTC `18:00`，即北京时间次日 `02:00`）
- 自动安装依赖并运行 Langfuse 验证脚本
- 自动上传 `.forge-agent/ci/langfuse/` 下的所有产物

### 2.2 CI 包装脚本

- [`scripts/run_langfuse_validation.py`](d:\StudyProjects\ProjectBench\forge-agent\scripts\run_langfuse_validation.py)

能力：

- 调用 `python -m entry.cli langfuse-validate`
- 统一生成：
  - `validation-report.json`
  - `baseline.json`
  - `comparison.json`
  - `summary.md`
  - `stdout.log`
  - `stderr.log`
- 可选基线对比
- 可选 token 回归阈值校验
- 自动写入 GitHub Actions 的 `GITHUB_STEP_SUMMARY`

### 2.3 基线对比工具

- [`observability/ci.py`](d:\StudyProjects\ProjectBench\forge-agent\observability\ci.py)

能力：

- 加载验证报告和基线快照
- 校验场景集合是否一致
- 校验 pass rate 是否劣化
- 校验平均 token 与单场景 token 是否超阈值回归
- 生成 Markdown 摘要与 JSON 对比结果

---

## 3. 需要配置的 GitHub Secrets / Variables

### 3.1 必需 Secrets

至少需要以下 Secrets，具体取决于你实际使用的模型提供方：

- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY` 或 `ANTHROPIC_API_KEY` 或 `GROQ_API_KEY`

### 3.2 推荐 Variables

- `FORGE_LLM_PROVIDER`
- `FORGE_LLM_MODEL`
- `FORGE_LLM_BASE_URL`
- `LANGFUSE_BASE_URL`
- `FORGE_PROMPT_SOURCE`
- `LANGFUSE_PROMPT_LABEL`
- `LANGFUSE_PROMPT_VERSION`

推荐最小配置示例：

```text
FORGE_LLM_PROVIDER=deepseek
FORGE_LLM_MODEL=deepseek-v4-flash
FORGE_LLM_BASE_URL=https://api.deepseek.com
LANGFUSE_BASE_URL=https://cloud.langfuse.com
FORGE_PROMPT_SOURCE=local
LANGFUSE_PROMPT_LABEL=production
```

---

## 4. 本地使用方式

### 4.1 只跑验证并产出报告

```bash
python scripts/run_langfuse_validation.py --repo .
```

默认会在：

```text
.forge-agent/ci/langfuse/<timestamp>/
```

下生成产物。

### 4.2 生成新的基线

```bash
python scripts/run_langfuse_validation.py \
  --repo . \
  --baseline-name nightly-main
```

### 4.3 对比已有基线

```bash
python scripts/run_langfuse_validation.py \
  --repo . \
  --compare-baseline .forge-agent/experiments/langfuse-baselines/nightly-main.json
```

### 4.4 限制 token 回归阈值

```bash
python scripts/run_langfuse_validation.py \
  --repo . \
  --compare-baseline .forge-agent/experiments/langfuse-baselines/nightly-main.json \
  --max-token-regression-pct 0.15
```

表示当前运行的平均 token 和单场景 token 相比基线最多允许上升 `15%`。

---

## 5. CI 使用方式

### 5.1 手动触发

进入 GitHub Actions，选择 `Langfuse Validation` 工作流，填写：

- `scenario`
- `baseline_name`
- `compare_baseline`
- `max_token_regression_pct`

其中：

- `scenario=both` 会同时跑成功场景和失败场景
- `compare_baseline` 可填仓库内基线 JSON 的相对路径
- 不填 `compare_baseline` 时，只做验证，不做回归对比

### 5.2 定时触发

工作流已内置 schedule：

```yaml
schedule:
  - cron: "0 18 * * *"
```

这表示每天 UTC `18:00` 运行，即北京时间次日 `02:00`。

---

## 6. 产物说明

CI 每次运行都会上传 `.forge-agent/ci/langfuse/` 目录作为 artifact，常见文件如下：

- `validation-report.json`
  - 原始验证结果，来自 `langfuse-validate --json-out`
- `baseline.json`
  - 当前运行生成的基线快照
- `comparison.json`
  - 与既有基线的回归对比结果
- `summary.md`
  - 适合人读的 Markdown 摘要
- `stdout.log`
  - CLI 标准输出
- `stderr.log`
  - CLI 错误输出

---

## 7. 基线管理建议

推荐两种策略二选一：

### 策略 A：只保存 artifact

适合前期验证阶段。

特点：

- 不需要在仓库里提交基线文件
- 每次运行后从 artifact 下载最新基线
- 适合快速试验

### 策略 B：提交稳定基线到仓库

适合正式回归阶段。

建议做法：

1. 在主分支挑一组稳定结果作为基线。
2. 把基线 JSON 提交到仓库，例如：

```text
ci/langfuse-baselines/nightly-main.json
```

3. 在工作流触发时填写：

```text
compare_baseline=ci/langfuse-baselines/nightly-main.json
```

这样每次 CI 都会对比当前结果和稳定基线。

---

## 8. 失败判定规则

当前 CI 会在以下情况返回失败：

1. `langfuse-validate` 本身失败
2. 当前验证报告 `all_passed=false`
3. 对比基线时场景集合不一致
4. 当前 pass rate 低于基线
5. 当前平均 token 超过基线允许阈值
6. 当前单场景 token 超过基线允许阈值
7. 当前场景 `actual_status` 与基线不一致

---

## 9. 推荐落地顺序

建议这样推进：

1. 先在本地跑通 `scripts/run_langfuse_validation.py`
2. 再在 GitHub 仓库配置 Secrets / Variables
3. 手动触发一次工作流确认 artifact 和 summary 正常
4. 选择一次稳定结果保存为基线
5. 最后开启 nightly 定时回归

---

## 10. 验证命令

这次新增代码可以用下面的本地命令验证：

```bash
pytest tests/test_langfuse_ci.py tests/test_langfuse_validation.py tests/test_langfuse_observability.py tests/test_langfuse_filtering.py
python -m compileall observability scripts tests/test_langfuse_ci.py
```

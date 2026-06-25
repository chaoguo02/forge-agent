# Langfuse Baselines

将稳定的 Langfuse 验证基线 JSON 放在这个目录下，供 CI 回归对比使用。

建议命名：

- `nightly-main.json`
- `release-2026-06.json`
- `prompt-production-v3.json`

生成方式示例：

```bash
python scripts/run_langfuse_validation.py \
  --repo . \
  --baseline-name nightly-main \
  --baseline-out ci/langfuse-baselines/nightly-main.json
```

CI 手动触发时，可将 `compare_baseline` 设置为：

```text
ci/langfuse-baselines/nightly-main.json
```

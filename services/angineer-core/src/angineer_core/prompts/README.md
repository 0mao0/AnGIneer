# Prompt 资产化约定（P5）

## 用途

本目录是 AnGIneer 全部 prompt 的唯一资产区。源码（`services/**/*.py`）中
不允许出现 `你是一个` / `You are a` 等 prompt 字面量，由
`scripts/audit_prompts.py` 在 CI 中强制审计（白名单仅放行既有未迁移资产）。

## 中英策略（成文）

- **面向用户生成（回答、小结、系统提示）用中文**：dispatcher system prompt、
  QA/COMPLEX 档、SOP 步骤解析、评测对比分析等。
- **结构化提取 / 评测判分沿用英文**：图谱 E1-E5（`docs-core/step07_graph/`）
  与 VERIFY 已验证英文指令效果稳定；智能选工具 / 智能执行（dispatcher 内部）
  同样保持英文，避免行为漂移。
- 新增 prompt 前先判断用途归属，不要混用语言。

## 版本约定

- 每个 prompt 一个常量 + 头部注释：用途 / 语言 / 版本 / 最后变更；
- 常量在模块底部 `register(name, version, text)` 登记；
- **改动 prompt 必须递增版本号**（`v1` → `v2`），禁止原地修改后仍标旧版本；
- `load(name, version="latest")` 加载；`versions()` 返回当前最新版本表，
  dispatcher 结果与 evals prediction 会持久化 `prompt_versions` 供审计；
- 同名同版本重复注册且内容不一致会抛 `ValueError`。

## 迁移清单（2026-08-09 完成）

| 来源 | 目标模块 |
|---|---|
| `dispatcher.py` system/extract/judge/SQL/smart/step-summary | `prompts/dispatcher.py` |
| `classifier.py` 意图分类 / SOP 路由 | `prompts/classifier.py` |
| `agent_configs.py` QA / COMPLEX 档 | `prompts/agent_configs.py` |
| `sop_routes.py` 步骤解析 | `prompts/sop_routes.py` |
| `evals_routes.py` 对比分析 | `prompts/evals_routes.py` |
| `answer_eval.py` 语义评测 | `prompts/answer_eval.py` |

未纳入迁移（白名单）：`sop-core/sop_parser.py`、`engtools` 工具侧、
`docs-core/step07_graph` 图谱 prompt（后续评估归位）。

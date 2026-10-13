# sop-api — SOP 数据面服务

SOP 模块的管理面与工厂：结构化 SOP 的 CRUD、Markdown 导入解析、审核流（draft→reviewed→published/disabled）与审计、文件夹管理、知识图谱路径生成。

## 边界

- 本服务**独占写** `data/platform/sops/`（json/ 为真相源，raw/ 为导入留档，index.json 自动生成）
- SOP **执行**不在本服务：SopRunner 在 angineer-core，由 aichat-api 对话面运行时承载
- 图谱读取走 docs-api HTTP（`/api/graph/*`），不直连 docs-core

## 端口与运行

- 容器：compose 服务 `sop-api`，`127.0.0.1:8792`，与 docs-api/aichat-api 共用 `docker/Dockerfile.backend`（整仓 COPY，无独立镜像层）
- 本地：`cd services/sop-api && uvicorn main:app --port 8792`

## 端点

| 路径 | 用途 |
| --- | --- |
| `GET /api/sops` | 列表（status 过滤） |
| `GET /api/sops/full?status=published` | 全量（含 steps/blackboard；执行面拉取用） |
| `POST /api/sops` / `PUT /api/sops/{id}` / `DELETE /api/sops/{id}` | CRUD（写路径过 validate_sop_data 校验闸） |
| `POST /api/sops/import` | 上传 md，LLM 解析为 draft |
| `POST /api/sops/{id}/review` | approve/reject/disable + 审计落 `audit/*.jsonl` |
| `GET /api/sops/{id}/audit` | 审计流 |
| `POST /api/sops/steps/parse` | 单步描述解析建议（编辑辅助） |
| `POST /api/sops/generate`、`/generate-from-doc` | 知识图谱生成 SOP 骨架（draft） |
| `/api/sops/folders*` | 文件夹树管理 |

## 消费方

- admin-web / user-web 管理页（经 nginx `/api/sops`）
- aichat-api 执行面：`GET /api/sops/full?status=published` 拉取 + 末次快照兜底（`sop_api_client.py`）

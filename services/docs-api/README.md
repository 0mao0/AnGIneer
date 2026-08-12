# docs-api

AnGIneer 文档处理服务：文档解析、知识库、图谱、产物下载与 API Key 管理。

## 启动

```bash
cd services/docs-api
uvicorn main:app --host 0.0.0.0 --port 8790
```

开发热重载：`python main.py`（端口从 `apps/shared/ports.json` 的 `docsApiPort` 读取，默认 8790）。

## 数据依赖

- `data/knowledge_base` — 知识库产物（content.md / images / jsonl / sqlite）
- `data/api_keys.sqlite` — API Key（本服务写入，aichat-api 只读）
- `data/parse_records.sqlite` — 解析记录与统计

两个服务共享 `data/` 数据卷；SQLite 均为 WAL 模式。本服务只写 api_keys / knowledge 相关库，禁止与 aichat-api 同时写同一文件。

## 认证

- 仅 `/api/v1/*` 校验 `X-API-Key`；`/api/knowledge`、`/api/graph`、`/api/api-keys` 等内部接口免认证。
- Key scope：`doc` 或 `both` 可访问；`chat` 仅能访问 aichat-api 的 v1 接口（当前 aichat-api 无 v1 路由）。
- 缺少/无效/scope 不匹配时分别返回 401 / 403（JSON detail）。

## 对外产物契约

`/api/v1/documents/{doc_id}/artifacts` 可下载：

- `content.md`
- `images.zip`
- `doc_blocks_graph.jsonl` / `doc_blocks_graph_meta.json`
- `index.sqlite`
- `graph.sqlite`

## 迁移说明

`api_keys` 表的 `scope` 列由 `models/api_key.init_db()` 自动补齐（旧行默认 `both`）。

## 错误响应

本服务不迁移原单体服务的全局异常处理器，错误返回 FastAPI 默认 4xx/5xx 形态。

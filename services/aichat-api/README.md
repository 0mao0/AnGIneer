# aichat-api

AnGIneer AI 问答服务：Agent 多轮会话（SSE）、模型配置、SOP、Evals 与 Dream Cycle。

## 启动

```bash
cd services/aichat-api
uvicorn main:app --host 0.0.0.0 --port 8791
```

开发热重载：`python main.py`（端口从 `apps/shared/ports.json` 的 `aichatApiPort` 读取，默认 8791）。

## 数据依赖

- 只读：`data/knowledge_base` 与 `data/knowledge_*.sqlite`（docs-api 写入）
- 读写：`data/sops`（SOP raw/json/index）、`data/evals/evals.sqlite`、`data/reports/*.json`（Dream Cycle 报告）

禁止与 docs-api 同时写同一 sqlite 文件。

## 认证

- 中间件按 `chat` scope 配置，但当前仅校验 `/api/v1/*`；aichat-api 暂无 v1 路由，因此内部 `/api/*` 免认证。
- 将来收紧为全量校验时，需配套前端 X-API-Key 注入与 `/api/api-keys` 豁免。

## SSE 事件契约

`POST /api/chat/agent` 返回 `text/event-stream`，每帧为 `data: <json>\n\n`：

- `run_start`
- `tool_start` / `tool_end`
- `note`
- `answer`
- `message_delta`
- `run_end`
- `error`

流结束以 `data: [DONE]` 收尾。

## 会话说明

AgentSession 会话池为进程内存态（`chat_agent.py`），单实例部署，重启后会话丢失。

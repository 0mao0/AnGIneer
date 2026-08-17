# Changelog

## 0.1.0（对外发布基线）

本版本为面向外部消费方（DredgeAI）发布的首个稳定基线，改动均向后兼容：

### 新增
- 异步 API：`achat` / `achat_result` / `achat_stream` / `achat_stream_events` / `achat_result_guarded`（基于 `AsyncOpenAI`）。
- 超时四段完整生效：`connect` / `read` / `write` / `pool` 通过 `httpx.Timeout` 传入（新增 `ANGINEER_TIMEOUT_WRITE` / `ANGINEER_TIMEOUT_POOL`）。
- 统一错误层级：`LLMError` 基类 + `ProviderUnavailableError` / `ProviderAuthError` / `RateLimitedError` / `LLMStreamError` / `AllProvidersFailedError`（`errors.py`）。
- `ChatResult` 元数据：`latency_seconds` / `attempts` / `used_config` / `used_model` / `circuit_breaker_state`。
- 可选用量回调 `usage_callback`（不落库，回调异常不影响请求）。
- 熔断可观测：`success_count` / `total_calls` / `last_error_message` / `last_success_time`。
- `messages` / `tools` 输入校验（Pydantic），非法输入尽早抛 `ValueError`。
- 流式语义固化：首个 delta 前失败 → 换 Provider；已产出后失败 → `stream_failed` 事件 / `LLMStreamError`（携带 partial text）。
- 模块级单例 `get_llm_client()` 线程安全初始化。
- 依赖清理：移除 fastapi / uvicorn / python-multipart；显式声明 httpx。HTTP 运行时依赖移至 `aichat-api` / `docs-api`（各自新增 pyproject，Dockerfile 同步更新）。
- 包内测试由 2 个扩至 66 个；新增 README 与 CHANGELOG。

### 行为变更
- `default_model` 改为"优先排序"而非"钉死"：默认 Provider 失败时会 fallback 到其他可用 Provider；显式 `config_name` / `model` 仍严格过滤。
- 单 Provider 失败时直接抛出精确错误（如 `RateLimitedError`）；多个 Provider 全部失败才抛 `AllProvidersFailedError`。
- `chat_stream_events` 的 `done` 事件增加元数据字段（`used_config` 等）。
- `_prepare_messages` 不再修改调用方传入的 `messages`（内部浅拷贝）。

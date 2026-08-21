# AnGIneer LLM 网关（ai-inference）技术说明

> AI 推理的唯一真相源，零外部依赖。所有模型配置从 `.env` 的 `LLM_CONFIGS`（JSON）加载，
> 上层服务统一 `from ai_inference import ...`，不经过 angineer-core 中转。

## 1. 配置模型

`.env`：

```env
LLM_CONFIGS=[{"name":"Qwen3.6-A3B","model":"Qwen3.6-35B-A3B-FP8","api_key":"...","base_url":"https://ai.bim-ace.com/chat/v1","enabled":true,"priority":10}, ...]
ANGINEER_DEFAULT_MODEL=Qwen3.6-35B-A3B
ANGINEER_MAX_TOKENS=16384
ANGINEER_TEMPERATURE=0.1
ANGINEER_TIMEOUT_CONNECT=10
ANGINEER_TIMEOUT_READ=60
ANGINEER_TIMEOUT_TOTAL=120
ANGINEER_MAX_RETRIES=3
ANGINEER_CB_FAILURE_THRESHOLD=5
ANGINEER_CB_RECOVERY_TIMEOUT=60
```

字段：`name`（配置名）、`model`（上游模型名）、`api_key`、`base_url`、
`enabled`、`priority`（同优先级倒序取用）。

## 2. 多模型与供应商

当前示例配置：

| 配置名 | 供应商 | 用途 |
| :--- | :--- | :--- |
| Qwen3.6-A3B | ai.bim-ace.com 私有网关 | 默认问答/解析 |
| Qwen2.5-7B | siliconflow | 备用 |
| Nemotron-30B | NVIDIA | 备用 |
| Qwen3-4B / Qwen3.6-Plus | DashScope | 备用 |
| DeepseekV4-Pro / Flash | api.deepseek.com | 可选 |

## 3. 客户端能力（llm_client.py）

- `chat` / `stream_chat`：OpenAI 兼容协议；
- `chat_result_guarded`：带重试、熔断、响应解析；
- 重试：指数退避（`ANGINEER_RETRY_INITIAL_DELAY / MAX_DELAY / EXPONENTIAL_BASE`）；
- 熔断：失败阈值 + 恢复窗口（`ANGINEER_CB_*`）；
- 超时：connect/read/total 三级；
- 日志：不打印完整 api_key（`"***"`），base_url 与 model 正常记录；
- 模式：`instruct`（文本）与流式输出。

## 4. 响应解析

- `extract_json_from_text(strict=True)`：剥离 ```json 围栏，解析 JSON；
- `llm_response_parser` 提供统一异常类型，供分类器/守卫复用。

## 5. 降级策略

| 服务 | 故障表现 | 降级 |
| :--- | :--- | :--- |
| Embedding（bge-m3） | 502 | 回退 hash embedding，融合权重降为 0.05 |
| Reranker | 502 | 回退本地 phrase rerank |
| 主模型 | 超时/失败 | 重试 → 熔断 → 上层报错/拒答 |
| PoPo LLM | 不可用 | PoPo 阶段 soft 失败，保留核心产物 |

> 注意：`api.openai.com` 在国内被 DNS 污染，PoPo 子模块必须使用环境变量
> `POPO_VLLM_URL / POPO_VLLM_API_KEY / POPO_MODEL_NAME`（见 AGENTS.md）。

## 6. Prompt 资产化

- 唯一资产区：`services/angineer-core/src/angineer_core/prompts/`；
- 每个 prompt 带版本号并 `register(name, version, text)`；
- 改动 prompt 必须升版本，`scripts/audit_prompts.py` CI 强制审计。

## 7. 关键代码锚点

- `services/ai-inference/src/ai_inference/llm_config.py`（LLM_CONFIGS 解析）
- `services/ai-inference/src/ai_inference/llm_client.py`（客户端）
- `services/ai-inference/src/ai_inference/llm_response_parser.py`（响应解析）
- `services/angineer-core/src/angineer_core/base_config.py`（Reranker/全局配置）
- 认证与 scope：`services/docs-api/middleware/api_key_auth.py`

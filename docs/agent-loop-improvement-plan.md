# AnGIneer Agent 化实施计划（详细版）

> 状态：待评审
> 理论依据：[pi-agent book](https://books.antinomie.org/pi/)（`@earendil-works/pi-agent-core` 架构解读，基线 commit `cd20a8d2e`）
> 前置文档：本文是实施级版本，替代原 224 行纲要
> 约束：本文件只出方案不含代码改动；每个阶段独立可交付、可用 feature flag 回退
> 代码基线：文中所有行号对应当前工作区，实施时以文件内容为准

---

# 第一部分 · 战略

## 1. π 理论浓缩（判断依据）

| # | 原则 | 出处 |
|---|------|------|
| P1 | **单一循环原语 + 组合出复杂功能**。`Agent` 与 `AgentHarness` 都直接调用同一个无状态 `runAgentLoop`，复杂度在 config 层不在循环里 | 第 1 章「三层而不是一层」 |
| P2 | **边界即设计**。循环不认识模型厂商（只依赖 `StreamFn` 函数形状）、不碰 UI（只发可辨识联合事件）、核心不持久化 | 第 1 章「四条拒绝」 |
| P3 | **循环退出主动权在模型**：不再产 toolCall 即停；`terminate` 旗需整批全票、只是省一轮 LLM 调用的优化；不设内置 max_turns，策略经 `shouldStopAfterTurn` 留给宿主 | 第 2 章「三种停法」 |
| P4 | **失败变成值**。工具异常 → `isError: true` 的结构化结果喂回模型；事件序列永不被异常打断 | 第 2 章「执行工具」 |
| P5 | **截断守卫**。`stopReason: "length"` 时整批工具调用一个不执行——抢救回来的 JSON 可能"悄悄不完整" | 第 2 章「执行工具」入口守卫 |
| P6 | **决策点显式化**。`steer`（中途插队）与 `followUp`（结束后续命）两条队列两种语义；`shouldStopAfterTurn`（turn 边界优雅停）与 `abort`（无条件停整个 run）两种粒度 | 第 2 章「为什么不去」 |
| P7 | **两道闸门**。`transformContext`（agent 消息→agent 消息）→ `convertToLlm`（agent 消息→LLM 三角色），翻译只发生在 LLM 调用边界 | 第 2 章「调模型」 |

## 2. 总判断

- **不全盘 agent 化**：定位（"人定 SOP，精确执行"）+ 工程域（可审计）+ SLM 约束决定了供给侧保持确定性管线。
- **一个循环原语、两档 config**（P1）：知识问答档（只读检索工具，≤3 轮）与大题档（+SOP 执行/计算器，≤8 轮）共用同一份循环代码。
- **先止血、再立新、后拆旧**：P0/P1 修现有安全缺口；P2 新建循环模块不碰旧代码；P6 最后才拆 dispatcher。

---

# 第二部分 · 现状精确诊断

## 3. 问题清单（含本轮新发现的硬 bug）

### 3.1 安全与正确性缺口

| # | 问题 | 证据（逐字核实） | 违反 |
|---|------|------|------|
| Q1 | **截断输出被静默 salvage 当成功**：全库 grep `finish_reason` 零匹配；`extract_json_from_text`（`llm_response_parser.py:35`）对截断 JSON 尽力修复后按成功返回；`_try_fix_json`（L78-88）甚至做 `content.replace("'", '"')` 暴力替换，会损坏字符串内撇号 | `services/ai-inference/src/ai_inference/llm_response_parser.py` | P5 |
| Q2 | **`chat_stream` 拿不到 `finish_reason`/`usage`**：`_call_openai_stream`（L325-356）只 yield `delta.content`，结束 chunk 的 `finish_reason` 被丢弃；且**无重试**（`chat_stream` L466 直接调 `_call_openai_stream`，绕过 `_call_with_retry`）、**无 `max_tokens` 参数**（固定用 `self._config.max_tokens`，L349） | `llm_client.py:325-356, 425-489` | P5、P4 |
| Q3 | **SOP 无审核闸门**：`SOP`/`Step` 模型无 status 字段（`base_contracts.py:20-47`）；`sop_routes.py` 有完整 CRUD + `/generate-from-doc`（L721）但无 review 端点；图谱有 `POST /api/graph/review`（`graph_routes.py:172`）而 SOP 没有对应物；LLM 生成的 SOP 经 `save_generated_sop`（`sop_loader.py:271`）落盘即进可执行库 | — | 安全缺口 |
| Q4 | **工具超时是假超时**：`_execute_tool_safe`（`dispatcher.py:2332-2413`）用 `ThreadPoolExecutor` + `future.result(timeout=120)`，超时后**底层线程不会被杀死**；且 `with ThreadPoolExecutor` 退出时 `shutdown(wait=True)` 会**阻塞等待线程跑完**——超时后调用方仍被挂住，等于假超时变成真等待；`TimeoutError` 被外层 `except Exception` 吞掉记为步骤错误；`llm_generate` 元工具（L2334-2353）**不受此超时保护** | `dispatcher.py` | P4（修复提前到 P0.1/P2，见 §6.3） |

### 3.2 架构缺口

| # | 问题 | 证据 |
|---|------|------|
| Q5 | **无 agent 循环，L4 名不副实**：`dynamic_orchestration` 与 `semantic_retrieval` 走同一分支（`dispatcher.py:350`），L4 实为 `_dispatch_semantic(enforce_evidence=False)`，无任何编排逻辑；全库无 tool calling | `dispatcher.py:350-363` |
| Q6 | **dispatcher.py 3003 行三层焊死**：意图、prompt 拼装（`_build_system_prompt` L1466-1538）、SOP 执行引擎（`run_sop` L2090、`_execute_step` L2172）、记忆、重排、引用校验全在一类 | `dispatcher.py` |
| Q7 | **dispatcher 完全无流式**：所有 LLM 调用是同步 `llm.chat(...)` 整包返回；`contracts.py:43` 声明了 `chat_stream` Protocol 但**零调用方**；前端"逐步展示"靠 `stage_callback`/`step_callback` 模拟 | `dispatcher.py`、`contracts.py` |
| Q8 | **两套聊天接口格式分裂**：`/chat/stream`（`main.py:390`）同步 NDJSON（routing/start/step/done/nomatch）；`/api/chat`（`main.py:454`）异步 SSE（start/chunk/end/error）——前端两套解析 | `main.py` |

### 3.3 本轮新发现的硬 bug（顺手修，见 P0）

| # | bug | 位置 |
|---|-----|------|
| B1 | `DocsRetrievalTool.run` 调 `fuse_candidates(dense_hits, sparse_hits, top_k=top_k)` 与真实签名 `fuse_candidates(source_candidates: Dict[str, List[RetrievedItem]], task_type, top_k, ...)` 不符，**调用必抛 TypeError，该工具实质不可用** | `engtools/DocsRetrievalTool.py:45` |
| B2 | `ConditionalTool` table_lookup 分支 `from .TableTool import TableTool`——`TableTool.py` 中不存在该类（只有 `TableLookupTool`），触发即 ImportError | `engtools/ConditionalTool.py:316` |
| B3 | SOP 路由双阈值：classifier 拒绝阈值 0.45（`classifier.py:46,1073`）vs dispatcher 执行门槛 0.6（`dispatcher.py:1072`），0.45~0.6 区间的路由结果语义未定义 | 两处 |
| B4 | dispatcher 模块 docstring 说 `run()` 是 SOP 执行引擎，实际方法名 `run_sop()`（L2090）；`_dispatch_semantic` 注解声明返回 7 元组实际返回 8 元组（L1159 vs L1263/L1387） | `dispatcher.py:1-12, 1159` |
| B5 | `main.py:217` 的 `SOPUpdate` 是死代码（仅有定义无任何引用，实际更新走 `sop_routes.SopUpdateRequest`） | `main.py:217-220` |
| B6 | `LLMClient.configs` 属性（`llm_client.py:200-213`）返回含 `api_key` 明文的配置列表——当前 `/api/llm_configs` 已脱敏（只返回 name/model/configured），属**潜在风险面**：属性本身暴露明文，任何新调用方都可能误透传 | `llm_client.py`、`main.py` |
| B7 | `chat` 返回 `response.choices[0].message.content`（L323）无 None 防护；`llm_client` 模块级代理通不过 `isinstance` 检查 | `llm_client.py:323, 551-562` |

### 3.4 工程化缺口

| # | 问题 | 证据 |
|---|------|------|
| Q9 | Prompt 散落 20+ 文件、中英混用、无版本管理；路由层临时 prompt：`evals_routes.py:282-298`（裸 Dict body + 函数内 import + f-string）、`sop_routes.py:353-387` | grep |
| Q10 | 无取消语义：`/api/chat` SSE 断连后 LLM 请求继续跑完才丢弃；无 token 预算、无上下文压缩路径 | `main.py:454-533` |
| Q11 | PoPo 子模块裸 `while cnt<5` + `print(e)` 重试，与主仓熔断体系不一致（改动须按 `AGENTS.md` 先在子模块内 commit） | `popo/post_processing/model_utils.py` |

## 4. 已是正确方向、直接复用的资产

| 资产 | 位置 | 复用方式 |
|---|---|---|
| 统一 LLM 客户端（熔断/failover/重试） | `llm_client.py` | ≈ π 的 `StreamFn` 层，循环只依赖它（P2）；P0 补齐 finish_reason/usage |
| 五路检索 + RRF 融合 | `step09_query/retrieval/`（dense/sparse/table/clause/formula + `fuse_candidates`，RRF_K=60） | P3 包装为循环的只读工具 |
| 检索契约模型 | `step09_query/protocols/contracts.py`（`KnowledgeQueryRequest`/`RetrievedItem`/`KnowledgeCitation` 等） | 工具返回结构直接复用 |
| 图谱三闸门验证 + 人工 review | `step07_graph`、`graph_routes.py:172` | P1 SOP 审核的参照样板 |
| 分类器（规则+LLM 双引擎、0.5 置信度回退） | `classifier.py:784-1114` | 保留不动；L1/L4 意图照旧分流 |
| evals 已持久化 `system_prompt` | `answer_eval.py:229`、`suite_runner.py:337` | P5 prompt 版本化自然衔接 |
| SOP 执行引擎（黑板、`${var}` 解析、步骤回调） | `dispatcher.py:run_sop/_execute_step`、`memory.py` | P4 下沉为"SOP 执行工具"内调用 |
| 注入契约 Protocol | `contracts.py`（KnowledgeProvider/SopProvider/LLMProvider） | 循环模块只依赖 Protocol |

---

# 第三部分 · 目标架构设计

## 5. 模块布局与依赖方向

```
services/angineer-core/src/angineer_core/
├── agent_events.py        【新】事件可辨识联合（P2）
├── agent_messages.py      【新】消息与工具调用数据模型
├── agent_loop.py          【新】无状态循环原语（P1/P3/P4/P5/P7）
├── agent_session.py       【新】有状态包装：队列、取消、结算（P6）
├── agent_tools.py         【新】工具契约 + BaseTool/检索器适配层
├── agent_configs.py       【新】两档 config 装配（知识问答档/大题档）
├── tool_codec.py          【新】工具调用协议编解码（文本 JSON / native 两种）
├── prompts/               【新，P5】统一 prompt 模块
├── sop_runner.py          【P6 从 dispatcher 下沉】SOP 步骤执行引擎
├── classifier.py          【不动】
├── dispatcher.py          【P6 瘦身】
└── ...（现有文件）
```

依赖方向（单向，不可逆）：

```
api-server (HTTP/SSE 协议转换)
   → agent_session (有状态)
      → agent_loop (无状态)
         → tool_codec / agent_tools / contracts.Protocol
            → llm_client (StreamFn 等价物)
            → step09_query 检索器 / engtools / sop_runner
```

**关键约束**：`agent_loop.py` 只允许 import `agent_messages`/`agent_events`/`agent_tools`/`tool_codec`/`contracts`，**不允许** import dispatcher、classifier、memory、api-server 任何东西（P2 边界）。

## 6. 核心数据模型

### 6.1 消息模型（`agent_messages.py`）

现状锚点：`llm_client.chat(messages: List[Dict])` 直接透传 OpenAI 格式。因此 agent 侧消息用轻量 dataclass，**边界上**经 `to_llm_messages()` 翻译（P7 第二道闸门）：

```python
@dataclass
class ToolCall:
    id: str            # 循环侧生成：f"call_{turn}_{seq}"
    name: str
    arguments: Dict[str, Any]

@dataclass
class AgentMessage:
    role: str                      # "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None   # role="tool" 时回指
    name: Optional[str] = None           # role="tool" 时的工具名
    is_error: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)  # citations/timings 等，不下发 LLM

def to_llm_messages(messages: List[AgentMessage]) -> List[Dict[str, Any]]:
    """P7 第二道闸门。tool 结果序列化为 role="tool"（native 模式）
    或 role="user" 包装（文本协议模式，由 codec 决定）。"""
```

设计要点：

- **SLM 不用 thinking 块**：现有客户端对 dashscope/aliyun 强制 `enable_thinking=False`（`llm_client.py:311-312`），消息模型不为 thinking 开字段，避免死代码。
- `meta` 不下发：citations、检索 debug 只进事件和最终响应，不进 LLM 上下文（省 token + 防模型误读）。

### 6.2 事件模型（`agent_events.py`）

镜像 π 的十种事件、四个层级（P2），用 pydantic 以便 SSE 直接 `.model_dump_json()`：

```python
class AgentEvent(BaseModel):
    type: str
    run_id: str
    turn: int = 0
    ts: float = Field(default_factory=time.time)
    payload: Dict[str, Any] = Field(default_factory=dict)

# type 枚举（可辨识联合，文档即协议）：
#   run_start / run_end              —— run 级；run_end.payload 含 messages、reason
#   turn_start / turn_end            —— turn 级；turn_end.payload 含 tool_results 摘要
#   message_start / message_delta / message_end
#       —— message_delta.payload.delta 是文本增量（对接 chat_stream）
#   tool_start / tool_end            —— tool 级；含 call_id、name、args（start）、
#                                      is_error、result 摘要（end）
#   error                            —— 致命错误（run 中止）
```

与 π 的两处有意差异（写明理由）：

1. 合并 `message_update` 为 `message_delta`：π 的 update 携带全量 partial 快照是为了 UI 就地替换；我们前端是追加渲染（`/api/chat` 现状就是 chunk 追加），增量即可。
2. 增加 `run_end.payload.reason`：取值 `completed | max_turns | cancelled | error | terminated`，把五种停法显式暴露给前端和 evals。

### 6.3 工具契约（`agent_tools.py`）

现状锚点：`BaseTool`（`BaseTool.py:5-27`）只有 `name/description_en/description_zh` + 抽象 `run(**kwargs)`；`ToolRegistry` 类级注册表。循环层不改动 engtools，加适配层：

```python
@dataclass
class AgentTool:
    name: str
    description: str                 # 给模型看的中文描述
    parameters_schema: Dict[str, Any]  # JSON Schema，进 prompt / 校验
    handler: Callable[..., Dict[str, Any]]  # 实际执行体
    read_only: bool = False          # 检索类 True；权限与审计用
    execution_mode: str = "parallel" # parallel | sequential（P4 决策点预留）
    timeout_s: int = 120             # 覆盖 _TOOL_EXEC_TIMEOUT_SECONDS 默认值

@dataclass
class ToolResult:
    call_id: str
    name: str
    content: str                     # 喂回模型的文本（JSON 序列化）
    is_error: bool = False
    terminate: bool = False          # P3 举旗：整批全票才提前停
    raw: Dict[str, Any] = field(default_factory=dict)  # citations 等，进 meta 不进 content
```

**执行语义硬性规定**（P4）：

- `handler` 抛任何异常 → catch → `ToolResult(is_error=True, content=f"工具执行失败: {e}")`，循环继续；
- 参数不过 `parameters_schema`（用 `jsonschema` 校验）→ `is_error=True` 并附校验错误文本，让模型自行修正重发；
- 超时：沿用线程池方案但**如实记录**"线程未杀死"的限制，超时结果 `is_error=True`；**必须**在超时后立即放弃等待——`executor.shutdown(wait=False, cancel_futures=True)` 或独立长驻线程池，**禁止** `with ThreadPoolExecutor` 原样退出（其默认 `shutdown(wait=True)` 会阻塞到线程跑完，超时后调用方仍被挂住，即 Q4 的真实危害）；彻底解需 `multiprocessing`，P6 评估。

### 6.4 循环配置（`agent_loop.py`）

```python
@dataclass
class AgentLoopConfig:
    # —— 模型出口（P2：循环只认 LLMProvider Protocol，不认厂商）——
    llm: Any                              # 满足 contracts.LLMProvider
    model: Optional[str] = None
    config_name: Optional[str] = None
    mode: str = "instruct"
    max_tokens: Optional[int] = None
    # —— 行为 ——
    tools: List[AgentTool] = field(default_factory=list)
    system_prompt: str = ""
    codec: Any = None                     # ToolCallCodec，默认 TextToolCallCodec
    max_turns: int = 3                    # 宿主策略（π 把 max_turns 留给宿主，我们显式化）
    # —— 闸门与决策点（全部可选回调，P6/P7）——
    transform_context: Optional[Callable[[List[AgentMessage]], List[AgentMessage]]] = None
    should_stop_after_turn: Optional[Callable[[TurnContext], bool]] = None
    before_tool_call: Optional[Callable[[AgentTool, Dict], Optional[str]]] = None   # 返回 str 即拦截理由
    after_tool_call: Optional[Callable[[ToolResult], ToolResult]] = None
    tool_timeout_s: int = 120
```

## 7. 工具调用协议（`tool_codec.py`）——本方案最关键的一个决策

**问题**：π 依赖模型的原生 tool calling；我们的 SLM 端点是 OpenAI 兼容 chat，dashscope 等对 `tools=` 支持不一，且现状全库未用 native tool calling。让 SLM 可靠产出工具调用，需要协议层抽象。

**设计**：`ToolCallCodec` 两个实现，循环对两者无感：

```python
class ToolCallCodec(Protocol):
    def augment_system_prompt(self, base: str, tools: List[AgentTool]) -> str: ...
    def parse_assistant(self, text: str) -> Tuple[str, List[ToolCall]]:
        """返回 (纯文本部分, 工具调用列表)。空列表 = 模型没要工具 = 循环正常停（P3）"""
```

**实现一（默认）`TextToolCallCodec`**：ReAct 式文本协议——

- system prompt 追加工具清单（名称/描述/参数 schema）+ 输出协议：
  - 要调工具：输出 ` ```tool_calls\n[{"name": "...", "arguments": {...}}]\n``` `，可多个；
  - 要作答：直接输出答案文本（不含 tool_calls 块即停）。
- `parse_assistant` 用 `extract_json_from_text` 同款思路解析 tool_calls 块，但**解析失败不 salvage**——直接整轮当纯文本答案处理并记 debug（fail-open 向答案侧，比误执行工具安全）。
- `tool_call_id` 循环侧生成（SLM 不会产出可靠 id）。

**实现二（可选）`NativeToolCallCodec`**：走 `tools=` 参数。需要 `llm_client` 支持传 `tools` 并返回 `message.tool_calls`（落地任务：P0.1 任务 7；默认不启用；仅当某端点验证支持后按 config_name 白名单启用）。

**选择默认文本协议的理由**：对一切 OpenAI 兼容端点可用、与现有 prompt 工程能力同构、调试时人可读；代价是多花少量 prompt token。

---

# 第四部分 · 分阶段实施

## P0 · 止血修复（1~2 天）

> 目标：截断不再静默撒谎；顺手修 7 个硬 bug。全部改动局限在 `ai-inference`、`engtools` 与 `angineer-core/contracts.py`（协议同步），不碰调度逻辑。

### P0.1 `llm_client` 扩展（`llm_client.py`）

| 任务 | 内容 |
|---|---|
| 1 | 新增 `@dataclass ChatResult: text: str; finish_reason: Optional[str]; usage: Optional[Dict]`——**实际落位**：定义在 `ai_inference/llm_client.py`（依赖方向为 angineer-core → ai-inference，避免循环）；`contracts.py` 的 LLMProvider 只声明协议方法（返回类型 Any），`agent_loop` 无需反向依赖 ai-inference |
| 2 | 新增 `chat_result(self, messages, temperature=None, model=None, mode="instruct", config_name=None, max_tokens=None) -> ChatResult`：与 `chat` 同走重试/熔断/failover，但返回完整结果；`chat()` 改为薄包装 `return self.chat_result(...).text or ""`（顺带修 B7 的 None 防护），**签名不变、向后兼容** |
| 3 | `_call_openai_stream` 改造：改为新增 `chat_stream_events(...) -> Generator[Dict, None, None]`，yield `{"type": "delta", "text": ...}` / `{"type": "done", "finish_reason": ..., "usage": ...}`；原 `chat_stream()` 保持纯文本 yield（兼容 `/api/chat`），内部调 events 版只取 delta。**兼容细节**：请求带 `stream_options={"include_usage": True}` 获取 usage；兼容"末 chunk 只有 usage 无 choices"（dashscope 等端点常见）与"端点不支持 include_usage 时 usage 为 None"两种形态，finish_reason 取最后一个带 choices 的 chunk |
| 4 | `chat_stream_events` 增加 `max_tokens` 参数（修 Q2 缺参） |
| 5 | `LLMClient.configs` 属性输出侧脱敏：`api_key` 替换为 `***`（修 B6；当前 `/api/llm_configs` 已脱敏，重点防属性本身暴露给新调用方） |
| 6 | `contracts.py` 的 `LLMProvider` 同步增加 `chat_result`/`chat_stream_events` 方法（返回类型见任务 1）——否则 P2 循环"只认 Protocol"拿不到 `finish_reason`/`usage` |
| 7 | `llm_client` 增加可选 `tools: Optional[List[Dict]]` 透传（`chat`/`chat_result`/`chat_stream_events` 均支持），并在 `ChatResult`/`done` 事件中携带 `message.tool_calls`；默认不启用，按 config_name 白名单启用——R3 的 native codec 落地载体（§7） |

### P0.2 截断守卫

| 任务 | 内容 |
|---|---|
| 8 | 新增 `class LLMTruncatedError(Exception)`，携带 `partial_text`；约定：所有**结构化输出**调用点在 `finish_reason == "length"` 时抛它 |
| 9 | 改造点（逐一过）：`classifier.py` 分类与路由两处 JSON 调用、`sop_path_generator.py`、`sop_parser.py`、`step07_graph` 各提取器、`answer_eval.py` 的 LLM judge、`_smart_step_execution`（`dispatcher.py:2519-2593`）。统一模式：`result = llm.chat_result(...); if result.finish_reason == "length": raise LLMTruncatedError(...)`，上层 catch 后按"缩短输入重试一次 → 仍截断则显式失败"处理 |
| 10 | `extract_json_from_text` 增加 `strict: bool = False` 参数；`strict=True` 时跳过 `_try_fix_json` salvage 直接抛 `ParseError`。上述结构化调用点全部改 strict。**删除或修复** `_try_fix_json` 的 `replace("'", '"')`（L86）——至少改为只替换键名位置的引号 |
| 11 | evals 侧注意：`parse_and_validate(strict=False)` 失败退化为 `{}`（L99-103）的行为在 judge 场景会把"解析失败"变成"空结果 0 分"，judge 改用 strict 并把解析失败计入 `semantic_fallback`（现有字段，L140-146 已有此语义，接上线即可） |

### P0.3 顺手修硬 bug

| # | 修复 |
|---|---|
| B1 | `DocsRetrievalTool.py:45`：改 `fuse_candidates({"dense": dense_hits, "sparse": sparse_hits}, task_type="content_qa", top_k=top_k)`，并对照 `dispatcher.py:1212-1226` 的组装方式补齐 `source_kind` 分桶 |
| B2 | `ConditionalTool.py:316`：`from .TableTool import TableLookupTool`，调用处类名同步改 |
| B3 | 阈值统一：dispatcher 执行门槛与 classifier 拒绝阈值收敛为一个常量（建议 0.5，先跑 evals 对比 0.45/0.5/0.6 三档再定），写入 `base_config.py` |
| B4 | 修正 dispatcher docstring（`run()`→`run_sop()`）与 `_dispatch_semantic` 返回注解（7→8 元组） |
| B5 | 删除 `main.py:217` 死代码 `SOPUpdate` |

### P0 测试与验收

- 新增 `tests/ai-inference/test_truncation.py`：mock OpenAI 客户端返回 `finish_reason="length"` + 半截 JSON，断言上层收到 `LLMTruncatedError` 而非残缺 dict；`strict=True` 下 salvage 不触发。
- B1/B2 修复后各补一个冒烟测试（`DocsRetrievalTool.run` 对测试库能返回 items；`ConditionalTool` table_lookup 分支不抛 ImportError）。
- **回归**：`POST /api/evals/runs` 跑 `reviewed-exam-2020-2019` 数据集（库中实际 ID；`exam-harbor-2019-2020` 仅是数据文件名，未注册为库 ID），分数不低于 P0 前基线。
- 回退：全部为新增方法/参数默认值，回退 = revert。

## P1 · SOP 审核闸门（3~5 天）

> 目标：LLM 生成的 SOP 未经审核不得进入答题链路。参照物：图谱三闸门 + `graph_routes.py:172` 人工 review。

### P1.1 数据模型（`base_contracts.py`）

```python
class SOP(BaseModel):
    # ... 现有字段 ...
    status: Literal["draft", "reviewed", "published", "disabled"] = "draft"
    confidence: float = 0.0              # 生成侧自评，预留
    source: Dict[str, Any] = Field(default_factory=dict)  # {"kind": "graph"|"import"|"manual", "doc_id": ..., "framework": ...}
    review: Dict[str, Any] = Field(default_factory=dict)  # {"reviewer": ..., "note": ..., "at": ...}
    stats: Dict[str, Any] = Field(default_factory=dict)   # {"runs": 0, "success": 0, "last_status": ...}
```

**兼容**：`sop_loader._load_json_sop`（L240-269）读旧 JSON 时 `status` 缺省 → `"published"`（grandfather 存量），新生成显式 `"draft"`。

### P1.2 结构校验器（新文件 `sop-core/src/sop_core/sop_validator.py`）

`validate_sop(sop: SOP) -> List[str]`（返回问题列表，空 = 通过），规则：

1. `steps` 非空；`id` 全局唯一；
2. `next_step_id` 非空时必须指向存在的 step；沿 `next_step_id` 链无环（现状 `run_sop` 是线性遍历未用此字段，但校验先行，P6 启用图执行时数据已干净）；
3. `tool` 必须命中 `ToolRegistry`（`sop_loader._is_known_tool` 已有判定逻辑，迁移过来）；`auto` 只允许显式声明 `analysis_status != "analyzed"` 的步骤；
4. `inputs`/`outputs` 为 dict；`blackboard.required` 每个键必须能由初始上下文或某步 `outputs` 提供（闭包检查）；
5. `description.content` 非空（sop_routes 已强制 `{content, citations[]}` 结构，校验对齐）。

**挂接点**：`SopPathGenerator` 落盘前（`save_generated_sop` 内）与 `sop_routes.py` 的 POST/PUT 入口统一调用；不通过 → 拒收并返回问题列表（生成侧）或 422（API 侧）。

### P1.3 审核 API（`sop_routes.py` 新增）

| 端点 | 说明 |
|---|---|
| `POST /api/sops/{sop_id}/review` | body：`{"action": "approve"\|"reject"\|"disable", "note": "", "reviewer": ""}`。approve → `published`（需先过 `validate_sop`）；reject → `draft` 回退 + 记录 note；disable → `disabled`。写审计：追加到 `data/sops/audit/{sop_id}.jsonl`（含时间戳/reviewer/action/note，补图谱 review 缺的审计字段） |
| `GET /api/sops?status=draft` | 列表端点加 status 过滤参数 |
| `GET /api/sops/{sop_id}/audit` | 返回该 SOP 的审计流 |

### P1.4 执行侧收口

1. `sop_loader.load_all()` 增加 `include_status: Tuple[str, ...] = ("published",)` 默认参数；`dispatcher.py:126`、`main.py:357,397`、evals 的 `_ensure_sop_loader`（`_query_helper.py:18-32`）全部走默认——**未审核 SOP 对分类器/路由/执行不可见**。
2. **执行反馈回流**：`dispatcher._summarize_sop_attempt`（L592-607）已有 success/failed 判定；在 `dispatch()` 收尾（L460-502）把结果写入 `sop.stats`（经 `sop_loader` 提供的 `record_run(sop_id, status)` 薄方法，JSON 文件原子更新）。`success_rate < 0.5 且 runs >= 10` 的 SOP 在审核界面标黄（不自动降级，决策留给人）。

### P1.5 前端（`packages/sop-ui`）

- 列表页加 status 徽标与过滤；详情页加"审核"操作区（approve/reject/disable + note）与审计时间线；生成按钮（`/generate-from-doc`）成功后提示"已进入待审核"。

### P1 测试与验收

- 单测：`validate_sop` 五条规则的正反例；loader 状态过滤；review 端点状态迁移与审计落盘。
- 集成：生成式创建一条 SOP → 断言 `POST /api/query` 路由不到它 → approve 后路由可达。
- evals 新增用例：未审核 SOP 不可见。

### P1 实施记录（2026-08-09）

- 数据模型：`SOP.status/confidence/source/review/stats` 已加入 `angineer_core/base_contracts.py`；存量 JSON 缺省 `status` 一律 grandfather 为 `published`（`sop_loader._load_json_sop` / `_load_raw_sop`）。
- 校验器：`sop-core/src/sop_core/sop_validator.py` 新增 `validate_sop` / `validate_sop_data`，五条规则全部落地。两个实现性决策：
  1. `blackboard.required` 闭包检查以「步骤 `outputs` 产出 ∪ 步骤 `inputs` 中的 `${var}` 引用 ∪ `user_query`」为可满足集合——存量 SOP 的 `required` 大多是用户查询参数（如 `k2`、`船型`），不做此放宽会把存量好 SOP 全部拒收；
  2. `auto` 工具特判为合法，但 `analysis_status == "analyzed"` 时仍拒绝（与计划一致）。
- 挂接点：`SopPathGenerator._write_sops_to_disk`（LLM 生成落盘）与 `sop_routes` 的 POST/PUT 均接校验；生成侧拒收并随响应返回 `rejected` 问题列表。导入（`/import`）同样置 `draft` + 校验，避免绕过审核闸门。
- 空步骤草稿：API 允许创建/编辑空 steps 的 `draft`（前端「新建 SOP」工作流需要），但 `approve` 时必须完整通过五条规则。
- 执行侧收口：`load_all(include_status=("published",))` 默认过滤；`dispatcher.dispatch` 收尾调用 `sop_loader.record_run(sop_id, status)`（原子写盘 + 内存同步）；`update_status` 供审核 API 复用。`preparse_all` 显式放开全部状态。
- 新增单测/集成测试：`tests/unit/test_unit_sop_validator.py`、`test_unit_sop_loader_status.py`、`test_unit_sop_review_routes.py`、`test_unit_sop_integration_gate.py`（覆盖未审核 SOP 对分类器不可见、审核后可见、生成落盘为 draft、非法 SOP 拒收）。

## P2 · 循环原语（1~2 周，核心）

> 目标：三个新模块 + 适配层，**不改 dispatcher**。只做库，不接链路。

### P2.1 任务分解

| # | 任务 | 文件 |
|---|---|---|
| 1 | 事件模型 + `AgentEvent` | `agent_events.py`（§6.2） |
| 2 | 消息模型 + `to_llm_messages` 两道闸门翻译 | `agent_messages.py`（§6.1） |
| 3 | `TextToolCallCodec`（默认）+ `NativeToolCallCodec`（预留） | `tool_codec.py`（§7） |
| 4 | `AgentTool`/`ToolResult` + 三个适配器：`EngtoolAdapter`（包 `BaseTool.run`，注入 config_name/mode，对齐 `_execute_tool_safe` 的 kwargs 注入方式 `dispatcher.py:2369-2373`）、`RetrieverAdapter`（包五路检索器，返回结构沿用 `RetrievedItem.model_dump`）、`SopRunnerAdapter`（P4 用，先留壳） | `agent_tools.py` |
| 5 | `run_agent_loop` 本体 | `agent_loop.py` |
| 6 | `AgentSession`：状态、双队列、取消、结算 | `agent_session.py` |

### P2.2 `run_agent_loop` 规格

```python
def run_agent_loop(
    messages: List[AgentMessage],      # 含 system 以外的对话历史；就地追加
    config: AgentLoopConfig,
    emit: Callable[[AgentEvent], None],
    cancel: threading.Event,           # 同步世界的 AbortSignal 等价物
) -> List[AgentMessage]:               # 返回本 run 新增的消息
```

**逐段规格**（对照 π 骨架，标注我们的取舍）：

1. **入口**：`emit(run_start)` → `emit(turn_start)`；prompt 消息逐条 `message_start/message_end`。
2. **内层 while（一个 turn）**：
   a. steer 注入（`pending_messages`，P2 先只支持 session 层传入，循环内 poll）；
   b. **闸门一** `transform_context`（可选）：messages 进、messages 出；
   c. **闸门二** `to_llm_messages` + codec.augment_system_prompt 拼 system；
   d. 调 `llm.chat_stream_events(...)`（P0.1 产物）：逐 delta `emit(message_delta)`，累积全文；拿到 `finish_reason`（P0.1 任务 3 的兼容细节：末 chunk 可能只有 usage 无 choices，`usage` 可能为 None）；
   e. **截断守卫（P5）**：`finish_reason == "length"` → 本轮解析出的 tool_calls **全部作废**，以 `is_error` 工具结果（文案："输出被长度截断，参数可能不完整，请重新发起调用"）喂回，`turn` 计数照走——与 π 的 `failToolCallsFromTruncatedMessage` 对齐；
   f. `codec.parse_assistant(text)` → 无 tool_calls → `emit(message_end)` → **正常退出**（P3：主动权在模型）；
   g. 有 tool_calls → 三段管线：
      - **prepare**：按名找工具（找不到 → is_error 结果）、`jsonschema` 校验参数、`before_tool_call` 拦截（返回理由字符串即拦）；
      - **execute**：默认并行（`ThreadPoolExecutor`，每工具 `timeout_s`；超时后 `shutdown(wait=False, cancel_futures=True)` 立即放弃等待，见 §6.3——`with` 块默认 `wait=True` 会阻塞到线程跑完）；任一工具声明 `execution_mode="sequential"` 则整批顺序（π 同款规则）；异常 → is_error 值（P4）；
      - **finalize**：`after_tool_call` 补丁；`terminate` 全票判定（P3）；
   h. 工具结果转 `AgentMessage(role="tool")` 追加；`emit(turn_end)`；
   i. **turn 边界决策点按序**（P6）：`should_stop_after_turn`? → `turn+1 >= max_turns`?（到达即收尾，见 4）→ steer poll → 下一 turn。
3. **外层 follow-up**：P2 实现为单次 drain（session 层在 run 将停时注入），保持与 π 同语义。
4. **max_turns 到达**（π 留给宿主的策略，我们的实现）：不硬断——追加一条 system 风格的 user 消息"轮次预算已用完，请基于已有证据直接给出最终答案"，再给**最后一次**无工具 turn（codec 传空工具集），随后 `run_end(reason="max_turns")`。这样 SLM 不会输出半截状态。
5. **取消（P6）**：每个决策点和工具执行前检查 `cancel.is_set()`；命中 → 当前 turn 完整收尾（事件序列完整：turn_end/run_end 照发）→ `run_end(reason="cancelled")`。流式进行中取消：P0 的 events 生成器支持外部关闭（`response.close()` 或 break 后底层 HTTP 连接随客户端超时释放；如实记录限制：openai SDK 同步流的最快取消点是下一个 chunk 到达时）。
6. **终止保护**：`emit` 自身异常 → 捕获记日志继续（事件出口绝不能炸掉循环）；回调（transform/should_stop/before/after）异常 → 视为未设置/不拦截（fail-open）并记 warning。

### P2.3 `AgentSession` 规格

```python
class AgentSession:
    def __init__(self, config_factory: Callable[[], AgentLoopConfig]): ...
    history: List[AgentMessage]          # 跨 run 持久（内存；持久化留给 harness，P2 不做）
    def run(self, user_text: str, emit) -> List[AgentMessage]
        # active_run 单飞：进行中再调 run 抛错（π：prompt() 并发直接 throw）
    def steer(self, text: str)           # 中途插队：进 steering 队列，下一 turn 注入
    def follow_up(self, text: str)       # 结束后续命：进 followUp 队列
    def cancel(self)                     # cancel_event.set()
    def wait_for_idle(self, timeout=None) # 旁观者等待：run_end 事件 + 所有 emit 完成才返回（P6 结算语义）
```

**死锁红线写进 docstring**（π 的教训）：监听器/回调内禁止调 `wait_for_idle`——结算在等监听器 return，监听器在等结算，Promise 依赖成环。我们虽无线程 promise，但 `wait_for_idle` 用 `threading.Condition` 实现，同一原则适用。

### P2.4 测试与验收（`tests/angineer-core/test_agent_loop.py`，mock LLM）

| 用例 | 断言 |
|---|---|
| 自然停 | mock 第一轮返回纯文本 → 循环 1 turn 退出，`run_end.reason=="completed"` |
| 两轮检索 | 第一轮 tool_calls(search) → 工具结果喂回 → 第二轮纯文本停 |
| 工具异常变值 | handler raise → 第二轮模型能看到 is_error 结果，循环不炸（P4） |
| 参数校验失败 | schema 不符 → is_error + 校验文案，handler 未被调用 |
| 截断守卫 | `finish_reason="length"` 且文本含 tool_calls 块 → 一个不执行，错误结果喂回（P5） |
| terminate 全票 | 两工具一举旗一不举 → 继续；全举 → 停（P3） |
| max_turns | 设 2：第三轮转为无工具收尾 turn，reason=="max_turns" |
| 取消 | 工具执行中 set → 批后完整收尾，事件序列含 turn_end/run_end，reason=="cancelled" |
| before/after 钩子 | 拦截理由生效；补丁字段合并正确 |
| 事件顺序 | 全程事件流断言层级嵌套合法（run ⊃ turn ⊃ message/tool） |

**验收**：以上全绿 + 循环模块 import 检查（`agent_loop.py` 不 import dispatcher/classifier/memory，用 import-linter 或 grep 断言，P2 边界）。

### P2 实施记录（2026-08-09）

- 新增六个模块（均在 `services/angineer-core/src/angineer_core/`）：`agent_events.py`、`agent_messages.py`、`tool_codec.py`、`agent_tools.py`、`agent_loop.py`、`agent_session.py`，未改 dispatcher。
- `run_agent_loop` 逐段规格全部落地：steer 注入（`pending_messages_provider`，session 层实现）、两道闸门（transform_context / to_llm_messages）、截断守卫（finish_reason=="length" 时 tool_calls 全部作废并喂回 is_error 结果）、三阶段工具管线（prepare 查找/schema 校验/before 钩子 → execute 并行或顺序 → finalize after 钩子）、超时后 `shutdown(wait=False, cancel_futures=True)` 立即放弃等待、max_turns 追加预算提示后的无工具收尾 turn、取消时当前 turn 完整收尾、emit/回调异常 fail-open。
- `should_stop_after_turn` 触发时 `run_end.reason` 取 `"should_stop"`（§6.2 的五种 reason 之外新增，供 P4 预算停用）。
- 工具执行约定：handler 返回 dict 中 `terminate: true` 会从内容中剥离并置 `ToolResult.terminate`，整批全票才终止 run；返回 dict 含 `error` 视为执行错误。
- 适配器：`EngtoolAdapter`（包 ToolRegistry，注入 config_name/mode）、`RetrieverAdapter.knowledge_search/table_search/entity_search`（懒加载 step09_query 与图谱，返回 `RetrievedItem`/实体的 JSON 结构）、`SopRunnerAdapter.sop_execute` 留壳（P4 接入，抛 NotImplementedError 由循环转 is_error）。
- `NativeToolCallCodec` 按计划预留：`parse_assistant` 抛 NotImplementedError，循环 catch 后 fail-open 为纯文本答案。
- 测试：`tests/angineer-core/` 新增 28 个（loop 10 场景、codec、session、适配器、import 边界 grep），全绿；`tests/unit` 263 个回归不变。

## P3 · 知识问答档接入（3~5 天）

> 目标：L1 路径在 feature flag 下切换到 agent 循环；evals 证明多跳提升、单跳不退化。

### P3.1 config 装配（`agent_configs.py`）

```python
def build_qa_config(*, llm, doc_nodes, library_id, doc_ids, filters,
                    task_type: str, max_turns: int = 3) -> AgentLoopConfig:
    tools = [
        RetrieverAdapter.knowledge_search(...),  # dense+sparse+clause 融合，
                                                 # 复用 fuse_candidates(source_candidates, task_type, top_k=20)
        RetrieverAdapter.table_search(...),      # table_retriever + 条件 formula_retriever
        GraphAdapter.entity_search(...),         # step07_graph.GraphStore.search_entities
                                                 # + get_relations_by_entity（KG_DB_PATH 环境变量）
    ]
    system_prompt = prompts.load("qa_agent", version="v1")  # P5 前先内联，留 TODO
    return AgentLoopConfig(llm=llm, tools=tools, system_prompt=system_prompt,
                           max_turns=max_turns, codec=TextToolCallCodec())
```

要点：

- **检索参数对齐现状**：`KnowledgeQueryRequest(query, library_id, doc_ids, top_k=10, filters)`（`dispatcher.py:1190-1196` 同款），融合 top_k=20、rerank 保留（远端 reranker 调用逻辑从 `dispatcher._rerank_candidates` L1540-1585 抽成共享函数）。
- **引用**：工具 `raw` 里带 `RetrievedItem`（含 `citation_target_id`、`section_path`）；system prompt 要求答案逐条引用规范编号；**保留现有引用校验**——`_has_unsupported_reference`（`dispatcher.py:1593-1632`）抽为 `after_tool_call` 等价的"答案后校验"钩子，挂在 P3 接入层。
- `enforce_evidence=True` 语义保留：工具全部空召回时，qa system prompt 指示模型直接按固定话术拒答（对齐 L1261-1263 现状），并设 `refusal` meta 供 evals 的 `is_refusal`（`answer_eval.py:58-66`）识别。

### P3.2 dispatcher 接入（最小侵入）

`dispatcher.py` 的 L1/L4 分支（L350-412）内插入：

```python
if path == "semantic_retrieval" and os.environ.get("ANGINEER_AGENT_L1", "false").lower() == "true":
    try:
        answer, citations, retrieved_items, agent_debug = self._dispatch_semantic_agentic(...)
        # 组 8 元组，strategy_desc 标记 "agentic_rag"
    except Exception:
        logger.exception("agentic L1 failed, falling back to legacy")
        # 落回现有 _dispatch_semantic
```

- `_dispatch_semantic_agentic` 新写在**独立文件**（`dispatcher_agentic.py` 或 P6 后归位），避免继续喂胖 dispatcher。
- 返回结构保持现有 8 元组契约，`retrieval_debug` 增加 `agent: {turns, tool_calls, reason}` 摘要——evals 的 `enrich_prediction_trace` 会自动带进 prediction。

### P3.3 evals 基线与对比（关键步骤，不可省）

1. **基线 run**：flag 关，`POST /api/evals/runs` 跑 `reviewed-exam-2020-2019` + `docs-retrieval-precision-v2`，记录 run_id（**数据集 ID 以 evals 库为准**：`exam-harbor-2019-2020.json` 只是磁盘文件名，库中实际注册 ID 为 `reviewed-exam-2020-2019`，50 题；实施前用 `eval:list` 确认）；
2. **失败分类**：用 `GET /api/evals/compare` 或导出的 detail，人工/半自动把失败题分为"未召回"vs"召回但答不全"——**若"未召回"占多数，暂停 P3，先修检索**（计划决策点，见 §11 风险 R2）；
3. **实验 run**：flag 开，同数据集同题，跑 run；
4. **对比**：`/api/evals/compare?run_id_a=&run_id_b=` + 轮数/token 统计（`agent.turns` 均值应 ≤1.5；单跳题允许"直接作答 turns==1"或"一轮检索+一轮作答 turns==2"，口径以 P3.4 为准）。

### P3.4 验收

- 多跳题（人工标注子集 ≥10 题）正确率显著提升（目标 +20% 或全过）；
- 单跳题平均分不降（±2% 内）且平均 `turns` ≤1.5（多数题直接作答 turns==1，允许一轮检索+一轮作答 turns==2；与 P3.3 第 4 步、§8 口径一致，token 成本可控）；
- 全程无异常落 legacy fallback（日志审计）。

### P3 实施记录（2026-08-09）

- `agent_configs.py`：`build_qa_config` 装配三个只读工具（knowledge_search/table_search/entity_search）+ 内联 QA prompt（P5 前）+ 显式引用证据（inline_citations）并入 system prompt。
- `retrieval_utils.py`：从 dispatcher 抽出 `rerank_candidates` / `has_unsupported_reference` / `build_citations_from_retrieved` 三个共享函数；dispatcher 对应 staticmethod 改为委托（行为不变，P6 归位）。
- `RetrieverAdapter.knowledge_search/table_search` 增加 `rerank` 开关（P3 config 默认开），复用共享 rerank 函数。
- `dispatcher_agentic.py`：`dispatch_semantic_agentic` 返回与 `_dispatch_semantic` 一致的 8 元组；`retrieval_debug["agent"]` 含 turns/tool_calls/reason/refusal 摘要 + 完整 `agent_events` 流。
- 拒答语义对齐 legacy：`enforce_evidence` 且工具无有效证据 → 返回空答案（调度链继续）+ `refusal=True`；答案出现未在证据中的规范编号/真题背景 → 替换为固定拒答话术（evals `is_refusal` 可识别）。
- dispatcher L1 分支：`ANGINEER_AGENT_L1=true` 时走 agentic，异常自动落回 legacy；默认 flag 关。
- 测试：`test_agent_configs.py` + `test_dispatcher_agentic.py` 新增 10 个（装配、双轮检索、拒答、引用校验、flag 开/关/fallback），`tests/angineer-core` 共 38 个全绿；`tests/unit` 263 个回归不变。
- evals 基线/对比待跑：数据集 ID 已确认（`reviewed-exam-2020-2019` 50 题、`docs-retrieval-precision-v2`）；等待外部 embedding/reranker 服务恢复后：flag 关跑基线 → flag 开跑实验 → `/api/evals/compare` 对比多跳 +20%、单跳不降、平均 turns ≤1.5。

### 当前进度与执行待办（2026-08-09）

- **已完成**：P0（止血）、P1（SOP 审核闸门）、P2（agent 循环原语）均已提交；P3（L1 agentic RAG）代码与测试完成，**尚未提交**。
- **P3 待提交文件**：`agent_configs.py`、`dispatcher_agentic.py`、`retrieval_utils.py`（新）、`dispatcher.py`、`agent_tools.py`（改）、`docs/agent-loop-improvement-plan.md`（改）。
- **下一步顺序（用户已确认）**：① 提交 P3；② 继续 P4（L4 大题档 agentic 接入：`SopRunnerAdapter.sop_execute` 实装、`build_complex_config`、`ANGINEER_AGENT_L4` flag、预算闸门 `make_budget_transformer/make_budget_stopper`）；③ 外部 embedding/reranker 服务恢复后统一跑 P3+P4 evals 基线/实验/compare。
- **约束**：`ANGINEER_AGENT_L1/L4` 默认关闭，不影响现有链路；`tests/` 目录仍被 `.gitignore` 忽略，测试不提交。
- **外部依赖**：DashScope embedding 与 reranker 服务当前不可用（回退 hash 检索，evals 分数不可比），P3.3/P3.4 验收挂起中。

## P4 · 大题档接入（1 周）

> 依赖：P2、P3 验证后的循环 + P1 的 SOP 审核（模型只能选到 published SOP）。

### P4.1 config 装配

```python
def build_complex_config(...) -> AgentLoopConfig:
    return AgentLoopConfig(
        tools=[*qa_tools,                                # P3 的只读三件套
               SopRunnerAdapter.sop_execute(...),        # 见下
               EngtoolAdapter("calculator", ...),
               EngtoolAdapter("table_lookup", ...),
               EngtoolAdapter("conditional", ...)],
        max_turns=8,
        transform_context=make_budget_transformer(max_tokens_est=100_000),  # P7 闸门一
        should_stop_after_turn=make_budget_stopper(threshold=120_000),      # P6 决策点
    )
```

### P4.2 `SopRunnerAdapter.sop_execute`（关键工具）

- **输入**：`{"sop_query": str, "args": {...}}`；
- **内部**：`IntentClassifier(published_sops).route(sop_query)`（复用精排 + 参数抽取，`classifier.py:944`）→ 命中且过阈值 → 调 P6 下沉前的 `Dispatcher.run_sop`（**短期**：包一层薄调用，注入 memory/step_callback；P6 后改调 `sop_runner.run_sop`）；
- **输出**：黑板 final_context 摘要 + 各步骤 status；`raw` 带完整 `sop_trace`（对齐 `dispatcher.py` 现有 trace 结构，前端可复用渲染）；
- **阈值**：用 P0 统一后的单一阈值常量（修 B3 的产出）；
- **保护**：`read_only=False`、声明 `execution_mode="sequential"`（SOP 执行与检索并行无意义）、超时 300s（SOP 内含多步 LLM）。

### P4.3 两道闸门实现（P7）

- `make_budget_transformer`：估算 `sum(len(m.content)) // 2`（对齐 `main.py:492-493` 现有粗估口径），超限时从 oldest-first 把 tool 结果替换为 `"[已压缩: 工具 {name} 的结果，要点: {raw.summary}]"`（压缩摘要 lazily 生成一次并缓存进 meta）；
- `make_budget_stopper`：turn 结束估算超阈值 → True，循环优雅停；宿主（接入层）拿到 `reason=="should_stop"` 后可选择压缩后开新 run 续跑（π 的 run 间压缩模式）。

### P4.4 dispatcher 接入

L4 分支（L350-412）在 `ANGINEER_AGENT_L4=true` 时改走 `_dispatch_complex_agentic`；**替换掉现在 L4=L1 换皮的假编排**（Q5）。默认 flag 关。

### P4.5 验收

- evals 综合大题集（无则新建 `complex-cases-v1`，≥15 题含 SOP+计算+查表混合）分数 ≥ 旧路径；
- 每题 `sop_trace` 记录进 eval detail，SOP 选择准确率可审计（与 P1.4 回流合流）；
- steer 场景人工验证：run 中途注入约束，下一 turn 生效。

## P5 · Prompt 资产化（1 周，可与 P3/P4 并行）

| # | 任务 |
|---|---|
| 1 | 新建 `angineer_core/prompts/`，每 prompt 一个常量 + 头部注释（用途/语言/版本/最后变更）；`load(name, version)` 薄加载器 |
| 2 | 迁移清单（逐一核对）：`dispatcher.py` 的 `_build_system_prompt`（L1466-1538，三个 task_type 分支 + 选择题规则 + 盲区段）、两阶段抽取/判定 prompt（L1283-1355）、`_build_smart_execution_prompt`（L2983-3041）；`classifier.py` 的分类 prompt（L856-900）与路由 prompt（L1007-1031）；`sop_routes.py:353-387` 步骤解析 prompt；`evals_routes.py:282-298` 对比分析 prompt（顺手改为模块 import + 结构化 body，修 Q9 的临时实现）；`answer_eval.py:13-25` judge prompt |
| 3 | 版本约定：改动 prompt 必须递增版本号；evals 的 prediction 已存 `system_prompt`（`answer_eval.py:229`），追加存 `prompt_versions: {name: version}` |
| 4 | 中英策略成文：结构化提取/评测判分沿用英文（图谱 E1-E5 与 VERIFY 已验证），面向用户生成用中文 |
| 5 | grep 审计脚本进 CI：`services/**.py` 中检测 `你是一个|You are a` 字面量，prompts/ 目录外出现即报警（白名单豁免） |

## P6 · dispatcher 拆分（1~2 周，最后做）

> 此时循环（P2）、两档接入（P3/P4）、prompts（P5）已就位，拆 dispatcher 是纯粹的位置移动。

| # | 任务 |
|---|---|
| 1 | `sop_runner.py`：下沉 `run_sop`（L2090）/`_execute_step`（L2172）/`_execute_analyzed_step`（L2215）/`_execute_tool_safe`（L2332）/`_smart_step_execution`（L2519-2593）/`_process_outputs`（L2702）/`_record_step`（L2905）及配套 `_handle_action_*`；`Dispatcher.run_sop` 保留薄委托一个版本周期（P4.2 的 SopRunnerAdapter 同步切换） |
| 2 | 修 Q4 剩余部分：`llm_generate` 元工具纳入统一超时（P0.1/P2 已先落实线程池超时后不等待，见 §6.3）；超时如实上报 + 记录"线程泄漏"warning（彻底解需 multiprocessing，本阶段只记录） |
| 3 | `retrieval_pipeline.py`：下沉 `_dispatch_semantic` 的多路召回/融合/重排段（L1190-1238）与 `_rerank_candidates`（L1540-1585）、`_build_citations_from_retrieved`（L1920-1971）、`_has_unsupported_reference`（L1593-1632）——P3 的 RetrieverAdapter 改为复用此模块（消除 P3 临时共享函数） |
| 4 | 答题段（两阶段抽取/判定 L1276-1376）改写为 `qa_pipeline.py` 的纯函数；legacy L1 路径与 agentic 路径共用证据后处理 |
| 5 | dispatcher 本体只剩 `dispatch()` 分级路由 + 回调编排，目标 < 800 行；修正 L4 分支使 flag 关时也走语义明确的 legacy 路径 |
| 6 | 清理：函数内局部 import（L154、L724-727、L988-989、L1164-1170、L1554、L1923）移顶部或注入；`_TOOL_EXEC_TIMEOUT_SECONDS` 进 config |
| 7 | 全程 evals 全绿即合并；纯重构不改行为 |

## P7 · API 层统一（2~3 天，P3 之后任意时点）

| # | 任务 |
|---|---|
| 1 | `/api/chat`（SSE）内部改为：`AgentSession` + qa config，agent 事件 → SSE 帧直转（`message_delta`→`chunk` 兼容映射），**对外帧格式不变**，前端零改动 |
| 2 | 新增 `/api/chat/agent`（SSE）：暴露完整 `AgentEvent` 流（run/turn/tool 四级），前端逐步切换；`scene` 参数选 qa/complex 档 |
| 3 | 取消：FastAPI 的 `Request.is_disconnected()` 轮询任务 → `session.cancel()`（修 Q10）；断连后 LLM HTTP 流在下一 chunk 处终止（如实记录此粒度） |
| 4 | `/chat/stream`（NDJSON SOP 执行流）保留不动——它是 SOP 调试工具，与答题链路解耦 |
| 5 | steer 接口：`POST /api/chat/agent/{run_id}/steer`（body: text）→ `session.steer()`；会话池按 `scene+session_id` 复用 `QueryRequest` 现有约定 |

---

# 第五部分 · 治理

## 8. 验收指标总表

| 阶段 | 指标 | 测量 |
|---|---|---|
| P0 | 截断输入零静默成功；salvage 仅存在于非 strict 兜底 | `test_truncation.py` + evals 基线不降 |
| P1 | 未审核 SOP 零触达；非法 SOP 生成侧 100% 拒收；审计流可查询 | 单测 + 集成测试 + evals 新用例 |
| P2 | 十种停法/守卫单测全绿；循环模块零反向 import | pytest + import 检查 |
| P3 | 多跳子集正确率 +20%；单跳平均分不降 ±2%；平均 `turns` ≤1.5（口径见 P3.4） | evals compare（基线 vs flag 开） |
| P4 | 综合大题集 ≥ 旧 L4 路径；SOP 选择准确率入 eval detail | evals |
| P5 | prompts/ 目录外零 prompt 字面量（CI 审计） | grep 脚本 |
| P6 | dispatcher.py < 800 行；行为零变化 | 全量 evals 回归 |
| P7 | SSE 断连后 run 在下一 chunk 终止；事件流完整收尾 | 集成测试 |

## 9. 风险与回退

| # | 风险 | 缓解 |
|---|---|---|
| R1 | SLM 工具选择错误率高，循环空转烧钱 | max_turns 硬上限 + 到顶转无工具收尾；P3 先只给 3 个只读工具；evals 盯平均轮数 |
| R2 | L1 失败主因是检索召回而非答题（P3.3 第 2 步判定） | 暂停 P3，先修检索（chunking/rerank/图谱召回接入），agent 化顺延 |
| R3 | 文本协议 tool_calls 块解析失败 | fail-open 向纯文本答案（不执行工具比误执行安全）；失败率进 debug 统计，超 5% 对该端点启用 native codec（落地载体：P0.1 任务 7 + §7 `NativeToolCallCodec`） |
| R4 | 循环 token 成本高于一枪一答 | terminate 旗、单跳一轮退出、transform_context 压缩；evals 记录 token 均值 |
| R5 | P1 审核流程拖慢 SOP 上线 | 存量 grandfather；自动校验门先挡低级错误；审核界面一键 approve |
| R6 | PoPo submodule 改动被上游冲掉 | 严格按 `AGENTS.md`：先子模块内 commit 再动 |
| R7 | 各阶段行为漂移 | 每阶段 feature flag（`ANGINEER_AGENT_L1/L4`）；旧实现保留一个版本周期；evals 基线先行 |

## 10. 依赖图与工期

```
P0 止血 ──────────────┐
                      ├─→ P2 循环原语 ─→ P3 知识问答档 ─→ P4 大题档 ─→ P6 dispatcher 拆分
P1 SOP 审核闸门 ──────┘        │                │              ↑
                               └──→ P5 prompts ─┴──────────────┘（P5 与 P3/P4 并行）
                                              P7 API 统一（P3 后任意时点插入）
```

| 阶段 | 工期 | 前置 |
|---|---|---|
| P0 | 1~2 天 | 无 |
| P1 | 3~5 天 | 无（与 P0 并行） |
| P2 | 1~2 周 | P0.1（chat_stream_events） |
| P3 | 3~5 天 | P2 |
| P4 | 1 周 | P2、P3 验证、P1 |
| P5 | 1 周 | 无（建议与 P3 并行） |
| P6 | 1~2 周 | P2/P3/P4/P5 |
| P7 | 2~3 天 | P3 |
| **合计** | **约 5~7 周**（单人**乐观**工期；P0/P1/P5 并行可压缩；P2 协议调试与 P6 重构不确定性高，建议实际按 7~9 周留缓冲） | |

## 11. 附录 A · 顺手修复 bug 清单（P0 内）

B1 `DocsRetrievalTool.py:45` fuse 签名错误（工具实质不可用）
B2 `ConditionalTool.py:316` import 不存在的 `TableTool` 类
B3 SOP 路由双阈值 0.45/0.6 收敛为单一常量（进 `base_config.py`，evals 定值）
B4 dispatcher docstring `run()`→`run_sop()`；`_dispatch_semantic` 返回注解 7→8 元组
B5 删除 `main.py:217` 死代码 `SOPUpdate`
B6 `LLMClient.configs` 属性输出脱敏 `api_key`（当前 `/api/llm_configs` 已脱敏，重点防新调用方误透传）
B7 `chat` 返回值 None 防护

## 12. 附录 B · 文本工具协议 prompt 模板（TextToolCallCodec 草案）

````
## 工具使用协议

你可以调用以下工具获取证据或执行计算：

{tools_json}    # [{name, description, parameters(JSON Schema)}]

规则：
1. 需要调用工具时，只输出一个工具调用代码块，不要输出其他内容：
```tool_calls
[{"name": "工具名", "arguments": {"参数名": "参数值"}}]
```
2. 工具结果会以"工具返回"的形式提供给你。你可以继续调用工具，或给出最终答案。
3. 当你掌握足够证据时，直接输出最终答案（不要包含 tool_calls 代码块），并逐条标注引用的规范编号。
4. 禁止编造工具返回中不存在的规范编号、表格数值与计算结果。
````

## 13. 附录 C · 事件 schema 速查

| type | 时机 | payload 关键字段 |
|---|---|---|
| `run_start` | run 开始 | `query` |
| `turn_start` | 每 turn 开始 | `turn` |
| `message_start` | assistant 消息开始流式 | — |
| `message_delta` | 每个文本增量 | `delta` |
| `message_end` | assistant 消息完成 | `finish_reason`, `has_tool_calls` |
| `tool_start` | 工具放行后执行前 | `call_id`, `name`, `args` |
| `tool_end` | 工具完成/失败/超时 | `call_id`, `is_error`, `duration_ms`, 结果摘要 |
| `turn_end` | turn 完整结束 | `tool_results` 摘要 |
| `run_end` | run 结束（五种停法之一） | `reason: completed\|max_turns\|cancelled\|error\|terminated`, `turns`, `messages` |
| `error` | 致命错误 | `message`, `stage` |

SSE 映射：`/api/chat/agent` 直转；`/api/chat` 兼容映射 `message_delta→chunk / run_end→end / error→error`。

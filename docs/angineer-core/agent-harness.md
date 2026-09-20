# AnGIneer Agent Harness 技术说明

> 本文档描述 AnGIneer 的 Agent 化问答框架：L0~L4 意图分级、Attempt 状态机、
> 循环执行器（AgentLoop）、事件协议（SSE）、工具文本协议、拒答守卫与会话池。
> 核心代码全部在 `services/angineer-core/src/angineer_core/`。

## 1. 为什么需要 Harness

工程规范问答不是单一 prompt 能覆盖的：既有"查条文""查表"这样的简单检索，
也有"计算""多步骤综合"这样的复杂任务。Harness 提供：

- **分级路由**：L0 闲聊 / L1 正文问答 / L2 条款·表格定位 / L3 规范计算 / L4 复杂综合；
- **Attempt 状态机**：每一级可展开为一次或多次尝试，失败自动降级/回退；
- **工具协议统一**：检索、SOP、计算器、条件分支都以同一 AgentTool 契约接入；
- **事件可观测**：run/turn/message/tool 四层事件流，前端据此渲染"思考过程"。

## 2. 核心概念

### 2.1 消息模型（agent_messages.py）

```python
AgentMessage(role, content, tool_calls, tool_call_id, name, is_error, meta)
ToolCall(id, name, arguments)
```

- `meta` 永不进入 LLM 上下文（存 citations/耗时/预算摘要）；
- `role`：user / system / assistant / tool。

### 2.2 事件模型（agent_events.py）

`AgentEvent(type, run_id, turn, ts, payload)`，type 枚举：

```text
run_start / run_end
turn_start / turn_end
message_start / message_delta / message_end
tool_start / tool_end
note（边界/过程说明） / answer（守卫替换的最终回答） / error
```

前端通过 SSE 订阅这些事件，实时渲染"思考过程（N 步 · 工具耗时 X）"与执行步骤。

### 2.3 工具契约（agent_tools.py）

```python
AgentTool(name, description, parameters_schema, handler, read_only, execution_mode, timeout_s)
```

- 检索类工具 `read_only=True`；
- `execution_mode`：parallel / sequential；
- 工具通过 `RetrieverAdapter` / `SopRunnerAdapter` / `EngtoolAdapter` 装配。

### 2.4 循环配置（agent_loop.py）

```python
AgentLoopConfig(
    llm, tools, system_prompt, max_turns, codec,
    attempts, final_answer_guard, should_stop_after_turn, pending_messages_provider,
)
TurnContext(turn, messages, tool_results, usage)
```

## 3. L0~L4 策略展开（agent_policy.py）

`build_attempts(intent_result, ...)` 按意图展开尝试列表：

| 级别 | Attempt 序列 | 说明 |
| :--- | :--- | :--- |
| L0 | 闲聊直答（无工具） | |
| L1 | 语义检索（enforce_evidence=True） | 无证据拒答收尾 |
| L2 | 条款/表格定位 → 回退 L1 语义检索 | table_search 优先；无证据降级 L1 |
| L3/L4 | 复杂任务（QA 三件套 + SOP + calculator + conditional） | 最多 8 轮 |

`_AttemptMachine` 按序执行 attempts：

- 当前 attempt 的 `config_factory()` 生成子配置（嵌套 LLM 循环）；
- 子循环成功（success_check 通过）→ 结束；失败 → 记 `fallback_note` 并进入下一个 attempt；
- 全部失败 → 拒答收尾。

## 4. 循环主流程（run_agent_loop）

```text
run_start
  └─ 按 attempt 进入子循环
       └─ 每 turn：
            ├─ 检查 steer（pending_messages_provider）
            ├─ 检查 should_stop（预算门）/ cancel
            ├─ 组装消息 → LLM
            ├─ codec 解析（正文 + tool_calls）
            ├─ 并行/顺序执行工具 → tool 消息写回
            └─ turn_end
run_end（reason：completed / should_stop / cancelled / max_turns）
```

关键点：

- **steer 注水**：turn 开始前把用户中途插入的消息注入；
- **预算门**：`make_budget_transformer` 按 oldest-first 压缩工具结果，`make_budget_stopper` 超阈值停止；
- **取消**：`cancel_event` 协作式中断；
- **最终守卫**：`_apply_final_guard` 在所有 attempt 结束后执行。

## 5. 工具调用协议（tool_codec.py）

默认 `TextToolCallCodec`（ReAct 式文本协议，兼容一切 OpenAI 兼容端点）：

- 系统提示注入工具 JSON + 协议说明；
- 模型输出：

````text
```tool_calls
[{"name": "knowledge_search", "arguments": {"query": "..."}}]
```
````

- 解析器抽取围栏块；无围栏时 salvage 纯 JSON 数组；正文与工具调用分离；
- `NativeToolCallCodec` 预留（原生 `tools=` 参数，默认不启用）。

## 6. 拒答与证据守卫

`make_final_answer_guard(enforce_evidence)`（详见 `docs/retrieval-chain.md` 第 6 节）：

1. 工具全部无有效证据 → 拒答；
2. 答案引用未检索到的规范/背景 → 拒答；
3. 编造 `[KTE]` 标记 → 移除（不拒答）。
4. 已有有效证据但回答为拒答 → 终段定向重试一次；仍拒答则保留原回答并留 trace 注记。

**提示词侧**（`prompts/agent_configs.py`）：

- 未调用任何检索工具前禁止直接回答"没有检索到足够证据"；
- 证据只覆盖部分内容时，先答已支持部分并明确说明缺失项，禁止整体拒答（QA v6）；
- 末尾追问必须为邀请式问句（"您是否想知道…？"），不得写成向用户索取答案的内容问句（followup_question_rule v3）；
- 查表/数值/尺度类必须优先 table_search 且用原问法；
- prompt 改动必须升版本（`scripts/audit_prompts.py` CI 强制审计）。

## 7. 会话池（agent_session.py / aichat-api）

- `AgentSession`：history + follow_up/steer 队列 + 单飞 run 锁；
- 池 key：`scene:session_id:scope_hash`（library_id + doc_ids 参与 hash），scope 变化开新会话；
- `/api/chat/agent` 输出完整 AgentEvent 帧（SSE）；
- `steer` / `follow_up` / `cancel` 子端点。

## 8. 关键踩坑记录

| 问题 | 现象 | 对策 |
| :--- | :--- | :--- |
| 模型未调工具先拒答 | 白烧一轮 | 提示词禁止"未检索先拒答" |
| 查表问题选错工具 | 搜到表标题无行值 | table_search 排首位 + 检索合并表格行 |
| 长上下文超预算 | 循环爆 token | budget transformer/stopper 两级门 |
| 工具结果被截断 | 模型缺证据 | oldest-first 压缩 + 摘要缓存 |
| SSE 事件与前端不同步 | 思考过程闪烁/重复 | 事件按 run/turn/message/tool 分层，前端按 run_id 合并 |

## 9. 关键代码锚点

- 策略：`agent_policy.py`
- 循环：`agent_loop.py`（`run_agent_loop` / `_AttemptMachine` / `TurnContext`）
- 消息/事件：`agent_messages.py` / `agent_events.py`
- 工具：`agent_tools.py`
- 协议：`tool_codec.py`
- 守卫：`agent_configs.py`（`make_final_answer_guard` / `build_qa_config` / `build_complex_config`）
- 会话：`agent_session.py`、`services/aichat-api/chat_agent.py`

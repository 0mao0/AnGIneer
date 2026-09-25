# TTFT 优化需求（最终回复首字提速 + 等待体验）

状态：待开发 ｜ 日期：2026-09-24（当日评审修订：B 删留方向写死、A1 投影式+独立阈值、C 收窄 L1 段）｜ 基线版本：v0.2.76

## 0. 背景与实测数据

生产问答（v0.2.76 检索已提速至 ~3.5s 后）用户从发消息到**最终回答首字**约 10s。
实测时间线（生产容器 SSE 事件流 ts 还原，问题「堤顶高程怎么计算」，全程 26s）：

```
0s        1.35s      4.6s           9.82s                26s
│─轮1─│──检索+rerank──│──最终轮 prefill──│────流式生成────│
 0.7s      3.25s        5.2s(30k tok)
   └ 轮1 模型没调检索工具 → 强制重试 → 白烧一轮，且 UI「输出→清空→再输出」
```

最终轮 prompt ≈30k tokens 的构成（已核实的代码事实，行号基于 v0.2.76）：

| 成分 | 大小 | 依据 |
|---|---|---|
| system（规则+工具协议，逐请求全等） | ≈2k tok | `agent_configs.py:17-90` + `tool_codec.py:33-66` |
| 工具返回 JSON 中 `items[].text` 全文 | 大头 | `agent_tools.py:382` |
| 同一份证据在 `evidences[].content` **再抄一遍** | ≈与上行等量 | `agent_tools.py:206,383`（evidence.content=item.text） |
| 历史各 run 的**全量工具 JSON** 无上限回灌 | 逐轮雪球 | `chat_agent.py:157-159`（回灌无 LIMIT）、QA 档无预算门（`agent_configs.py:334-345`，budget 闸门只装 complex 档 `:542-543`） |

## 1. 目标与非目标

**目标（验收口径，生产容器内复测「堤顶高程怎么计算」）**：

| 指标 | 现状 | 目标 |
|---|---|---|
| 单轮会话首字（run_start→最终轮首 delta） | 9.8s | **≤6s** |
| 同会话第 2/5 轮首字 | 逐轮恶化（雪球） | **≤6s，不随轮次增长** |
| 等待期 UI | 思考中转圈；重试轮出现「输出→清空→再输出」 | 分段进度；**任何已流出正文不被静默抹掉** |

> 余量测算：C 省轮1（~0.7s）+ B 省 prefill（5.2s→约 3s）后时间线 ≈ 检索 3.25s + prefill ~3s + 首 delta 余量 ≈ 6.3s——**≤6s 是临界目标**，B 收益不及预期即破线；验收若落在 6~6.5s，先查证据 token 是否真减半（citations/snippet/历史有无隐性重复），再考虑追加手段，不默许放宽。

**非目标（明确不做）**：
- 检索并行化、意图分类换小模型/并行、vLLM prefix caching、rerank 提速（另案）
- 不改检索召回逻辑/条数（`ANGINEER_CONTEXT_TOP_N=15` 不动）、不改 prompt v10 规则文本、不改拒答话术
- 不改模型/硬件/端点配置

## 2. 需求 B：LLM 侧证据去重（真实收益主刀）

**现状**：`_assemble_search_result` 产出的 dict 同时含 `items[]`（全文+metadata 含 cite）与 `evidences[]`（`agent_tools.py:382-383`，由 items 一一构造、content 为同一文本），整个 dict 经 `_json_content` 原样成为工具消息 content 进 LLM（`agent_loop.py:309-330`）——**同一份证据全文进 prompt 两遍**。

**通道事实（2026-09-24 逐行核实，决定删留方向）**：工具消息的 `content` 是「三位一体」——同一份字符串同时是 ① LLM prefill 输入、② SSE run_end 帧数据源（`agent_message_to_dict` 不含 meta，`agent_messages.py:181-195`；`tool_end` 实时事件只带 `content[:300]`）、③ chat.sqlite 落库与历史回灌本体。前端引用卡片/思考轨迹条目/citation_target_id 归一化全部从 **content** 解析（`chatTransport.ts:251-266,497-545`、`ThinkingSteps.vue:150-152`）；`ToolResult.raw`（meta 通道）只有评测 in-process 链路在读（`policy_query.py:176-204`），前端拿不到。**因此「只改进 LLM 的序列化、其余不动」在现有架构下没有接缝，content 一改三端一起变。**

**要求**：
1. content 中**删 `evidences[]`、保留 `items[]`**（方向写死，不可二选一）——引擎内三处判定解析 content 里的 items：`_has_evidence`（`agent_policy.py:18-33`，L2 success_check，删了会永远判未命中、永远 fallback）、`_tool_evidence_present`（`agent_loop.py:200-204`）、`_tool_evidence_parts`（`:243-266`，删了拒答重试无证据可喂）。
2. items 内字段零删减：全文 `text`、`metadata.cite`、`metadata.doc_title`、`section_path`、页码、`citation_target_id`（前端 `BaseChat.vue:548` / `ThinkingSteps.vue:152` 归一化依赖）。
3. `ToolResult.raw`（meta）**保持现有完整结构不动**——评测回放消费它（`policy_query.py:176-204`）；前端不经 meta，不受此约束。
4. `citations[].snippet` 可瘦身但保留展示可用长度（前端引用卡片展示 snippet，`chatTransport.ts:246`）；`citations` 数组本体保留（前端引用聚合优先读它，`chatTransport.ts:236-250`）。
5. 同族装配（table/graph 走 `_items_to_evidences`/`_entities_to_evidences` 的工具）同规则：content 删 evidences，保留 items/entities。

**边界**：不改检索、rerank、cite 分配、evidences 数据结构本体（raw 里 evidences 原样保留）。

**预期**：证据 token 减半 → 最终轮 prefill 5.2s→约 3s。

## 3. 需求 A1：历史工具消息预算压缩（治多轮雪球）

**现状**：`AgentSession.history` 无上限（`agent_session.py:24,57`），历史 run 的全量工具 JSON 逐轮进 prefill；现成机制 `make_budget_transformer`（oldest-first 压缩工具结果，`agent_configs.py:372-396`）只装在了 complex 档（`:542-543`）。

**两个已核实的坑（2026-09-24，必须先解决再谈装闸）**：
1. **现 transformer 是原地改写**：`message.content = "[已压缩...]"`（`agent_configs.py:391`）直接改 history 本体对象——messages 列表就是 `session.history` 本体，压缩结果会永久写进内存 history，并随 `main.py` persist 落 chat.sqlite，与下面第 3 条「本体不裁」**直接矛盾**。QA 档接入前必须先把 transformer 改造为**投影式**（copy-on-write：返回新消息对象列表，不碰原对象；complex 档一并切换，行为对齐）。
2. **阈值口径缺口**：估算口径 `字符数//2`（`_estimate_tokens`，`agent_configs.py:348-350`），中文场景 1 字≈1 token，est 100k ≈ 真实 200k token；而单轮证据 est 仅 ~15k，第 5 轮雪球 ~75k **根本触不到 100k 闸门**——照 complex 档现口径装闸，对「第 2/5 轮 ≤6s」目标基本无约束力。

**要求**：
1. QA 档（`build_qa_config`）装**投影式** budget transformer，**当轮 run 的工具结果不压**（oldest-first 天然最后才压到；投影实现里可显式跳过本 run 区间）。
2. 阈值 QA 档独立定：**默认 30k est（≈真实 60k token）起步**，环境变量可覆盖（如 `ANGINEER_QA_BUDGET_TOKENS_EST`）；不对齐 complex 档 100k。`字符数//2` 粗估缺陷不优化，注明即可。
3. 压缩只作用于「发给 LLM 的 messages」投影，chat.sqlite 落库与 `history` 本体不裁（回放/审计不受影响）——靠坑 1 的投影式改造保证。
4. **跨 run 摘要替换提为主路径而非兜底**：超阈值时对历史 run 的 tool 消息投影为一行摘要（含哪些文档被引用过），当轮不压；验收看第 2/5 轮指标。

## 4. 需求 C：确定性首轮检索注入（范围收窄为 L1 段）

**现状**：requires_tools 路由（`agent_policy.py:89,115,145,198`）轮 1 靠模型自觉调工具（文本协议）；模型不调则事后重试（`agent_loop.py:636-642`，白烧一轮生成）或代检索（`:643-668`，实现 `_force_retrieve_tool` `:269-296`）。实测轮 1 无论调不调都花 ~0.7-2s，且不调时用户可见「输出→清空→再输出」。

**范围修正（2026-09-24 核实）**：`requires_tools=True` 的段有 4 个——meta 统计（`agent_policy.py:89`）、L1（`:115`）、L2（`:145`）、L3/L4（`:198`），**不能一刀切注入 knowledge_search**：meta 段注入正文证据会污染统计通道（可能诱发拿正文硬答统计题）；L2 段的正确注入工具是 table_search 而非 knowledge_search。**首期只对 L1 段注入**（默认路由的 L1 + L2 fallback 后的 L1）；L2 段是否注入 table_search 留作后续，需门禁数据支撑。

**「首轮」定义**：每个 run 至多注入一次；时机 = L1 段 apply 之后、该段第一次 `_run_llm_turn` 之前。L2→L1 fallback 场景在进入 L1 段时注入（L2 段本身不注入）。

**要求**：
1. L1 段首轮 LLM 调用前由系统直接执行 knowledge_search（query=用户原文，复用 `_latest_user_query`，`agent_loop.py:231-240`）。
2. 注入消息构成 = **assistant 工具调用消息 + tool 结果消息成对注入**：assistant 消息按 TextToolCallCodec 文本协议格式伪造 content（使 codec 解析与 `buildThinkingTrace` 的 call/result 配对成立，`chatTransport.ts:625-660`）。注意现有 `_force_retrieve_tool`（`agent_loop.py:652-659`）**只注入 tool 消息、无 assistant 调用消息**，思考轨迹本就有「有 result 无 call」错位——本次是成对注入新写，不是照抄代检索。
3. 注入后**保留**模型继续追调其他工具（图谱/表格/SOP）的能力，不锁 tool 轮。
4. 注入照常产生 tool_start/tool_end SSE 事件（前端思考轨迹展示依赖）。
5. 既有「未调工具重试 / 代检索」兜底代码保留，但明确语义：注入成功后 `used_tools=True`，二者**实质成为死路径**，仅注入异常（检索报错/工具缺失）时可达；39 题拒答基线对比时，原依赖代检索路径的题行为必然变化，差异来源归此项、不算回归。
6. 顺手修 `_force_retrieve_tool` docstring（`agent_loop.py:276-279`）与代码条件不符：代码不判「最终答案是否拒答」，只判 requires_tools && !used_tools && 重试已用（`:643-647`）。
7. query 传原文 vs 模型自改写对命中率的影响以第 6 节门禁把关；若 nightly 集 hit 掉，退回开关 `ANGINEER_FORCE_FIRST_SEARCH=0` 可关（默认开）。

**预期**：省轮 1（~0.7-2s）+ 消灭重试轮灾难路径 + 消除该场景的清空重答。

## 5. 需求 A2/A3：前端等待体验（apps/shared + packages/aichat-ui）

1. **A2 清空重答修复**（`chatTransport.ts:97-105` turn_start 清空已流正文）：turn_start 不再硬清；已流出正文转入「思考过程」卡片（置灰折叠），最终答案区只留最终轮输出。判定标准：任何场景下不出现「已可见文字消失」。注意与 run_end 权威覆盖逻辑（`chatTransport.ts:166-179`，取最后一条 assistant 覆盖流式正文）协调：转入思考卡片的是中间轮正文快照，run_end 覆盖只作用于最终答案区。
2. **A3 分段进度**：等待期文案按事件驱动分阶段——`意图理解`（run_start）→`检索规范库…（实时秒数）`（tool_start）→`精排证据…`（后端 rerank 无独立事件，可并入 tool 卡片，**不新增后端事件**）→`生成回答…`（最终轮 turn_start）。现有 `思考中...` spin（`BaseChat.vue:186-189`）保留为兜底。
3. 流式重渲 O(n²)（每 delta 全文重解析+innerHTML 重赋值，无节流）：加 rAF 或 ≥50ms 节流即可，不引入虚拟滚动等重构。

## 6. 验证与回归门禁（B、C 触碰模型输入，必须过闸）

1. 单测：`python -m pytest tests/unit services/docs-core/tests tests/aichat-api tests/angineer-core -q` 全绿（8 例预存失败基线除外：parse_resume/v1_resume/delete_library 系）。
2. **39 题拒答专项**（生产 evals API 手工 run）：拒答正确数不得低于 v0.2.76 基线。
3. **nightly smoke 集**（open-ragbench-smoke-v1 25 题，与生产同流水线）：门禁 green、hit@1(doc) 不低于基线。
4. gold 计算题人工比对 ≥3 题（堤顶高程、疏浚工程量、波浪要素）：答案与引用不劣化。
5. 新增 TTFT 打点：run 结束在日志记 `ttft_ms`（run_start→最终轮首 message_delta）与最终轮 `prompt_tokens`，供生产验收与后续观察。口径注意：`agent_loop.py:872` 的 `total_usage.update(usage)` 逐轮覆盖同 key，run_end 的 usage 本就是**最后一轮**口径，打点直接取最终轮即可，勿当全程累计。
6. 验收测量：部署生产后同一问题 curl 复现（SSE ts 还原时间线），对照第 1 节目标表。

## 7. 交付约定（repo 契约，务必遵守）

- 改动 commit 到 main 即可；**push / 发版（tag、版本号）由业主确认后执行，开发者不得自行 push**。
- 发版时 CHANGELOG 条目与 README 摘要行一一对应、全角「；」分隔（规范见 AGENTS.md）。
- 功能开关须可回退：B 若需开关（如 `ANGINEER_LLM_EVIDENCE_DEDUP`）默认开；C 见 4.5。
- 关键文件导航：`services/angineer-core/src/angineer_core/{agent_loop,agent_tools,agent_policy,agent_messages}.py`、`prompts/agent_configs.py`、`services/aichat-api/{main,chat_agent}.py`、`apps/shared/chatTransport.ts`、`packages/aichat-ui/src/{components/BaseChat.vue,composables/useAIChat.ts}`。

## 8. 遗留尾巴（2026-09-24 发版 v0.2.77 时记录；2026-09-25 更新）

1. ~~打点修复待生产验收~~ **已闭环（09-25）**：生产同会话 3 轮实测，服务器打点与客户端 SSE 逐毫秒一致（L2→L1 12.4s/11.9s turns=2，L1 注入轮 7.0s turns=1）；「首轮直达」note 生产确认 firing；多轮 prompt 稳定 18-21k（A1 闸压平）。结论：轮次劣化目标达标，单轮 ≤6s 未达标（最好 7.0s，大头=意图分类 ~4.5s，业主决定分类提速等 Jev 进展）。
2. **探针 turns=2 未定性**：本地探针（session `step4-verify-1`）turns=2 而非预期的 1，疑似模型拿到注入证据仍触发拒答重试（refusal_retry）；日志随进程丢失未确证。生产观察：若 L1 注入轮频繁 turns=2，查拒答重试触发原因（可能是注入证据与问题不相关时模型仍拒答——语义正确但说明注入检索质量需关注）。
3. ~~PUT 400 `unknown msg_seq`~~ **已闭环（09-25）**：根因=`useAIChat.ts` 把池 key「`docs:chat-x`」当 `session_id` 发给后端，而宿主记录层用裸 id「chat-x」——落库在带前缀行、PUT/详情/删除打裸 id → 400、同会话列表双 id。修法=发送时剥掉 `${scene}:` 前缀发裸 id（服务端池 key 本就含 scene，行为不变）；存量带前缀行保留（列表/详情按服务端返回 id 仍可用）。回归：`useAIChat.test.ts` 断言 `session_id` 为裸 id，4 绿 + vue-tsc 绿。
4. ~~Qwen3.8-Flash 被选中之谜~~ **已闭环**：业主下午手动改的默认模型（本地 .env），非缺陷；服务器 .env 未动，nightly 不受影响（judge=DeepSeek-V4-Flash 已核实）。
5. **本地验证环境教训**：Windows SO_REUSEADDR 语义下新旧 worker 可并存抢 8791，验证流量随机打到旧代码进程（本次实踩两次，一次致「修复无效」假象）。验证前必须先确认 8791 只有一个监听者（`Get-NetTCPConnection -LocalPort 8791 -State Listen` 唯一）且其启动时间晚于最后编辑。
6. ~~跟进式提问的注入 query 无会话上下文~~ **已闭环（09-25，业主拍板「上下文化改写」）**：当前消息 ≤15 字（`ANGINEER_INJECT_FOLLOWUP_CHARS`，设 0 关闭）且有上文时，注入 query 改写为「上一问真实提问，当前消息」（上文跳过拒答重试等内部 user 提示）；note 追加「已结合上一问改写检索词」。回归：改写/长文不改/无上文不改/跳过内部提示/开关关闭 5 例。
7. **拒答 22→19（09-25 nightly）**：v0.2.77 首跑整体 +2.02pp（CI95 显著）、hit@5(doc) +1.8pp，但拒答专项 56.4%→48.7%（-3 题），初步方向=注入证据诱导「相邻证据不可答题」作答。业主已暂缓归因，待查时逐题核对 3 道翻转题。
8. ~~guard 边界规则替换路径「输出→清空→再输出」~~ **已修（09-25，随 §5 A2 一并）**：guard 改写/run_end 权威覆盖发生真实替换时，被顶替的流式正文快照进 `interim_answers`，流式区与最终消息气泡下均可折叠展开回看。

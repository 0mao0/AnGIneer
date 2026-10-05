# 报告：对话黑板夜间推进总结（2026-10-04 夜）

> 业主指令：「不只是 M0，是所有」+「该 commit 的 commit，不需要找我」。
> **边界（严格遵守）**：commit 自主完成；**push 与发版一次未做**（那是另外两次授权）。
> 全部新能力**默认关**，生产行为与 v0.2.90 逐字一致。

## 一、今晚交付了什么（按里程碑）

| 里程碑 | 状态 | 提交 | 落地物 |
| --- | --- | --- | --- |
| 臂 2 指针骨架 | ✅ | `8ab8e4d` | 预算压缩行追加候选指针（`ANGINEER_POINTER_SKELETON` 默认关）+ 10 例行为锁 |
| 文档口径更正 | ✅ | `d03e12c` | per-tool 覆盖率 / `meta_json` 裁剪陷阱 / 末段条款写回 BB 与 arms |
| **M0 离线壳 + 干跑** | ✅ | 后续一笔 | `evals_core.blackboard`（cases/graph/arms/runner）+ 15 例；报告 `report-blackboard-m0-dryrun-20261004.md` |
| **M1 写路径** | ✅ | `886a86b` | 图四表 + `apply_ops`/水位/补跑/五处级联 + `busy_timeout`；`distill_run` 入口 |
| **M2 读路径内核 + 接线** | ✅ | `886a86b` + `76aa805` | `recall/render/make_conv_graph_transformer`；attempt 级 config_factory 包装；run_end 异步蒸馏 |
| **M3 多轮评测进 nightly** | ⏳ 未做 | — | 见「四、待裁决」——需你定口径后再动 |
| **M4 路径交互（UI）** | ⏳ 未做 | — | BB §10.4 已定：交互设计与工程量单独评估、不含在 8-12 天内；本轮**未动任何前端** |

## 二、可核证据（不是自述）

| 项 | 证据 |
| --- | --- |
| 单测 | `tests/angineer-core/`（含新增 `test_conv_graph.py` 12 例、`test_budget_gates.py` 39 例）**368 passed**；`services/chat-history/tests/` **15 passed**；`services/evals-core/tests/test_blackboard_m0.py` **15 passed**；`tests/aichat-api/` **111 passed** |
| 存量红（非本次引入，均已复现证明） | ① `test_search_memo.py::test_second_identical_call_hits_memo_single_use`（v0.2.90 的 `_prefetch_ms`，stash 干净树同样红）；② `test_route_pre.py` 3 例（同上，v0.2.90 提交信息里已记录同一批）；③ **`tests/angineer-core/test_llm_turn_liveness.py` 整文件挂死**——它是**另一个并发会话的未提交在飞文件**（07:18 创建、`git status` 为 `??`，同一批还有 `agent_loop.py`/`.env.example` 未提交改动），**不是仓库里的存量回归**：stash 掉本次改动后同样挂死 → 与本次无关。卡点已定位：文件内假生成器的 `self.abandoned.wait()` **无超时**（`tests/angineer-core/test_llm_turn_liveness.py:36`）。**未改动该文件**（属他人在飞工作） |
| 干跑实测（22 例真实会话） | 题面保真 **22/22**；臂 2 指针在场 **17/22**；臂 3 子图段 est 中位 63 / max 270（闸 B 上限 2,000）；臂 2 指针开销中位 +318 est、max +989 |
| 生产默认行为未变 | `ANGINEER_CONV_GRAPH` / `ANGINEER_POINTER_SKELETON` 均未在任何 `.env` 里设置；接线路径「store 缺省 / 开关关 / 异常」三种情形都原样返回 |
| 未发版、未 push | `git status` 干净；`main` 领先 `origin/main` 若干（本地提交），无 tag 变更 |

## 三、M1 写路径端到端验证（2026-10-05 晨，**不调模型**）

用本地真库最长会话（`chat-muj4iiw7-2jwt5v`，92 条消息 / 19 run）逐轮跑 `distill_run` → `ConvGraphStore`，
合成 owner `u:verify-20261005`（不碰真实会话的图）：

| 指标 | 修前 | 修后 |
| --- | --- | --- |
| 进图轮次 | 12/19（**7 轮整轮丢图，37%**） | **19/19** |
| 图规模 | 5 节点 / 13 边 | **24 节点 / 41 边** |
| 拒收原因 | 「批次 ops 超上限 20」被当致命错 | 容量超限改为**截断 + 注记**，不再拒收 |
| 节点 key 质量 | `doc-cac5bc0e/3<sub>.</sub> 4 …`（HTML 泄漏）、整句 locator | HTML 已剥离、字段 ≤40 字截断 |
| 幂等 / 水位 | — | 同 run 复跑 `applied=False`；水位 `last_run_id=verify-19` ✓ |
| 渲染段体量 | — | 三个真实追问分别为 32 / 34 / 151 est（上限 2,000） |

**顺带测得的两条设计信号（未修，留给 M2）**：
1. **value 节点产出率 = 0/19 轮**：真实文本里的量多以「12.8m」「T 取 12.8m」这类形式出现，
   而严格正则只认 `X=12.8m` → B 类题（值复用）的靶面在确定性蒸馏下**抓不到**，
   M2 要么放宽抽取、要么由小模型蒸馏产出 value 节点。
2. **表类节点仍只能用 `doc_id` 当显示名**（上游 `doc_title_map={}`）→ T 类指针可读性弱。

## 三·B、真问答端到端冒烟（开关开 + 真模型，2026-10-05 08:37）

方法：本机 aichat-api 重启并设 `ANGINEER_CONV_GRAPH=1`（`ANGINEER_NO_RELOAD=1`），guest 会话两轮真问答；
判据 = **服务日志 + DB 双侧**（不是"看代码应该会"）。

| 环节 | 证据（原样日志／DB 读数） |
| --- | --- |
| 图存储懒初始化 | `08:37:37 INFO main \| 对话黑板图存储就绪: D:\AI\AnGIneer\data\platform\chat.sqlite` |
| **写路径**（第 1 轮） | `08:38:04 INFO main \| 对话黑板蒸馏: {'run_id': '06990ed35f91', 'ops': 4, 'accepted': 4, 'rejected': [], 'notes': [], 'applied': True, 'note': '已进图'}` |
| **写路径**（第 2 轮） | `08:38:41 \| {... 'run_id': 'ccac6e430c37', 'ops': 10, 'accepted': 10, ..., 'applied': True}` |
| **读路径**（第 2 轮） | `08:38:17 INFO angineer_core.conv_graph \| 对话黑板读路径：召回 1 节点／注入子图段 80 字符（40 est，上限 2000 est）` |
| DB 侧 | 第 1 轮后 节点 1 / 边 1 / 版本 1 / 水位 `06990ed35f91`；第 2 轮后 节点 6 / 边 6 / 版本 2 / 水位 `ccac6e430c37`；assistant 落库 4 条 |

**顺序也对（这是设计里最容易写错的一环）**：蒸馏日志（08:38:04）出现在该轮 TTFT／run_end（08:38:04）**之后**
——即「persist 之后才推进水位」；读路径日志（08:38:17）出现在第 2 轮 LLM 调用**之前**——即子图段确实进了那一次 prompt。

**顺带观察（不是结论，只记录）**：`final_turn_prompt_tokens` 第 1 轮 17,695 → 第 2 轮 12,187（两轮口径不同，不可直接相减）；
第 2 轮虽注入了子图段，模型**仍然拒答**（"没有检索到足够证据"）——**机制通 ≠ 效果有**，而这正是 M0 判分跑要量的东西。
更关键的线索：该轮召回只有 1 节点／80 字符，且节点 key 是 `doc-c29d731e/注：350000t散货船…`（表类无 doc_title）——
**可读性不足会让机制白注入**，与 §三 里那条「表类 doc_title 缺口」信号一致。

冒烟数据（本机库，可清）：会话 `s-verify-blackboard-1005`，owner `g:khYDc0OasUoc_pONSA7ACcPO`；
清理 = 删该会话消息 + `conv_graph_*` 里该 owner 的行（图是派生缓存，可重建）。

## 四、干跑暴露并当场修掉的四个真问题

1. **召回命中率是最大缺口**：修前 22 例只有 **4 例**能召回出子图段（BB §4 首版只匹配规范号/条款号，
   覆盖不了「DWT=40000 的满载吃水」这类无线索追问）→ 补 token 匹配 + 近邻兜底后 20/22；
   剩 2 例是单轮题与「历史无被引用条款」，属预期。
2. **序数消解指向空 run（bug）**：本轮提问自己开新 run，`runs[-1]` 是空的当前轮 →
   「刚才第二条…」召回 0 节点；改为指向最近一个**产出过引用**的已完成轮。
3. **图空不许移除证据（护栏）**：臂 3 原无条件丢弃历史 tool 消息，D4 实测 prompt 从 13,248 est
   掉到 164 est（丢了又没补 = 裸答）→ 空图/空段退化为现状。
4. **题集引号与库不一致**：C2/C3 库里是全角弯引号 `“ ”`，题集/arms 写的是 `「 」` → 保真测试当场报红，
   已按库内原文改正。

另有两个实现级发现已写进 BB：`doc_title`/`clause_id` 覆盖率是**按工具全有/全无**（knowledge 100% /
table 0%）；**落库 `meta_json` 只留 `{name, tool_call_id}`**，items 必须从 `content` 解析
（否则重建/离线/评测路径静默拿空）。

## 四、待你裁决（明天四句话就能定）

| # | 事项 | 为什么必须你定 |
| --- | --- | --- |
| 1 | **冻结 arms §3 的 22 题**（确认/替换/删除），并把 sha256 写进 arms §6 | 预注册纪律：判分跑前锁死；跑后再改＝重开 |
| 2 | **16k 预算下有效样本只有 17/22**（B1/B2/C6/D2/D4 不触发压缩 → 臂 1 ≡ 臂 2）：接受 17 题口径，或对这 5 题另设更小预算重跑 | 属预注册口径变更，必须在跑基线前定 |
| 3 | **是否跑判分跑**（臂 1 基线 → 三臂盲序判分） | 要真实模型窗口；且会占生产算力（建议挑夜间空闲、我可在你点头后用线程池 1 限流） |
| 4 | **是否开启开关做影子期**（`ANGINEER_CONV_GRAPH=1` + `ANGINEER_POINTER_SKELETON=1`，服务器 `.env` 改完须 `docker compose up -d` 重建容器） | 上线动作，且 BB §7.6：多轮评测未建好前图模式**不得**对外灰度 |

**M3 未做的原因**：多轮评测进 nightly 需要你上面第 1/2 条的口径 + 现行 nightly 的 suite 注册方式；
我不擅自把新 suite 挂进夜间流水线（会污染 nightly 结论与企微播报）。
**M4 未做的原因**：BB 自己把它定为独立立项（交互设计 + 前端工程量另估），今晚动它只会产出不可验证的半成品。

## 五、如何启用 / 如何回退

- 启用（任一或组合）：`ANGINEER_CONV_GRAPH=1`（读路径 + 写路径）、`ANGINEER_POINTER_SKELETON=1`（臂 2）、
  `ANGINEER_CONV_GRAPH_SUBGRAPH_EST=800`（子图段上限，默认 2000）。
- 回退：清掉上述变量即回 v0.2.90 行为；图是派生缓存，`conv_graph_*` 可整表删除后由消息流重建。
- 影子期观测入口（已就绪，未接 UI）：`chat_history.store.graph_store.stats(conn, owner, session)`。

## 六、下一步（按顺序，等你点头）

1. 你冻结题集 + 裁决有效样本口径（第 1、2 条）；
2. 我跑臂 1 基线快照（真实模型、稳定窗口、答案文本 + sha256）；
3. 三臂判分跑（盲序呈现；你判分）；
4. 按判读结果决定图的边界（全量 / 收缩），再谈 M3 灰度与 M4 立项。

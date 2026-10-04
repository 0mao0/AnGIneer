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
| 存量红（非本次引入，均已复现证明） | ① `test_search_memo.py::test_second_identical_call_hits_memo_single_use`（v0.2.90 的 `_prefetch_ms`，stash 干净树同样红）；② `test_route_pre.py` 3 例（同上，v0.2.90 提交信息里已记录同一批） |
| 干跑实测（22 例真实会话） | 题面保真 **22/22**；臂 2 指针在场 **17/22**；臂 3 子图段 est 中位 63 / max 270（闸 B 上限 2,000）；臂 2 指针开销中位 +318 est、max +989 |
| 生产默认行为未变 | `ANGINEER_CONV_GRAPH` / `ANGINEER_POINTER_SKELETON` 均未在任何 `.env` 里设置；接线路径「store 缺省 / 开关关 / 异常」三种情形都原样返回 |
| 未发版、未 push | `git status` 干净；`main` 领先 `origin/main` 若干（本地提交），无 tag 变更 |

## 三、干跑暴露并当场修掉的四个真问题

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

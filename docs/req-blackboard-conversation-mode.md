# 需求：对话黑板（会话记忆图）

> 状态：**两道闸均已过（2026-10-04 核验）——可开工**。开工范围与依据见下；键模型已按 D6 定版（§5）。
> 立项不变（目标定版见 §0.1），本文件全部结论保留、无需重做。
>
> ✅ **闸 1 已过（2026-10-03 核验）**：DB 改造阶段一/二已落地并提交——
> `15709f9`（sqlite 按组拆文件）、`9d5625f`（data/ 三域归位）。现场证据：`data/registry.sqlite`、
> `data/platform/chat.sqlite`、`data/knowledge/groups/standards.sqlite`、`data/evals/groups/evals_corpus.sqlite`
> 均在位；旧 `data/chat.sqlite` 与 `knowledge_base/` 已消失；`chat_history.store.DB_PATH` 默认值已改为
> `platform/chat.sqlite`（→ §5 落位表述与本条对齐，M1 **不得写死任何 data/ 路径**，跟随该常量）。
>
> ✅ **闸 2 已过（2026-10-04 核验）**：阶段三「多库勾选问答」已落地并提交——
> `60f349d`（Phase B ScopeContext 集合化）、`50fc410`（Phase C `chat_messages` 主键去 scope + 存量迁移 +
> `library_ids_json`）、`1487de0`（Phase D 端点/集合鉴权/池 key 去 scope）、`8f2bf8a`（Phase E 前端）。
> 键语义以 `docs/superpowers/specs/2026-10-04-kb-multi-library-qa-design.md` **D6** 为准：
> **会话身份 = `(owner_key, session_id)`，`scope_hash` 降级为消息级来源标记**。
> → §5 的键模型已同步改版（不再把 `scope_hash` 写进 `conv_graph_*` 主键），原「预留
> `scope_key + scope_version`」的过渡措施**作废**（问题已被 D6 回答）。
> **现在可开工的三件**：① 臂 2 指针骨架（≈1 小时，**须带开关**，否则臂 1「现状」在生产里不复存在、
> M0 无法逐题对照）；② M0 三臂离线跑（图落临时文件，不入 `data/`）；③ M1 落表——**键模型已定，不必再等**。
> 判分基线要挑检索栈稳定的窗口跑。
>
> **定位（2026-10-04 定名「对话黑板」）**：本文档 = **对话黑板**（Dialogue Blackboard）——一种以「会话记忆黑板」
> 为核心的新对话形态：语义层（全部提问 + 全部回答）逐字全带一个字不丢；证据层（检索结果）不再原文回灌，
> 蒸馏进会话图、按指针回引。
> **正名轨迹**：会话语义图（路线 B，上游 `req-chat-history-bloat.md` 的视角，只命名了证据层那一半）
> → Blackboard 新对话模式（2026-10-02 业主口径完整定位）→ **对话黑板（2026-10-04，术语去撞名）**。
> 去撞名的原因：本仓库原有两个「黑板」——SOP 侧 `Memory.blackboard`（单次 sop_execute 的**变量**槽）
> 与本方案的会话记忆结构。现定版：**「对话黑板」＝本方案**；SOP 侧一律写 **「变量黑板」**
> （代码标识符 `Memory.blackboard` 不改，理由同 9d5625f「`KNOWLEDGE_BASE_DIR` 变量名保留」）。
> 文件名 `req-blackboard-conversation-mode.md` **保持不动**（避免链接失效），英文标识符一律 `conv_graph_*`。
> ⚠️ **范围边界**：意图识别改造（废 meta_query 路由）是独立轨道，归 `req-abolish-meta-query-route.md`，
> 与本模式互不依赖、可并行（分工与融合分析见该文档 §4）。
> ⚠️ 2026-10-02 曾误按 `req §7` 决策点把本文判为「归档/不立项」，**该结论已撤回**（原因见 §0.1.0）。
> 撤回理由两条：① 越权——业主从未授权结案；② **目标认错**——本文原以 token/延迟为标的做性价比，
> 而业主的立项目标是**专业领域对话能力**，两者不是同一件事。
>
> ⚙️ **锚点约定（2026-10-03 复核修正）**：本文档引用代码一律写 `file:symbol`（如
> `agent_configs.py:make_budget_transformer`），**不写裸行号**——行号已随 commit 漂过一轮
> （2026-10-03 的 17fff5d 把 `main.py` 推后约 60 行、`agent_tools.py` 推后 24 行，
> 而本文档的旧行号在提交当刻就已失效）。行号只作为「当时核对的快照」保留在修订表里。
> 数据类断言一律标注复现口径与复现日期（2026-10-03 对 `data/chat.sqlite` 只读复算）。
>
> ## 0.1 目标定版（业主口径，2026-10-02）
>
> > **「B 肯定是要做的，我的目标就是做 B。A 不足以完成专业领域的对话。」**
>
> 这句话重新定义了本方案的标的，务必以此为准：
>
> | | 原稿件口径（错） | **业主口径（以此为准）** |
> | --- | --- | --- |
> | 标的 | prompt token / ttft 收敛 | **专业领域的多轮对话能力**：跨轮可回引条款、可复用上一步算出的量、可持续追问 |
> | A 的定位 | 削斜率的止血（token 视角） | **不足以支撑专业对话**：它把 96.2% 的检索证据压成一行摘要，证据丢了就答不准 |
> | 「做得值不值」的秤 | 省下几秒 ttft | ** domain 追问能不能答对**（§7.1 的指涉专项才是主线） |
> | token/ttft 的位置 | 主目标 | 约束条件（要在不炸 prompt 的前提下保住保真度），不是收益本身 |
>
> **目标完整表述（2026-10-03 业主补述，以此为准）**：终态 = **多轮对话的实时图结构**——
> 相互关系与关键参数沉淀在图上，用户在对话/做题时不只读线性上下文（尤其是海量知识库引用内容），
> 而是**沿图走路径**。双重收益：① 避免击穿上下文窗口（证据层降维的本来职责）；② 摆脱纯文字束缚，
> 图成为对话本体与交互界面。在此口径下，§7.1 的指涉正确率是**地基阶段的验收代理指标**，
> 不是终态目标本身；路径交互形态见 §10.4，里程碑见 §8 M4。
>
> ### 0.1.0 撤回记录：为什么上一版判错了
>
> 误判发生在把**手段当成目的**。见下图的数据链条——本来它指向的就是「必须做 B」，
> 却被读成了「收益太小不必做」：
>
> - tool 证据占会话 **96.2%** 字符（全库 6,078,058 字符），assistant+user 合计仅 **3.8%**；
> - A-min 的封顶手法 = 把历史的 tool 消息压成 `[已压缩: 工具 xx 的结果，要点: …]` 一行；
> - **【2026-10-03 复核补强】压缩后的「要点」正文比本文档原先写的还空**：
>   `agent_configs.py:_summarize_tool_raw` 对检索类结果只回 `检索到 {N} 条候选`
>   （`agent_configs.py:_summarize_tool_raw` 内 `if "items" in raw` 分支）——**文档名、条款号、
>   指针全部不留**。所以「封顶的代价」不只是证据原文消失，连图要用的节点 key 也一起消失；
> - 于是**封顶的代价就是证据原文的消失**——专业对话里「刚才第二条规范」「上一步那个系数」
>   这类追问的答案恰恰只存在于那 96.2% 里。
> - 结论方向应当是：**正因为 A 会丢证据，才必须用结构化方式把证据留下来**，
>   而不是「反正丢的是块体积，无所谓」。
>
> token 相关的数字（§2.0 那张表）依然有效，但只用来回答**约束**问题：
> 结构化保留证据要花多少 prompt，有没有超过预算。它不再具有否决权。
>
> ## 0.2 设计要点：别动对话语义，只改证据层
>
> 既然标的从 token 换成保真度，原 §2 的 prompt 构成要跟着改。数据给了一条省事的路：
> **对话语义（全部提问 + 全部回答）本身就很便宜，真正贵的只有证据层**，所以两者应分开处理：
>
> | 层 | 体量（最长那条 19 轮会话） | 处理策略 | 现状（2026-10-03 核码） |
> | --- | --- | --- | --- |
> | **user 提问** | 455 字符（≈227 tokens） | **全部逐字保留**（§2.1） | **已是现状**：预算压缩器只动 `tool` 角色（`agent_configs.py:make_budget_transformer`）；§2.1 唯一真变化＝过滤引擎注入的 user 提示 |
> | **assistant 回答** | 13,919 字符（≈7.0k est tokens） | **全部逐字保留**（§2.2）——答过的话是最可靠的上下文，不蒸馏 | **已是现状**：历史回灌无窗口（`chat_history.store.SqliteHistoryStore.load` 全量），assistant 从不被压；§2.2 实际新增的是一条**超预算截断闸**（减配，不是加法） |
> | **tool 检索证据** | 647,735 字符（≈324k est tokens） | **结构化替换**：clause/value 节点 + 引用边 + 指针；被指涉时按指针重检索原文（§2.3） | **真增量**：现状压成 `检索到 N 条候选` 一行（信息量为零） |
>
> 即：**语义层今天就已经一个字不丢**——本方案在语义层上零工程量，工程量全在证据层：
> 把「压成一行、连指针都不剩」换成「结构化节点 + 引用边 + 指针回引」。
> 相比「把整段对话蒸馏成图」，这个范围保真度高得多、蒸馏出错的破坏面小得多，且落在 M0 可验证的范围内。
> （原稿把 §2.1/§2.2 当增量，导致工程量与收益的对应关系算错——2026-10-03 复核修正。）

## 0. 评审修订摘要（2026-10-02 起，含 2026-10-03 五评）

| # | 修订 | 依据 |
| --- | --- | --- |
| 1 | **立项理由改写**：A-min 是封顶不是削斜率；**封顶的代价是占会话 96.2% 的检索证据被压成一行**——这就是 A 撑不住专业对话的根因，也是 B 存在的理由。token/ttft 降为**约束项**，不参与价值判断 | `make_budget_transformer` 压到达标为止；§0.1、§2.0 |
| 2 | **新增 M0**：离线重放真实长会话 + A-min 基线对照；M1-M3 顺延 | §8 |
| 3 | **prompt 构成改**：分层处理——**全部 user 提问（§2.1）+ 全部 assistant 回答（§2.2）逐字保留**，只对 tool 证据层做结构化替换（§2.3） | user 0.1% + assistant 3.7% = **3.8%** 字符（原记 4.8% 系算术笔误，2026-10-03 更正）；tool 96.2%、单条 p50 26,917 字符 |
| 4 | **§3 cite 说法更正**：`metadata["cite"]` 是标记不是映射；join 口径写死；clause_id 仅 11.0% 覆盖 | `agent_tools.py:195`；3,139 条检索块实测 |
| 5 | **存储 schema 补全**：三表加 `owner_key` + `scope_hash`，新增 `conv_graph_state` 水位表 | `chat_messages` 主键含二者；`scope_hash_for` 语义 |
| 6 | **GC / 删除级联补齐**：`gc_expired` / `delete_session` / `delete_sessions_by_library` / `claim_guest` 四处同改 | 否则孤儿图永久残留，「可从消息流重建」有失效窗口 |
| 7 | **异步可靠性**：水位 + 补跑 + 断连兜底路径 | `main.py:532` 补写那一支同样要触发蒸馏 |
| 8 | **ops 校验**（悬挂边 / 非法 op 拒绝）+ 写并发口径 | 蒸馏漂移是静默累积的（§9） |
| 9 | **prefix-cache 论证反转**：不是「保持复用」而是「主动破坏现成的跨轮复用」——读 vLLM `cached_tokens` 出净账；**但它是约束项**，为负只触发渲染优化，不否决路线（2026-10-02 误判教训，见 §0.1.0） | 现状历史 append-only，跨轮前缀天然复用 |
| 10 | **验收主线换位**：从 token 收敛改为**多轮指涉正确率**（§7.1，唯一一票否决项），由业主本人判分即可（他就是领域专家）；新建多轮评测能力降为 M3 上线前置而非起步前置 | 现有评测每题独立 session 且不走 SSE（§7.6） |
| 11 | 工程量 3-5 天 → **8-12 天**（含多轮评测能力 + 前端图可视化/回放） | §9 |
| 12 | **【2026-10-02 追加】撤回误归档**：曾按 `req §7` 决策点判为「不立项」，属越权且目标认错，已撤回；B 按业主口径立项推进 | §0.1.0 |
| 13 | **【2026-10-02 二次复核】**：① §2.3 指针召回补现状缺口——`knowledge_search` 模型侧仅 `query` 参数，`fetch_clause` 列 M1 前置；② §2 标题「常数」更正为斜率口径（§2.0 表同步改 ~5k → 13-18k real）；③ §4 补段序约束（prefix-cache）；④ §11 A-full 降级为可选归因实验，M0 对照臂改 A-min；⑤ M0 补脚本化合成样本（n=1 → n≥2，兼作 §7.6 雏形）；⑥ §3.3 value 原文回查、§7.1 判分留痕 | `agent_tools.py:625`；`agent_loop.py:1153` |
| 14 | **【2026-10-02 更正】§3.5「`LLM_CONFIGS` 里没有现成「小模型」端点」不成立**：默认端点即 A3B（35B MoE / **3B 激活**），另有更小的 `Qwen3.8-Flash-Next` 走独立 `/api/llm2` 且已作 judge 模型；真正的问题只剩**抢同一张卡**，指定方式应对齐 `EVAL_JUDGE_MODEL` 现成范式而非新造平行变量 | 本机 `.env` 实测 3 端点；`llm_config.py:111`；`answer_eval.py:90-110` |
| 15 | **【2026-10-02 三评】两处 P1 修正**：① §2 prompt 构成段序对齐 §4 补充 3——子图渲染段移到 user/assistant 逐字史**之后**、本轮提问之前（原版式会让逐字史每轮 cache miss，§7.3 净账直接判负）；版式里「近端 1~2 轮 assistant 逐字尾」同步为 §2.2 全带口径；② §3.2 检索块计数更正 **13,139 → 3,139**（chat.sqlite 重扫，cite 100% / clause_id 11.0% 两比率在 n=3,139 上逐位复现，原数为笔误） | §4 补充 3；chat.sqlite 实测 |
| 16 | **【2026-10-02 四评】七处一致性收口**：① §3 蒸馏输入「摘要」→**原文**（对齐 §3.1 红线——§3.2 join、§3.3 原文回查都依赖原文，按摘要实现三处全断）；② §8 M2 出口摘掉「prefix 净账为正」闸（对齐 §7.3 约束项无否决权），降为记录项；③ §1 形态图补 assistant 逐字层（§2.2 之前的旧口径残留）；④ §7.2「第 10+ 轮收敛」→「斜率 ~400 est/轮 ±25%」（线性增长是新设计常态，收敛是 A-min 封顶语义残留）；⑤ §9 prefix-cache「可能直接判负」→「触发 §4 补充 3 段序优化」；⑥ §4/§10.1 常驻段摘除「意图轨迹」（topic 已降级由 user 原文承担），未决事项载体定为轻量 issue 节点（mark_resolved 唯一作用对象）；⑦ fetch_clause 的 docs-core 读端点列 M0 前置确认，工程量估算补挂 | 四评逐条核码：A/B/D/E/F/G 成立，C 半成立（§1 图缺层属实；§2 代码块三评已改新口径） |
| 17 | **【2026-10-02 正名】文档从「会话语义图（路线 B）」改为「Blackboard 新对话模式」**：路线 B 视角只覆盖证据层，业主口径的完整形态 = 新对话模式（语义层逐字史＋会话图黑板＋指针回引）；文件名同步改为 `req-blackboard-conversation-mode.md`；**意图识别改造划出本方案范围**（归 `req-abolish-meta-query-route.md`，分工与融合见其 §4） | 业主定调（2026-10-02） |
| 18 | **【2026-10-02 意图改造落地后校准】**：① §6 意图识别改行更新为**已落地**（468f7a9 止血＋5e6ecb5 拆档）——M2 的装配区地基（meta 档删除、L1 统一四工具箱、P-1 guard 兼容 stats、P-2 QA v14 注入对冲）已就绪；② §3.1 蒸馏输入补 **tool 名过滤**——knowledge_stats 已下沉 L1 全量暴露，stats 消息不进蒸馏（结论已逐字在 assistant 原文、JSON 无指针价值），只喂检索类三工具；③ §2 引擎判定句补 P-1 注（evidence_parts 纳入 stats 摘要，仍限当前 run）；④ §7.1/§8 基线口径＝**改造后现状重放**（intent 97/100、financebench 58% 等改造前数字跨口径不可比）；⑤ 行号校准 `agent_tools.py::_assign_cites`（当时 195，现 219）、`AgentTools.knowledge_search` 的 parameters_schema（当时 625，现 804-808）——⚠️ **本条的「其余引用未漂移」推断无效**：判据是「这两个 commit 没碰这些文件」，不是打开文件逐行核对；同日稍后的 17fff5d 把 `main.py` 推后约 60 行、`agent_tools.py` 推后 24 行，旧行号在本文档提交当刻（9594030）就已失效（见 #20） | 468f7a9、5e6ecb5 逐文件核对 |
| 19 | **【2026-10-03 目标补述】**：业主明确终态 = **多轮对话实时图结构 + 用户沿图走路径**（对话/做题摆脱纯文字线性上下文，双重收益：不击穿窗口 + 路径模式）；§0.1 增目标完整表述（§7.1 降为地基阶段代理指标，非终态本身）、§1 增终态形态段、§8 增 **M4 路径交互形态**（交互设计与工程量单独估算，不含在 8-12 天内）、§10.4 新增「从观测到导航」+ 实时性口径（图随 run_end 增量帧边说边长，蒸馏保持异步不进关键路径）、§9 增终态范围外溢风险 | 业主 2026-10-03 口径 |
| 20 | **【2026-10-03 五评：全量复核修正】**（三路只读核对：`data/chat.sqlite` 复算 + 工作区 3342ad0 逐行核码 + 上游两篇 req 交叉比对；8 项数据主张全部逐位复现，无一项失败）：① **增量口径更正**——§2.1/§2.2 已是现状（压缩器只压 `tool`；回灌无窗口），语义层零工程量，真增量只有证据层与子图（§0.2/§2）；② **验收数字更正**——「~400 est/轮」实为 n=1 会话均值 378，全库均值 230；§7.2 闸门改**差分口径**（新模式同会话斜率 ≤ A-min 实测斜率）；ttft 行 0.9/1.4 s 是 20/30 轮的**累计值**不是每轮，且 0.168 s/1k 不在 `req-chat-history-bloat.md §11.2`（§2.0/§7.2）；③ §0 修订表算术 4.8%→**3.8%**；④ **M0 改三臂 + 判分预注册**（新建 `docs/plan-blackboard-arms.md`，§8/§7.1）；⑤ 全部锚点改 `file:symbol` 并重建（`main.py` 451→505-521/582、519→579-583、532→565-567+592-594、549→609；`agent_tools.py` 195→219、625→804-808；`agent_loop.py` 1153→1182；引擎判定实为 `agent_loop.py:_tool_evidence_present` + `agent_policy.py:success_check`，不在 `agent_configs.py:116-191`）；⑥ **§6 残留行删除**（「图启用后历史轮不进 prompt」与 §2 冲突）；§8.6 悬空引用改为 `agent_loop.py:_contextualize_followup_query`；⑦ **关闭两个 M0 待确认项**：`fetch_clause`（docs-core 无 HTTP 端点，但 `canonical_sql_store.list_blocks_by_clause_refs` 现成且 `clause_id` 有索引 → +1-2 天成立）、`X-Chat-Frame-Version`（全仓无消费方，未知字段被忽略 → additive 安全）；⑧ **补四个工程缺口**：蒸馏输入口径定死＋成本/排队（与 `EVAL_JUDGE_MODEL` 同端点）、SQLite 双写（`busy_timeout`＋schema 归属 chat-history）、截断与 prefix-cache 的相互作用、M4 需显式「上下文选择」对象（§3.1/§3.5/§4/§5/§10.4）；⑨ **数据精度**：assistant 均值 435.5（原记 436）、p90 用 nearest-rank 且含 6 条迷你工具消息、19「轮」= run 数（该会话 user 消息 25 条）、注入 user 提示实测 45/292 条 / 760 字符（§2.1/§2.2） | 本地 `data/chat.sqlite` 只读复算（2026-10-03）；工作区 3342ad0 核码；`req-chat-history-bloat.md`、`req-abolish-meta-query-route.md` 交叉比对 |
| 21 | **【2026-10-04 正名与路径校准】**：① **术语去撞名**——本文档定名**对话黑板**（Dialogue Blackboard），SOP 侧 `Memory.blackboard` 定名**变量黑板**（代码标识符不改，理由同 9d5625f「`KNOWLEDGE_BASE_DIR` 变量名保留」）：该对象生命周期 = 单次 sop_execute、内容是步骤变量（T/Z0/result…）与 required/outputs 数据流契约，不装跨轮经验，故不叫「经验黑板」；② **§5 路径校准**——聊天历史库已随 DB 改造阶段二迁至 `data/platform/chat.sqlite`（`chat_history.store.DB_PATH`），本节旧写 `data/chat.sqlite` 作废，M1 一律跟随路径常量；③ **状态**：闸 1（阶段一/二）已过、闸 2（阶段三 多库勾选）未过，见文档头部 | 业主 2026-10-04 定名；`15709f9` / `9d5625f` 核验 |
| 22 | **【2026-10-04 键模型定版：闸 2 已过】**：阶段三多库勾选落地（`60f349d`/`50fc410`/`1487de0`/`8f2bf8a`），会话身份按 **D6** 定在 `(owner_key, session_id)`，`scope_hash` 降为消息级来源标记 → **§5 的 `conv_graph_*` 主键去掉 `scope_hash`**，改为 `(owner_key, session_id)` + `library_ids_json`/`scope_hash` 作来源列；原「预留 `scope_key + scope_version`」作废；补「库集合变化时召回只取有交集的节点、不删历史节点」；§5.1 级联补第 5 处（库拆/合/退役，retire ≠ delete）。依据 `docs/superpowers/specs/2026-10-04-kb-multi-library-qa-design.md` D6/§5.3 | `history_store.scope_hash_for` 接列表；`sqlite_store.py` `_CHAT_MESSAGES_BODY` 主键 = (owner,session,seq) |
| 23 | **【2026-10-04 外部评审 P1 回写】**：① **§3.2 数字与正则更正**——实测 `data/platform/chat.sqlite`：带 cite 的 items 3,289（K 2,533 / **T 756 = 23.0%**）、assistant 560 条中**含任一引用标记 221 = 39.5%**（原 3,139 / 174 / 534 / 32.6% 作废）；**正则必须覆盖三类前缀 `\[([KTE])(\d+)\]`**，只抽 `[Kx]` 会漏 23% 的被引用 item 并系统性低估臂 2；② **§7.2 拆两闸**——闸 A（斜率闸，只读语义层增量，差分口径）＋ 闸 B（子图渲染段 ≤2,000 est 硬上限，§2 同步钉死）；原文把水平项与斜率项混在一句，±25% 容差容不下子图波动；③ **臂 3 必须自带通道 1**（离线直连 `list_blocks_by_clause_refs`，不等 M1 的 HTTP 端点），否则「收缩边界」可能是假阴性；④ **§3 两条落地约束**——蒸馏入口必须可调用（禁止内联在 SSE 分支，否则多轮评测测不到图）＋ 蒸馏读内存切片、水位在 persist 之后；⑤ A5 改判为「机制自检题」，不计入 §7.1 净改善分母 | 评审意见（2026-10-04）＋本次自测：`data/platform/chat.sqlite` 只读复算、`agent_tools.py` 的 `prefix=` 三处、`agent_loop.py:transform_context` 签名 |
| 24 | **【2026-10-04 臂 2 落地 + 三处实测口径更正】**：**臂 2（变体 ii 候选指针行）已实现**——`agent_configs.py:pointer_skeleton_enabled / _item_pointer_parts / _pointer_suffix`，在 `_summarize_tool_raw` 的 items 分支**追加**后缀（前缀与「检索到 N 条候选」逐字不动）；开关 `ANGINEER_POINTER_SKELETON` 默认关；上限 ≤5 条 / 文档名 30 字（先去扩展名）/ 条款 30 字 / 整段 280 字。三处口径更正（本节 §3.2 同步）：① `doc_title`/`clause_id` 覆盖是**按工具全有/全无**（knowledge 100% / table 0%），原「75.9% 部分覆盖」把两类混算、掩盖结构；② **落库 `meta_json` 只留 `{name, tool_call_id}`**，items 必须从 `content` 解析（260/260 实测无反例），否则重建/离线/评测路径静默拿空；③ `section_path` 最具体的一级在**最后一段**（单段 1,694 / 两段 1,524 / 三段 144 / 四段 2），从头截断会丢条款号。另：真实数据渲染校准出两条质量规则——同 doc+section 的重复条目**合并标记**（`T3,T4=…`，标记是 `[Tx]` join 键不可丢）、去 `.pdf` 扩展名 | 实现即证据：`tests/angineer-core/test_budget_gates.py` 新增 10 例（39 passed）；真实 `data/platform/chat.sqlite` 渲染对照；`agent_loop.py:915/1160/1277` 的 `meta=result_raw` |

## 1. 形态定版：一张持续演化的会话图

**模式定义（一句话）**：沿用同一条对话管线，只换「历史与证据怎么进 prompt」——user/assistant 逐字全带（语义层），
检索证据不再原文回灌、由会话图（**对话黑板**的本体，§5）结构化承接。

不是滚动摘要板。所有对话沉淀为**一张图**，每轮对话蒸馏出的关键节点、关系和引用
增量合并进图；对话不是被「压缩丢弃」，而是被**结构化吸收**：

```
                 一张持续演化的会话图（跨 run 存活）
        ┌────────────────────────────────────────────┐
        │ 节点：                                     │
        │   entity   实体（船型/码头型/地名…）        │
        │   clause   规范条款（JTS 165-2013 §5.4.12） │
        │   value    算出的量（T=12.8m、Z1=0.4m…）    │
        │   issue    未决事项（备淤深度 Z4 待确认）   │
        │ 边：                                       │
        │   cites    答案引用了条款（带轮次）          │
        │   derives  值由哪些条款/值推导              │
        │   follows  话题先后/未决关系               │
        │ 指针：节点挂文档位置（doc+条款号），不存原文 │
        └────────────────────────────────────────────┘
                     │ 每轮 prompt 只携带
                     ▼
        与本轮提问相关的子图 + 全量 user 提问逐字 + 全量 assistant 回答逐字
        （§2.1/§2.2，超预算按最老截断）+ 本轮全量证据
```

「上轮算出的系数」成为 value 节点可直接读；「引用过 JTG D60 §5.3.1」成为 cites 边；
细节出图不出索引——被指涉时模型按指针重检索自捞（L1 段工具能力在手）。
参照系：MemGPT/Letta core memory、Zep 时序知识图谱、LangGraph summary node 一脉，
但形态是图而非摘要文本。

**终态形态（2026-10-03 业主口径）**：图不只是后端记忆结构，而是**对话本体**——用户沿节点-边
路径导航推进对话与做题（§10.4）。M0-M3 交付的是「图作为记忆与证据层」的地基，M4 才交付
「图作为交互界面」的路径模式；验收指标分阶段对应，勿用地基指标宣告终态完成。

**【评审修订】topic 节点降级**：意图轨迹不再靠蒸馏产出，改由**真实 user 提问原文逐字**承担
（§2.1）——实测 19 轮会话的全部 user 原文合计 455 字符（≈227 tokens），占会话 0.07%，
而蒸馏出来的 topic 节点只是这个信号的**有损版本**。蒸馏范围由此收缩为 entity / clause / value 与边，
外加一个轻量 **issue 节点**（未决事项的唯一载体，open→resolved 两态，`mark_resolved` 的唯一作用
对象，§4 常驻段的数据来源），风险面相应变小。

## 2. 终态每轮 prompt（语义层斜率 ≈230 est tokens/轮 + 有界子图段；闸门口径见 §7.2）

```
system（档位提示词 + 工具 schema）
+ 全部真实 user 提问逐字（§2.1；一条一行，带轮次号）
+ 全部 assistant 回答逐字（§2.2；超预算按最老截断）
+ 相关子图渲染段（见 §4 召回；纯文本渲染，**硬上限 ≤2,000 est tokens**，见 §7.2 闸门 B）
+ 本轮提问 + 本轮全量证据（当轮不压，与 A1 protect_current_run 语义一致）
```

（段序约束，2026-10-02 三评修正：子图渲染段每轮变动，**必须后置到本轮提问之前**——user/assistant 逐字史在其前保持稳定前缀；若放在历史之前，其后全部内容每轮 cache miss，§7.3 净账直接判负。原版式把渲染段放在逐字史之前，与 §4 补充 3 矛盾，已按 §4 对齐。）

**【2026-10-03 补】截断与 prefix-cache 的相互作用**：最老优先截断一旦触发，逐字史前缀每轮都在变，
其后内容同样全部 cache miss。故 §7.3 的净账必须**分「未截断态」与「截断态」两段记**，
不能只报一个数；触发截断的长会话要单独看（这恰好是 §7.2 混合 L1/L2/L0/L3 连发压测的目的）。

**分层处理（按 §0.2，2026-10-02 业主口径重排）——语义层一个字不丢，只对证据层降维：**

| 层 | 是否进 prompt | 处理 | 现状（2026-10-03 核码） |
| --- | --- | --- | --- |
| system + 工具 schema | 是 | 不变 | — |
| **全部 user 提问** | **逐字全带** | §2.1 | 已是现状；本模式新增「过滤引擎注入提示」 |
| **全部 assistant 回答** | **逐字全带**（超预算按最老截断） | §2.2 | 已是现状（无截断）；本模式新增截断闸 |
| **历史 tool 证据** | **不回灌原文，改由图/指针替代** | §2.3 | **真增量**（现状压成 `检索到 N 条候选`） |
| 本轮提问 + 本轮证据 | 是 | 不压，与 protect_current_run 同语义 | 不变 |

原稿在这块的口径是「历史轮消息不再进 prompt（被图吸收）」——**这条已作废**：把对话压缩成图节点
是损失最大的一步，而它恰好是全会话里最便宜的部分（3.8%）。图应该只负责它真正擅长的事：
把占 96.2% 体积、且 A-min 一压就丢的**检索证据**变成可回引的结构。

**tool 原文一律不回灌**（哪怕属于近端轮）：本机实测单条 tool 消息 p50 = 26,917 字符
（≈13.5k tokens est）、p90 = 35,746 字符（nearest-rank 口径；含 6 条 ≤2.4k 字符的
`knowledge_stats`/`calculator` 迷你消息）、**77.3% ≥20k 字符**（最大 70,431 字符），回灌一条就打穿预算。
安全性由上游 §3 的闭环保证：引擎判定（`agent_loop.py:_tool_evidence_present`、
`agent_configs.py:final_answer_guard`、`agent_policy.py:success_check`）只扫当前 run 切片，
不吃历史证据（P-1 落地后 guard 的 evidence_parts 纳入 knowledge_stats 摘要，仍限当前 run）。
A-min 预算闸同步保留作保险丝（`req-chat-history-bloat.md` §6 第 8 条）。
另注：单 run 的工具循环 `max_turns` 默认 3（`agent_loop.py:AgentLoopConfig.max_turns`）——
§2.3 通道 1 的「按指针重检索」要与本轮其它工具调用抢这 3 个轮次，不能假设无限重试。

### 2.0 【评审修订】立项理由更正（重要）

原稿与本需求长期沿用的表述「A-min 只是削斜率，prompt 仍随轮数线性涨」**不成立**。
A-min 的闸语义是 oldest-first 压到达标为止，是**封顶**：

| 口径 | 数值 |
| --- | --- |
| A-min 后历史边际增量 | ≈ **279 est tokens/轮**（**n=1**：那条 19 轮会话的实测口径，含每轮压缩摘要行的补偿；按 `req-chat-history-bloat.md` §11.1 的 real/est p99=1.46 折算约 310-400 tokens/轮 **real**） |
| 19 轮会话历史压缩后总量 | **8,187 est tokens**（压缩前 331,054 est tokens） |
| 封顶线（QA 档 16k est） | **实测落在 20.7-20.9k real**（`req-chat-history-bloat.md` §11.3）；按 p99=1.46 折算的规则值 23.4k real 是上限估计，两个数不要混用 |
| 图路线对 token 的影响 | 19 轮口径 ≈ 子图 2-3k + 语义层（user+assistant 逐字）~7.2k est + system/当轮证据，real ≈ **13-18k tokens**（vs A-min 实测封顶 ~20.9k；降幅来自证据层降维，这是**约束**，不是收益）。历史斜率从证据原文 ~17k est/轮压到语义层 **≈230 est/轮**（全库均值：user 23.1 + assistant 435.5 字符 = 458.6 字符 ÷ 2；同一条 19 轮会话按自身总量算是 378 est/轮，**n=1，不能当斜率**） |
| 折算 ttft | ⚠️ **不是「每轮」数字**：按斜率 ≈0.168 s/1k tokens（由 `req-chat-history-bloat.md` §11.2 的表格折算，该节本身未写斜率）算，20 轮会话的**历史段累计** ≈0.9 s、30 轮 ≈1.4 s；折到单轮约 0.04-0.06 s。**仅作参照，不用于判定价值** |

**【2026-10-03 复核修正】原稿此表两处口径错**：① 上图路线行的「~400 est/轮」实为把同一条
19 轮会话的自身均值 378 当成斜率，与全库均值 230 冲突，且 §2.0 的 ttft 行又把同一个 400 标成 real；
② ttft 行的 0.9/1.4 s 是 20/30 轮的累计值，写成「s/轮」放大约 20 倍。
两者都不影响立项结论（token 只是约束项），但**闸门数字不能再用**——§7.2 改差分口径。

**📏 est 口径（2026-10-03 补，防再犯上面那个错）**：本项目的 **est token = 字符数 ÷ 2**
（`agent_configs.py:_estimate_tokens` / `make_budget_transformer` 的 `total_chars // 2`，两者逐位一致）。
**real 与 est 是两个数**：real ≈ est × 1.46（p99 实测系数，`req-chat-history-bloat.md` §11.1）。
凡写「N tokens/轮」必须标口径（est 还是 real），**不标口径的数字不得进闸门**——
上一版的「400 est/轮」就是把 real 当 est 写、又被当成斜率用。

**这张表回答的是约束，不是动机。** 关键结论只有一句：

> A-min 之所以能把 prompt 封在 ~20.9k real tokens，**手段是把历史的检索证据压成一行摘要
> （`[已压缩: 工具 xx 的结果，要点: 检索到 N 条候选]`）**。而那些被压掉的内容占会话 **96.2%** 字符，
> 正是专业对话里「刚才第二条规范怎么说」「上一步那个系数哪来的」的唯一答案来源。
> **封顶的代价 = 证据原文的消失**——这就是 A 支撑不了专业领域对话的根因，也是本方案存在的理由。

所以 token 的正确定位是：**在结构化保留证据的前提下，别让 prompt 炸掉**。
讨论路线要不要上、做得好不好，一律只看 §7.1 的指涉保真度，不看这张表。

### 2.1 全部真实 user 提问逐字全带

**【2026-10-03 复核】本条 95% 已是现状**：`agent_configs.py:make_budget_transformer` 只压缩
`role == "tool"` 的消息，user/assistant 从不被压；历史回灌（`chat_history.store.SqliteHistoryStore.load`）
无窗口、无条数上限。所以「全部提问逐字在手」今天已经成立，**本模式只新增一件事：过滤引擎注入的提示**。

| 项 | 实测（2026-10-03 复算 `data/chat.sqlite`） |
| --- | --- |
| user 消息占会话字符比 | **0.1%**（tool 96.2% / assistant 3.7%） |
| 平均单条 user | 23 字符（≈12 tokens） |
| 最长那条 19 run / 92 消息会话 | 全部 user 原文合计 **455 字符 ≈ 227 tokens**（该会话 user 消息 25 条：19 是 run 数，不是提问数） |
| 引擎注入的 user 提示 | **45/292 条**（占 user 消息 15.4%）、**760 字符**（占 user 字符 11.3%）——最大两类：`请先调用检索工具获取证据后再回答`（35 条）、`上一段未命中，进入下一段：`（10 条） |

作为上下文化改写 / 代检索 / 指涉消解的红线保障：

- 无论会话多长，模型始终看得到完整提问史，「刚才第二条规范」「第 4 题的计算再讲一遍」类指涉
  有一手材料，不依赖图召回命中；
- 上下文化改写取「上一问」的行为完全不变（还更稳）——实现是
  `agent_loop.py:_contextualize_followup_query`（跟进式阈值 `agent_loop.py:_FOLLOWUP_*`；
  项目内沿用的旧节号「§8.6」即指这段，本文档不再引用裸节号）；
- **必须过滤引擎内部注入的 user 提示**（口径同 `agent_loop.py:_INJECTED_USER_PROMPTS`，
  5 条前缀）：实测占 user 消息 15.4%，只带真实提问。这是本条**唯一的新增工程量**（约 10 行）；
- 超预算时按最老优先**丢弃**（不做摘要），并在丢弃位置留一行「前 N 条提问已省略」标记，
  以免模型误判为无历史。截断对 prefix-cache 的影响见 §2 段首补注。

### 2.2 全部 assistant 回答逐字保留（不蒸馏）

**【2026-10-03 复核】本条也已是现状**——原稿称「相对于原稿最大的一处加法」，实测是零工程量：
assistant 消息从不进压缩器（只压 `tool`），回灌无窗口。本模式在本条上做的唯一动作是**加一条截断闸**
（超预算按最老截断），属于减配，不是加法。

| 项 | 实测（2026-10-03 复算） |
| --- | --- |
| assistant 占会话字符比 | **3.7%**（全库 232,578 字符） |
| 平均单条 assistant | **435.5** 字符（≈218 est tokens；原记 436 系四舍五入） |
| 最长那条 19 轮会话 | assistant 合计 **13,919 字符 ≈7.0k est tokens**（按 real/est ≈1.4 折 ≈10k real tokens） |

理由：

- 历史答案是**已经消化过的结论**（引了哪本规范、用了哪个公式、算出多少），比从图重新生成可靠得多；
  专业追问多为「基于上一步的 XXX 再算一次」，执行前提就是上一步的结论原文在手。
- 让小模型把答过的话重写成图节点是整个链路里**信息最容易失真的一环**；既然体量付得起，就不必做。
- **控制手段：超预算时按最老优先截断（保留完整段落，不做摘要）**，并在断点留标记。
  assistant 与 user 谁先让路：优先保 assistant（结论密度更高），user 全带的代价本来只有 0.1%。
  ⚠️ 截断一触发，逐字史前缀每轮都变 → 其后全部 cache miss（见 §2 段首补注，§7.3 要分态记账）。

### 2.3 证据层的三种回引方式（图的主战场）

历史 tool 消息不再以原文形式进 prompt，改由下面三条通道保证「追问时能捞回来」：

1. **指针召回**：图节点挂 `doc_id + clause_id（或 section_path）+ page_label`，被指涉时模型按指针
   重捞原文。这是「证据不丢」的兜底保证。
   ⚠️ **现状缺口**：agent loop 的多轮工具循环能力具备（`agent_loop.py:AgentLoopConfig.max_turns`，
   默认 3 轮），但 `knowledge_search` 的模型可见参数只有 `query` 一个字符串
   （`agent_tools.py:AgentTools.knowledge_search` 的 `parameters_schema`），
   `doc_ids`/`clause` 是构造期绑定、模型不可传——模型拿到指针只能改写成语义 query 碰运气。
   ⚠️ **M1 前置项：新增只读工具 `fetch_clause(library_id, doc_id, clause_id|section_path)` → 原文块**，
   否则本通道名存实亡，证据回引只剩通道 2（引用边覆盖 39.5% 轮次 × clause_id 11.0% 的双重折损）。
   ⚠️ **多库下必须带 `library_id`（2026-10-04 补）**：同一条款可能同时存在于两个库，指针光有
   `doc_id + 条款` 无法定位到组文件；而节点来源列已记 `library_id`（§3.2），直接透传即可。
   `fetch_clause` 与 `knowledge_search` 一样从**构造期绑定**改为**参数化**（但必须受会话库集合白名单约束，
   不许模型越权取库外文档）。
   ✅ **M0 前置确认已关闭（2026-10-03 核码）**：docs-core **没有**按条款号/section_path 取原文的
   HTTP 端点（`docs_api/retrieve_routes`、`routes/v1/documents`、`docs_routes` 均按 query/page 过滤），
   **但 store 层现成**——`canonical_sql_store.py:list_blocks_by_clause_refs`（`clause_id` 有索引，
   `clause_resolver.py` 已在用，只服务于「query 文本里带条款号」的既有路径）。
   所以结论是：**要新建一个薄 HTTP 端点（+1-2 天成立）**，不是「未知工作量」。
   同时注意 `max_turns=3`：指针重检索要与本轮其它工具调用抢轮次，M1 要为它留额度。
   ⚠️ **两种回引机制必须在 M0 前选定（2026-10-04 评审补）**：① **召回层预取注入**——消解命中节点后
   由管线直接取回原文块拼进渲染段（确定性、不吃轮次预算，**M0 默认**）；② **模型可见工具自捞**——
   由模型决定调 `fetch_clause`（吃 `max_turns=3` 预算）。两者测出的增益不是一回事，混用等于换臂；
   定版见 `plan-blackboard-arms.md` §1「臂 3 的指针回引机制」。**M0 的臂 3 必须带通道 1**——
   离线直连 `list_blocks_by_clause_refs`，不等 HTTP 端点（否则臂 3 vs 臂 2 被低估，可能得出假的
   「收缩边界」）。
2. **引用边 + 值节点**：本轮答案引了哪几条规范、算出什么量，落成节点/边粘在图上，
   「刚才第二条规范」「上轮算出的系数」直接命中（§3.2 给出 join 口径）。这是免重检索的快通道。
3. **被引用片段的原文缓存（备选，默认关）**：对本轮**真正被 `[Kx]` 引用到**的那 1~5 个 item，
   把原文（而非全部 20 条候选）存进图。体量估算：5 条 × 1,500 字 = 7,500 字符/轮，
   10 轮 = 75k 字符 ≈37.5k est tokens —— **明显超预算**，故默认关；退而求其次只存
   **指针 + 200 字摘录**。是否值得由 M0 用真实长会话量一次。

统一的判断标准只有一条：**追问能不能答对**（§7.1），不是「省了多少 token」。

## 3. 写路径：run_end 后异步蒸馏合并

```
run_end（主路径结束，ttft 不受影响；挂载点 main.py:event_stream 的 `event.type == "run_end"` 分支）
   │   断连/异常分支同接（main.py 的 `is_disconnected()` 取消支，与其后 `persisted` 兜底补写支）
   ▼ 异步任务（不进关键路径）
小模型蒸馏：输入 = 本轮切片（口径见 §3.1，且**定死为**：user/assistant 原文
   │   + tool 结果的全部 items 元数据 + 被引用 item 正文；**不是**整段 tool 原文照搬）
   │   输出 = 图增量操作集（add_node/add_edge/update_value/mark_resolved：仅作用于 issue 节点）
   ▼
ops 校验（§3.3）→ 合并进图（append-only 为主，修订走追加标记）
   │            → 落 conv_graph_version + 推进 conv_graph_state 水位（§3.4）
   ▼
图版本随 run_id 落盘（可事后逐轮归因；图污染是静默累积的，必须可回放）
```

**【2026-10-04 评审补】两条落地约束（都会造成静默错误，必须写进实现）**：

1. **蒸馏入口是一个可调用的函数，不许内联在 SSE 分支里**：定形为
   `conv_graph.distill_run(owner_key, session_id, run_id, slice_messages, library_ids) → ops`。
   三方共用：SSE 的 run_end、M0 的离线壳、M3 的评测基建。理由：§7.6 的多轮评测若沿用
   `_query_helper.run_eval_query`（直连 `run_policy_query`、不走 SSE），内联式挂载**根本不触发**，
   评测测到的会是「图是空的」的残血臂 3。
2. **蒸馏读内存切片、水位在 persist 之后**：输入用 `hist_list[hist_base:]` 的内存切片（与 §3.1 一致），
   **不要重读 chat.sqlite**——客户端断连兜底支的 persist 滞后，重读会拿到不含本轮的库；
   `conv_graph_state` 水位推进放在 persist 成功之后，错了也由 `run_id` 幂等兜底，
   但**水位不得先于落库前进**。

**蒸馏成本（2026-10-03 补，原稿只写「零头」）**：按上面的输入口径，单轮输入 ≈ 全部 items 元数据
+ 被引用 item 正文（1~5 条），量级在数千字符。⚠️ 若实现成「整段 tool 原文照搬」，单轮输入会到
**10 万字符量级**（单条 tool 消息 p90 35.7k 字符 × 一轮多次工具调用）——两者差约 10 倍，
**所以 §3.1 的输入口径必须先定死再写代码**。另外，省下的 prefill 不是「40~60k」，
而是 §2.0 那张表里的量级；且蒸馏与在线推理**抢同一批算力**，按 §3.5 的三条约束管住。

### 3.1 【评审修订】蒸馏输入的原文纪律（红线）

- 必须取 **`session.history` 本体 / `chat.sqlite` 的全量原文**（未被 `transform_context` 投影过的版本）。
  理由：A-min 的投影式压缩会把历史 tool 消息换成一行摘要，压缩后 `[Kx] → item` 的 join 材料
  （§3.2）随之丢失；投影式纪律的好处恰恰是「本体永不动」。
  **「取原文」指的是取投影前的切片，不是把 tool 原文整段喂给蒸馏模型**——喂进去的是
  「全部 items 元数据 + 被引用 item 正文」（见 §3 流程与成本段）。
- ⚠️ **items 必须从 `content` 解析，不能读 `meta_json`（2026-10-04 实测）**：落库时
  `chat_messages.meta_json` 只剩 `{name, tool_call_id}`（260 条 tool 消息里 0 条带 `items`），
  而完整 JSON（`items`/`citations`/`total`）在 `content` 列。凡走「回读 chat.sqlite」的路径
  （图重建、M0 离线壳、M3 评测）读 `meta_json` 都**静默拿到空 items**；
  在线压缩路径读 `message.meta`（内存态 = `result_raw`）才是对的——两条路不要混。
- 本轮切片口径直接复用 `main.py` 中 `hist_list[hist_base:]` 的语义（`hist_base` 在 run_future 创建前
  capture），**不要另算基线**——那段注释记录了三次实踩（丢本轮 user 消息、空列表 `or []` 快照脱节、
  基线 capture 竞态；两次生产 + 一次本地）。
- **蒸馏输入按 tool 名过滤（2026-10-02 意图改造落地后新增）**：knowledge_stats 已下沉 L1 统一工具箱
  （5e6ecb5），stats 消息会出现在本轮切片——**不进蒸馏**：其结论已逐字落在 assistant 原文（语义层），
  JSON 无 doc 定位、无指针价值；只喂检索类三工具（knowledge_search/table_search/entity_search）。
  stats 类追问的指涉由语义层承担，图不重复承载。
  ⚠️ **跨文档冲突（2026-10-03 发现）**：`req-abolish-meta-query-route.md` §4 写的是「蒸馏吃
  knowledge_search/knowledge_stats JSON」——与本条相反。**以本条为准**，那篇需回改。

### 3.2 引用边：不是白送，是可确定性重建（澄清原稿）

**⚠️ 2026-10-04 复核修正：原表口径过期，且标记前缀是三类不是一类。** 重测（`data/platform/chat.sqlite`
只读，2026-10-04；阶段二三域归位后该库已从 `data/chat.sqlite` 迁走并继续增长，**原 n=3,139 / 174 / 534
三个数均作废**）：带 cite 的 items **3,289**（`K` 2,533 / **`T` 756 = 23.0%**）；
assistant 消息 **560** 条，含 `[Kx]` 179、含 `[Tx]` 51、含 `[Ex]` 0、**含任一 221 = 39.5%**。
前缀由工具决定：`knowledge_search`=`K`、`table_search`=`T`、`entity_search`=`E`
（`agent_tools.py:_assemble_search_result` 的 `prefix=`）。

| 字段 | 覆盖率 | 说明 |
| --- | --- | --- |
| `cite`（`[Kx]`/`[Tx]`/`[Ex]` 标记） | **100.0%** | `agent_tools.py:MarkerAllocator.next` 分配，写进 `items[].metadata.cite`（赋值点 `agent_tools.py:_assign_cites`） |
| `doc_title` | **knowledge 100% / table 0%**（合计 ~76.6%） | ⚠️ **2026-10-04 实测更正**：不是「75.9% 部分覆盖」，而是**按工具全有/全无**——table_search 侧上游传 `doc_title_map={}`，故 table item 只能退 `doc_id`。原「2,383/3,139 = 75.9%」把两类混算，掩盖了这个结构 |
| `clause_id`（规范号+条款号） | **knowledge 14.4% / table 0%**（合计 11.0%） | ⚠️ 同样按工具分：只有 knowledge_search 的部分条目带（371/2,578） |
| `title`（item 顶层） | 100% | ⚠️ **是章节标题/表名不是文档名**，不得拿它冒充 doc_title 把覆盖率「凑到 100%」 |
| `section_path` | 100% | 单段 1,694 / 两段 1,524 / 三段 144 / 四段 2——**最具体的一级在最后一段**，从头截断会丢条款号（`_last_section_segment` 的理由）；**0 条含规范号** |
| `library_id` | 单库会话 0%，多库扇出时逐项带 | `agent_tools.py:_items_to_evidences` 的「多库扇出下逐图标源」——**多库请求直接取它；单库请回退会话库集合**，别当必填字段 |

**⚠️ 另有一条实现级陷阱（2026-10-04 实测，会静默毁掉重建/离线路径）**：**落库的 `chat_messages.meta_json`
只保留 `{name, tool_call_id}`，没有 `items`**（260 条 tool 消息实测 0 条带 items）。
内存态相反：`agent_loop.py` 构造 tool 消息时传的是 `meta=result_raw`，所以**在线压缩**读 `message.meta` 是对的；
但凡**从 chat.sqlite 回读的路径（图重建、M0 离线壳、M3 评测）必须解析 `content`（JSON 文本）取 items**，
读 `meta_json` 会得到空结果且不报错。样本：`content` 顶层键 = `citations / items / relevance_scale / total`。

据此更正：

- ✅ 「引用边」几乎白送，但**不是读 `metadata["cite"]` 就完事**——该字段存的是**标记本身
  （字符串 "K1"）而非映射**。映射要按下面口径重建。
- ⚠️ **正则必须覆盖三类前缀**：`\[([KTE])(\d+)\]`。只抽 `[Kx]` 会漏掉 **23.0% 的被引用 item**
  （表题在本领域是高频），后果是「引用边覆盖不全」+「臂 2 被系统性低估」。
- ⚠️ 「文档名/条款号并入 clause 节点」不白送：**只有 11.0% 的块带 clause_id**。剩余部分要么落到
  「文档名 + section_path」的粗粒度节点，要么让蒸馏模型从正文抽——后者等于放弃
  「不依赖蒸馏模型记得原文」的一半前提。**M0 必须先量化这一点对指涉专项的影响。**
- ⚠️ 覆盖面有限：**含任一引用标记的 assistant 消息 = 221/560 = 39.5%**（闲聊/无检索轮不产生引用边）。
  图的实质内容主要由四成左右的轮次贡献。

重建口径（写进实现）：

```
同一 run 切片内：
  1) 从 assistant 文本正则抽全部 [KTE]x 标记（\[([KTE])(\d+)\]）→ 得到「本轮真正被引用的标记集合」
  2) 在本轮 tool 消息 JSON 的 items[].metadata.cite 里找同名标记的 item
     （K 来自 knowledge_search、T 来自 table_search、E 来自 entity_search）
  3) clause 节点 key = (library_id, doc_id, clause_id | section_path)：
     library_id 取该 item 的 metadata.library_id（阶段三逐项标源，现成；缺失回退本轮请求库），
     doc_id 取 item 的文档标识 —— 三者齐备才唯一，**同一条款跨两个库不再撞车**
  4) 建 cites 边：本轮 assistant → clause 节点，meta 记 {run_seq, marker}；
     节点/边的来源列同时写 scope_hash 与 library_ids_json（该轮的库集合）
MarkerAllocator 每 run 独立分配（跨 run 撞号），故 join 必须限定在单 run 切片内。
```

### 3.3 【评审修订】ops 校验（新增，动工前必须定）

- 白名单：只接受四种 op，其它整批丢弃 + 打日志（不部分应用）。
- **引用完整性**：`add_edge` 的 src/dst 必须指向本图已存在的 node_id（含本批次新增），
  否则丢弃该 op——悬挂边是图损坏的主要形态。
- 值节点必须带单位与来源轮次（「12.8」不合格，「T=12.8m」合格）；无单位的数值不允许建 value 节点。
- **值节点原文回查（2026-10-02 追加）**：蒸馏产出的数值必须能在本轮 assistant 原文中字符串命中，
  查无此值整 op 拒收——assistant 原文逐字保留，真实值必然在原文出现过；零成本防蒸馏幻觉。
- 单批次 ops 上限（建议 20 条）+ 单会话节点数上限，防蒸馏模型把图刷爆。

### 3.4 【评审修订】异步可靠性：水位 + 补跑（新增）

只有 `conv_graph_version` 台账不够：进程重启 / 异步任务被杀 → 该轮**永久丢失且无痕迹**。

```sql
-- 键与会话身份同型（阶段三 D6）：(owner_key, session_id)
conv_graph_state(owner_key, session_id, last_run_id, last_seq, status, updated_at)
```

- 蒸馏成功后推进 `last_run_id`；启动时对 `chat_runs` 做差集补跑（幂等由 run_id 保证）。
  会话身份是 `(owner_key, session_id)`——**库集合变化不再换会话**（D6），所以水位天然跨集合续接，
  补跑用同一把键即可。
- 补跑失败不改水位，下一轮重试；连续失败进运维告警（`WEBHOOK_SYSTEM` 已有）。

### 3.5 蒸馏模型与配额（新增）

> **【2026-10-02 更正】原稿「`LLM_CONFIGS` 里没有现成的「小模型」端点，默认配置就是在线服务那张卡上的
> 模型」前半句不成立**——核代码 + 读本机 `.env` 后推翻：默认端点本身就是 A3B（**35B MoE / 3B 激活**），
> 且已有一个更小的独立端点在用。后半句（抢卡）成立，保留并写具体。

本机 `.env` 实测（`LLM_CONFIGS` 解析见 `llm_config.py:111`；字段 `name` / `model` / `base_url` /
`priority` / `enabled` / `enable_thinking`）：

| 配置名（`LLM_CONFIGS[].name`） | model | base_url | priority | 说明 |
| --- | --- | --- | --- | --- |
| `Qwen3.6-35B-A3B` | `qwen3.6-35b` | `https://angineer.cn/api/llm` | 10 | **默认问答模型**（`ANGINEER_DEFAULT_MODEL`）。A3B = **3B 激活**，本身就是小激活量模型 |
| `Qwen3.8-Flash-Next` | `qwen3.8-flash-next` | `https://angineer.cn/api/llm2` | 5 | **独立端点**，已被 `EVAL_JUDGE_MODEL` 用作专用判分模型（`answer_eval.py:_judge_candidates`） |
| `Qwen3.6-A3B` | `qwen3.6-35b` | 同上 `/api/llm` | 1 | 与上者同 model 同 base_url 的**冗余重复项** |

据此更正三条：

- ✅ **「小模型」现成可用，不需要为蒸馏部署新模型**：默认端点 A3B 激活量只有 3B；更小的
  `Qwen3.8-Flash-Next` 走独立端点 `/api/llm2`。原稿担心的「没有小模型端点」不存在。
- ⚠️ **真正的问题只剩一条：抢卡**。不指定时按 `priority` 取最高 = `/api/llm`，与在线问答
  **同一端点、同一张卡**（`/api/llm` → `127.0.0.1:18004` 隧道 → dgx1 vLLM，
  `req-table-retrieval-latency.md` 的 AI 网关端点清单）。蒸馏必须**显式指定走 `/api/llm2`**，
  否则每轮多出的这次生成请求直接压在在线推理头上。
- 🔧 **指定方式对齐现有范式，不新造平行变量**：项目已有 `EVAL_JUDGE_CONFIGS` / `EVAL_JUDGE_MODEL`
  （`answer_eval.py:_judge_candidates`，元素是 `LLM_CONFIGS` 里**已注册的 `name`**，带失败切链；
  注意未设置时它回退 `[None]` = 被测默认模型，不是「静默降级」而是既有语义）。蒸馏照抄即可：
  **`ANGINEER_GRAPH_DISTILL_CONFIGS`（JSON 数组）/ `ANGINEER_GRAPH_DISTILL_MODEL`（单名，向后兼容）**。
  原稿「建议单独新增 `ANGINEER_GRAPH_DISTILL_MODEL`」方向对，但必须**挂到 `LLM_CONFIGS` 的 name
  体系上**——别另起一套端点配置，否则又是一个「改了变量但没接进配置源」的静默失效口子
  （教训源：`WEBHOOK_SYSTEM`/`WEBHOOK_OWNER` 改名后服务器 `.env` 未同步，nightly 结论静默漏发，
  见根 `AGENTS.md` 运维段）。超时 / 重试 / 并发上限需单独写明：蒸馏异步，不应复用在线侧的
  `ANGINEER_TIMEOUT_TOTAL` 语义。

- **【2026-10-03 补】三条硬约束（原稿只写「需单独写明」，这里给值）**：
  ① **并发上限 = 1**（每会话串行；跨会话也要限流，因为下游是同一批算力）；
  ② **与 nightly 错峰**：`/api/llm2` 同时是 `EVAL_JUDGE_MODEL` 的端点（本机 `.env`），
  nightly 判分时段蒸馏应退让（或整体走低优先队列），否则评测与蒸馏互相排队、两边都不稳；
  ③ **超时 / 退避**：蒸馏失败不改水位（§3.4），按指数退避重试，连续失败进 `WEBHOOK_SYSTEM` 告警。
- **游客配额口径**：`chat_auth.py` 的 `ANGINEER_GUEST_ROUNDS` **代码默认 30**（本机 `.env` 覆盖为 5）——
  放大倍数按服务器实际值算，别按默认值报数。

- **成本面（承接上条）**：每轮多一次生成请求，且**默认只对登录用户启用图**，游客走 A-min
  （游客侧放大倍数按服务器 `ANGINEER_GUEST_ROUNDS` 实际值算）。
- **同卡与否仍未查证（M0 待确认项，保持开放）**：`/api/llm2` 上游是 `100.86.101.0:8888`，与 `/api/llm`
  的 18004 隧道路径不同，但**隧道远端是否与 llm2 同机未查证**
  （`req-table-retrieval-latency.md` 已自标为「高嫌疑而非定论」）。
  这一条决定「批处理错峰」还是「走独立端点」——M0 一并给结论。

## 4. 读路径：子图召回

按本轮提问从图里取相关子图，这是相比摘要板多出的核心工程量：

```
本轮提问（含 agent_loop.py:_contextualize_followup_query 改写后的 query）
   │
   ├─ 实体/条款号匹配：query 中的规范号、条款号、数值、实体词 → 直接命中节点
   ├─ **序数/指示代词消解（2026-10-03 新增，直指 §7.1 的样例追问）**：「刚才第二条规范」
   │   「上一步那个系数」这类指涉，字符串匹配**命不中**——它需要的是「上一轮 cites 边的第 2 条」
   │   这种**指针算术**，不是词面匹配。规则：连到最近一轮 assistant 的 cites 边序列，按序号取第 N 条；
   │   无序号时取该序列全部（≤5 条）。纯确定性，无模型调用，与下面 p95 预算同档。
   ├─ 近邻扩展：命中节点的一跳邻边（cites/derives 反查）
   ├─ 常驻段：未决事项（每轮必带，体量小；意图轨迹由 §2.1 user 原文承担，不再重复入常驻段）
   └─ 向量召回（可选二期半）：节点描述 embedding 近邻——首版不做，
      先用字符串/编号匹配验证图形态价值
   ▼
渲染成固定版式的文本段进 prompt（节点按类型分节，每条一行，自描述）
```

渲染段必须**自描述**（「JTS 165-2013 §5.4.12：杂货船 Z1=0.4m（第4轮算出）」），
不带 [Kx] 编号——编号每 run 独立分配会跨轮撞号（见 `req-chat-history-bloat.md` §5.2 定下的约束）。

**【评审修订】三条补充**：

1. **召回输入带上 §2.1 的 user 提问史**：多轮追问形如「那第二条呢」时，用历史提问原文做字符串匹配，
   命中率显著高于只用改写后的 query——这是全带 user 原文的第二重收益，零额外成本。
   （提示代词类靠上方的序数消解规则兜底，别指望字符串匹配。）
2. **读路径是同步的**，落在 ttft 关键路径上。必须给延迟预算：**p95 ≤ 30 ms**（纯 SQLite 查询 +
   字符串匹配，不得引入任何模型调用）；超时或异常一律降级为「只带常驻段」，由 A-min 保险丝兜底。
3. **段序约束（prefix-cache，2026-10-02 追加）**：子图渲染段是每轮变动的内容，必须**后置到本轮
   提问之前**——user/assistant 逐字史在其前保持稳定前缀。若放在历史之前，其后全部内容每轮
   cache miss，§7.3 的净账直接判负。配套：渲染排序固定 + 追加式渲染。
4. **【2026-10-03 补】截断态要单独记账**：§2.2 的最老截断一旦触发，逐字史前缀每轮变化，
   子图段后置也救不回缓存。§7.3 因此按「未截断态 / 截断态」两段读数，各自与 A-min 同态比。

## 5. 存储与载体裁决

**裁决结果（2026-10-01 核实代码后定版，2026-10-02 复核维持）：独立会话图存储，不扩 `Memory`。**

依据（已复核）：`memory.py` 的 **变量黑板**（代码标识符 `Memory.blackboard`）是 `Dict[str,Any]`、
`chat_context` 是实例内 append-only `list`，`sop_runner.py:60` 为 `self.memory = memory or Memory()`——
生命周期 = 单次 sop_execute，不过 run 边界，与会话历史零交集。方向上远期可汇流（任务态+对话态分区进
一份 Memory），本期不动 SOP 侧。⚠️ 术语：SOP 侧叫**变量黑板**，与本方案的**对话黑板**是两个对象
（见文档头部「正名轨迹」）。

存储选型：**SQLite 新表**（落在聊天历史库，与聊天历史同命、同卷跨发版存活）。
⚠️ **路径随 DB 改造更新（2026-10-04 核验）**：该库现已随阶段二迁到 **`data/platform/chat.sqlite`**
（`chat_history.store.DB_PATH = resolve_data_file("CHAT_DB_PATH", "platform/chat.sqlite")`，旧
`data/chat.sqlite` 已不存在）——本节此前写的 `data/chat.sqlite` 作废，**M1 一律跟随该路径常量，
不得写死任何 data/ 路径**。

**【2026-10-04 定版】落位、键模型与并发**（阶段三 Phase B–E 已提交：`60f349d`/`50fc410`/`1487de0`/`8f2bf8a`；
键模型以 `docs/superpowers/specs/2026-10-04-kb-multi-library-qa-design.md` 的 **D6** 为准）：

- **schema 归属**：`data/platform/chat.sqlite` 由 `services/chat-history` 拥有（建表在
  `chat_history.store.init_db`，`aichat-api` 通过 `SqliteHistoryStore` 读写同一文件）。
  `conv_graph_*` 四表必须**加进那个 `init_db`**（并在同包内提供 DAO），不要另起第二套建表入口——
  这个库的迁移是「init_db 内联 ALTER / 重建表」（`_migrate_scope_out_of_pk`、`_migrate_sessions_library_ids`
  即先例），没有 `PRAGMA user_version` 版本机制，多入口建表必然漂移。
- **双写并发**：现有连接只设了 `journal_mode=WAL`（`sqlite_store.py:_get_conn`），**没有 `busy_timeout`**。
  加一个异步蒸馏写入方后，`SQLITE_BUSY` 会变成偶发丢图。M1 落地时同处补 `busy_timeout`（建议 5s）
  与短事务（单批 ops 一个事务），并保持「每会话串行」。
- 图是**派生缓存**：消息原文不动，图损坏/版本错乱可从消息流整体重建（重放蒸馏），
  延续投影式纪律「本体永不动」。**阶段三后重建更完整**：`chat_messages.scope_hash` 现为消息级来源标记，
  故重放时能逐轮复原节点的 `scope_hash` / `library_ids_json` 来源列，不必额外落盘。

**键模型（2026-10-04 定版，对齐 D6）**：

```sql
-- 图本体（当前态）。会话身份 = (owner_key, session_id)，与 chat_messages 现主键同型
conv_graph_node(owner_key, session_id, node_id,
                type, key, value_json,
                scope_hash, library_ids_json,      -- 来源标记：本节点由哪一轮的哪些库产出
                first_run, last_run, status)
conv_graph_edge(owner_key, session_id, edge_id,
                type, src, dst, meta_json, run_id,
                scope_hash, library_ids_json)
-- 版本台账（归因/回放/重建）
conv_graph_version(owner_key, session_id, run_id, ops_json, created_at)
-- 水位（见 §3.4）
conv_graph_state(owner_key, session_id, last_run_id, last_seq, status, updated_at)
```

- **为什么不再把 `scope_hash` 写进主键**：阶段三（D6）把会话身份定在 `session_id`——池 key 去掉 scope、
  `chat_messages` 主键重建为 `(owner_key, session_id, seq)`、`scope_hash` **降级为消息级来源标记**
  （`history_store.scope_hash_for` 现接**列表**；单库输入与旧算法逐位一致，旧行不需迁移）。
  若图仍按 scope 分桶：同一会话一换库集合就开出第二张图，与「跨集合续接」的既有语义冲突，级联删除还会漏桶。
- **原稿「库或文档集变化即新 hash → 新会话，不回灌旧 scope 历史」的表述作废**（那是阶段三之前的语义）。
- **库集合变化时的召回规则**：节点上的 `library_ids_json` 记的是**产出时**的库集合。召回默认
  **只取与当前会话库集合有交集的节点**（防「换了库还在答旧库条款」）；被排除的节点**不删**——
  它们是历史见证，§10 调试版可见。
- **`owner_key`**：缺失则无法随 owner 删除 / `claim_guest` 改挂级联。

### 5.1 删除 / GC 级联（原稿「天然对齐」不成立）

有一处必须写死的坑：`sqlite_store.py:gc_expired` **先按消息 `created_at` 删消息、
后按会话 `updated_at` 删会话** → 存在「消息已删、会话行还在」的时间窗，此时「图可从消息流重建」
失效（本体没了、图还在且无法验证）。**五处**调用点必须同步改造
（`sqlite_store.py:delete_session` / `:delete_sessions_by_library` / `:claim_guest` / `:gc_expired`，
后两者已实测：`claim_guest` 现改挂 guests+messages+sessions+runs 四处）：

| 调用点 | 需要联动 |
| --- | --- |
| `delete_session` | 同删 `conv_graph_{node,edge,version,state}` |
| `delete_sessions_by_library` | 同上（批量）。阶段三后判据是 `chat_sessions.library_ids_json` 的**成员匹配**（命中任一勾选库即算本库会话），图级联走同一判据 |
| `claim_guest`（owner 改挂） | 图行 `owner_key` 一并 UPDATE（含 `conv_graph_version` / `conv_graph_state`），否则按 owner 查询漏图 |
| `gc_expired`（`ANGINEER_CHAT_RETENTION_DAYS`） | **按会话维度整会话连带删图**，不得残留孤儿图 |
| **（第 5 处，2026-10-04 补）知识库拆 / 合 / 退役**（`plan-kb-split-groups.md` 阶段四） | **retire ≠ delete**：退役只让指针悬空（`fetch_clause` 须优雅失败，不删图）；拆分/合并改的是 `library_id`，而图节点 key 用 `doc_id + 条款`（库无关）→ 只需按新归属回填 `library_ids_json` 标记 |

## 6. 与现有机制的衔接

| 现有机制 | 衔接方式 |
| --- | --- |
| A-min 预算闸（transform_context） | 保留为保险丝。**图启用后 user/assistant 逐字史照旧进 prompt**（不是「历史轮不进 prompt」——那是已作废的旧口径），真正不再进 prompt 的只有历史 **tool** 消息；总字数量级因此下降，闸通常不触发，触发时按原语义压 tool 层（§2.0：二者是「同预算下的保真度」对比关系，不是线性/常数的对立） |
| protect_current_run / 当轮证据 | 语义不变：当轮证据全量进 prompt，不压不进图（run_end 后才蒸馏） |
| 上下文化改写 / 代检索取「上一问」 | 实现在 `agent_loop.py:_contextualize_followup_query`（项目内旧节号「§8.6」指这段）；由 §2.1 全部 user 提问逐字承担，红线不动且更强 |
| MarkerAllocator [Kx] | 每 run 独立分配不变；图内引用边用自描述文本；跨 run join 口径见 §3.2 |
| 思考过程面板 resultItems | 不受影响（渲染的是当轮工具返回） |
| **【评审修订】评测体系** | 现有 nightly / 39 题拒答 / open_ragbench **不会触发图**（§7.6），必须新建多轮评测能力 |
| **【已落地并上生产】意图识别改造（独立轨道，2026-10-02 两步走实施完毕，随 v0.2.87 发版）** | `req-abolish-meta-query-route.md`（468f7a9 止血＋5e6ecb5 拆档）：meta 档与 `_meta_answer_usable` 已删、路由只剩 level 轴、knowledge_stats 进 L1 统一四工具箱、P-1 guard 兼容 stats、P-2 QA v14 注入对冲——**本模式 M2 的装配区地基已就绪**；分工与融合结论（其 §4）维持：上下文层改造与本模式零耦合 |

## 7. 质量闸与验收

**验收主线 = 业主口径的专业对话能力**（§0.1），即：**同等 prompt 预算下，多轮追问能不能答对**。
token / ttft / prefix-cache 全部降为**约束项**——它们是「别把 prompt 弄炸」的护栏，
不具有否决本路线的权力（这一条是 2026-10-02 误判的教训，别再拿延迟当秤）。

1. **主线：多轮指涉质量（唯一的一票否决项）**。至少 20 题真实专业追问
   （「刚才第二条规范说什么」「上轮算出的系数是多少」「第 4 题的计算再讲一遍」
   「按上一步的结论换个船型再算一次」），与 A-min 基线逐题比对（**基线＝意图识别改造落地后的现状
   重放**，见 §8 M0 行；改造前后数字跨口径不可比——intent 97/100→98/100、financebench 58%→46.7%，7 题误路由虚假基线水分已挤出），要求
    **不劣化且至少一项明显改善**。判分由业主本人执行即可——他就是领域专家，也是这套系统目前
    唯一的使用者，**不必为此先造一套大规模评测基础设施**。每题留判分依据（对错理由/结论截图），
    供 §9 图漂移归因复用。
   ⚠️ **【2026-10-03 补】判分必须预注册，且「明显改善」要有判定规则**（项目自己的规范：判分跑前
   锁死，见 `plan-officeqa-arms.md` 的做法）。落地件 = `docs/plan-blackboard-arms.md`：
   题集清单与来源（**优先取自库里 247 条真实 user 提问 + 那条 19 轮真实会话**，合成追问只作补充——
   合成问题天然使用字符串匹配期待的词表，会系统性高估召回命中）、判分口径、**呈现盲序**
   （业主不知道哪条答案来自哪一臂、逐题独立判、禁跨题对比）、以及判定规则（建议：净改善题数 ≥3
   且净回归 = 0 才算「明显改善」，否则按「未达线」处理）。跑对照臂之前先冻结 A-min 基线快照
   （同 case 集的完整答案文本 + 运行时间）。
2. **约束①：prompt 不炸（拆成两条闸，2026-10-04 评审修正）**。原稿把两件不同量纲的事写成一条闸：
   子图渲染段是**每轮全量进 prompt 的水平项**，语义层是**逐轮累加的斜率项**——混在一句里，
   ±25% 的容差（≈±58 est tokens）根本容不下子图段随 query 的波动，闸会误判。拆开：

   - **闸 A（斜率闸，差分口径）**：同会话连发 ≥15 题（混合 L1/L2/L0/L3），只读**语义层（user+assistant
     逐字史）的每轮增量 est tokens**，判据 = **新模式 ≤ A-min 在同一会话上的实测增量**
     （A-min 基线实测 ≈279 est tokens/轮，`req-chat-history-bloat.md` §11 口径；理论值：新模式
     = 语义层 ≈230 est/轮——历史 tool 压缩行不再进 prompt，本就该**更低**）。容差 ±25%。
     若触发 §2.2 最老截断则按封顶口径读数。**子图段不计入本闸**。
   - **闸 B（段上限闸，水平口径）**：子图渲染段每轮 **≤2,000 est tokens**（§2 的硬上限），
     且**逐轮留痕**该段实际 est；超限即视为 M2 不达标（先压渲染，不是压语义层）。
   - 超预算的处置优先级：见 §2.2——先截断历史证据本身，**语义层（全部 user + assistant）优先保住**。
   - ⚠️ 原稿的绝对数「~400 est/轮 ±25%」作废：它把同一条 19 轮会话的自身均值当斜率，且 §2.0
     又把同一个数标成 real。绝对数不能做闸，因为新模式相对 A-min 只减不增。
3. **约束②：prefix-cache 净账**（账单口径见 `req-chat-history-bloat.md` §4 第 4 条）：现有历史 append-only，跨轮前缀
   天然命中；换成每轮子图召回后会被破坏。读 vLLM 的 `cached_tokens` 输出净值即可，
   **分「未截断态 / 截断态」两段记**（见 §4 补充 4）。
    **它只是一个成本读数：为负 → 先查 §4 补充 3 的段序约束是否落实，再优化渲染稳定性
    （排序固定 + 追加式渲染），而不是否定本路线。**
4. **nightly 不低于基线、39 题拒答专项不劣化**——但只有在 §7.6 的多轮评测建好之后才有意义。
5. **可归因**：图版本随 run_id 落盘；上线初期每次蒸馏的 ops 留痕，漂移可逐轮定位。
6. **【评审修订】前置依赖（硬）**：现有评测**每题一个 session**
   （`answer_eval.py` / `retrieval_eval.py` / `sop_eval.py` / `text2sql_eval.py` 四处
   `session_id=f"eval-{question_id}"`，其中 session_id 多只当日志字段），且
   `_query_helper.run_eval_query` 直接调 `run_policy_query`——**不走 SSE、不落 chat.sqlite、
   根本没有会话**。故 nightly / 39 题 / open_ragbench 一律看不到本路线。
   **在补齐多轮评测能力之前，图模式不得上线。**
7. **开关**：`ANGINEER_CONV_GRAPH=0` 默认关。**灰度规则修正**：开关**只对新建会话生效**
   （按 session 首见把策略写进会话侧）。必须避免的反例：正在跑的长会话一旦被切到图模式，
   历史 tool 证据不再进 prompt 而图是空的 → **证据层当场失忆**（语义层不受影响，
   这正是 §0.2 分层带来的附带好处）。回退 = 关开关即回 A-min 行为。
8. **【评审修订】冷启动定义**：要不要对存量会话回填图？建议**不回填**（维持该会话的 A-min 行为
   直到会话结束）——回填需离线重放全部历史，成本与 M0 同量级而收益是一次性的。

## 8. 里程碑

**工程进展（2026-10-04 夜；全部默认关，未发版、未 push）**

| 里程碑 | 状态 | 落地物（可核） |
| --- | --- | --- |
| **M0 干跑预演** | ✅ 完成 | `evals_core.blackboard`（cases/graph/arms/runner）+ 15 例单测；报告 `docs/report-blackboard-m0-dryrun-20261004.md`。**不含判分跑**（待业主冻结题集 + 真实模型窗口） |
| **M1 写路径** | ✅ 完成（只写不读，默认关） | `chat_history.store.graph_store` 四表 + `apply_ops`/水位/补跑/五处级联 + `busy_timeout`；引擎 `conv_graph.distill_run`（可被 SSE/离线壳共用）；aichat-api run_end 后**异步**蒸馏（线程池 1）+ 断连支同接 |
| **M2 读路径** | ✅ 内核 + 接线完成（默认关） | `conv_graph.recall/render/make_conv_graph_transformer`；`chat_agent` 包装每个 attempt 的 config_factory（先图装配、后预算压缩）；开关 `ANGINEER_CONV_GRAPH` |
| **M2 出口闸** | ⏳ 待业主 | §7.1 指涉专项（盲序判分）+ 闸 A/闸 B 读数（干跑已给出 22 例预演值） |
| **M3 灰度 + 多轮评测进 nightly** | ⏳ 未做 | 需业主裁决后再动（见报告「待裁决」四条） |
| **M4 路径交互形态** | ⏳ 未做 | BB §10.4 已注明：前端交互与工程量需单独评估，**不含在 8-12 天内**；本轮未动 UI |

**【评审修订】新增 M0（前置验证），M1-M3 顺延。**

执行状态：**可开工（2026-10-04：闸 1、闸 2 均已过）**；**M0 干跑、M1 写路径、M2 读路径内核与接线
已落地（2026-10-04 夜，全程默认关）**，判分跑与灰度仍待业主。已落地明细见下表「工程进展」。
B 已确认立项——而是**用最低成本校准设计**：在多轮评测尚未建好之前（§7.6），
先用真实长会话把「保真度收益」量出来，避免 M1 建完才发现蒸馏链路不可用。

**执行件：`docs/plan-blackboard-arms.md`（三臂预注册，2026-10-03 新建）——判分跑前锁死题集、口径与判定规则。**

| 步 | 内容 | 出口判据 |
| --- | --- | --- |
| **M0-arm2（≈1 小时，最先做）** | **指针骨架**：把 A-min 压缩后的 `[已压缩: 工具 knowledge_search 的结果，要点: 检索到 N 条候选]` 换成带**确定性 join** 的一行（`[已压缩: knowledge_search 20 条候选；被引用 K3=《JTS 165-2013》/5.4.12、K7=…]`，join 口径 = §3.2）。零 LLM、零新表、零蒸馏——它同时是图写入路径必须写的同一段 join | 产出「证据层值多少分」的**可归因读数**；它是 M0 的臂 2，不是 §11 撤掉的那种「性价比秤/退路」 |
| **M0（0.5-1 天）** | **离线重放（三臂）**：把蒸馏器 + 召回器做成可离线调用的模块（不依赖 SSE、不依赖线上流量），样本 = 那条 19 run / 92 消息真实会话 + 脚本化合成追问会话（补足样本，兼作 §7.6 多轮评测雏形）+ 库里真实 user 提问拼出的追问序列。**臂 1 = 线上现状 A-min；臂 2 = 指针骨架（上一步）；臂 3 = 图**（基线取意图识别改造落地后现状重放——468f7a9+5e6ecb5 后随 v0.2.87 上生产，classifier v4/QA v14/P-1 已生效） | 出口不是「要不要立项」（B 已立项），而是**四个设计决策**：① 蒸馏出的节点/边能否被后续追问正确召回（命中率）；② **臂 3 vs 臂 2** 的追问正确率差值——这才是「图到底值多少」；③ 臂 3/臂 2 vs 臂 1 是否不劣化（丢证据原文有没有伤到专业追问）；④ 蒸馏链路（模型/耗时/失败率/是否抢卡）是否可用。②≈0 → 图的边界收缩到指针覆盖不到的部分（derives/值复用/未决跟踪/导航）；任一不过 → 调整设计后重跑 M0，不停工 |
| M1 | 图 schema（含 `sqlite_store.py:init_db` 建表与 DAO、`busy_timeout`）+ 落库 + run_end 蒸馏通道（不进 prompt，只写图）+ 水位/补跑；**并行**：`fetch_clause` 及其 docs-core 读端点（+1-2 天） | 线上只写不读 1 周，观察蒸馏质量（前提是 M0 已证明蒸馏可用） |
| M2 | 子图召回（字符串/编号匹配 + §4 序数消解）+ prompt 渲染段 + §2.1 注入提示过滤 + 开关 | **多轮指涉专项（§7.1）通过**（预注册题集、盲序判分）+ 本地 15 题连发 prompt 不炸（**闸 A 斜率差分 ≤ A-min ＋ 闸 B 子图段 ≤2,000 est**，§7.2）；prefix 净账**只记录不设闸**（§7.3：为负触发段序/渲染优化，不否决） |
| M3 | 灰度上线 + 图版本归因台账 + 多轮评测进 nightly | §7.6 的多轮评测能力已上线且不劣化 |
| **M4（路径交互形态，终态目标本体）** | 图从「观测面板」升级为**导航界面**：用户沿节点-边路径推进对话/做题——点 clause 节点回引条款原文、点 value 节点沿 derives 链看推导来源并「换参数重算」；图增量随 run_end 帧实时下发（蒸馏仍异步、不进关键路径）。前端交互设计 + 工程量需单独估算，**不含在 §9 的 8-12 天内**。⚠️ **M4 不是纯前端**：路径模式决定「哪些轮进 prompt」，所以 M1 的读路径必须从第一天就产出显式的**上下文选择对象**（图召回已经是这样一个对象；把语义层的取舍也交给它），否则 M4 要重写上下文装配 | 业主真实做题场景可纯路径流走通（不依赖滚动读文字历史）；M0-M3 交付的只是地基，不得以 §7.1 通过宣告终态完成（§0.1 目标完整表述） |

M0 要回答的核心矛盾由本机数据给出：**≥10 轮的会话只占 2.9%（104 会话中 3 个），≥20 轮 0 个**——
在线影子跑一周大概率凑不够样本。离线重放绕开样本不足，且零线上风险。
注意唯一那条 19 轮会话 n=1，召回命中率结论外推性弱，故 M0 样本必须含合成追问会话；
但**合成集只作补充**，主集取自 247 条真实 user 提问与真实会话（合成问题会系统性高估字符串匹配的召回）。

## 9. 风险

- **【评审修订】没有自动化闸门能看见它（最高优先级）**：现有评测无会话、不走 SSE（§7.6），
  nightly / 39 题 / open_ragbench 对图路线**既测不出收益也测不出回归**。补齐前上线 = 无人区飞行。
- **蒸馏漂移**：小模型写错图且静默累积——靠 append-only + 版本落盘 + 水位补跑 + 可重建兜底；
  M0 离线重放 + M1 影子期共同量化（原稿只靠 M1，而在线样本不足）。
- **召回漏子图**：指涉的节点没召回 = 变相失忆——§2.1 的 user 提问全带是第一道保底
  （图漏了模型仍看得见提问史），常驻段是第二道，指涉专项集量化。
- **prefix-cache 反噬**（原稿方向写反）：见 §7.3，这是净损失项而非白赚——为负触发 §4 补充 3 的
  段序优化（排序固定 + 追加式渲染），不否决路线、不作 M2 出口闸（§8 已同步）。
- **clause 节点信息不足**：`clause_id` 仅 11.0% 覆盖（§3.2），节点 key 可能退化为
  「文档名 + section_path」，指涉命中率下降 → M0 专项量化。
- **工程量（2026-10-03 重估）**：原估 **8-12 天**含「§2.1 user 全带 + §2.2 assistant 全带 + 多轮评测能力
  + 前端图可视化/回放」，其中**前两条复核为零工程量**（现状已如此，见 §0.2），
  而 `fetch_clause` 与 docs-core 读端点**已确认要新建**（+1-2 天，§2.3）——**一增一减相抵，
  量级维持 8-12 天**，但别把它当承诺：重启时按下面分项自下而上核一遍。
  分项粗估（M1-M3，不含 M4）：蒸馏通道 1-2 天 ／ 图 schema + 落库 + 水位补跑 1-1.5 天 ／
  子图召回 + 渲染段 + 序数消解 1.5-2 天 ／ `fetch_clause` + docs-core 端点 1-2 天 ／
  多轮评测能力（§7.6 硬前置）2-3 天 ／ 前端调试版 + 简版 tab 1-2 天。
  M0 的最先一步（arm 2 指针骨架）≈**1 小时（变体 ii 候选指针行）或半天～1 天（变体 i 精确引用 join）**——
  变体由 `plan-blackboard-arms.md` §1 跑前圈定。
- **成本面**：每轮多一次蒸馏调用，输入口径见 §3（误按整段原文实现会差 10 倍）；蒸馏与在线推理
  **抢算力**，且 `/api/llm2` 同时是 `EVAL_JUDGE_MODEL` 的端点 → 按 §3.5 三条约束（并发 1、nightly 错峰、
  退避重试）管住；游客放大倍数按服务器 `ANGINEER_GUEST_ROUNDS` **实际值**算（默认 30，本机 .env=5）。
- **【2026-10-03 新增】语义层截断与图指向错位**：一旦 §2.2 的最老截断触发，最老的提问/回答离开 prompt，
  而图节点恰恰指向那些轮——此时图是唯一见证。这是分层的必要兜底，但要在 §7.3 分态记账后单独看，
  别把它错读成「图召回的收益」。
- **【2026-10-03 新增】未决项以前只由本文档承载**：`fetch_clause` / `ANGINEER_CONV_GRAPH` / `conv_graph`
  在仓库其它位置 grep 为 0。现已落 `docs/plan-blackboard-arms.md`（三臂预注册与待确认项清单）；
  动工时建议同步开 issue，避免需求文档成为唯一的待办载体。
- **【2026-10-03 新增】终态范围外溢**：路径交互（§10.4/M4）的交互设计与前端工程量未估算，
  8-12 天只覆盖到 M3 地基；M4 立项时需单独排期，且「图可视化」从 M2 调试版到 M4 导航界面
  不是平滑延续，可能重做交互范式。

## 10. 前端展示（2026-10-01 与业主讨论定版：同一入口，tab 切换简版/调试版）

不拆两端（用户侧/管理侧），同一会话的记忆展示入口内置两个 tab：

### 10.1 简版 tab（默认）

```
┌─ 会话记忆 ────── [简版|调试版] ──┐
│ 本轮召回：                       │
│  ⚓ JTS 165-2013 §5.4.12        │
│  📐 T=12.8m（第4轮算出）        │
│  🏷 5万吨级散货船码头设计        │
│ 未决事项：备淤深度 Z4 待确认      │
└──────────────────────────────────┘
```

- 展示**本轮召回的子图**（节点按类型渲染 chip：条款⚓/数值📐/实体🏷/未决❓）+ 常驻段
  （未决事项；意图轨迹由提问原文承担，不在此处），不进正文回答。
- 数据来源：本轮召回清单随 run_end 事件帧下发（transport 管道同工具事件，免二次请求）；
  常驻段与图本体走独立只读 API（按 **`owner_key` + `session_id`** 查 `conv_graph_*` 表——
  阶段三（D6）后会话身份就是这两列，`scope_hash` 不再是键；库集合过滤用行的 `library_ids_json` 列）。
- **【评审修订】契约约束**：`X-Chat-Frame-Version: 1` 是冻结契约（`main.py` 的 SSE 响应头 +
  `frame["frame_version"] = 1` 字段），新增字段必须 **additive**。
  ✅ **兼容策略已核实并关闭（2026-10-03）**：全仓**没有** `frame_version` 的消费方
  （`apps/shared/chatTransport.ts` 只读 `msg_seqs` 与 `payload.*`，未知字段直接忽略），
  所以新增召回字段是安全的；仍建议同时给字段加版本前缀以便将来识别。
- 价值：「模型看到了什么」可见即可信；召回漏了当场可发现（「它忘了第 4 题」）——
  把 §9 召回漏子图风险变成可观测。

### 10.2 调试版 tab

```
┌─ 会话记忆 ────── [简版|调试版] ──┐
│  (图可视化：节点-边，按类型着色)  │
│   5万吨散货船 ──derives──► T=12.8│
│       │cites                     │
│       ▼                          │
│   JTS 165-2013 §5.4.12           │
├──────────────────────────────────┤
│ 轮次滑块: ●━━━○━━○ 第4/9轮       │  ← 按 conv_graph_version 回放
│ 本轮增量: +2 节点 +3 边 (展开ops)│
└──────────────────────────────────┘
```

- 图可视化 + **按轮回放**（conv_graph_version 台账的直接用途）+ 每轮增量 ops 查看。
- 这是 §9「蒸馏漂移可逐轮归因」的落点——没有它，图污染只能靠 SQL 排查。

### 10.3 节奏与红线

| 里程碑 | 前端动作 |
| --- | --- |
| M0-M1 影子期 | 只做调试版 tab 的最小形态（图 JSON 原文 + ops 列表，不画边） |
| M2 | 简版 tab + 调试版图可视化 |
| M3 | 调试版轮次回放 |

**红线：影子期图不进 prompt，简版 tab 必须不上线**（调试版仅内部可见）——
否则用户看到「记忆召回」但回答没用它，认知错位。

### 10.4 【2026-10-03 业主口径新增】终态：从观测到导航（路径模式）

简版/调试版 tab 是过渡形态（「可观测即可信」）。终态是**路径模式**：图成为对话本体，
用户沿节点-边推进，而非滚动阅读线性文字历史：

```
点 clause 节点（⚓ JTS 165-2013 §5.4.12）→ 按指针回引条款原文，直接发起追问
点 value 节点（📐 T=12.8m）             → 沿 derives 链回看推导来源 →「换个船型重算」
点 issue 节点（❓ Z4 待确认）            → 接续未决事项，resolved 后从常驻段消失
```

- **实时性口径**：「实时图结构」= 图随对话边说边长、用户即时可见——由 run_end 帧增量下发
  （§10.1 的 transport 管道复用）+ 常驻段只读 API 即可满足；蒸馏保持 run_end 后异步、
  不进关键路径（§3），不改为推理过程中实时读写图。
- **工程量警示**：路径导航的交互设计与前端实现**未含在 §9 的 8-12 天估算内**，归 M4 单独评估（§8）。
- **【2026-10-03 补】这不是纯前端**：路径模式决定「哪些轮进 prompt」——点开哪条路径，
  语义层就该带哪些轮（而不是无条件全带）。所以 M1 的读路径必须从第一天产出显式的
  **上下文选择对象**（图召回清单已经是这样一个对象；把「带哪些 user/assistant 轮」也交给它），
  前端只负责呈现同一个对象。否则 M4 会退化成重写上下文装配（§8 M4 行已同步）。
- **与验收的关系**：§7.1 指涉正确率验收的是地基（记忆结构可用）；路径模式的验收是
  「真实做题场景能否纯路径流走通」，由业主本人在 M4 判定。

## 11. A-full 的定位（2026-10-02 撤销两种身份；2026-10-03 恢复为「构件」）

A-full（历史 tool 消息常驻降级：被引用 items → 自描述摘要行；未引用 → 文档名/条款号指针行，
纯 `transform_context` 投影，约 1 天）在本稿早期版本中曾有两重身份，二次复核后**均不成立**：

- ~~M0 对照组~~：「图 vs A-full 差值是否配得上工程量」是否决式问法，与 §0.1.0 撤回的性价比秤
  同源，不得再用。M0 对照臂改用**线上现状 A-min**——与 §7.1 验收基线同口径，零额外工程量。
- ~~蒸馏失败的退路~~：§8 已定「M0 不过 → 调整设计后重跑，不停工」，退路论与之直接冲突。

**【2026-10-03 五评修订】上面两条撤销仍然成立，但撤销过头了——A-full 里有一半是「构件」，必须留下**：

- **留下的是「指针半边」**：被引用 item 的 `doc_title + (clause_id|section_path)` 指针行，
  由 §3.2 那套**确定性 join** 生成，零 LLM。它不是「秤」，也不是「退路」，而是
  **图写入路径本来就要写的同一段 join**（图的 clause 节点 key 只能从它来）。
- **落地位置提前到 M0 的臂 2**（§8）：把 A-min 的 `检索到 N 条候选` 换成带指针的一行，
  ≈1 小时，零新表零蒸馏。它让 M0 从「图 vs 现状」变成三臂可归因。
- **仍不做的**：把 A-full 当对照组去判「值不值得做」，或当退路去顶替图——这两条照旧禁止。
- 归因能力保留：若臂 3 有增益，臂 2 的存在正好区分「增益来自证据结构化」还是「来自蒸馏模型」。

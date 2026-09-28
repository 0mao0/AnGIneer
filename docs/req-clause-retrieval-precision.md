# 需求：条款号检索精度（跨规范同号撞车 + 公式号误当条款号）

> 状态：**P0/P1 全部落地并端到端验收通过（2026-09-28）——q_028 拒答→答对（judge 1.0），可答题 22→24、零转错；
> 纯检索侧噪声 20→0、金标答案进第 4 位**。遗留：eval_1 数据集作用域失效（全 30 题 doc_ids 指向已不存在的
> 文档，见 §4 缺陷 1，需修）+ 拒答行为线 3 题 + 表格线 3 题。发现于 2026-09-27 知识库基线评测集 1（30 题，
> run `run-5c37706a1f71`，22/30）的错题归因，见 §1 证据表。
> 与 `docs/req-table-retrieval-latency.md`（表格检索**提速**）是**同目录不同线**：那条治「慢」，
> 本条治「**张冠李戴**」，协作边界见 §5。执行者需先读仓库 AGENTS.md。

## 1. 背景与实锤证据

2026-09-27 本地跑「知识库基线评测集 1」（`eval_1`，30 题，全部挂 `default` 规范库）得 22/30。
逐题归因（**界面序号 + question_id 双标注**，两套编号不同，勿混）：

| 界面# | question_id | 题干（截） | 归类 | 证据 |
|---|---|---|---|---|
| 3 | q_003 | 锚地按功能可分哪些类型 | **语料缺口**（已改拒答金标） | 全库 0 块含「引航锚地」 |
| 19 | q_024 | 待泊锚地宜设置在什么水域 | 措辞不精确被严判 | 答「靠近港口」，金标「靠近码头」 |
| 20 | q_025 | 港口给水排水在哪一章规定 | **语料缺口**（已改拒答金标） | 全库 0 篇含该规范名；系统答「未收录」本身是对的 |
| 23 | q_027 | 锚地按功能可分哪几种类型 | **语料缺口**（已改拒答金标） | 同 q_003（同题变体） |
| **24** | **q_028** | **公式 6.2.8 中时间富裕系数 Kt** | **条款号跨规范撞车 + 公式号误当条款号** | 见 §2，本条需求主用例 |
| 27 | q_031 | 5 万吨散货船双线航道宽度计算 | 表格选错（拿了应力系数表） | 引用的是「应力系数表 E.0.3」等结构表，非航道宽度参数表 |
| 29 | q_033 | 普通/全潮航道通航水位取值区别 | 生成结论反向（材料对） | 引用 JTS 145 + JTS 181 均正确，结论与金标相反 |
| 30 | q_034 | 8000 吨杂货船波浪富裕深度系数 | **读表取值错**（表找对了） | 引用含「表 5.5.5-2 船浪夹角 ψ 与 Z₂/H₄%」，系数读错 |

**结论**：8 题里 3 题是语料缺口（2026-09-27 已将金标改为拒答口径：`refusal_expected=True` + 拒答话术 +
清空要素断言 + `refusal` 标签，bundle 与运行库同步）；**真失分 5 题中有 3 题（q_028/q_031/q_034）
集中在「条款/表格的检索与取值」**——本条需求治其中的**条款侧**（q_028），表格侧（q_031/q_034）
另线归口。

## 2. 根因（q_028，代码级 + 数据级三层叠加）

**现状实现**：`ClauseResolver.retrieve`（`services/docs-core/src/docs_core/step09_query/retrieval/clause_resolver.py`）
抽到条款号后**对全库每篇文档**查同号条款，命中统一给 `_CLAUSE_DIRECT_BASE_SCORE = 12.0`
（精确一致再 +2），**零主题判别**——跨文档同号时谁赢取决于遍历顺序。

| 层 | 事实（可复现，SQL 见 §6） |
|---|---|
| ① 编号体系搞混 | 题面是「**公式**6.2.8」，但上下文模式 `(?:表\|图\|式\|公式)\s*(编号)` 把**公式编号**当条款号采信——公式号与条款号是两套体系 |
| ② 跨规范撞车且无判别 | 库里 `clause_id='6.2.8'` 有 **5 篇**文档：低槛活动坝 / 干船坞灌水阀门 / 接岸结构检测——**无一**与时间富裕系数有关 |
| ③ 真实内容在别的编号下 | 「时间富裕系数」实际在 `doc-5d1cbf73` 的 **5.4 节**（section「5 沿海及潮汐河口航道 / 5.4 设计通航水位及乘潮水位」，09-27 复核：命中 chunk 的 clause_id 是 5.4.1/5.4.2）；**且不止一处**——`doc-30d8fc05` / `doc-c29d731e` 的 **6.2.1**（进港航道、锚地）也含该词——题目引用的编号与库内该内容的编号不同源（不同规范/版本体系） |
| ④ 证据不带出处 | 条款直达 item 的 `title` 取 `section_path` 或 node.title，**不含规范名**——生成器无法察觉这条 6.2.8 出自《船闸设计规范》而非水文规范 |

## 3. 修复项（按性价比排序）

| 优先级 | 改动 | 位置 | 验收点 |
|---|---|---|---|
| **P0-1** | **公式号踢出条款抽取**（两处抽取器**性质不同，改法不同**，09-27 实施前复核）：<br>① `clause_resolver.extract_clause_refs_strict` 有上下文模式表——把 `式\|公式` 从 `_CLAUSE_CONTEXT_PATTERNS` 移除即可；<br>② `query_normalizer.extract_clause_refs` **没有模式表**，是纯数字形态抽取（`\d+(\.\d+){1,4}` 等，任何「6.2.8」都进 clause_refs），改法须改成**剔除紧跟「公式/式」后的数字或加上下文门控**——不能照抄「删模式项」。该函数被 dense（`dense_retriever.py:135`）、formula（`formula_retriever.py:243/:368`）、table（`table_retriever.py:41`）三路各自直调并用 `contains_clause_ref` 加分，公式号污染在三路独立存在（`extract_query_signals` 的 `locate_formula` 类型路由本身是对的，问题只在 clause_refs 污染）。公式标识符承接函数 `extract_formula_identifiers` 定义在 `query_normalizer.py:157`（formula_retriever 仅 import） | `clause_resolver.py` / `query_normalizer.py` | 「公式6.2.8」不再产出条款号 6.2.8；「表6.4.2」「第6.2.8条」等仍正常抽取（勿误伤）；三路 `contains_clause_ref` 加分路径对公式号不再触发 |
| **P0-2** | **主题校验加权**：条款精确命中后，用查询剩余实词（去掉编号后，如「时间富裕系数」「Kt」）与块文本算重合度参与排序——没这层，跨规范撞车永远随缘 | `clause_resolver.py` 打分处 | q_028 的 5 个 6.2.8 候选中，含主题词者排首位（或用主题筛选后为空 → 走 P1-2 回退） |
| **P1-1** | **文档名门控**：问题里出现《规范名》或 `JTS/GB xxx` 编号时，对该文档的条款命中加权（或限域） | `clause_resolver.py`（可选加一个查询侧的规范名抽取） | 构造用例：「《海港总体设计规范》6.4.2 条…」只应返回该规范的条款 |
| **P1-2** | **空命中/主题全不符 → 回退语义路**：撞车命中若主题校验全不通过，判为无效证据并让主题词走 dense/sparse，**不得把同号噪声条款当证据上呈**（现状即噪声逼模型拒答） | `clause_resolver.py` + 调用方策略 | q_028 在修完 P0 后若条款路无有效命中，应回退语义并答出 Kt 取 1.1~1.3 |
| **P1-3** | **证据必须带文档名**：条款直达 item 的 title/metadata 写入**规范名**（文档标题），使生成器与用户都能分辨「这条 6.2.8 出自哪本规范」 | `clause_resolver.py` 构造 `RetrievedItem` 处 | 前端证据卡片与 prompt 证据块中可见规范名 |

**P0-1 实施回填（2026-09-27）**：`query_normalizer.mask_formula_number_spans` 屏蔽「式/公式X」编号段，
`extract_clause_refs` 与 `extract_clause_refs_strict` 两处抽取器共用（strict 侧同时从模式表移除 `式|公式`，
并靠屏蔽堵住裸号三段点分路 `_CLAUSE_BARE_DOTTED_PATTERN` 漏回）；顺带修 `formula_refs` 兜底正则收全点分号
（原只捕获 "6"）。单测 `tests/unit/test_unit_retrieval_text.py::TestFormulaNumberNotClauseRef`（8 例，
RED→GREEN）。q_028 题干提取级验证：strict/三路 clause_refs=[]、question_type=locate_formula、
formula_refs=['6.2.8']。**未做**：端到端单题重跑与 30 题回归（待 P0-2 后一并跑，口径纪律 §4）。

**P0-2 实施回填（2026-09-27）**：`query_normalizer.extract_topic_terms`（抹掉编号数字后的 n-gram 主题信号，
过滤通用词表与纯数字）+ `clause_resolver._topic_overlap`（块文本加权重合度 ∈[0,1]，仅取 4–8 字 n-gram 与
ASCII 标识符；跨虚词长串如"条规定的X"不是词、必须排除，曾按极大词去重致真实库探针 topic 全 0——教训记此）。
打分 `12 + 精确2 + 6×重合度`（主题权重 > 精确加成：父级命中的主题相关条款要能压过无关文档的精确同号条款）；
`retrieve` 改为按分数降序返回，metadata 记 `topic_overlap`（供 P1-2 主题筛选复用）。
单测 `TestClauseTopicWeighting`（3 例：撞车首位/元数据/主题词无编号）。真实库探针（题面点名低槛活动坝 + 5 篇
真实 6.2.8 文档）：主题相关条款 17.37 分排首（topic 0.561），灌水阀门/接岸结构 14.00 沉底（topic 0.000）。
回归 tests/unit+docs-core+classifier fastpath：799 passed / 7 failed（7 为 parse-resume 线既有问题，
stash 基线已验证与本改动无关）。

**P1 三项实施回填（2026-09-28）**：均在 `clause_resolver.py`。
- **P1-1 文档名门控** `_restrict_nodes_by_spec_hint`：题面出现《规范名》（标题子串匹配）或
  JTS/JTG/GB… 编号（去空格连字符的紧凑串包含匹配）时，条款直达限域到该文档；
  **点名规范对不上任何候选文档时回退不限域**（不清空正常召回）。
  实际库节点标题两形态均可命中（`JTS 190-2018 船厂水工工程设计规范.pdf`、`《上海港口…技术导则》（印发）.pdf`）。
- **P1-2 噪声守卫**：题干有具体主题信号（核心主题词非空）而全部命中 topic_overlap=0 → 判无效证据返回 `[]`，
  主题词让 dense/sparse 接管；裸条款号引用（无核心主题词）不触发，防误杀正常直达。
  **部分相符时只靠 P0-2 排序压后噪声、不删除**（现行口径，防改述题召回损失）。
- **P1-3 证据带规范名**：`title = {node.title}｜{section_path}`、metadata 记 `doc_title`
  （生产链路 node.title=库树节点标题即文档名，探针中显示 doc-id 为探针占位）。
单测 4 类共 12 例（门控 4 / 噪声守卫 3 / 规范名 1 / 前述 4 调整夹具）RED→GREEN；
回归 tests/unit+docs-core：802 passed / 7 failed（parse-resume 线既有，stash 基线已验证无关）。
真实库终探针：撞车+主题全不符 → 条款路返回 `[]`（语义接管）；主题相符 → 17.37 保留且 title 带规范名。

## 4. 验收与回归

**端到端验收结论（2026-09-28，run-4bbafe1e02e0，被测 `Qwen3.6-35B-A3B` / judge `Qwen3.8-Flash-Next`）**：

| 口径 | 基线 run-5c37706a1f71 | 新跑 run-4bbafe1e02e0 |
|---|---|---|
| 可答题（27 题，排除 3 道拒答金标） | 22 | **24**（+2） |
| 全量 | 22/30 | 24/30 |
| **q_028** | 拒答（`model_refusal_kept`，错） | **答「Kt 取 1.1~1.3」并引 JTS 165-2013 / JTS 181-2016（judge semantic 1.0）** |
| 转错 | — | 0 题 |
| 判分健全性 | judge_failed 0 | 初跑 judge 端点瞬时故障 8 题（确定性 contains_all 已兜住、与错题不相交），**补判后 judge_failed_count=0 / anomaly=0** |

**归因纪律**：+2 里的 **q_028 是本改动的因果收益**（改前拒答理由即「检索到的 6.2.8 条款未提及时间富裕系数 Kt」，
改后条款噪声清零、语义路给出金标内容）；**q_024 翻绿属判分/措辞波动**（judge 认定「靠近港口」≈「靠近码头」，
与条款路无关，不计入本改动功绩）。持续错的 3 题是拒答金标（系统答而非拒答，归拒答行为线）+ 表格线 3 题
（q_031 表选错 / q_033 结论反向 / q_034 读表错）。

**验收途中发现的三处基础设施缺陷（与代码改动无关，均需单独立项）**：
1. **eval_1 全 30 题 `doc_ids=["doc-fbabad08"]` 指向库中已不存在的文档**（现库 400 篇无此 id，bundle 与运行库一致，
   非本次改动写坏）→ 作用域过滤使检索恒返 0 条、秒回空、模型被迫拒答。本次验收以 `doc_ids=[]` 覆盖为全库口径
   完成；**数据集作用域需修**（重映射到现存文档或清空），否则任何重跑都拿不到证据。
2. **运行库 eval_question 有 3 行 tags JSON 非法**（q_003/q_025/q_027：`[...],refusal` —— 当初「改拒答」写库时
   字符串拼接而非解析追加）→ `list_questions` 逐题解析即抛 400，**整个 eval_1 起不了跑**。已修复（旧值备份
   `.scratch/eval1_tags_backup.json`）。
3. **本地 aichat-api 跑的仍是 09-27 23:36 的旧代码**（`ANGINEER_NO_RELOAD=1` 无热载，改动 mtime 09-28 07:51），
   首跑拒答是旧代码所致；重启后复跑即正确。**结论：改动后必须重启内嵌 docs-core 的服务进程再评测**。

**面上收益验收（2026-09-28，13 题同号检索探针集 `docs-retrieval-precision-v2`，零 LLM，`git worktree`@HEAD 为改动前臂）**：

原金标 doc（doc-24aa8f8a / doc-5c9031df / doc-8474a7fe）在现库已不存在（旧一代库遗留），先按「现存库中真装该内容的文档」重映射
（映射表落盘为 `data/evals/datasets/docs-retrieval-precision-v2.gold-map-20260928.json`；harbor-2 因旧编号 6.3.7 在当前解析已变 5.5.7，取内容载体并集）：

| 指标 | 改动前 | 改动后 | 复现性 |
|---|---|---|---|
| 跨文档同号噪声（非金标文档含该条款号的证据条数） | **35** | **20**（−43%） | 两臂各跑两次：旧 35/35、新 20/20，**波动 0** |
| 精确命中（条款号 + 金标文档同块）进 top-20 | 11/13 | 11/13 | 无回归 |
| 金标文档进 top-20 | 12/13 | 12/13 | 无回归 |
| harbor-2 三道金标文档位次 | 第 2 | **第 1** | 提前 |

**可见代价**：harbor-2 两道「精确命中位次」后退（第 2→第 4、第 2→第 6）——同号无关块被压下去的同时，含该号的金标块也随降权略后移
（未出 top-20）；其余 9 题逐项一致，concrete（GB 50010 附录 C）与 harbor-1 完全无变化。**收益=同号噪声少上屏，代价=金标块位次小幅后移，召回总量无损。**

**纯检索验收结论（2026-09-28，零 LLM / 零服务启动，直调 `retrieve_knowledge` 全库检索）**：
工具 `.scratch/ab_q028_probe.py`（改动 stash 前后各跑一次，同一题面同一库）：

| 指标 | 改前（stash 基线） | 改后（现行） |
|---|---|---|
| 证据集内撞车 6.2.8 噪声条数（clause_direct） | **20（占满 top20）** | **0** |
| 含「时间富裕系数」条数 | 0 | 4 |
| 含金标答案「1.1~1.3」条目的排名 | 不在结果内 | **第 4 位** |

改前噪声直接把 top20 全部吃掉、金标内容一条不进——比 §2 原归因（噪声「混入」证据）更严重，原归因可据此上修为
「噪声挤占全部证据位」。回归探针（同批）：真条款号+主题相符 → 条款路 17.37 排首；裸「第6.2.8条」仍产出
（守卫不误杀）；《上海港口基础设施检测评估技术导则》+第6.2.8条 → clause_direct 仅该文档 2 条（P1-1 真实库生效）；
表格 mode 20 条零报错。证据截断口径：`ANGINEER_CONTEXT_TOP_N` 默认 15（仅 rerank 开启时截断），金标第 4 位
两种配置下均进上下文。**端到端（生成+判分）未跑**——待 PoPo 验证让出 DGX 后补 q_028 单题与 eval_1 30 题 A/B。

- **单题用例（q_028）**：修完 P0 系列后重跑该题——① 不得把「低槛活动坝/干船坞/接岸结构」的 6.2.8
  当证据；② 期望经条款主题校验或语义回退答出「时间富裕系数 Kt 取 1.1~1.3」。
  真实内容分布在两套规范（`doc-5d1cbf73` §5.4.x 与 `doc-30d8fc05`/`doc-c29d731e` §6.2.1，09-27 SQL
  复核），**均为合法来源，证据判读勿只钉 doc-5d1cbf73 一处**。
- **30 题集回归**：`eval_1` 重跑，可答题基线 **22/27**（语料缺口 3 题已改拒答金标）不得回归，
  预期 q_028 转对（可答题 ≥23/27）。
- **不误伤**：现有「第X条/表X/图X/附录X」抽取与 `clause_direct` 召回路径的行为需有单测覆盖
  （新增：公式号不抽、表/图/条号仍抽；跨规范同号时主题优先）。
- **口径纪律**：改动判分/召回口径的，按仓库惯例跑 30 题 A/B 并记录；结果无论好坏回填本文件。

## 5. 协作边界（重要）

- **同目录并行线**：`docs/req-table-retrieval-latency.md`（表格检索提速）正在改
  `step09_query/retrieval/table_retriever.py` 等。本条改动集中在 `clause_resolver.py` 与
  `query_normalizer.py`，**请勿同时改同一文件**；两线若需共改 `retrieve_service.py` 的融合调用点，
  先协调顺序（建议：先落地本条 P0-1/P0-2，再合提速改动）。
- **表格侧问题（q_031 表选错 / q_034 取值错）不在本条范围**：归口表格检索线，但可用同一 30 题集
  做联合回归。

## 6. 复现证据（只读 SQL，本机知识库）

```sql
-- ② 跨规范撞车：5 篇文档各有一条 6.2.8（全部与主题无关）
select doc_id, section_path, substr(text_clean,1,70) from canonical_chunks where clause_id='6.2.8';
-- ③ 真实内容位置：时间富裕系数在 5.4.2.1，不在 6.2.8
select doc_id, clause_id, section_path from canonical_chunks where text_clean like '%时间富裕系数%';
-- ① 抽取规则位置
--   services/docs-core/src/docs_core/step09_query/retrieval/clause_resolver.py 的 _CLAUSE_CONTEXT_PATTERNS
--   services/docs-core/src/docs_core/step09_query/retrieval/query_normalizer.py 的 extract_clause_refs
```

## 7. 关键路径速查

| 件 | 路径 |
|---|---|
| 条款解析与召回 | `services/docs-core/src/docs_core/step09_query/retrieval/clause_resolver.py` |
| 条款抽取（共用） | `services/docs-core/src/docs_core/step09_query/retrieval/query_normalizer.py` |
| 公式召回（承接公式号） | `.../retrieval/formula_retriever.py` |
| 30 题集与运行记录 | `data/evals/datasets/eval_1.json`、本机 `data/evals/evals.sqlite`（run `run-5c37706a1f71`） |
| 同类需求范例 | `docs/req-table-retrieval-latency.md` |

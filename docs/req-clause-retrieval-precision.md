# 需求：条款号检索精度（跨规范同号撞车 + 公式号误当条款号）

> 状态：**观测完成（有实锤用例）——待实施**。发现于 2026-09-27 知识库基线评测集 1（30 题，
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
| ③ 真实内容在别的编号下 | 「时间富裕系数」实际在 `doc-5d1cbf73` 的 **5.4.2.1**（section「5 沿海及潮汐河口航道 / 5.4 设计通航水位及乘潮水位」）——题目引用的编号与库内该内容的编号不同源（不同规范/版本体系） |
| ④ 证据不带出处 | 条款直达 item 的 `title` 取 `section_path` 或 node.title，**不含规范名**——生成器无法察觉这条 6.2.8 出自《船闸设计规范》而非水文规范 |

## 3. 修复项（按性价比排序）

| 优先级 | 改动 | 位置 | 验收点 |
|---|---|---|---|
| **P0-1** | **公式号踢出条款抽取**：把 `式|公式` 从条款上下文模式移除，公式标识符交给 `formula_retriever`（已有 `extract_formula_identifiers`）。**注意两处抽取器都要审**：`clause_resolver.extract_clause_refs_strict` 的模式表 + `query_normalizer.extract_clause_refs`（dense/formula/table 三路共用） | `clause_resolver.py` / `query_normalizer.py` | 「公式6.2.8」不再产出条款号 6.2.8；「表6.4.2」「第6.2.8条」等仍正常抽取（勿误伤） |
| **P0-2** | **主题校验加权**：条款精确命中后，用查询剩余实词（去掉编号后，如「时间富裕系数」「Kt」）与块文本算重合度参与排序——没这层，跨规范撞车永远随缘 | `clause_resolver.py` 打分处 | q_028 的 5 个 6.2.8 候选中，含主题词者排首位（或用主题筛选后为空 → 走 P1-2 回退） |
| **P1-1** | **文档名门控**：问题里出现《规范名》或 `JTS/GB xxx` 编号时，对该文档的条款命中加权（或限域） | `clause_resolver.py`（可选加一个查询侧的规范名抽取） | 构造用例：「《海港总体设计规范》6.4.2 条…」只应返回该规范的条款 |
| **P1-2** | **空命中/主题全不符 → 回退语义路**：撞车命中若主题校验全不通过，判为无效证据并让主题词走 dense/sparse，**不得把同号噪声条款当证据上呈**（现状即噪声逼模型拒答） | `clause_resolver.py` + 调用方策略 | q_028 在修完 P0 后若条款路无有效命中，应回退语义并答出 Kt 取 1.1~1.3 |
| **P1-3** | **证据必须带文档名**：条款直达 item 的 title/metadata 写入**规范名**（文档标题），使生成器与用户都能分辨「这条 6.2.8 出自哪本规范」 | `clause_resolver.py` 构造 `RetrievedItem` 处 | 前端证据卡片与 prompt 证据块中可见规范名 |

## 4. 验收与回归

- **单题用例（q_028）**：修完 P0 系列后重跑该题——① 不得把「低槛活动坝/干船坞/接岸结构」的 6.2.8
  当证据；② 期望经条款主题校验或语义回退答出「时间富裕系数 Kt 取 1.1~1.3」。
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

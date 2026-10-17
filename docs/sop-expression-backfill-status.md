# SOP expression 补全：根因、已修、存量清单（2026-10-15 起，2026-10-17 全部清零）

## 一句话

57 条已发布 SOP 里 39 条的 calculator 步从生成那天起就缺公式（`inputs` 被写成了「参数名→参数说明」字典），
运行时 1ms 报「表达式不能为空」；根因是生成提示词的输出 schema 从未要求 `expression`。
2026-10-15：修生成提示词 + 加校验闸门（规则 6）+ 补全实踩的半圆堤 SOP。
**2026-10-17：A 类 16 条补公式完毕；B 类 22 条重构完毕（并行会话 18 条 + 本会话 4 条，其中 4 条复核出真实封闭式）；
全库 55 条残废扫描 0 坏、22 条野跑 QA 全过；另修 ConditionalTool 分支子工具假成功缺陷（引擎层）。**
生产同步状态见文末「生产现状」。

## 根因链（实据）

```
SOP_GENERATION_SYSTEM_PROMPT 旧 schema: "inputs": {"变量名": "变量说明"}
        │  从未要求 expression
        ▼
自动生成的 calculator 步 inputs = 参数说明字典（如 {"设计波高H": "设计波高，单位m"}）
        │  解析器不认汉字说明、原样当成"已就绪的值"→ 判定"参数全齐"→ 直接调 calculator
        ▼
calculator 收到无 expression 键的字典 → {"error": "表达式不能为空", "expression": null}（1ms）
```

- 对照：手工/对齐过的 SOP（设计底高程、通航宽度等）calculator 步为
  `{"expression": "${T} + ${Z0} + ..."}`，能正常出数——工具本身没问题，数据也在（题面值都进了黑板）。
- 规模：`data/platform/sops/json/` 57 条里 39 条同病（117 个 calculator 步缺 expression）。
- 实踩记录：chat run `ea4f09a6a7cd`（2026-10-15 16:06），SOP `96682af0ed26` 4/4 步 failed，
  `missing_report` 为空（说明缺失被描述串掩盖，连缺参闸都没触发）。

## 已修

| 改动 | 文件 | 内容 |
|---|---|---|
| 生成提示词修根 | `services/sop-core/src/sop_core/sop_path_generator.py` | calculator 步必须给 `expression`（`${变量名}` 占位、不许写死数值）；写不出公式的步骤改用 table_lookup/manual；`outputs` 一律写 `{"结果变量名": "result"}` |
| 校验闸门（规则 6） | `services/sop-core/src/sop_core/sop_validator.py` | calculator 步缺 `expression`（且无 `expressions`）→ 校验不通过；生成落盘（`_write_sops_to_disk`）与 API 保存/发布（422）均拦 |
| 补全实踩 SOP | `data/platform/sops/json/96682af0ed26.json` | 半圆型防波堤波浪力计算：9 步公式全部按 JTS 154-2018 附录J（式 J.0.1-1 ~ J.0.1-12），原定义备份在 `json/.bak-20261015-sopexpr/` |
| 测试 | `tests/unit/test_unit_sop_expression_backfill.py`（新）+ `test_unit_sop_validator.py`（规则 6 正反例） | 全参数直跑 9 步出数并与规范公式独立复算比对；题面只给 H/d/L 时 η/αs/ps 出数、5 个几何参数如实报缺、No「表达式不能为空」 |

### 半圆堤补全的公式与接线（样例，供其余 SOP 参照）

黑板键 → 表达式（值由运行时代入；失败即按缺参口径报缺，不臆造）：

1. η = 1.5·H（式J.0.1-1）
2. αs = 0.6 + 0.5·[(4πd/L)/sinh(4πd/L)]²（式J.0.1-4）
3. ps = αs·γ·H，γ 取海水重度 10.25 kN/m³（式J.0.1-2）
4. αb = 1 − (d1/d)[1 − 1/cosh(2πd/L)]（式J.0.1-5）
5. pb = αb·ps（式J.0.1-3）
6. λp = cos⁴(2πΔl/L)，按度写 `cos(360·Δl/L)**4`（式J.0.1-9）
7. pb′ = λp·pb（式J.0.1-7/-8；ps′=ps）
8. p(θ) = [pb′ + (ps−pb′)·z/d1]·cosθ（式J.0.1-10，z 为 0~d1 线性内插）
9. Pu = pb′·B/2（式J.0.1-11/-12）

规范未给封闭式的「总分力」（J.0.1.2 只说明「由各点压力分解积分求得」），
故不放进 calculator 步，写进 SOP/步骤描述由图形法或数值积分完成——**不臆造公式是红线**。

## 存量其余 38 条：分流清单

判定口径（启发式，逐条施工前须再核）：段公式 = 源段正文（JTS 154-2018 全文，本地
`data/knowledge/libraries/std-water/documents/doc-fbb3306e/parsed/content.md`）内的公式条数；
内公式 = 步骤描述里已自带显式公式的步数。

### A 类：公式在原文/描述里可依（16 条，优先补）—— **2026-10-17 已全部补全**

16 条全部补完 expression 并按需分流工具类型，逐条过 `scripts/sop_check.py`（validator 全规则含规则 6）
+ 全参数直跑出数（手算抽核）+ 缺参直跑如实报缺；原件备份在 `data/platform/sops/json/.bak-20261017-sopexpr/`。
施工中修正的共性问题：部分步骤误用未注册工具 `manual`（改 calculator 守卫/user_input/conditional）；
`doc-e2eeabd7` 为死溯源链接，16 条 `doc_id` 统一改为实际规范文档 `doc-fbb3306e`；
个别原描述误引规范/式号或写错不等式右端的，已按 JTS 154-2018 原文更正（见各步骤 description）。

| SOP | 缺步 | 源段 | 备注 |
|---|---|---|---|
| 斜坡堤护面层厚度计算流程 5ad5f191ef20 | 2 | 4.3.12.2 | 段内公式 8 |
| 重力式直立堤堤顶高程确定流程 5eb80f952936 | 1 | 5.2.2 | 段内公式 8 |
| 胸墙抗倾稳定性验算流程 5e68efbd84aa | 5 | 4.3.6.2 | 描述内公式 4 |
| 重力式直立堤抗倾稳定验算流程 188a39bdc9b3 | 2 | 5.3 | |
| 重力式直立堤承载能力极限状态验算流程 47c03850b676 | 7 | 5.3.1 | |
| 重力式直立堤抗滑稳定验算流程 efd10ff391f0 | 2 | 5.3 | |
| 坐床式圆筒直立堤稳定性计算流程 c74a8e948a3e | 4 | 5.7.3-5.7.5 | |
| 箱筒型基础结构防波堤稳定性估算 2b61dcff5d38 | 4 | 附录K | |
| 护面块体稳定重量计算流程 4daf8ab7c5ef | 2 | 4.3.7 | 已修 2026-10-17：式4.3.7-1/-2 入 step_8；manual×2 改 user_input；波向角/斜坡倾角补 calculator |
| 斜坡式防波堤承载能力极限状态设计流程 25ae5b6a36df | 8 | 4.3.1/4.3.3/4.3.5 | 已修 2026-10-17：护面（4.3.7)/底流速（4.3.22)/抗滑（4.3.6-1)/抗倾（4.3.6-2) 5 步 calculator；设计状况/γ0 改 conditional；水位/波高改 user_input；表4.3.24 改 table_lookup；胸墙强度/整体稳定改 knowledge_search |
| 开孔沉箱波浪力计算 61ef9eb27ba9 | 4 | 附录H | 已修 2026-10-17：重构为波峰（H.0.2-1~-12)/波谷（H.0.3-1~-10) 20 步 calculator；P0/Pv0/l0/lv0(JTS 145) 列 required |
| 斜坡式防波堤正常使用极限状态设计流程 dae53763ea51 | 4 | 4.3.1/4.3.3/4.3.4 | 已修 2026-10-17：源段无封闭式——沉降/裂缝按 4.3.26/JTS147 由用户提供后以式3.2.2-2 裕度 C−Sd≥0 验算；设计状况改 conditional |
| 胸墙抗滑稳定性验算流程 6e5dee1dad6f | 4 | 4.3.6.1 | |
| 明基床基肩和坡面块体稳定重量计算 22d61b71f16a | 3 | 附录E | |
| 斜坡堤前海底冲刷形态判别与计算 8603d564dc3f | 2 | 附录D | 含判别分支，部分步转 conditional |
| 削角直立堤抗倾稳定性设计流程 cc2ba2fad57a | 3 | 5.5 | |

### B 类：公式少/无，多为「确定性计算」之外的动作（22 条，需重构而非补公式）—— **2026-10-17 已全部修复**

实际分流复核后，B 类口径有修正：22 条里有 4 条其实有真实封闭式（原 SOP 引错规范/臆造公式）——
0eac83f39548 直立堤前冲刷（附录F，判别β式F.0.2-1~-4、细沙型Z_mf式F.0.4-5、粗沙型查图F.0.5+l_r式F.0.5-2）、
6cff89f19b75 斜向波护面块体（附录A.0.1 K_Dβ=K_D/cos^k(β−22.5°) + 式4.3.7-1）、
c125b4582268 斜向波直立堤折减（附录A.0.2 k_p=[1+cos(β−22.5°)]/2，β∈[22.5°,90°]）、
d8a3838320bf 透空式防波堤（6.3.2 桩基透浪系数Kt、6.3.6 沉箱墩式折减系数K/反射系数Kr，波浪力本体按6.3.4/6.3.7模型试验）。
其余 18 条由并行会话重构（conditional/table_lookup/knowledge_search/llm_generate 分流）。
备份：原件在 `data/platform/sops/json/.bak-20261017-sopexpr-b/`（22 个）。

**QA 复核（2026-10-17，只对 22 条做只读验证）**：
- validator 全规则 22/22 通过；全库 55 条残废扫描 0 坏。
- 空上下文野跑 22/22：无「表达式不能为空」、无假成功、缺参报告齐全。
- 公式抽查对 JTS 154-2018 原文：ce561e87e28b（式6.2.3-1/-2/-3/-4，γd=1.35）、9a767f690bd4（式H.0.2-1/-2/-11）
  逐位吻合；我方 4 条全参直跑与独立复算逐位一致（附录F β=23.4302/Z_mf=0.419028/l_r=13.170224；
  A.0.1 K_Dβ=15.010023/W=1.192246；A.0.2 k_p=0.896677；6.3.2 K_t=0.484515；6.3.6 K=0.907554/K_r=0.460600）。

**同批引擎修复（QA 中发现）**：ConditionalTool 分支内嵌 calculator/table_lookup 的子工具错误原先埋在
`calculator_result.error`/`table_result.error`，runner 只认顶层 `error` 键——分支计算失败时步骤被记
假成功（result=None）且缺参不进 missing_report。修复为错误透传顶层（`services/engtools/src/engtools/ConditionalTool.py`），
回归测试 3 例新增于 `tests/unit/test_unit_conditional_tool.py`。此改动在 engtools 镜像内，生效需代码部署（非数据同步）。

原分流记录（2026-10-15 启发式判定，已被上述复核取代）：

- **查表/取值类**：042d0c727708、626073291d97、78b844ea044d、8170ca85c27e、bc80ca46cf49。
- **统计/资料处理类**：9e6bab387fa1、4176b2aabad4。
- **图形积分/分点类**：ce561e87e28b、9663d82d1035、9a767f690bd4、c125b4582268（复核后确认有式A.0.2可依）。
- **试验/原则类**：f7aac0df783e、73e7af80fb10、361a205387da、bda108484a75/ddad3e0e5927、e610fe64e3d9、
  db749895caef、ed533f83d382、d8a3838320bf（复核后确认 6.3 有近似封闭式）、0eac83f39548（附录F 有封闭式）、
  6cff89f19b75（附录A.0.1 有封闭式）。

### 施工次序建议（已执行完毕，留档）

1. A 类逐条：打开源段 → 把带编号公式抄成 `${变量}` 表达式（同半圆堤样例）→ 直跑器验证（全参出数 / 缺参报缺）→ 校验器过。
2. B 类逐条：先判该步的真实动作，能查表改 `table_lookup`，不能算的改 `manual`/`knowledge_search`；
   确实无封闭式（积分/统计）的把口径写进描述，不硬凑公式。
3. 任何一条在新规则下保存都会过规则 6 校验，不会再静默放行。

## 验证与测试

- 单测：`python -m pytest tests/unit/test_unit_sop_expression_backfill.py tests/unit/test_unit_sop_validator.py -q` → 18 passed；
  SOP/计算器相关全量回归 118 passed（含缺参引导 AI 预算闸两条新例）。
- 直跑：全参数 → 9 步 success（值与本文件公式独立复算一致，误差 ≤1e-3）；
  题面只给 H/d/L → step_1~3 success（η=4.2，ps=17.4819），step_4~9 failed 且 `missing_report`=
  [基床上水深d1, 作用点间水平距离Δl, 计算点高度z, 圆心角θ, 底宽B]，全程无「表达式不能为空」。
- 聊天链装配（LLM-free，真 sop-api + 真适配器帧 + 真 runner，2026-10-15 21:2x 跑通）：
  `SopRunnerAdapter.sop_execute` 走桩分类器（args 复刻生产 16:06 run 提取的 H/d/L）→
  11 帧（plan 1 + step 9 + done 1），done 计数 9/9；
  步状态 = step_1/2/3 success（η=4.2、αs=0.609124、ps=17.481859）、step_4~9 failed；
  summary =「命中 SOP 96682af0ed26，执行 9 步，成功 3 步，失败 6 步；缺参：基床上水深d1、
  作用点间水平距离Δl、圆心角θ、计算点高度z、底宽B——请补充后重问（系统不臆造数值…）」。
- SSE 实链一分钟级验证被环境阻塞：当刻共享 DGX 被 Harvey 入库占满（网关探针 25s 无响应、
  LLM 调用进客户端重试循环），LLM 驱动的分类/规划段无法在合理时间内完成；
  LLM-free 装配验证覆盖了同一代码路径（除 LLM 路由本身），路由段有当日 16:06 生产 run 的 L3 实据。

## 缺参引导的预算闸（同批修复）

补全后 SOP 会如实报出 5 个几何缺参，而 AI 推荐值的 LLM 调用是**逐步同步**的——
2026-10-15 实踩：慢网关下 4 次调用累计 ≈11 分钟，把 `sop_execute` 的 120s 工具预算拖爆，
9 个步骤结果与全部 sop_flow 帧被超时吞掉（用户侧表现为「问完没反应」）。
修法（`sop_runner._llm_recommend`）：同 run 共享一个总预算
`ANGINEER_SOP_AI_RECOMMEND_TIMEOUT`（默认 30s，`.env.example` 已登记）；
单次等待与累计都不超预算，超了降级「仅报缺」（不臆造）。增强项永不阻塞主结果。

## 生产现状（2026-10-17 复核更正 + 当日晚更新）

2026-10-15 21:1x 只读核查时部署机 `/home/runner/AnGIneer/data/platform/sops/json/` 为空（0 条）属实；
但**当夜 23:15–23:32 本地做过一轮批量改写（仅工具类型分流，未补 expression），23:36 已同步上生产**。
2026-10-17 白天复核（按 `execution.tool == "calculator"` 且 inputs 缺 `expression`/`expressions` 口径）：
- 生产 55 条，其中 38 条 / 113 个 calculator 步缺 expression；即残废 SOP 已是线上缺陷。
- 本文档早先「57 条/39 条残废」口径含已修复的半圆堤；现 55 条/38 条残废（少了市场研究等改名/并档差异，残废数 39→38 即半圆堤已修）。

**2026-10-17 晚状态**：
- 本地 55 条全部修复（A 类 16 补公式 + B 类 22 重构），残废扫描 0 坏、野跑 QA 全过。
- 已同步生产一批：A 类 16 条 + 半圆堤（含 index.json 重建），sop-api 重启后接口实拉确认带 expression——生产残废 38→22。
- **待同步**：B 类 22 条 + A 类中 4 条的后续精修（4daf8ab7c5ef/25ae5b6a36df/dae53763ea51/47c03850b676
  的 user_input→守卫式 calculator 统一、工况别名补充）尚未上生产。
- **待部署（代码层，非数据同步）**：ConditionalTool 分支子工具错误透传修复在 engtools 镜像内，
  需随下次镜像重建/部署生效；未部署前生产上分支内嵌计算失败仍会假成功（仅缺参场景，不影响有参计算）。

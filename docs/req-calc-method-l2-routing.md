# 需求票：无参「计算方法问句」误判 L3 治理（堤顶高程怎么计算 → L2）

- 状态：已评审（2026-10-16 设计通过；实施与部署待闸门）
- 来源：2026-10-16 用户实测「堤顶高程怎么计算」判 L3 → SOP 缺参/拒答
- 涉及：`angineer-core`（classifier.py 快路径+规则兜底、prompts/classifier.py v5）、`scripts/build_intent_set.py`（题集 +3）及 `evals-core` bundle 自检、`tests/angineer-core`

## 0. 一句话

含计算动词但题面零数值的「XX 怎么计算 / 如何计算 / 公式是什么」是**查方法/公式**（L2），不是**执行计算**（L3）：现状三层判据（LLM prompt、规则兜底）都把它判 L3，而 L3 链路按「有 SOP 可执行」设计，必然收场在「缺数据 / 未匹配 SOP → 拒答」；本票给它一条确定性 L2 通道（规则快路径 + prompt v5 + 兜底同步 + 金标 3 题），题面一旦含数值仍走原 L3 链路。

术语（英文标识符）：**计算方法问句**= 含计算类动词但题面零数值的方法/公式查询；**计算快路径**= 规则层直达 L2 的通道，开关 `ANGINEER_CALC_METHOD_FASTPATH`，intent_type 标识 `method_lookup`。与既有「条款号快路径」（`ANGINEER_CLAUSE_FASTPATH` / `rule_clause`）同构，勿混称。

## 1. 事故经过（证据链，2026-10-16）

生产 classify 落盘（服务器 `/home/runner/AnGIneer/data/ops/classify-*.jsonl`；本地同结构）：

| 时刻(北京) | 问句 | 判级 | 备注 |
|---|---|---|---|
| 10-03 23:31 / 10-04 01:22 | 堤顶高程怎么计算 | **L1** | 分类 LLM（≥2.6s，非规则前置） |
| 10-06 22:51 / 10-07 02:29 | 堤顶高程怎么计算 | **L3** | 同上；期间无分类相关代码/prompt 改动（网关模型漂移） |
| 10-07 01:44 | 防波堤的堤顶高程**如何确定**？ | L2 | 对照：措辞变体稳定 L2 |
| 10-16 16:54 | 堤顶高程怎么计算 | **L3** | 今日用户实踩（2843ms） |

现状链路（10-16 生产实况）：

```
「堤顶高程怎么计算」（题面零数值）
   → 分类 LLM：见"计算"动词 + 工程词"堤顶高程" → L3
       （prompt L3 定义/规则 1 未硬性要求"必须含数值"）
   → L3 = 复杂档（agent_policy.py:216）＋ SOP 点名引导 _build_sop_hint 注入
       （本地实测：粗筛命中"…顶高程计算"SOP，0.105 > 0.10 阈值）
   → 模型按引导调 sop_execute
        ├─ 命中 SOP 但缺参（设计高水位/设计波高/越浪允许性）→ 报"缺数据"
        └─ 未命中 → "未匹配到合适的 SOP" → 段内零证据 → 拒答收尾
```

规则兜底同口径错：`_rule_based_classify`（classifier.py:448）注释即「纯计算关键词（无参数）也走 L3，由 SOP 内部处理」。
10-04→10-06 的 L1→L3 翻转无代码归因、系网关模型漂移——**只改 prompt 会再漂**，故加确定性快路径（与条款号快路径同一立项逻辑，见 classifier.py:269-271 注释）。

## 2. 目标行为

- 无参计算方法问句 → **L2 structured_lookup**（条款/公式查证；L2 链路自带 L1 回退段，agent_policy.py:252-256）。
- 题面含任何数值（阿拉伯或全角数字）→ 不进快路径，交 LLM 判级（真计算题 L3 链路不变，缺参纪律保留）。
- 「如何确定 / 如何取值」类不改（LLM 现行为已稳定 L2；如需确定性另行立项，勿顺手扩正则）。

## 3. 方案（B 档全量）

### 3.1 `services/angineer-core/src/angineer_core/classifier.py`

- 新增三件套（镜像条款号快路径 `_clause_fastpath_enabled` / `_is_clause_number_query`，classifier.py:272-286 同区）：
  - `_CALC_METHOD_PATTERN`：

    ```
    (?:怎么|如何|怎样)(?:计算|算(?!法)|求解|求|算出|得出|推算)
    |(?:计算|求解|(?<![寻请要需])求)(?:公式|方法|步骤|过程)\s*(?:是什么|是啥|是多少|怎么样|是怎样的|为多少|为|有哪些|分别|呢|[?？]|$)
    ```

    第二分支用 `(?<![寻请要需])求` 防「寻求/请求/要求/需求+方法」语素误伤（实测旧式命中、修后全拦且「求解方法是什么」不受影响；16k ops+3.5k 题零实测命中，属知情防御项）。
  - `_calc_method_fastpath_enabled()`：读 `ANGINEER_CALC_METHOD_FASTPATH`，缺省开（值解析口径与 `_clause_fastpath_enabled` 逐字一致）。
  - `_is_calc_method_query(query)`：命中上述正则 **且** 不含 `[0-9０-９]` 任一字符。
- `_classify_intent_impl` 插入「步骤 1.8」（现步骤 1.7 条款快路径之后、步骤 2 LLM 之前，classifier.py:573-585 之间）：

  ```python
  if _calc_method_fastpath_enabled() and _is_calc_method_query(user_query):
      return _build_intent_result(
          intent_level="L2",
          intent_type="method_lookup",
          required_capabilities=["retrieval", "sql"],
          service_mode="structured_lookup",
          reason="计算方法问句快路径：似查公式/方法而非执行计算（无数值参数），规则直达 L2",
      )
  ```
- `_rule_based_classify`：方法判据**不能**放 `if has_l3_keyword:` 分支（:429）——`L1_KEYWORDS` 含「是什么」（classifier.py:31），含「公式是什么/方法是什么」的问句会被 L1 分支（:407）先截胡（实测 `_rule_based_classify("堤顶高程计算公式是什么")` → L1 concept_resolution，与快路径/prompt v5 的 L2 口径矛盾）。判据放到 **L1 分支之前**（:404 特征提取后、:407 前），并**与快路径共用 `ANGINEER_CALC_METHOD_FASTPATH` 开关**（关闭即回旧行为，开关语义单一）：命中则返回 L2（intent_type=`method_lookup`，reason「计算方法问句（无数值参数）：规则归 L2 条款/公式查证」）；其余分支不动。步骤 1.5 仅消费 locate 结果，该调整不影响预 LLM 主链（真正的预 LLM 变化在步骤 1.8 快路径）。
- 观测面：`classify_intent` 落盘 payload（classifier.py:533-540）现状只有 dur_ms/level/mode/query、**不落 reason**；本次为 payload 增 `"reason": getattr(result, "reason", None)` 一行，使「快路径命中」可在 `data/ops/classify-*.jsonl` 直接审计（已核验：该文件无严格 schema 消费者，仅人读/临时脚本；record_event 包裹层自动补 ts/kind/run_id）。
- `.env.example`:174 旁补一行 `# ANGINEER_CALC_METHOD_FASTPATH=true    # 无参计算方法问句规则直达 L2（默认开；false 走 LLM 分类）`（与条款号快路径样例行并列）。

### 3.2 `services/angineer-core/src/angineer_core/prompts/classifier.py`（v4 → v5）

- L3 行（现第 19 行）：`有具体数值参数需要计算（吨级、水位、波高、尺寸等工程参数），且存在预定义SOP可承接` → `题面给出具体数值参数（如 3.5m、5万吨级、C40）需要计算，且存在预定义SOP可承接；仅问“XX怎么计算/如何计算”而无数值的是方法查询（→L2）`
- 规则 1（现第 24 行）：`只要题目包含“计算/求/验算/求解/算出”等动词 + 工程参数（吨级、水位、波高、尺寸等数值），优先判为 L3` → `题目包含“计算/求/验算/求解/算出”等动词且题面给出了具体数值（吨级、水位、波高、尺寸等），优先判为 L3；只有计算动词而题面无任何数值的（“XX怎么计算/如何计算/计算公式是什么”），是查方法/公式，判 L2`
- 规则 3（现第 26 行）尾补：`；问计算方法/公式依据（无数值）同样归 L2`
- Few-shot 增一条（置于 L2 查表例之后）：
  `Q: "堤顶高程怎么计算？" A: {"intent_level": "L2", "intent_type": "条款查表", "confidence": 0.9, "service_mode": "structured_lookup", "reason": "问计算方法与公式、题面无数值参数，属规范公式/条款查证，不执行计算"}`
- docstring 版本说明 v5（日期 2026-10-16 + 变更一句话）；`register(..., "v5", ...)`。

### 3.3 `scripts/build_intent_set.py`（题集 100 → 103）

- 新 family `L2_method` 3 题（(id, question, level, mode, family, trap, rationale)，第 8 列 source 缺省）：

  | id | 题面 | gold | trap | rationale 要点 |
  |---|---|---|---|---|
  | ir-l2-method-01 | 堤顶高程怎么计算 | L2 / structured_lookup | 无参数计算方法问句 | 计算方法/公式查证，题意无数值不构成计算；计算快路径直达（v5 规则 1 收紧） |
  | ir-l2-method-02 | 乘潮水位怎么计算 | L2 / structured_lookup | 无参数计算方法问句 | 同上（沿用 agent 测试同题面，属真实生产问法） |
  | ir-l2-method-03 | 高速公路桥梁的雪荷载计算方法是什么 | L2 / structured_lookup | 无参数计算方法问句+跨域 | 同族跨域验证（非海港域） |
- `rule_hit_for()` 增计：`_is_calc_method_query(question)` 且开关开 → `"rule_calc_method"`（顺序：L0 → 条款 → 计算 → model）。
- `validate()`：题数 100 → 103；`expect_level` L2 22 → 25；`expect_route` L2 22 → 25；新族对账断言——`family == "L2_method"` 必须 `rule_hit == "rule_calc_method"`（与 L2_clause_number 对账同构，第 371-376 行）。
- 头部 docstring（第 2 行）与 dataset title/description（第 308-310 行）「100 题」→「103 题」；`scripts/backfill_dataset_meta.py:147/152` 标题与 source_note 同类字串同步。

### 3.4 测试

- 新增 `tests/angineer-core/test_classifier_calc_method_fastpath.py`（镜像 `test_classifier_clause_fastpath.py` 结构）：
  - 正例（`_is_calc_method_query` 为真）：ops 实测 5 条（乘潮水位怎么计算 / 堤顶高程怎么计算 / 疏浚底高程怎么计算 / 钢板桩的单宽强度怎么计算 / 高速公路桥梁的雪荷载计算方法是什么）+「堤顶高程计算公式是什么」+「堤顶高程的计算方法」
  - 反例（为假）：含数值（「某5万吨级散货船，设计船型总长L=230m，型宽B=32m，满载吃水T=12.8m，试计算码头前沿水深。」「堤顶高程计算：设计高水位3.2m、设计波高2.0m」）/「《疏浚与吹填工程设计规范》中计算超深的取值是多少？」（术语「计算超深」）/「下列关于重力式直立堤设计原则和计算方法的叙述，符合规范规定的是」（MCQ 叙述句，尾部限定排除）/「把第4题的计算过程再详细讲一遍」/「试计算码头前沿水深」/「寻求方法是什么」（裸「求」语素误伤，lookbehind 防护例）/ 空串
  - 开关：缺省开；`ANGINEER_CALC_METHOD_FASTPATH=false` 关闭（含清理环境变量还原）——规则兜底与快路径共用开关，关闭后同回旧层级
  - 链路：`classify_intent("堤顶高程怎么计算")` → L2 method_lookup（快路径即使 LLM 可判也不调 LLM）；关闭开关后以 LLM/规则兜底为准
  - 规则兜底同步（覆盖 :407 L1 分支截胡缺口）：
    - `_rule_based_classify("堤顶高程怎么计算")` / `("堤顶高程计算公式是什么")` / `("高速公路桥梁的雪荷载计算方法是什么")` → L2 `method_lookup`（后两条修复前实测落 L1 concept_resolution）
    - `_rule_based_classify("求泊位长度")`（无参数非方法句）→ 仍 L3
    - 开关关闭（=false）：规则兜底同回旧层级（「堤顶高程怎么计算」→ L3、「堤顶高程计算公式是什么」→ L1）
- `services/evals-core/tests/test_intent_set_bundle.py`：`== 100` → `== 103`（测试函数名同步）；`rule_hit` 白名单加 `"rule_calc_method"`；`test_new_trap_families_present` 加 `"L2_method"`。
- `tests/angineer-core/test_prompts.py`：增 v5 断言（「意图层级定义」保留 + 新 few-shot 题面在场）。

### 3.5 部署与重导（push 后，须单独授权）

1. deploy 落地 → 服务器 `python scripts/build_intent_set.py` 重生成 `data/evals/datasets/intent-router-v1.json`（data/ 不入 git，必须重生成而非等待部署携带）。
2. 重导 evals 库：`evals_core.dataset.manager.import_bundle`（本地/脚本口径，INSERT OR REPLACE）或 POST `/api/evals/datasets/import`；**评测读导入副本不读文件，不重导则夜间仍是 100 题旧金标**（前例：`docs/req-abolish-meta-query-route.md` 的「重导」实证条目）。
3. 次日 nightly 起按 103 题口径跑 intent-router-v1（`data/evals/nightly_settings.json` 的 `extra_dataset_ids` 已含该集，无需改配置）。

## 4. 证据：正则口径实测（2026-10-16 本地）

- ops 去重 **2192** 条真实查询（原始 16060 行，`data/ops/classify-*.jsonl` 全量）：宽口径 7 命中 → 加尾部限定、数字排除与「寻求/请求/要求/需求」语素 lookbehind 后 **5 命中，全部为目标类**；两个易伤形态被正确排除（MCQ「计算方法的叙述」、追问「把第 4 题…讲一遍」）。
- 24 个本地评测数据集共 **3576 题**（含 intent-router-v1 / exam-harbor / open-ragbench 全系 / officeqa / financebench / gdp-pdf）：**0 命中**。
- 现有题集 L3 金标题面均含数值 → prompt v5 收紧「必须含数值」不翻转既有金标（以 §5 全量回放为准）。

## 5. 验收闸门

- `python scripts/build_intent_set.py --check`：103 题 + 机械校验 + 新族快路径对账全过。
- pytest：新快路径测试 + `test_classifier_clause_fastpath.py` + `services/evals-core/tests/test_intent_set_bundle.py` + angineer-core 分类相关全绿。
- `python scripts/intent_route_probe.py`（103 题全量回放，走生产分类链）：route 全绿、L3 族无回归；重点对照题：
  - 堤顶高程怎么计算 → route L2（rule_calc_method）
  - 某5万吨级散货船…试计算码头前沿水深。 → route complex（L3 不回归）
- 定向：`IntentClassifier.classify_intent("堤顶高程怎么计算")` → L2、reason 含「快路径」（毫秒级，不再 2.8s）；同调用后检查 `data/ops/classify-*.jsonl` 新记录含 reason 字段（观测面上线验收）。

## 6. 边界（不做）

- 不动 L3/L4 复杂链路、`_build_sop_hint` 注入逻辑、10-15「SOP 缺参收尾正文回退保险」（真计算题缺数据仍如实报缺 + 推荐值）。
- 不扩展「如何确定 / 如何取值」类（与 L1_KEYWORDS 有交集，单独评估）。
- MCQ 含「计算方法」字样不快速吞（尾部限定排除，交 LLM）。
- 不做会话上下文感知（首轮追问「再讲一遍」类走 LLM，不在快路径）。

## 7. 复现入口

- 分类历史：`data/ops/classify-*.jsonl`（本地与服务器同路径结构）。
- 快路径命中验证：`python scripts/intent_route_probe.py`（题集全量）；直接调用 `IntentClassifier.classify_intent`。
- SOP 缺参现场：`data/platform/sops/json/5eb80f952936.json`（重力式直立堤堤顶高程确定流程，必需参数 设计高水位/设计波高/越浪允许性）。
- 题集构建与自检：`python scripts/build_intent_set.py`（唯一真相源，data/ 下 bundle 为产物）。

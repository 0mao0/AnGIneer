# 实施计划：计算方法问句 L2 路由（无参方法问句快路径 + prompt v5 + 金标 3 题）

> 设计稿（唯一依据）：`docs/req-calc-method-l2-routing.md`（2026-10-16 定稿，含评审修订——问题 1 兜底位置、问题 2 ops reason、(bad) 小项三项已修入）。
> 目标档位：**B 全量** = 正则快路径 + prompt v5 + 规则兜底同步 + 题集金标 +3。
> 本计划面向零上下文执行者；行号以 2026-10-16 当前 HEAD 为准，**实施时若行号漂移，以引用的原文串为准**（Edit/替换必须精确匹配原文）。
> 纪律：**commit 需用户授权、push 需用户明确指令**（主仓库 AGENTS.md）；本计划只给建议 commit 消息，不自动执行 commit/push。

---

## 0. 背景一句话与验收口径

生产「堤顶高程怎么计算」等无参方法问句被 LLM 漂判 L3（→ complex 档，无 SOP 可执行 → 缺参/拒答），
目标 = **L2 条款/公式查证**（`structured_lookup`）。三层同步口径：预 LLM 正则快路径（步骤 1.8）+
prompt v5（LLM 主力口径）+ 规则兜底（LLM 失败时的同口径）。

验收闸门（见 Task 6）：
1. `python scripts/build_intent_set.py --check` → 题数 103、校验通过、`rule_calc_method: 3`；
2. pytest 新增文件全绿 + 存量不回归；
3. `python scripts/intent_route_probe.py` → 103 题全量回放 `route` 无 FAIL、退出码 0（L3 无回归）；
4. 定向手动 classify → L2 `method_lookup`，`data/ops/classify-*.jsonl` 新行含 `reason`。

## 前置（Task 0）

- `git status` 确认工作树状态（预期：仅有 `docs/req-calc-method-l2-routing.md` 与本计划两个未提交文档）；
- 记录基线：`python -m pytest tests/angineer-core -q`（新文件出现前的结果；本计划不允许新增失败）；
- 环境：Windows PowerShell，跑中文 Python 建议 `$env:PYTHONIOENCODING='utf-8'; python -X utf8 ...`。

## 改动文件清单

| 文件 | 动作 | 任务 |
|---|---|---|
| `services/angineer-core/src/angineer_core/classifier.py` | 改：快路径三件套；步骤 1.8；规则兜底判据；payload 补 `reason` | T1/T2/T3 |
| `tests/angineer-core/test_classifier_calc_method_fastpath.py` | **新建**（分三个任务追加） | T1/T2/T3 |
| `.env.example` | 改：`:174` 后插新开关样例行 | T1 |
| `services/angineer-core/src/angineer_core/prompts/classifier.py` | 改：v4→v5（5 处） | T4 |
| `tests/angineer-core/test_prompts.py` | 改：v5 断言 2 行 | T4 |
| `scripts/build_intent_set.py` | 改：题集 +3 题、rule_hit_for、validate 计数、标题/描述/docstring | T5 |
| `scripts/backfill_dataset_meta.py` | 改：`:147`/`:152` 标题与题数串 | T5 |
| `services/evals-core/tests/test_intent_set_bundle.py` | 改：`==103`、白名单、`L2_method` | T5 |

---

## Task 1 — 快路径判据三件套（regex + 开关 + 判据）+ 判据单测 + .env.example

### 1.1 先写测试（红）

**新建** `tests/angineer-core/test_classifier_calc_method_fastpath.py`，内容：

```python
# -*- coding: utf-8 -*-
"""计算方法问句规则快路径（设计稿 docs/req-calc-method-l2-routing.md）。

「堤顶高程怎么计算」类问句（计算动词 + 题面零数值）是查方法/公式（L2 条款/公式查证），
不是执行计算（L3 需具体数值参数 + SOP 承接）。生产实况：同句 2026-10-04→10-06 被 LLM
从 L1 漂到 L3（网关模型漂移），L3 链路无 SOP 可执行即缺参/拒答。

本文件随实现分三步补齐（计划 Task 1/2/3）：
1) 判据窄口径（ops 实测命中集 + 含数值/术语/叙述句反例）+ 开关默认；
2) classify_intent 全链路直达 L2（LLM 不参与）+ ops 落盘含 reason；
3) 规则兜底同口径（覆盖 L1_KEYWORDS 含「是什么」的 L1 分支截胡缺口）。
ops 纯采集（data/ops/classify-*.jsonl 全量 16060 行/去重 2192 条）扫描命中恰 5 条、24 个评测
数据集 3576 题 0 命中误伤（2026-10-16）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core.classifier import (  # noqa: E402
    _calc_method_fastpath_enabled,
    _is_calc_method_query,
)

PRODUCTION_HITS = [
    "乘潮水位怎么计算",
    "堤顶高程怎么计算",
    "疏浚底高程怎么计算",
    "钢板桩的单宽强度怎么计算",
    "高速公路桥梁的雪荷载计算方法是什么",
]

MORE_HITS = [
    "堤顶高程计算公式是什么",
    "堤顶高程的计算方法",
]

NOT_CALC_METHOD_QUERIES = [
    "某5万吨级散货船，设计船型总长L=230m，型宽B=32m，满载吃水T=12.8m，试计算码头前沿水深。",  # 含数值 = 真计算题
    "堤顶高程计算：设计高水位3.2m、设计波高2.0m",  # 含数值
    "《疏浚与吹填工程设计规范》中计算超深的取值是多少？",  # 「计算超深」是术语，不是方法问句
    "下列关于重力式直立堤设计原则和计算方法的叙述，符合规范规定的是",  # MCQ 叙述句（尾部限定排除）
    "把第4题的计算过程再详细讲一遍",  # 追问复述
    "试计算码头前沿水深",  # 祈使计算（无参数也不判方法）
    "寻求方法是什么",  # 裸「求」语素误伤防护（lookbehind）
    "",
]


class CalcMethodPatternTests(unittest.TestCase):
    def test_production_hits_match_pattern(self):
        for query in PRODUCTION_HITS + MORE_HITS:
            self.assertTrue(_is_calc_method_query(query), query)

    def test_non_calc_method_queries_not_hit(self):
        for query in NOT_CALC_METHOD_QUERIES:
            self.assertFalse(_is_calc_method_query(query), query)

    def test_switch_default_on_and_off(self):
        old = os.environ.get("ANGINEER_CALC_METHOD_FASTPATH")
        try:
            os.environ.pop("ANGINEER_CALC_METHOD_FASTPATH", None)
            self.assertTrue(_calc_method_fastpath_enabled())
            os.environ["ANGINEER_CALC_METHOD_FASTPATH"] = "false"
            self.assertFalse(_calc_method_fastpath_enabled())
        finally:
            if old is None:
                os.environ.pop("ANGINEER_CALC_METHOD_FASTPATH", None)
            else:
                os.environ["ANGINEER_CALC_METHOD_FASTPATH"] = old
```

运行（红）：

```
python -m pytest tests/angineer-core/test_classifier_calc_method_fastpath.py -q
```

**期望失败**：collection error（`ImportError: cannot import name '_is_calc_method_query'`）。

### 1.2 实现（`classifier.py` 插判据三件套）

在 `_is_clause_number_query` 函数（:283-286，以 `return bool(_CLAUSE_NUMBER_PATTERN.search(query))` 结尾）
之后、`# L0 闲聊快速检测` 注释（:289）之前插入：

```python
# 计算方法问句快路径（2026-10-16，docs/req-calc-method-l2-routing.md）：
# 「XX怎么计算/如何计算/计算公式是什么」类问句（计算动词 + 题面零数值）问的是方法与公式
# （规范条款查证，L2），不是执行计算（L3 需具体数值参数 + SOP 承接）。
# 生产实况：同句 2026-10-04→10-06 被 LLM 从 L1 漂到 L3，L3 链路无 SOP 可执行即缺参/拒答。
# 刻意窄口径（问句尾巴限定）防误伤；开关 ANGINEER_CALC_METHOD_FASTPATH 默认开。
_CALC_METHOD_PATTERN = re.compile(
    r"(?:怎么|如何|怎样)(?:计算|算(?!法)|求解|求|算出|得出|推算)"
    r"|(?:计算|求解|(?<![寻请要需])求)(?:公式|方法|步骤|过程)\s*"
    r"(?:是什么|是啥|是多少|怎么样|是怎样的|为多少|为|有哪些|分别|呢|[?？]|$)"
)

_DIGIT_PATTERN = re.compile(r"[0-9０-９]")


def _calc_method_fastpath_enabled() -> bool:
    return (os.getenv("ANGINEER_CALC_METHOD_FASTPATH", "true") or "").strip().lower() not in ("0", "false", "no", "off")


def _is_calc_method_query(query: str) -> bool:
    if not query:
        return False
    if _DIGIT_PATTERN.search(query):
        return False
    return bool(_CALC_METHOD_PATTERN.search(query))
```

再运行同一命令，**期望 3 passed**。

### 1.3 样例行（`.env.example`）

在 `:174`（`# ANGINEER_CLAUSE_FASTPATH=true        # 条款号问句规则直达 L2（默认开；=false 回 LLM 分类）`）
之后插入一行：

```
# ANGINEER_CALC_METHOD_FASTPATH=true   # 无参计算方法问句规则直达 L2（默认开；=false 回 LLM 分类与旧规则兜底）
```

### 1.4 commit（待授权）

```
git add services/angineer-core/src/angineer_core/classifier.py tests/angineer-core/test_classifier_calc_method_fastpath.py .env.example
```

建议消息：`意图分类：计算方法问句快路径判据（无参+计算方法词→L2），开关 ANGINEER_CALC_METHOD_FASTPATH 默认开`

---

## Task 2 — 步骤 1.8 主链 + ops 落盘补 reason

### 2.1 先写测试（红）：文件末尾追加

```python
class CalcMethodFastPathEndToEndTests(unittest.TestCase):
    """快路径命中时 classify_intent 直达 L2——llm_client 传哨兵对象：快路径若失效，LLM 被触即可见。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_ops = {k: os.environ.get(k) for k in ("ANGINEER_OPS_DIR", "ANGINEER_OPS_DISABLE")}
        os.environ["ANGINEER_OPS_DIR"] = self._tmp.name
        os.environ.pop("ANGINEER_OPS_DISABLE", None)  # conftest 全局停用观测，这里定向重开

    def tearDown(self):
        for k, v in self._old_ops.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def test_calc_method_query_routes_l2_without_llm(self):
        from angineer_core.classifier import IntentClassifier

        classifier = IntentClassifier([], llm_client=object())
        for query in PRODUCTION_HITS + MORE_HITS:
            result = classifier.classify_intent(query)
            self.assertEqual(result.intent_level, "L2", query)
            self.assertEqual(result.service_mode, "structured_lookup", query)
            self.assertEqual(result.intent_type, "method_lookup", query)

    def test_reason_and_dur_recorded_to_ops_jsonl(self):
        import json

        from angineer_core.classifier import IntentClassifier

        classifier = IntentClassifier([], llm_client=object())
        classifier.classify_intent("堤顶高程怎么计算")
        files = [f for f in os.listdir(self._tmp.name) if f.startswith("classify-")]
        self.assertEqual(len(files), 1, f"应恰好落一个 classify 观测文件：{os.listdir(self._tmp.name)}")
        with open(os.path.join(self._tmp.name, files[0]), encoding="utf-8") as fh:
            row = json.loads(fh.readline())
        self.assertEqual(row["kind"], "classify")
        self.assertEqual(row["level"], "L2")
        self.assertEqual(row["mode"], "structured_lookup")
        self.assertIn("快路径", row["reason"])
```

并在文件头部 import 区补 `import tempfile`（与现有一并排好，`os/sys/unittest` 旁）。

运行：`python -m pytest tests/angineer-core/test_classifier_calc_method_fastpath.py -q`

**期望红**（2 failed，都因链路未实现）：level 落 L3/L1 而非 L2（哨兵 LLM 若抛异常被吞，则落规则兜底旧层级）；
payload 无 `reason` 键（KeyError）。此任务后两者必转绿。

### 2.2 实现（A）：步骤 1.8（`_classify_intent_impl` 内）

在步骤 1.7 条款号块结尾（`return clause_result`，:583）之后、`# 步骤 2: LLM 直接分类 L1/L2/L3/L4（主力分类器）`（:585）之前插入：

```python
        # 步骤 1.8: 计算方法问句快路径（2026-10-16，docs/req-calc-method-l2-routing.md）
        # 「堤顶高程怎么计算」类：问方法/公式而非执行计算（题面无数值参数），规则直达 L2。
        if _calc_method_fastpath_enabled() and _is_calc_method_query(user_query):
            calc_method_result = _build_intent_result(
                intent_level="L2",
                intent_type="method_lookup",
                required_capabilities=["retrieval", "sql"],
                service_mode="structured_lookup",
                reason="计算方法问句快路径：似查公式/方法而非执行计算（无数值参数），规则直达 L2",
            )
            logger.info(f"[DEBUG-SOP-ROUTE] 计算方法问句快路径命中: {user_query[:50]}")
            return calc_method_result
```

（构造形态与步骤 1.7 完全同款。）

### 2.3 实现（B）：payload 补 `reason`（观测面）

`classify_intent` 公开入口的 `record_event("classify", {...})`（:533-541），在 `"query": user_query,`（:539）之后补一行：

```python
                    "reason": getattr(result, "reason", None),
```

（已核验无严格 schema 消费者；现有落盘行字段 = ts_utc/ts_bj/kind/dur_ms/level/mode/query/run_id。）

运行同一命令，**期望 5 passed**。

### 2.4 commit（待授权）

建议消息：`意图分类：计算方法问句规则直达 L2（步骤 1.8，LLM 前）+ ops 落盘补 reason 字段`

---

## Task 3 — 规则兜底同步（必须放 L1 分支之前）

### 3.1 先写测试（红）：文件末尾追加

```python
class RuleFallbackSyncTests(unittest.TestCase):
    """LLM 失败时的规则兜底同口径。判据必须置于 L1 分支之前——L1_KEYWORDS 含「是什么」，
    「计算公式是什么」会被 :407 L1 分支先截胡（评审实测：修复前落 L1 concept_resolution）。"""

    def setUp(self):
        self._old = os.environ.get("ANGINEER_CALC_METHOD_FASTPATH")
        os.environ.pop("ANGINEER_CALC_METHOD_FASTPATH", None)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ANGINEER_CALC_METHOD_FASTPATH", None)
        else:
            os.environ["ANGINEER_CALC_METHOD_FASTPATH"] = self._old

    def test_method_queries_route_l2(self):
        from angineer_core.classifier import _rule_based_classify

        for query in ("堤顶高程怎么计算", "堤顶高程计算公式是什么", "高速公路桥梁的雪荷载计算方法是什么"):
            result = _rule_based_classify(query)
            self.assertIsNotNone(result, query)
            self.assertEqual(result.intent_level, "L2", query)
            self.assertEqual(result.intent_type, "method_lookup", query)

    def test_non_method_calc_query_stays_l3(self):
        from angineer_core.classifier import _rule_based_classify

        result = _rule_based_classify("求泊位长度")
        self.assertIsNotNone(result)
        self.assertEqual(result.intent_level, "L3")

    def test_switch_off_restores_legacy_levels(self):
        from angineer_core.classifier import _rule_based_classify

        os.environ["ANGINEER_CALC_METHOD_FASTPATH"] = "false"
        self.assertEqual(_rule_based_classify("堤顶高程怎么计算").intent_level, "L3")
        self.assertEqual(_rule_based_classify("堤顶高程计算公式是什么").intent_level, "L1")
```

运行：**期望 1 failed**（`test_method_queries_route_l2`：三条全落旧层级）、其余 passed（旧行为即 L3 / L1，与 legacy 断言暂相符）。

### 3.2 实现

`_rule_based_classify` 中，`has_l4_compound = any(kw in query for kw in L4_COMPOUND_SIGNALS)`（:404）
之后、`# L1: 概念/定义/位置类查询（只要检测到L1关键词且没有强L3信号）`（:406）之前插入：

```python
    # 计算方法问句（无数值参数）→ L2 条款/公式查证（与计算快路径同口径；2026-10-16）
    # 必须置于 L1 分支之前：L1_KEYWORDS 含「是什么」，否则「计算公式是什么」会被 L1 先截胡（实测）
    if _calc_method_fastpath_enabled() and _is_calc_method_query(query):
        return _build_intent_result(
            intent_level="L2",
            intent_type="method_lookup",
            required_capabilities=["retrieval", "sql"],
            service_mode="structured_lookup",
            reason="计算方法问句（无数值参数）：规则归 L2 条款/公式查证（计算快路径同口径）",
        )
```

运行同一命令，**期望 8 passed**（三个任务的全部用例）。

### 3.3 commit（待授权）

建议消息：`意图分类：规则兜底方法问句改判 L2（置于 L1 分支之前，修「公式是什么」被 L1 截胡）`

---

## Task 4 — prompt v5（LLM 主力口径）

### 4.1 先写测试断言（红）

`tests/angineer-core/test_prompts.py` 的 `test_classifier_prompts_registered`（:85-92），在
`self.assertIn("意图层级定义", CLASSIFY_INTENT_SYSTEM_PROMPT)` 之后补两行：

```python
        self.assertIn("题面给出具体数值", CLASSIFY_INTENT_SYSTEM_PROMPT)
        self.assertIn("堤顶高程怎么计算", CLASSIFY_INTENT_SYSTEM_PROMPT)
```

运行：`python -m pytest tests/angineer-core/test_prompts.py -q` → **期望 1 failed**（新断言不在 v4 文本）。

### 4.2 实现：`prompts/classifier.py` 五处改

① 头 docstring :3-6 替换为：

```
用途：意图层级分类、SOP 两阶段路由精排；语言：中文；classify_intent 版本 v5。
最后变更：2026-10-16（v5：无参「计算方法问句」判 L2——L3 定义与规则 1 收紧为「题面须给出具体数值
参数」，规则 3 补方法/公式查询归属；新增 few-shot「堤顶高程怎么计算？→ L2」；配套计算快路径
ANGINEER_CALC_METHOD_FASTPATH 与规则兜底同口径改判，见 docs/req-calc-method-l2-routing.md）。
```

② L3 行（:19）原文 `有具体数值参数需要计算（吨级、水位、波高、尺寸等工程参数），且存在预定义SOP可承接` 替换为：

```
题面给出具体数值参数（吨级、水位、波高、尺寸等）且存在预定义SOP可承接；仅问"XX怎么计算/如何计算/公式是什么"而无数值的是方法查询（→L2）
```

③ 规则 1（:24）原文 `1. 只要题目包含"计算/求/验算/求解/算出"等动词 + 工程参数（吨级、水位、波高、尺寸等数值），优先判为 L3` 替换为：

```
1. 只要题目包含"计算/求/验算/求解/算出"等动词且题面给出具体数值（吨级、水位、波高、尺寸等工程参数），优先判为 L3；只有计算动词而题面无数值的"XX怎么计算/如何计算/计算公式是什么"是查方法/公式，判 L2
```

④ 规则 3（:26）原文 `3. "查表""依据XX规范""取值""应符合XX条" + 无计算 = L2` 替换为：

```
3. "查表""依据XX规范""取值""应符合XX条" + 无计算 = L2；问计算方法/公式/步骤（题面无数值）同样归 L2
```

⑤ few-shot：在 :46（L2 查表示例 `依据《海港总体设计规范》确定5万吨级散货船的设计船型尺度`）与 :48（L3 示例）
之间插入（保留空行分隔）：

```
Q: "堤顶高程怎么计算？"
A: {"intent_level": "L2", "intent_type": "条款查表", "confidence": 0.90, "service_mode": "structured_lookup", "reason": "问计算方法与公式、题面无数值参数，属规范公式/条款查证，不执行计算"}
```

⑥ 注册（:95）：`register("classifier.classify_intent_system_prompt", "v4", ...)` → `"v5"`。

运行：`python -m pytest tests/angineer-core/test_prompts.py tests/angineer-core/test_classifier_calc_method_fastpath.py -q` → 全绿。

### 4.3 commit（待授权）

建议消息：`意图分类：classify_intent prompt v5——无参计算方法问句判 L2（L3 收紧为须有数值参数）`

---

## Task 5 — 题集 100→103（+3 道 L2_method）+ CI 自检同步

### 5.1 改 `scripts/build_intent_set.py`

① docstring：`:2` `100 题` → `103 题`；`:9` `（v3 层级表与规则 1-7）` → `（v5 层级表与规则 1-6）`；
并在 :24 之后补一段：

```
2026-10-16：+3 道 L2_method（无参「XX怎么计算/计算公式是什么」问句；L3 定义随 v5 收紧为须有数值参数），
100→103；规则对账新增 rule_calc_method（_is_calc_method_query 快路径，见 docs/req-calc-method-l2-routing.md）。
```

② ITEMS：在 `ir-l2-nc-03` 行（:169-170）之后、`# ---------------- L3 标准计算` 注释（:172）之前插入：

```python
    ("ir-l2-method-01", "堤顶高程怎么计算", "L2", "structured_lookup", "L2_method",
     "无参数计算方法问句", "问计算方法/公式且题面无数值 → L2；计算快路径直达（v5 规则 1 收紧），对照 ir-l3-calc-* 有数值参数"),
    ("ir-l2-method-02", "乘潮水位怎么计算", "L2", "structured_lookup", "L2_method",
     "无参数计算方法问句", "生产同族问法（ops 实测）→ L2"),
    ("ir-l2-method-03", "高速公路桥梁的雪荷载计算方法是什么", "L2", "structured_lookup", "L2_method",
     "无参数计算方法问句（跨域）", "「计算方法是什么」型；跨域（非海港）验证通用性 → L2"),
```

③ `rule_hit_for`（:256-270）：import 行补 `_calc_method_fastpath_enabled, _is_calc_method_query`；在条款号检查之后、`return "model"` 之前插：

```python
    if _calc_method_fastpath_enabled() and _is_calc_method_query(question):
        return "rule_calc_method"
```

④ validate：`:327-328` `100` → `103`（两处，含报错串 `≠ 100`）；`:364` L2 `22`→`25`；`:365` L2 `22`→`25`；
在 `L2_clause_number` 对账块（:373-376）之后追加同款族对账：

```python
    # L2_method 族的定义就是「生产计算快路径能认出的问句」，该族必须真被快路径命中（与条款号族同款对账）。
    for it in items:
        if it["intent"]["family"] == "L2_method" and it["intent"]["rule_hit"] != "rule_calc_method":
            problems.append(f"{it['question_id']}: L2_method 族未被计算快路径命中（rule_hit={it['intent']['rule_hit']}）")
```

⑤ 元数据：`:308` title → `"意图路由测试集 v1（103 题 L0-L4 分层）"`；`:310-311` description 的 `100 题` → `103 题`。

### 5.2 改 `scripts/backfill_dataset_meta.py`

`:147` → `"意图路由测试集 v1（103 题 L0-L4 分层）"`；
`:152` → `"103 题；前 100 题 3 次重跑逐题一致；2026-10-16 新增 L2_method 族 3 题（无参计算方法问句→L2）"`。

### 5.3 改 `services/evals-core/tests/test_intent_set_bundle.py`

① `:35` 函数名 → `test_shape_is_103_items_covering_l0_to_l4`；`:38` `== 100` → `== 103`；
② `:51` 白名单元组加 `"rule_calc_method"`；
③ `:81-84` `test_new_trap_families_present`：docstring「三个后补陷阱族」→「后补陷阱族必须在位」；元组加 `"L2_method"`。

### 5.4 跑

```
python scripts/build_intent_set.py --check
```

**期望输出**：`题数: 103`；`by level: {'L0': 12, 'L1': 38, 'L2': 25, 'L3': 16, 'L4': 12}`；
`by route: {'L0': 12, 'L1': 38, 'L2': 25, 'complex': 28}`；`by rule_hit` 含 `'rule_calc_method': 3`；`校验通过`。

```
python -m pytest services/evals-core/tests/test_intent_set_bundle.py -q
```

**期望**：全绿（含 `test_shape_is_103...`、族对账、route 派生同源）。

### 5.5 commit（待授权）

建议消息：`意图题集：+3 道 L2_method（无参计算方法问句），100→103 口径（builder/backfill/CI 自检同步）`

---

## Task 6 — 全量闸门（无新代码；逐条命令 + 期望）

1. `python -m pytest tests/angineer-core -q` → 新增 8 例全过、存量与 Task 0 基线一致（无新增失败）。
2. `python -m pytest services/evals-core/tests/test_intent_set_bundle.py -q` → 全绿。
3. `python scripts/build_intent_set.py` → 写盘 `data/evals/datasets/intent-router-v1.json`（data/ 不入 git），打印 103/校验通过。
4. `python scripts/intent_route_probe.py` → 103 题全量回放，`route` 无 FAIL、退出码 0（L1 记录项噪声属存量，不看）；
   新增 3 题应显示 `rule_hit=rule_calc_method`（规则前置，不经分类模型）。
   耗时 ≈ 5-15 分钟（全题走生产分类链）。
5. 定向冒烟（本地会真实落 `data/ops/`）：

```
python -X utf8 -c "import sys; sys.path.insert(0,'services/angineer-core/src'); sys.path.insert(0,'services/ai-inference/src'); from angineer_core.classifier import IntentClassifier; r=IntentClassifier([], llm_client=object()).classify_intent('堤顶高程怎么计算'); print(r.intent_level, r.intent_type, r.service_mode); print(r.reason)"
```

**期望**：`L2 method_lookup structured_lookup` + reason 含「快路径」；`data/ops/classify-*.jsonl` 最新行含 `"reason"` 字段。

---

## Task 7 — 部署与服务器重导（**需用户授权；push 不自动执行**）

前置事实（2026-10-16 探明）：
- 部署机 host `python3` = 3.6.8（不足以跑本仓库脚本）→ **服务器侧不跑 builder**；
- `angineer-aichat-api` 容器内 `evals_core` 可直接 import（`/app/services/evals-core/src`）；
  数据卷内 `/app/data/evals/evals.sqlite` 可写；但镜像里**没有** `/app/scripts/build_intent_set.py`。
- 结论路径：**本地生成 → scp → 容器内 `import_bundle` 重导**（`INSERT OR REPLACE` 语义，重导幂等）。

步骤（执行时逐条征得用户指示）：

1. **用户明确指令后** push → deploy.yml 自动部署（服务器 `git fetch` + `reset --hard` + 容器重建）。
2. 本地已生成新 bundle（Task 6 第 3 步）。
3. 上传：
   `& "C:\Windows\System32\OpenSSH\scp.exe" data/evals/datasets/intent-router-v1.json root@124.221.238.70:/home/runner/AnGIneer/data/evals/datasets/`
4. 备份数据库：`ssh root@... 'cp /home/runner/AnGIneer/data/evals/evals.sqlite /home/runner/AnGIneer/data/evals/evals.sqlite.bak-20261016'`
5. 容器内重导（命令含三层引号，按 AGENTS.md 规则用 base64 传输执行）：
   `docker exec angineer-aichat-api python -c "import json; from evals_core.dataset.manager import import_bundle; r = import_bundle(json.load(open('/app/data/evals/datasets/intent-router-v1.json', encoding='utf-8')), source_file='deploy-2026-10-16'); print(r.get('dataset_id'), r.get('question_count'), r.get('title'))"`
   **期望**：`intent-router-v1 103 意图路由测试集 v1（103 题 L0-L4 分层）`。
6. 验收：次日 nightly `data/evals/nightly/<date>/` 中 intent-router-v1 为 103 题、route 全绿。

## 回滚预案

- **行为回滚（零部署）**：`ANGINEER_CALC_METHOD_FASTPATH=false`（快路径 + 规则兜底 + `.env` 注释语义一并回旧行为）；
  改服务器 .env 后必须 `cd docker && docker compose up -d aichat-api docs-api` 重建（restart 无效，2026-09-25 实踩）。
- prompt 回滚：revert Task 4 commit（或 register 改回 v4）。
- 题集回滚：恢复 `evals.sqlite.bak-20261016`（重导为覆盖写，旧行可恢复）。

## 边界（不在本计划内）

- 不改既有 100 题金标与审计结论（含 ambiguous 清单）；本计划只 +3 题与新增族。
- probe 的 L1「level 记录项」噪声属存量记录项，不是本计划的验收失败。
- 判据保持窄口径：宁漏勿误（漏 = 回现状 LLM 判 L3 的已知缺陷，误伤 = 把真计算题拉离 L3 更贵）。

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
import tempfile
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


class RuleFallbackSyncTests(unittest.TestCase):
    """LLM 失败时的规则兜底同口径。判据必须置于 L1 分支之前——L1_KEYWORDS 含「是什么」，
    「计算公式是什么」会被 L1 分支先截胡（评审实测：修复前落 L1 concept_resolution）。"""

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

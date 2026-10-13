"""缺参引导回归（2026-10-13 业主纪律：如实报缺 + 引导补充 + 给推荐值，系统不臆造数值）。

覆盖：领域包 param_recommendations 装载、build_missing_guidance 成文规则、
runner 失败步挂引导（含嵌套模板扫描与计算器 unknowns 收集）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core.base_contracts import Step  # noqa: E402
from angineer_core.sop_domain import load_domain_pack  # noqa: E402
from angineer_core.sop_runner import SopRunner, build_missing_guidance  # noqa: E402


class TestMissingGuidanceText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = load_domain_pack("harbor")

    def test_pack_carries_recommendations(self):
        rec = self.pack.param_recommendations
        self.assertEqual(rec.get("船舶航速", {}).get("recommend"), "8")
        self.assertEqual(rec.get("ΔF", {}).get("recommend"), "0.5")
        self.assertIn("6.4.2-2", rec.get("船舶航速", {}).get("rationale", ""))

    def test_guidance_with_recommendation(self):
        out = build_missing_guidance(["船舶航速"], self.pack)
        self.assertEqual(out[0]["param"], "船舶航速")
        self.assertEqual(out[0]["recommend"], "8")
        self.assertEqual(out[0]["unit"], "kn")

    def test_guidance_unmapped_reports_without_number(self):
        out = build_missing_guidance(["某未登记参数"], self.pack)
        self.assertNotIn("recommend", out[0])
        self.assertIn("不臆造", out[0]["rationale"])

    def test_guidance_dedup_preserves_order(self):
        out = build_missing_guidance(["k", "k", "Z0"], self.pack)
        self.assertEqual([i["param"] for i in out], ["k", "Z0"])

    def test_empty_pack_reports_only(self):
        out = build_missing_guidance(["X"], None)
        self.assertEqual(out[0]["param"], "X")
        self.assertNotIn("recommend", out[0])


class TestRunnerAttachesGuidance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = load_domain_pack("harbor")

    def _runner(self):
        return SopRunner(domain_hints=self.pack, llm_client=object())

    def test_nested_template_scan(self):
        runner = self._runner()
        names = SopRunner._collect_unresolved_names(
            {"table_name": "表6.4.2-2", "query_conditions": {"船型": "集装箱船", "航速(kn)": "${船舶航速}"},
             "expr": ["${ΔF}", "ok"]}
        )
        self.assertEqual(names, ["船舶航速", "ΔF"])

    def test_failed_step_gets_guidance(self):
        runner = self._runner()
        step = Step(id="s1", name_zh="查表", tool="table_read", inputs={}, outputs={"c": "result"})
        runner._step_missing["s1"] = ["船舶航速"]
        runner._record_step(step, {}, {"error": "读表判读未能得到值"}, error="读表判读未能得到值")
        runner._attach_missing_guidance(step)
        rec = runner.memory.history[-1]
        self.assertEqual(rec.outputs.get("missing_params"), ["船舶航速"])
        self.assertEqual(rec.outputs["missing_guidance"][0]["recommend"], "8")
        self.assertTrue(any(i["param"] == "船舶航速" for i in runner.missing_report))

    def test_calculator_unknowns_collected(self):
        runner = self._runner()
        step = Step(id="s2", name_zh="计算", tool="calculator", inputs={}, outputs={"W": "result"})
        runner._record_step(step, {}, {"error": "表达式包含未知量，请补充变量值", "unknowns": ["k"]}, error="未知量")
        runner._attach_missing_guidance(step)
        rec = runner.memory.history[-1]
        self.assertIn("k", rec.outputs.get("missing_params") or [])
        guide = {i["param"]: i for i in rec.outputs.get("missing_guidance") or []}
        self.assertEqual(guide["k"]["recommend"], "1.2")


if __name__ == "__main__":
    unittest.main()

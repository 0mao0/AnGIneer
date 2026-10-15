# -*- coding: utf-8 -*-
"""SOP expression 补全回归（2026-10-15）。

背景：39/57 条图谱自动生成的 SOP 的 calculator 步 inputs 写成了「参数名→参数说明」字典、
不含 expression，运行时 1ms 报「表达式不能为空」四步全灭（半圆型防波堤波浪力实踩）。
本例以半圆堤 SOP（96682af0ed26，公式为 JTS 154-2018 附录J J.0.1-1~J.0.1-12）为样本，
验证两件事：
1. 补全后的定义过校验器（规则 6：calculator 必须有 expression）；
2. 全参数直跑全部出数（与按规范公式独立复算的值一致）；题面只给 H/d/L 时，
   水位以上部分（η/αs/ps）正常出数、几何缺参如实报缺，
   且不再出现「表达式不能为空」（缺参口径 = 报缺 + 引导，不臆造）。
"""
import json
import math
import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, os.path.join(_ROOT, "services/angineer-core/src"))
sys.path.insert(0, os.path.join(_ROOT, "services/sop-core/src"))
sys.path.insert(0, os.path.join(_ROOT, "services/engtools/src"))

from angineer_core import ports  # noqa: E402
from angineer_core.sop_domain import load_domain_pack  # noqa: E402
from angineer_core.sop_runner import SopRunner  # noqa: E402
from sop_core.sop_validator import build_sop_model, validate_sop_data  # noqa: E402

_SOP_PATH = os.path.join(_ROOT, "data/platform/sops/json/96682af0ed26.json")


def _register_engtool_port():
    from engtools.BaseTool import ToolRegistry
    ports.register_agent_search(engtool_registry=lambda: ToolRegistry)


class HemicycleBreakwaterSopTests(unittest.TestCase):
    """半圆型防波堤波浪力 SOP：定义过校验 + 执行出数/报缺。"""

    @classmethod
    def setUpClass(cls):
        _register_engtool_port()
        with open(_SOP_PATH, encoding="utf-8") as f:
            cls.data = json.load(f)
        cls.sop = build_sop_model(cls.data)
        cls.step_names = {s.id: (s.name_zh or "") for s in cls.sop.steps}

    def _run(self, context):
        # llm_client=object()：缺参推荐的 LLM 兜底走「仅报缺」降级路径，测试不打网关
        runner = SopRunner(domain_hints=load_domain_pack("harbor"), llm_client=object())
        final = runner.run_sop(self.sop, dict(context))
        return runner, final

    def test_definition_passes_validator(self):
        """补全后的定义必须完全过校验（含规则 6 calculator expression）。"""
        self.assertEqual(validate_sop_data(self.data), [])

    def test_calculator_steps_all_carry_expression(self):
        for s in self.data["steps"]:
            ex = s.get("execution") or {}
            if ex.get("tool") == "calculator":
                expr = (ex.get("inputs") or {}).get("expression")
                self.assertTrue(isinstance(expr, str) and expr.strip(), f"{s['id']} 缺 expression")

    def test_full_inputs_compute_appendix_j_values(self):
        """全参数（含几何）→ 9 步全过，数值与 JTS 154-2018 附录J 公式独立复算一致。"""
        ctx = {
            "设计波高H": 2.8, "静水位水深h": 8.5, "波长L": 26,
            "基床上水深d1": 7.5, "作用点间水平距离Δl": 3.2,
            "计算点高度z": 4.0, "圆心角θ": 45, "底宽B": 9.0,
            "user_query": "半圆型防波堤波浪力计算",
        }
        runner, final = self._run(ctx)
        statuses = [r.status for r in runner.memory.history]
        self.assertEqual(statuses, ["success"] * 9, f"有步骤失败: {[(r.step_id, r.error) for r in runner.memory.history]}")

        H, d, L, d1, dl, z, th, B = 2.8, 8.5, 26.0, 7.5, 3.2, 4.0, 45.0, 9.0
        eta = 1.5 * H
        x = 4 * math.pi * d / L
        alpha_s = 0.6 + 0.5 * ((x / math.sinh(x)) ** 2)
        ps = alpha_s * 10.25 * H
        alpha_b = 1 - (d1 / d) * (1 - 1 / math.cosh(2 * math.pi * d / L))
        pb = alpha_b * ps
        lam = math.cos(math.radians(360 * dl / L)) ** 4  # λp=cos⁴(2πΔl/L)，按度展开
        pb2 = lam * pb
        p_theta = (pb2 + (ps - pb2) * z / d1) * math.cos(math.radians(th))
        pu = pb2 * B / 2

        self.assertEqual(final["波压力零点高度η"], 4.2)
        self.assertAlmostEqual(final["系数αs"], alpha_s, places=4)
        self.assertAlmostEqual(final["水位处波压力强度ps"], ps, places=3)
        self.assertAlmostEqual(final["系数αb"], alpha_b, places=4)
        self.assertAlmostEqual(final["底面波压力强度pb"], pb, places=3)
        self.assertAlmostEqual(final["相位修正系数λp"], lam, places=4)
        self.assertAlmostEqual(final["修正后底面波压力强度pb2"], pb2, places=3)
        self.assertAlmostEqual(final["角度修正后点压力强度pθ"], p_theta, places=3)
        self.assertAlmostEqual(final["底板波浪浮托力Pu"], pu, places=3)

    def test_partial_inputs_compute_and_report_missing(self):
        """题面只给 H/d/L：η/αs/ps 出数；几何参数如实报缺；无「表达式不能为空」。"""
        ctx = {"设计波高H": 2.8, "静水位水深h": 8.5, "波长L": 26, "user_query": "半圆堤"}
        runner, final = self._run(ctx)
        rec = {r.step_id: r for r in runner.memory.history}

        self.assertEqual(rec["step_1"].status, "success")
        self.assertEqual(rec["step_2"].status, "success")
        self.assertEqual(rec["step_3"].status, "success")
        self.assertEqual(final["波压力零点高度η"], 4.2)
        self.assertAlmostEqual(final["水位处波压力强度ps"], 17.4819, places=3)

        for sid in ("step_4", "step_5", "step_6", "step_7", "step_8", "step_9"):
            self.assertEqual(rec[sid].status, "failed", f"{sid} 应因缺参失败")

        # 关键回归：不得再出现「表达式不能为空」（那是定义残废的旧症状）
        errors = " ".join(str(r.error or "") for r in runner.memory.history)
        self.assertNotIn("表达式不能为空", errors)

        reported = {item["param"] for item in runner.missing_report}
        self.assertEqual(
            reported,
            {"基床上水深d1", "作用点间水平距离Δl", "计算点高度z", "圆心角θ", "底宽B"},
        )
        # 缺参不得给数值臆造（无 recommend 或显式标注仅报缺）
        for item in runner.missing_report:
            self.assertIn("不臆造", str(item.get("rationale") or ""))

    def test_step_bindings_and_result_snapshot(self):
        """参数绑定与结果标量快照（2026-10-16 面板展示绿步参数/值）：两条路径都要有。"""
        ctx = {"设计波高H": 2.8, "静水位水深h": 8.5, "波长L": 26, "user_query": "半圆堤"}
        runner, _ = self._run(ctx)

        # ① live 步骤回调携带 bindings/result
        infos = {}
        runner2 = SopRunner(domain_hints=load_domain_pack("harbor"), llm_client=object())
        runner2.run_sop(self.sop, dict(ctx), step_callback=lambda i: infos.setdefault(i["step_id"], i))
        self.assertEqual(infos["step_1"]["bindings"], {"设计波高H": 2.8})
        self.assertEqual(infos["step_1"]["result"], 4.2)
        # 失败步：已知值照给、缺失名记 None（前端渲染为「缺」）
        self.assertEqual(infos["step_4"]["bindings"].get("静水位水深h"), 8.5)
        self.assertIsNone(infos["step_4"]["bindings"].get("基床上水深d1"))
        self.assertIsNone(infos["step_4"]["result"])

        # ② 终态 trace（回放/历史路径）同样携带
        trace = SopRunner._build_sop_trace(runner, self.sop)
        by_id = {t["step_id"]: t for t in trace}
        self.assertEqual(by_id["step_1"]["bindings"], {"设计波高H": 2.8})
        self.assertEqual(by_id["step_1"]["result"], 4.2)
        self.assertEqual(by_id["step_3"]["result"], 17.481859)


class GeneratorPromptTests(unittest.TestCase):
    """生成提示词根因回归：calculator 步必须要求 expression、outputs 固定 result。"""

    def test_prompt_requires_expression(self):
        from sop_core.sop_path_generator import SOP_GENERATION_SYSTEM_PROMPT as p

        self.assertIn("expression", p)
        self.assertIn('"result"', p)
        # 旧 schema（参数名→变量说明）不得复现
        self.assertNotIn('"inputs": {"变量名": "变量说明"}', p)


if __name__ == "__main__":
    unittest.main()

"""Calculator 三角函数「度」口径回归（2026-10-13）。

规范公式 sin(γ) 中 γ 为度数（_clean_expression 会剥掉 ° 符号），
历史上 sp.sin 按弧度算：sin(15°)→sin(15rad)=0.65，Q2 通航宽度整链错值。
另锁：度数安全闸不得再以子串误杀 cos（'os' 关键字命中 'cos'）。
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/engtools/src")))

from engtools.CalculatorTool import Calculator


class TestCalculatorDegrees(unittest.TestCase):
    def setUp(self):
        self.calc = Calculator()

    def _run(self, expr, **vars_):
        return self.calc.run(expression=expr, variables=vars_ or None)

    def test_sin_degrees(self):
        self.assertAlmostEqual(self._run("sin(30)")["result"], 0.5, places=6)

    def test_cos_degrees_and_guard(self):
        # cos 曾被危险词表 'os' 子串误杀（表达式包含不允许的字符或操作）
        r = self._run("cos(60)")
        self.assertIsNone(r.get("error"))
        self.assertAlmostEqual(r["result"], 0.5, places=6)

    def test_tan_degrees(self):
        self.assertAlmostEqual(self._run("tan(45)")["result"], 1.0, places=6)

    def test_inverse_returns_degrees(self):
        self.assertAlmostEqual(self._run("asin(0.5)")["result"], 30.0, places=6)

    def test_norm_expression_degree_semantics(self):
        # 式(6.4.2-3)：A = n(L sinγ + B)，γ=7°、L=293、B=b=32.2、n=1.69
        r = self._run("n * (L * sin(g) + b)", n=1.69, L=293, g=7, b=32.2)
        self.assertAlmostEqual(r["result"], 1.69 * (293 * math.sin(math.radians(7)) + 32.2), places=4)

    def test_numeric_expression_tolerated(self):
        # 模型传参/黑板值可能是 JSON number（2026-10-13 实踩：表达式 4.5 报「表达式不能为空」）
        self.assertEqual(self._run(4.5)["result"], 4.5)
        self.assertEqual(self._run(0)["result"], 0)
        r = self.calc.run(expressions=[1.5, "1+1"])
        self.assertEqual(r["labeled_results"]["expr_1"], 1.5)

    def test_dangerous_keywords_still_blocked(self):
        for expr in ("import os", "__import__('os')", "eval('1+1')"):
            with self.subTest(expr=expr):
                self.assertIsNotNone(self._run(expr).get("error"))

    def test_power_operator(self):
        # 规范表达式用 ^ 表幂（sympy 原生按异或解析，_clean_expression 必须转 **）
        self.assertEqual(self._run("2^3")["result"], 8)

    def test_pi_char_and_compact_form(self):
        # 裸 π 字符 → pi；紧凑 2π → 2*pi（防被单位清理误删成 2）
        self.assertAlmostEqual(self._run("π * 2")["result"], math.pi * 2, places=6)
        self.assertAlmostEqual(self._run("2π * 3")["result"], 6 * math.pi, places=4)

    def test_hyperbolic_cth(self):
        # 规范壅高式：η = πH²/L · cth(2πd/L)（step_8 同款）
        r = self._run("pi * H^2 / L * cth(2 * pi * d / L)", H=2.5, L=45, d=14.5)
        expected = math.pi * 2.5 ** 2 / 45 * (math.cosh(2 * math.pi * 14.5 / 45) / math.sinh(2 * math.pi * 14.5 / 45))
        self.assertAlmostEqual(r["result"], expected, places=5)


if __name__ == "__main__":
    unittest.main()

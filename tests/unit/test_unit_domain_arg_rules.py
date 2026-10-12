"""
domain_arg_rules（领域参数规则应用器）回归测试。

对拍纪律：旧键逐键全等（2026-10-12 重构基线，采集自生产路径 _supplement_sop_args_from_query）；
新键（土质/状态/angle/Hnav/H_nav）为本次新增规则，独立断言。
无领域包时=通用行为（不注入任何领域参数）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.domain_arg_rules import supplement_args
from angineer_core.sop_domain import load_domain_pack

# (名称, 题面, required, 旧键期望)  —— 旧键期望=重构前生产行为快照
CASES = [
    ("Z4/回淤", "某工程备淤深度取0.4m，求通航水深", ["Z4"], {"Z4": "0.4m", "回淤条件": "有回淤", "h0": "0"}),
    ("K1顺浪", "码头受顺浪作用，波高H=2.5m", ["K1"], {"K1": "0.3", "掩护情况": "部分掩护", "h0": "0"}),
    ("K1横浪", "码头受横浪作用", ["K1"], {"K1": "0.5", "掩护情况": "部分掩护", "h0": "0"}),
    ("掩护开敞", "码头位于开敞海域", ["掩护情况"], {"掩护情况": "开敞水域", "h0": "0"}),
    ("单线航道", "某单线航道工程", ["船舶类型"], {"船舶类型": "单线航道", "h0": "0"}),
    ("双线航道", "某双线航道工程", ["船舶类型"], {"船舶类型": "双线航道", "h0": "0"}),
    ("夹角推算", "流向 N 45°，航道轴线方位 30°~60°", ["夹角"], {"夹角": "0.0", "h0": "0"}),
    ("d推算", "设计高水位 4.5 m，码头前沿底高程 -10.0 m", ["d"], {"h0": "0", "d": "14.5", "设计高水位": "4.5"}),
    ("h0默认", "一般工程条件", ["h0"], {"h0": "0"}),
    ("H4%提取", "设计波高 H4%=1.8m，求堤顶高程", ["H4%"], {"h0": "0", "H4%": "1.8"}),
    ("H提取", "一遇波高为2.2m", ["H"], {"h0": "0", "H": "2.2"}),
    ("L提取", "波长 L=45m", ["L"], {"h0": "0", "L": "45"}),
    ("水深d提取", "水深 d=12m", ["d"], {"h0": "0", "d": "12"}),
    ("上部结构h", "上部结构高度 h=3.0m", ["h"], {"h0": "0", "h": "3.0"}),
    ("吨级清洗", "50000吨级集装箱船", ["吨级"], {"h0": "0", "吨级": "50000"}),
    ("船型推断", "矿石运输，5万吨级", ["船型", "设计船型"], {"h0": "0", "船型": "散货船", "设计船型": "干散货船"}),
    ("底质清洗", "底质条件为海底淤泥", ["底质条件"], {"h0": "0", "底质条件": "淤泥", "土质": "淤泥"}),
    ("设计高水位", "设计高水位 4.5 m，底高程 -10.0 m", ["设计高水位"], {"h0": "0", "d": "14.5", "设计高水位": "4.5"}),
]

# 新规则断言（本次新增，行为独立锁定）
NEW_CASES = [
    ("Hnav乘潮多档取90~95%档", "题目提供乘潮水位：90%对应2.8m，95%对应2.5m", {"Hnav": "2.8", "H_nav": "2.8"}),
    ("Hnav设计低水位兜底", "设计低水位 0.5 m，其余条件略", {"Hnav": "0.5", "H_nav": "0.5"}),
    ("Hnav显式优先", "航道设计通航水位 1.2 m，乘潮水位 90%对应2.8m", {"Hnav": "1.2", "H_nav": "1.2"}),
    ("土质状态", "航道穿越淤泥质土，状态为松散", {"土质": "淤泥质土", "状态": "松散"}),
    ("转向角", "某航道转弯段，转向角 φ 为 45°，求转弯半径", {"angle": "45"}),
]


class TestDomainArgRulesPacked(unittest.TestCase):
    """启用 harbor 包：旧键逐键全等 + 新规则生效。"""

    @classmethod
    def setUpClass(cls):
        cls.pack = load_domain_pack("harbor")

    def test_legacy_keys_equivalence(self):
        for name, query, required, expected in CASES:
            with self.subTest(case=name):
                got = supplement_args(query, required, {}, self.pack)
                self.assertEqual(got, expected, f"{name} 对拍失败: {got}")

    def test_new_rules(self):
        for name, query, expected in NEW_CASES:
            with self.subTest(case=name):
                got = supplement_args(query, [], {}, self.pack)
                for key, value in expected.items():
                    self.assertEqual(got.get(key), value, f"{name}: {key} 期望 {value}，实得 {got.get(key)}")


class TestDomainArgRulesNoPack(unittest.TestCase):
    """无领域包：通用行为（不注入领域参数），仅通用清洗生效。"""

    def test_no_domain_args_injected(self):
        got = supplement_args("码头受顺浪作用，波高H=2.5m", ["K1", "H"], {}, None)
        self.assertIsNone(got.get("K1"))
        self.assertIsNone(got.get("掩护情况"))
        self.assertIsNone(got.get("h0"))


if __name__ == "__main__":
    unittest.main()

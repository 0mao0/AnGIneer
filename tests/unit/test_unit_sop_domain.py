"""
sop_domain（SOP 领域知识包加载器）单元测试。
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.sop_domain import (
    EMPTY_HINTS,
    DomainHints,
    load_domain_pack,
    load_domain_pack_from_env,
)


class TestLoadDomainPack(unittest.TestCase):
    """测试 load_domain_pack 各路径。"""

    def test_empty_ref_returns_empty(self):
        """空引用返回空包。"""
        self.assertFalse(load_domain_pack(None))
        self.assertFalse(load_domain_pack(""))
        self.assertFalse(load_domain_pack("   "))

    def test_builtin_harbor_loads(self):
        """内置 harbor 包可加载且三个字段齐备。"""
        hints = load_domain_pack("harbor")
        self.assertTrue(hints)
        self.assertIn("H", hints.param_descriptions)
        self.assertEqual(hints.output_aliases["dwl_basic"][0], "design_high_water_level")
        self.assertIn("K1", hints.calculator_hint)

    def test_builtin_unknown_name_degrades_to_empty(self):
        """未知内置名按空包降级，不抛异常。"""
        hints = load_domain_pack("no_such_pack")
        self.assertEqual(hints, EMPTY_HINTS)

    def test_path_pack_loads(self):
        """按文件路径加载自定义包。"""
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        ) as f:
            json.dump(
                {
                    "param_descriptions": {"X": "测试参数"},
                    "output_aliases": {"k": ["alias_a"]},
                    "calculator_hint": "- For X: use 1",
                },
                f,
            )
            path = f.name
        try:
            hints = load_domain_pack(path)
            self.assertEqual(hints.param_descriptions, {"X": "测试参数"})
            self.assertEqual(hints.output_aliases, {"k": ["alias_a"]})
            self.assertEqual(hints.calculator_hint, "- For X: use 1")
        finally:
            os.unlink(path)

    def test_missing_file_degrades_to_empty(self):
        """文件不存在按空包降级。"""
        hints = load_domain_pack("Z:/definitely/not/here.json")
        self.assertEqual(hints, EMPTY_HINTS)

    def test_malformed_json_degrades_to_empty(self):
        """JSON 损坏按空包降级。"""
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("{not valid json")
            path = f.name
        try:
            hints = load_domain_pack(path)
            self.assertEqual(hints, EMPTY_HINTS)
        finally:
            os.unlink(path)

    def test_result_cached_per_ref(self):
        """同一引用二次加载命中缓存（同一对象）。"""
        first = load_domain_pack("harbor")
        second = load_domain_pack("harbor")
        self.assertIs(first, second)


class TestLoadDomainPackFromEnv(unittest.TestCase):
    """测试环境变量入口。"""

    def test_env_set(self):
        with patch.dict(os.environ, {"ANGINEER_SOP_DOMAIN_PACK": "harbor"}):
            hints = load_domain_pack_from_env()
            self.assertTrue(hints.param_descriptions)

    def test_env_unset_returns_empty(self):
        env = {k: v for k, v in os.environ.items() if k != "ANGINEER_SOP_DOMAIN_PACK"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(load_domain_pack_from_env(), EMPTY_HINTS)


class TestDomainHintsDataclass(unittest.TestCase):
    """测试 DomainHints 真值语义。"""

    def test_falsy_when_all_empty(self):
        self.assertFalse(DomainHints())

    def test_truthy_with_any_field(self):
        self.assertTrue(DomainHints(calculator_hint="x"))
        self.assertTrue(DomainHints(param_descriptions={"a": "b"}))
        self.assertTrue(DomainHints(output_aliases={"a": ["b"]}))


if __name__ == "__main__":
    unittest.main()

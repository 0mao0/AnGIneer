"""JSON 提取/修复/校验（包内回归）。"""

import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SRC = TESTS_DIR.parent / "src"
for p in (str(SRC), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from ai_inference.llm_response_parser import (
    ParseError,
    extract_json_from_text,
    parse_and_validate,
    safe_extract_dict,
    safe_extract_string,
)
from pydantic import BaseModel


class _Schema(BaseModel):
    name: str = "default"
    value: int = 0


class TestExtractJson(unittest.TestCase):
    def test_fence_json(self):
        text = '```json\n{"name": "x"}\n```'
        self.assertEqual(extract_json_from_text(text), {"name": "x"})

    def test_bare_json(self):
        self.assertEqual(extract_json_from_text('{"a": 1}'), {"a": 1})

    def test_salvage_trailing_comma(self):
        self.assertEqual(extract_json_from_text('{"a": 1,}'), {"a": 1})

    def test_strict_rejects_malformed(self):
        with self.assertRaises(ParseError):
            extract_json_from_text('{"a": 1,', strict=True)

    def test_empty_raises(self):
        with self.assertRaises(ParseError):
            extract_json_from_text("")


class TestParseAndValidate(unittest.TestCase):
    def test_valid_schema(self):
        result = parse_and_validate('{"name": "x", "value": 3}', _Schema)
        self.assertEqual(result.name, "x")
        self.assertEqual(result.value, 3)

    def test_defaults_on_missing_field(self):
        result = parse_and_validate('{"name": "x"}', _Schema)
        self.assertEqual(result.name, "x")
        self.assertEqual(result.value, 0)


class TestSafeExtract(unittest.TestCase):
    def test_safe_extract_string_default(self):
        self.assertEqual(safe_extract_string("not json", "key", "fallback"), "fallback")

    def test_safe_extract_dict_default(self):
        self.assertEqual(safe_extract_dict("not json", "key", {"d": 1}), {"d": 1})


if __name__ == "__main__":
    unittest.main()

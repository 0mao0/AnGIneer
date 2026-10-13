"""
canonical_table_read（读表判读通道，方案 B）单元测试。

选表确定性 + 取值单次 LLM 抽取；覆盖：取值成功 / 无编号候选 / LLM 读不到 / 文件解析失败。
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.canonical_table_lookup import canonical_table_read, _render_table_text


_MATRIX_TABLE = {
    "headers": ["风力", "横风≤7级", "横风≤7级"],
    "rows": [["横流V(m/s)", "V≤0.10", "0.75 < V≤1.00"], ["n", "1.81", "1.45"], ["γ(°)", "3", "14"]],
    "context": "船舶漂移倍数 n 和风、流压偏角γ值表6.4.2-1",
    "doc_id": "doc-x",
}


def _llm_result(payload_text):
    return MagicMock(text=payload_text)


class TestCanonicalTableRead(unittest.TestCase):
    def _run(self, llm_text, candidates=None):
        provider = MagicMock(return_value=candidates if candidates is not None else [_MATRIX_TABLE])
        with patch("angineer_core.ports.get_table_blocks_provider", return_value=provider), \
             patch("ai_inference.llm_client.get_llm_client", return_value=MagicMock()), \
             patch("ai_inference.llm_client.chat_result_guarded", return_value=_llm_result(llm_text)):
            return canonical_table_read(
                table_name="表6.4.2-1",
                query_conditions={"风力": "横风≤7级", "横流V(m/s)": "0.78"},
                target_column="n；γ(°)",
                library_id="default",
                doc_ids=["doc-x"],
            )

    def test_value_extracted_with_cell_ref(self):
        out = self._run('{"value": {"n": 1.45, "γ(°)": 14}, "cell": "n行×(0.75,1.00]列", "quote": "0.75 < V≤1.00 → 1.45"}')
        self.assertEqual(out["result"], {"n": 1.45, "γ(°)": 14})
        self.assertEqual(out["_method"], "llm_read")
        self.assertIn("1.45", str(out["_read_quote"]))
        self.assertIn("表6.4.2-1", out["_table_context"])

    def test_no_matching_number_reports_missing(self):
        out = self._run('{"value": null}')
        self.assertIn("未能得到", out["error"])

    def test_unresolved_condition_blocks_read(self):
        # 条件含未解析 ${船舶航速}：必须拦截，不许 LLM 自行挑档（2026-10-13 编造通道实踩）
        with patch("angineer_core.canonical_table_lookup._resolve_doc_ids_by_file_name", return_value=["doc-x"]), \
             patch("angineer_core.ports.get_table_blocks_provider", side_effect=AssertionError("不应触达 provider")):
            out = canonical_table_read(
                table_name="表6.4.2-2",
                query_conditions={"船型": "集装箱船", "航速(kn)": "${船舶航速}"},
                target_column="c的系数",
                library_id="default",
            )
        self.assertIn("读表缺参", out["error"])
        self.assertEqual(out["missing_params"], ["船舶航速"])

    def test_no_candidate_with_number(self):
        no_num = dict(_MATRIX_TABLE, context="无关表格 A.0.9")
        out = self._run('{"value": 1}', candidates=[no_num])
        self.assertIn("均无编号", out["error"])

    def test_file_name_unresolvable(self):
        with patch("angineer_core.canonical_table_lookup._resolve_doc_ids_by_file_name", return_value=None):
            out = canonical_table_read(
                table_name="表6.4.2-1", query_conditions={}, target_column="n",
                library_id="default", doc_ids=None, file_name="不存在的规范",
            )
        self.assertIn("未找到知识库文件", out["error"])

    def test_render_marks_row_labels(self):
        text = _render_table_text(["风力", "横风≤7级"], [["n", "1.81", "1.45"]])
        self.assertIn("[n] n | 1.81 | 1.45", text)


if __name__ == "__main__":
    unittest.main()

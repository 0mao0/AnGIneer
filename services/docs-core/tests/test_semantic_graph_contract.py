"""语义图契约回归测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from docs_core.ingest.normalize.formula_semantics import build_formula_representations
from docs_core.ingest.normalize.structure_builder import build_structured_from_rawfiles


class SemanticGraphContractTests(unittest.TestCase):
    """覆盖公式语义契约与结构化输出字段。"""

    def test_build_formula_representations_returns_formula_contract(self) -> None:
        """公式语义结果应返回稳定的契约字段与参数计数。"""
        result = build_formula_representations(
            formula_text="q=(γzμsAω^2)/g",
            explanation_lines=[
                "式中 γ——风、流压缩角（°）；z——高度系数；μs——体型系数。",
            ],
            use_llm=False,
        )

        self.assertEqual(result["formula_text"], "q=(γzμsAω^2)/g")
        self.assertIn("formula_number", result)
        self.assertIn("formula_params", result)
        self.assertIn("formula_param_count", result)
        self.assertIn("formula_summary", result)
        self.assertIn("llm_status", result)
        self.assertIn("explanation_lines", result)
        self.assertEqual(result["llm_status"], "disabled")
        self.assertEqual(result["formula_param_count"], len(result["formula_params"]))
        self.assertGreaterEqual(result["formula_param_count"], 3)

    def test_build_structured_from_rawfiles_embeds_formula_semantics(self) -> None:
        """结构化图中的公式节点与索引行应携带公式语义契约。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            parsed_dir = Path(temp_dir)
            content_list_path = parsed_dir / "content_list_v2.json"
            content_list_path.write_text(
                json.dumps(
                    [
                        [
                            {
                                "type": "title",
                                "bbox": [0, 0, 100, 20],
                                "content": {
                                    "title_content": [{"content": "1 总则"}],
                                    "level": 1,
                                },
                            },
                            {
                                "type": "equation_interline",
                                "bbox": [0, 30, 100, 50],
                                "content": {
                                    "math_content": "q=(γzμsAω^2)/g",
                                },
                            },
                            {
                                "type": "paragraph",
                                "bbox": [0, 55, 100, 75],
                                "content": {
                                    "paragraph_content": [
                                        {
                                            "content": "式中 γ——风、流压缩角（°）；z——高度系数；μs——体型系数。"
                                        }
                                    ]
                                },
                            },
                        ]
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = build_structured_from_rawfiles(
                parsed_dir=parsed_dir,
                doc_id="doc-1",
                doc_name="demo.pdf",
                options={"use_llm": False},
            )

        equation_node = next(node for node in result.nodes if node["block_type"] == "equation_interline")
        equation_index_row = next(
            row for row in result.index_rows if row["block_type"] == "equation_interline"
        )

        self.assertEqual(equation_node["formula_param_count"], 3)
        self.assertEqual(equation_node["formula_llm_status"], "disabled")
        self.assertEqual(len(equation_node["formula_params"]), 3)
        self.assertIn("γ", equation_node["formula_summary"])

        self.assertEqual(equation_index_row["formula_param_count"], 3)
        self.assertEqual(equation_index_row["formula_llm_status"], "disabled")
        self.assertEqual(len(equation_index_row["formula_params"]), 3)
        self.assertIn("μs", equation_index_row["formula_summary"])


if __name__ == "__main__":
    unittest.main()

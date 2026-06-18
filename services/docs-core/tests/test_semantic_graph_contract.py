"""语义图契约回归测试。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

DOCS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(DOCS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(DOCS_CORE_SRC))

import docs_core.ingest.normalize as normalize_exports
from docs_core.ingest.normalize.formula_semantics import build_formula_representations
from docs_core.ingest.normalize.structure_builder import build_structured_from_rawfiles


class SemanticGraphContractTests(unittest.TestCase):
    """覆盖公式语义契约与结构化输出字段。"""

    def test_build_formula_representations_returns_formula_contract(self) -> None:
        """公式语义结果应返回稳定的契约字段与参数计数。"""
        result = build_formula_representations(
            formula_text="q=(γzμsAω^2)/g",
            explanation_lines=[
                "式中 γ——风、流压缩角（°），采用表6.4.2-2中的数值；z——高度系数；μs——体型系数。",
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
        self.assertEqual(
            set(result.keys()),
            {
                "formula_text",
                "formula_number",
                "formula_params",
                "formula_param_count",
                "formula_summary",
                "llm_status",
                "explanation_lines",
            },
        )

        gamma_param = next(param for param in result["formula_params"] if param["symbol"] == "γ")
        self.assertEqual(
            set(gamma_param.keys()),
            {
                "symbol",
                "description",
                "unit",
                "reference_hint",
                "confidence",
                "extracted_by",
            },
        )
        self.assertEqual(gamma_param["description"], "风、流压缩角（°），采用表6.4.2-2中的数值")
        self.assertEqual(gamma_param["unit"], "°")
        self.assertEqual(gamma_param["reference_hint"], "采用表6.4.2-2中的数值")
        self.assertGreaterEqual(gamma_param["confidence"], 0.9)
        self.assertEqual(gamma_param["extracted_by"], "rule")

    def test_build_structured_from_rawfiles_embeds_formula_semantics(self) -> None:
        """结构化图与落盘行中的公式节点应携带完整语义契约。"""
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
                                            "content": "式中 γ——风、流压缩角（°），采用表6.4.2-2中的数值；z——高度系数；μs——体型系数。"
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
        equation_storage_row = next(
            row for row in result.stats["derived_rows"] if row["block_uid"] == equation_node["block_uid"]
        )

        self.assertEqual(equation_node["formula_param_count"], 3)
        self.assertEqual(equation_node["formula_llm_status"], "disabled")
        self.assertEqual(len(equation_node["formula_params"]), 3)
        self.assertIn("γ", equation_node["formula_summary"])
        self.assertEqual(
            equation_node["formula_explanation_lines"],
            ["式中 γ——风、流压缩角（°），采用表6.4.2-2中的数值", "z——高度系数", "μs——体型系数。"],
        )

        self.assertEqual(equation_index_row["formula_param_count"], 3)
        self.assertEqual(equation_index_row["formula_llm_status"], "disabled")
        self.assertEqual(len(equation_index_row["formula_params"]), 3)
        self.assertIn("μs", equation_index_row["formula_summary"])
        self.assertEqual(
            equation_index_row["formula_explanation_lines"],
            equation_node["formula_explanation_lines"],
        )

        self.assertEqual(equation_storage_row["math_content"], "q=(γzμsAω^2)/g")
        self.assertEqual(equation_storage_row["formula_number"], None)
        self.assertEqual(equation_storage_row["formula_param_count"], 3)
        self.assertEqual(equation_storage_row["formula_llm_status"], "disabled")
        self.assertEqual(len(equation_storage_row["formula_params"]), 3)
        self.assertIn("γ", equation_storage_row["formula_summary"])
        self.assertEqual(
            equation_storage_row["formula_explanation_lines"],
            ["式中 γ——风、流压缩角（°），采用表6.4.2-2中的数值", "z——高度系数", "μs——体型系数。"],
        )
        gamma_storage_param = next(
            param for param in equation_storage_row["formula_params"] if param["symbol"] == "γ"
        )
        self.assertEqual(gamma_storage_param["unit"], "°")
        self.assertEqual(gamma_storage_param["reference_hint"], "采用表6.4.2-2中的数值")
        self.assertEqual(gamma_storage_param["extracted_by"], "rule")

    def test_normalize_package_root_re_exports_semantic_contracts(self) -> None:
        """normalize 包根应导出公式契约与结构化入口。"""
        self.assertEqual(
            normalize_exports.FormulaParamContract.__module__,
            "docs_core.ingest.normalize.formula_semantics",
        )
        self.assertEqual(
            normalize_exports.FormulaSemanticsContract.__module__,
            "docs_core.ingest.normalize.formula_semantics",
        )
        self.assertIs(normalize_exports.build_formula_representations, build_formula_representations)
        self.assertIs(normalize_exports.build_structured_from_rawfiles, build_structured_from_rawfiles)


if __name__ == "__main__":
    unittest.main()

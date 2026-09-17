"""A 层解析回归（evals_core.parse_regression + scripts/run_parse_regression.py 入档模式）。

覆盖方案 docs/plan-parse-regression-entry.md §4.4 的 Δ 规则与 §4.3 的 meta 契约：
页集合不同就不出 Δ、子集按交集重算（非官方口径）、指标扁平化与官方产物命名对齐。
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "evals-core" / "src", ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evals_core import parse_regression as pr  # noqa: E402


def _official_dir(root: Path, pages, text_edits, tables=None) -> Path:
    """造一份官方产物目录（只用得到逐页/逐表两个文件 + metric_result）。"""
    out = Path(root) / "official"
    out.mkdir(parents=True, exist_ok=True)
    (out / "predictions_quick_match_text_block_per_page_edit.json").write_text(
        json.dumps({f"{p}.png": v for p, v in zip(pages, text_edits)}), encoding="utf-8")
    if tables:
        (out / "predictions_quick_match_table_per_table_TEDS.json").write_text(
            json.dumps({k: {"TEDS": v, "TEDS_structure_only": v} for k, v in tables.items()}),
            encoding="utf-8")
    # 层级照官方真实产物（<模块>→all→<指标>→ALL_page_avg/all）：2026-09-17 从 full_html_result 实测
    (out / "predictions_quick_match_metric_result.json").write_text(json.dumps({
        "text_block": {"all": {"Edit_dist": {"ALL_page_avg": sum(text_edits) / len(text_edits) if text_edits else None}}},
        "table": {"all": {"TEDS": {"all": 0.9}, "TEDS_structure_only": {"all": 0.95},
                          "Edit_dist": {"ALL_page_avg": 0.05}}},
        "display_formula": {"all": {"Edit_dist": {"ALL_page_avg": 0.11}, "CDM": {"all": 0.94}}},
        "reading_order": {"all": {"Edit_dist": {"ALL_page_avg": 0.13}}},
    }), encoding="utf-8")
    return out


def _structure_result(pages) -> dict:
    return {"meta": {"pages_evaluated": len(pages), "pred_source": "chain"},
            "overall": {"block_recall": 0.88, "teds": 0.91, "text_similarity": 0.74,
                        "pred_used_ratio": 0.9, "text_similarity_matched": 0.85,
                        "formula_similarity": 0.67, "order_adjacent_accuracy": 0.97,
                        "order_kendall_tau": 0.92},
            "pages": [{"page_id": f"{p}.png"} for p in pages]}


class TestFlatten(unittest.TestCase):
    def test_official_metric_keys(self):
        # 取 20260913 离线基线（full_html_result）的真实数值与层级，防止夹具形状臆造
        metrics = pr.flatten_official(json.loads(
            '{"text_block": {"all": {"Edit_dist": {"ALL_page_avg": 0.07246560755417171,'
            ' "edit_whole": 0.04997995256063882}}, "group": {"sample_count": {}}, "page": {}},'
            ' "table": {"all": {"TEDS": {"all": 0.9154785609846913},'
            ' "TEDS_structure_only": {"all": 0.9324165248555886},'
            ' "Edit_dist": {"ALL_page_avg": 0.04878683518910947}}},'
            ' "display_formula": {"all": {"Edit_dist": {"ALL_page_avg": 0.11159129296746055},'
            ' "CDM": {"all": 0.9508798076923077}}},'
            ' "reading_order": {"all": {"Edit_dist": {"ALL_page_avg": 0.1348579195963533}}},'
            ' "match_debug": {"page_count": 200}}'))
        self.assertAlmostEqual(metrics["text_edit"], 0.07246560755417171)
        self.assertAlmostEqual(metrics["table_teds"], 0.9154785609846913)
        self.assertAlmostEqual(metrics["table_edit"], 0.04878683518910947)
        self.assertAlmostEqual(metrics["formula_cdm"], 0.9508798076923077)
        self.assertAlmostEqual(metrics["order_edit"], 0.1348579195963533)

    def test_missing_module_yields_none_not_zero(self):
        metrics = pr.flatten_official({"text_block": {}})
        self.assertIsNone(metrics["text_edit"])
        self.assertIsNone(metrics["table_teds"])

    def test_structure_metrics_from_overall(self):
        metrics = pr.flatten_structure(_structure_result(["a", "b"]))
        self.assertAlmostEqual(metrics["block_recall"], 0.88)
        self.assertAlmostEqual(metrics["order_kendall_tau"], 0.92)
        self.assertNotIn("text_edit", metrics)    # A② 不产官方口径的键（稀疏，别臆造 0）


class TestPageSets(unittest.TestCase):
    def test_official_page_set_strips_table_index_and_ext(self):
        with tempfile.TemporaryDirectory() as td:
            pages = ["p1", "p2"]
            out = _official_dir(td, pages, [0.1, 0.2],
                                tables={"p1.png_[0]": 0.9, "p1.png_[1]": 0.8, "p2.png_[0]": 0.7})
            self.assertEqual(pr.official_page_set(out), {"p1", "p2"})

    def test_structure_page_set_and_predict_state(self):
        self.assertEqual(pr.structure_page_set(_structure_result(["a", "b"])), {"a", "b"})
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            state.write_text(json.dumps({"a": {"status": "done"}, "b": {"status": "failed"}}), encoding="utf-8")
            self.assertEqual(pr.predict_page_set(state), {"a"})

    def test_relation_equal_subset_underscore(self):
        equal = pr.page_set_relation({"a", "b"}, {"a", "b"})
        self.assertTrue(equal["equal"])
        self.assertEqual(equal["intersection"], 2)
        sub = pr.page_set_relation({"a"}, {"a", "b", "c"})
        self.assertTrue(sub["subset"])
        self.assertFalse(sub["equal"])
        self.assertEqual(sub["base_only"], ["b", "c"])
        self.assertEqual(sub["intersection"], 1)

    def test_page_ids_hash_is_order_insensitive(self):
        self.assertEqual(pr.page_ids_hash(["b", "a"]), pr.page_ids_hash(["a", "b"]))
        self.assertEqual(len(pr.page_ids_hash(["a"])), 12)


class TestCompare(unittest.TestCase):
    def test_delta_and_direction(self):
        rows = {r["metric"]: r for r in pr.compare({"text_edit": 0.06, "table_teds": 0.93},
                                                   {"text_edit": 0.07, "table_teds": 0.92})}
        self.assertAlmostEqual(rows["text_edit"]["delta"], -0.01)
        self.assertFalse(rows["text_edit"]["higher_is_better"])   # edit 越小越好
        self.assertTrue(rows["table_teds"]["higher_is_better"])
        self.assertEqual(pr.fmt_delta(rows["text_edit"]), "-1.00pp ↓")        # edit 降 = 变好，无 ⚠
        self.assertEqual(pr.fmt_delta(rows["table_teds"]), "+1.00pp ↑")      # TEDS 升 = 变好
        worse = {"label": "x", "metric": "text_edit", "cur": 0.08, "base": 0.07, "delta": 0.01,
                 "higher_is_better": False}
        self.assertEqual(pr.fmt_delta(worse), "+1.00pp ↑ ⚠")                 # edit 升 = 回归，标 ⚠

    def test_missing_side_yields_no_delta(self):
        rows = pr.compare({"block_recall": 0.88}, {})
        self.assertIsNone(rows[0]["delta"])
        self.assertEqual(pr.fmt_delta(rows[0]), "—")


class TestRecomputeByIntersection(unittest.TestCase):
    def test_mean_over_subset_matches_subset_run(self):
        with tempfile.TemporaryDirectory() as td:
            out = _official_dir(td, ["p1", "p2", "p3"], [0.1, 0.2, 0.3],
                                tables={"p1.png_[0]": 1.0, "p3.png_[0]": 0.5})
            recomputed = pr.recompute_official_by_intersection(out, {"p1", "p3"})
            self.assertAlmostEqual(recomputed["text_edit"], 0.2)      # (0.1+0.3)/2
            self.assertAlmostEqual(recomputed["table_teds"], 0.75)    # (1.0+0.5)/2
            self.assertIsNone(recomputed["formula_edit"])             # 无逐页产物 → None，不臆造

    def test_pages_outside_subset_are_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            out = _official_dir(td, ["p1", "p2"], [0.1, 0.9])
            self.assertAlmostEqual(pr.recompute_official_by_intersection(out, {"p1"})["text_edit"], 0.1)


class TestBaselineResolution(unittest.TestCase):
    def test_pointer_run_id_and_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "20260914-0930").mkdir()
            pr.write_pointer(root, "baseline.json", {"dir": "20260914-0930"})
            self.assertEqual(pr.resolve_baseline(root, "baseline"), root / "20260914-0930")
            self.assertEqual(pr.resolve_baseline(root, "20260914-0930"), root / "20260914-0930")
            self.assertIsNone(pr.resolve_baseline(root, "none"))
            self.assertIsNone(pr.resolve_baseline(root, "latest"))   # 指针不存在 → 无基线，不报错


class TestImportArchiveEndToEnd(unittest.TestCase):
    """入档模式端到端：meta 契约完整性 + summary 可读 + 官方产物原样拷入。"""

    def _run_import(self, td: Path):
        spec = importlib.util.spec_from_file_location("run_parse_regression",
                                                      ROOT / "scripts" / "run_parse_regression.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        official = _official_dir(td, ["p1", "p2"], [0.1, 0.2])
        chain = Path(td) / "chain.json"
        chain.write_text(json.dumps(_structure_result(["p1", "p2"])), encoding="utf-8")
        out_root = Path(td) / "arch"
        old_argv = sys.argv
        sys.argv = ["run_parse_regression.py", "--import-official", str(official),
                    "--import-chain", str(chain), "--out-root", str(out_root),
                    "--tag", "baseline-20260913", "--note", "离线重投影"]
        try:
            rc = module.main()
        finally:
            sys.argv = old_argv
        run_dirs = [p for p in out_root.iterdir() if (p / "meta.json").is_file()]
        self.assertEqual(len(run_dirs), 1)
        return rc, run_dirs[0]

    def test_meta_contract_and_summary(self):
        with tempfile.TemporaryDirectory() as td:
            rc, run_dir = self._run_import(Path(td))
            self.assertEqual(rc, 0)
            meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
            for field in ("run_id", "ts", "kind", "page_ids", "page_ids_hash", "pages_scored",
                          "stages", "environment", "skipped", "sources"):
                self.assertIn(field, meta, field)
            self.assertEqual(meta["kind"], "offline-reprojection")
            self.assertEqual(meta["page_ids"], ["p1", "p2"])
            self.assertEqual(len(meta["skipped"]), 3)          # 三步都写明未跑，不静默
            self.assertIn("source_prep", meta["stages"])
            summary = (run_dir / "summary.md").read_text(encoding="utf-8")
            self.assertIn("离线重投影", summary)
            self.assertIn("A① 官方 markdown 口径", summary)
            self.assertIn("A② 结构层口径", summary)
            self.assertIn("0.1500", summary)                    # 官方表按 metric_result 渲染：text_edit (0.1+0.2)/2
            self.assertTrue((run_dir / "official" / "predictions_quick_match_metric_result.json").is_file())


if __name__ == "__main__":
    unittest.main()

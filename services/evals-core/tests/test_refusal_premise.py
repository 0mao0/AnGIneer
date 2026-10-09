"""拒答前提对账单测：前提解析、两种前提的违规判定、降级与渲染。

背景见 docs/report-refusal-premise-drift-20261009.md：6 道拒答题的源论文在语料扩充后
入库，标注静默过期 18 天——本模块把「前提仍成立」做成断言。造假数据源即可，不碰真实库。
"""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
P = os.path.join(ROOT, "services", "evals-core", "src")
if P not in sys.path:
    sys.path.insert(0, P)

from evals_core.nightly import refusal_premise as rp  # noqa: E402


class _FakeSources:
    def __init__(self, items, docs=None, keywords=None, boom=False):
        self._items = items
        self._docs = docs or {}      # (library, paper) -> present_name 或 None
        self._keywords = keywords or set()  # {(library, term)}
        self._boom = boom
        self.doc_calls = []

    def list_refusal_items(self):
        return list(self._items)

    def doc_present(self, library_id, doc):
        if self._boom:
            raise RuntimeError("store unavailable")
        self.doc_calls.append((library_id, doc))
        return self._docs.get((library_id, rp._paper_id(doc) or doc))

    def keyword_present(self, library_id, term):
        if self._boom:
            raise RuntimeError("store unavailable")
        return (library_id, term) in self._keywords


def _item(qid="refusal-x", dataset="ds", library="lib-a", tags=None, gold=None):
    return {"dataset_id": dataset, "question_id": qid, "library_id": library,
            "tags": tags if tags is not None else ["text", "extractive", "2412.18501v3", "refusal"],
            "gold": gold if gold is not None else {"refusal_expected": True}}


class PremiseResolveTests(unittest.TestCase):
    def test_arxiv_tag_derives_doc_absent(self):
        got = rp.resolve_premises({"refusal_expected": True}, ["text", "extractive", "2412.18501v3", "refusal"])
        self.assertEqual(got, [{"kind": "doc_absent", "doc": "2412.18501"}])

    def test_explicit_premise_wins_over_tags(self):
        gold = {"refusal_expected": True,
                "premise": {"kind": "keyword_zero_hit", "terms": ["引航锚地"]}}
        got = rp.resolve_premises(gold, ["doc-89bc80c3", "锚地", "分类", "refusal"])
        self.assertEqual(got, [{"kind": "keyword_zero_hit", "terms": ["引航锚地"]}])

    def test_explicit_premise_list_supported(self):
        gold = {"premise": [{"kind": "doc_absent", "doc": "doc-89bc80c3"},
                            {"kind": "keyword_zero_hit", "terms": ["给水排水"]}]}
        self.assertEqual(len(rp.resolve_premises(gold, [])), 2)

    def test_no_premise_returns_empty(self):
        self.assertEqual(rp.resolve_premises({"refusal_expected": True}, ["doc-89bc80c3", "锚地"]), [])

    def test_paper_id_strips_version_and_suffix(self):
        self.assertEqual(rp._paper_id("2404.19707v4.pdf"), "2404.19707")
        self.assertEqual(rp._paper_id("2412.18501v3"), "2412.18501")
        self.assertEqual(rp._paper_id("not-a-paper"), "")


class RunCheckTests(unittest.TestCase):
    def test_clean_premises_ok(self):
        src = _FakeSources([_item()])
        res = rp.run_check(src)
        self.assertEqual(res["severity"], "ok")
        self.assertEqual(res["checked"], 1)
        self.assertEqual(res["violations"], [])
        self.assertEqual(res["by_kind"], {"doc_absent": 1})

    def test_doc_back_in_library_is_violation(self):
        src = _FakeSources([_item()], docs={("lib-a", "2412.18501"): "2412.18501v3.pdf"})
        res = rp.run_check(src)
        self.assertEqual(res["severity"], "warn")
        self.assertEqual(len(res["violations"]), 1)
        self.assertIn("源文档已入库", res["violations"][0]["detail"])
        self.assertIn("2412.18501v3.pdf", res["violations"][0]["detail"])

    def test_keyword_hit_is_violation(self):
        item = _item(tags=["doc-x", "refusal"],
                     gold={"refusal_expected": True,
                           "premise": {"kind": "keyword_zero_hit", "terms": ["引航锚地"]}})
        res = rp.run_check(_FakeSources([item], keywords={("lib-a", "引航锚地")}))
        self.assertEqual(res["severity"], "warn")
        self.assertIn("前提词「引航锚地」", res["violations"][0]["detail"])

    def test_unknown_premise_reported_not_violation(self):
        item = _item(tags=["doc-89bc80c3", "refusal"])  # 无 arXiv 号、无显式 premise
        res = rp.run_check(_FakeSources([item]))
        self.assertEqual(res["checked"], 0)
        self.assertEqual(len(res["unknown"]), 1)
        self.assertEqual(res["violations"], [])
        self.assertEqual(res["severity"], "warn")  # 全无前提可核=元数据缺了，要看得见

    def test_mixed_unknown_keeps_ok(self):
        res = rp.run_check(_FakeSources([_item(), _item(qid="q2", tags=["doc-x", "refusal"])]))
        self.assertEqual(res["severity"], "ok")
        self.assertEqual(res["checked"], 1)
        self.assertEqual(len(res["unknown"]), 1)

    def test_same_doc_checked_once_per_library(self):
        src = _FakeSources([_item(qid="q1"), _item(qid="q2")])
        rp.run_check(src)
        self.assertEqual(len(src.doc_calls), 1)  # memo 去重：同库同论文只查一次

    def test_storage_error_degrades_to_error(self):
        res = rp.run_check(_FakeSources([_item()], boom=True))
        self.assertEqual(res["severity"], "error")
        self.assertIn("存储不可访问", res["error"])
        self.assertEqual(res["violations"], [])


class RenderTests(unittest.TestCase):
    def test_ok_line_lists_kinds(self):
        line = rp.render_line({"severity": "ok", "checked": 33, "violations": [],
                               "unknown": [], "by_kind": {"doc_absent": 33}})
        self.assertIn("ok", line)
        self.assertIn("核 33 题", line)
        self.assertIn("doc_absent 33", line)

    def test_warn_line_names_first_violations(self):
        res = {"severity": "warn", "checked": 39, "unknown": [],
               "by_kind": {"doc_absent": 39},
               "violations": [{"question_id": f"refusal-{i}", "dataset_id": "ds",
                               "detail": "源文档已入库（x.pdf）", "premise": {}} for i in range(4)]}
        line = rp.render_line(res)
        self.assertIn("4 题前提失效", line)
        self.assertIn("refusal-0", line)

    def test_error_line_shows_reason(self):
        line = rp.render_line({"severity": "error", "checked": 0, "violations": [],
                               "unknown": [], "by_kind": {}, "error": "存储不可访问: X"})
        self.assertIn("未完成", line)

    def test_render_detail_lists_violations(self):
        res = {"severity": "warn", "checked": 1, "unknown": [{"dataset_id": "ds", "question_id": "q9"}],
               "by_kind": {"doc_absent": 1},
               "violations": [{"dataset_id": "ds", "question_id": "q1", "detail": "源文档已入库（a.pdf）",
                               "premise": {"kind": "doc_absent", "doc": "2404.19707"}}]}
        text = rp.render_detail(res)
        self.assertIn("q1", text)
        self.assertIn("2404.19707", text)
        self.assertIn("q9", text)


if __name__ == "__main__":
    unittest.main()

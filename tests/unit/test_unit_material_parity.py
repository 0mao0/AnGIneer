# -*- coding: utf-8 -*-
"""B 层素材传递性检查（evals_core.material_parity）单测。

用注入的假数据源，不碰真实 DB/向量库。覆盖四类断言与"缺失清单"的产出。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/evals-core/src")))

from evals_core.material_parity import DocReport, Sources, check_document, render_summary, run_check


def _node(block_type="paragraph", plain_text="", content=None, **kw):
    node = {"block_type": block_type, "plain_text": plain_text}
    if content is not None:
        node["content_json"] = content
    node.update(kw)
    return node


_NOT_GIVEN = object()   # 未注入阶段状态 → 保持旧行为（缺 canonical 即报）


def _sources(nodes, chunk_texts, vectors=3, indexed=True, stage_state=_NOT_GIVEN):
    src = Sources(
        list_docs=lambda: [("lib", "doc")],
        load_nodes=lambda lib, doc: nodes,
        load_chunk_texts=lambda lib, doc: chunk_texts,
        has_canonical=lambda lib, doc: indexed,
        count_vectors=lambda lib, doc: vectors,
    )
    if stage_state is not _NOT_GIVEN:
        src.index_stage_state = lambda lib, doc: stage_state
    return src


class CheckDocumentTests(unittest.TestCase):
    def test_all_good_document_has_no_issue(self):
        nodes = [_node(plain_text="这是一段足够长的正文内容"), _node(plain_text="另一段正文内容也很长")]
        report = check_document("lib", "doc", _sources(nodes, ["这是一段足够长的正文内容 另一段正文内容也很长"]))
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(report.coverage, 1.0)

    def test_detects_content_json_text_lost_from_plain_text(self):
        """复现 2026-09-12 那类 bug：content_json 有内容、plain_text 为空。"""
        nodes = [_node("page_footnote", plain_text="", content={"page_footnote_content": [{"type": "text", "content": "参考文献：比较文学概论"}]})]
        report = check_document("lib", "doc", _sources(nodes, []))
        self.assertFalse(report.ok)
        self.assertEqual(report.blocks_text_lost, 1)
        self.assertTrue(any("内容落地缺失" in i for i in report.issues), report.issues)

    def test_detects_block_missing_from_chunks(self):
        nodes = [
            _node(plain_text="这一块进了 chunk 文本"),
            _node(plain_text="这一块被 chunk 构建环节弄丢了"),
        ]
        report = check_document("lib", "doc", _sources(nodes, ["这一块进了 chunk 文本"]))
        self.assertEqual(report.blocks_uncovered, 1)
        self.assertTrue(any("块→chunk 覆盖不足" in i for i in report.issues), report.issues)
        self.assertTrue(report.samples)

    def test_coverage_tolerance_allows_small_gap(self):
        nodes = [_node(plain_text=f"正文块{i}号内容足够长") for i in range(100)]
        chunk = " ".join(n["plain_text"] for n in nodes[:-1])   # 缺 1/100 = 1%
        report = check_document("lib", "doc", _sources(nodes, [chunk]))
        self.assertTrue(report.ok, report.issues)

    def test_detects_missing_index(self):
        report = check_document("lib", "doc", _sources([_node(plain_text="正文")], [], indexed=False))
        self.assertFalse(report.indexed)
        self.assertTrue(any("未索引" in i for i in report.issues), report.issues)

    def test_index_assertion_exempt_when_fts_never_planned(self):
        """没计划建索引的文档（评测库只跑 5 阶段）：豁免"未索引"，但标记出来，不能静默。"""
        report = check_document("lib", "doc",
                                _sources([_node(plain_text="正文内容足够长")], [], indexed=False,
                                         vectors=None, stage_state=None))
        self.assertFalse(report.indexed)
        self.assertTrue(report.index_not_planned)
        self.assertTrue(report.ok, report.issues)

    def test_index_assertion_exempt_when_fts_skipped(self):
        report = check_document("lib", "doc",
                                _sources([_node(plain_text="正文内容足够长")], [], indexed=False,
                                         vectors=None, stage_state="skipped"))
        self.assertTrue(report.index_not_planned)
        self.assertTrue(report.ok, report.issues)

    def test_index_assertion_applies_when_fts_interrupted(self):
        """服务重启打断 fts（状态 running/pending/failed）→ 照报（2026-09-06 实踩）。"""
        for state in ("running", "pending", "failed", "partial"):
            with self.subTest(state=state):
                report = check_document("lib", "doc",
                                        _sources([_node(plain_text="正文内容足够长")], [], indexed=False,
                                                 vectors=None, stage_state=state))
                self.assertFalse(report.index_not_planned)
                self.assertTrue(any("未索引" in i for i in report.issues), report.issues)
                self.assertIn(state, report.issues[0])

    def test_index_assertion_applies_when_fts_completed_but_no_canonical(self):
        report = check_document("lib", "doc",
                                _sources([_node(plain_text="正文内容足够长")], [], indexed=False,
                                         vectors=None, stage_state="completed"))
        self.assertTrue(any("未索引" in i for i in report.issues), report.issues)

    def test_detects_zero_vectors_while_chunks_exist(self):
        nodes = [_node(plain_text="正文内容足够长")]
        report = check_document("lib", "doc", _sources(nodes, ["正文内容足够长"], vectors=0))
        self.assertTrue(any("chunk→向量缺失" in i for i in report.issues), report.issues)

    def test_vector_check_skipped_when_unavailable(self):
        nodes = [_node(plain_text="正文内容足够长")]
        report = check_document("lib", "doc", _sources(nodes, ["正文内容足够长"], vectors=None))
        self.assertIsNone(report.vector_points)
        self.assertTrue(report.ok, report.issues)

    def test_whitespace_insensitive_for_code_blocks(self):
        nodes = [_node("code", plain_text="function a() {\n  return 1;\n}")]
        report = check_document("lib", "doc", _sources(nodes, ["function a() { return 1; }"]))
        self.assertEqual(report.blocks_uncovered, 0)

    def test_furniture_blocks_excluded_from_coverage(self):
        """页眉/页脚/页码按设计不进检索素材，不能算"内容没送达"。"""
        nodes = [
            _node(plain_text="正文内容足够长的一段"),
            _node("page_number", plain_text="123"),
            _node("page_header", plain_text="某本书第三章"),
            _node("page_footer", plain_text="版权所有"),
            _node(plain_text="被标为家具的块", layout_category="furniture"),
        ]
        report = check_document("lib", "doc", _sources(nodes, ["正文内容足够长的一段"]))
        self.assertEqual(report.blocks_with_text, 1)
        self.assertEqual(report.blocks_uncovered, 0)
        self.assertTrue(report.ok, report.issues)

    def test_inactive_blocks_excluded(self):
        nodes = [_node(plain_text="正文内容足够长的一段"), _node(plain_text="停用的块内容", is_active=0)]
        report = check_document("lib", "doc", _sources(nodes, ["正文内容足够长的一段"]))
        self.assertEqual(report.blocks_with_text, 1)
        self.assertTrue(report.ok, report.issues)

    def test_empty_artifacts_is_issue(self):
        report = check_document("lib", "doc", _sources([], []))
        self.assertTrue(any("无解析产物" in i for i in report.issues), report.issues)

    def test_probe_uses_corrected_text_when_present(self):
        """链路 chunk 消费 plain_text_corrected；探针只比 plain_text 会把被校正改写的块报成未覆盖。

        2026-09-14 实踩：PoPo 把公式左端的 V_{s}= 校正成 V=，4 个方程块全部误报未覆盖。
        """
        nodes = [{"block_type": "equation_interline", "plain_text": "V _ {s} = V _ {s 0} \\frac {r}{x}",
                  "plain_text_corrected": "V = V _ {s 0} \\frac {r}{x}",
                  "content_json": {"math_content": "V _ {s} = V _ {s 0} \\frac {r}{x}"}}]
        sources = _sources(nodes, ["V = V _ {s 0} \\frac {r}{x}"])
        report = check_document("lib", "doc", sources)
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(report.blocks_uncovered, 0)

    def test_counts_symbol_mismatch_without_failing(self):
        nodes = [{"block_type": "equation_interline", "plain_text": "V _ {s} = V _ {s 0} \\frac {r}{x}",
                  "plain_text_corrected": "V = V _ {s 0} \\frac {r}{x}",
                  "math_content": "V _ {s} = V _ {s 0} \\frac {r}{x}",
                  "math_content_corrected": "V = V _ {s 0} \\frac {r}{x}",
                  "symbol_mismatch": True,
                  "content_json": {"math_content": "V _ {s} = V _ {s 0} \\frac {r}{x}"}}]
        report = check_document("lib", "doc", _sources(nodes, ["V = V _ {s 0} \\frac {r}{x}"]))
        self.assertEqual(report.blocks_symbol_mismatch, 1)
        self.assertTrue(report.ok, report.issues)          # 符号改动不判 fail
        self.assertTrue(report.mismatch_samples)
        self.assertIn("校正改符号", report.mismatch_samples[0])


class RunCheckTests(unittest.TestCase):
    def test_aggregates_and_lists_missing(self):
        good_nodes = [_node(plain_text="正常文档的正文内容足够长")]
        bad_nodes = [_node(plain_text="丢失文档的正文内容也足够长")]

        def load_nodes(lib, doc):
            return good_nodes if doc == "good" else bad_nodes

        sources = Sources(
            list_docs=lambda: [("lib", "good"), ("lib", "bad")],
            load_nodes=load_nodes,
            load_chunk_texts=lambda lib, doc: ["正常文档的正文内容足够长"] if doc == "good" else [],
            has_canonical=lambda lib, doc: True,
            count_vectors=lambda lib, doc: 2,
        )
        result = run_check(sources=sources)
        self.assertEqual(result["docs_checked"], 2)
        self.assertEqual(result["docs_with_issues"], 1)
        self.assertEqual(result["issues"][0]["doc_id"], "bad")
        self.assertIn(result["severity"], ("warn", "fail"))
        text = render_summary(result)
        self.assertIn("素材检查", text)
        self.assertIn("bad", text)

    def test_libraries_filter_and_max_docs(self):
        sources = Sources(
            list_docs=lambda: [("libA", "d1"), ("libB", "d2"), ("libA", "d3")],
            load_nodes=lambda lib, doc: [_node(plain_text="正文内容足够长")],
            load_chunk_texts=lambda lib, doc: ["正文内容足够长"],
            has_canonical=lambda lib, doc: True,
            count_vectors=lambda lib, doc: 1,
        )
        result = run_check(libraries=["libA"], sources=sources)
        self.assertEqual(result["docs_checked"], 2)
        result_limited = run_check(sources=sources, max_docs=1)
        self.assertEqual(result_limited["docs_checked"], 1)

    def test_ok_severity_when_clean(self):
        sources = Sources(
            list_docs=lambda: [("lib", "doc")],
            load_nodes=lambda lib, doc: [_node(plain_text="正文内容足够长")],
            load_chunk_texts=lambda lib, doc: ["正文内容足够长"],
            has_canonical=lambda lib, doc: True,
            count_vectors=lambda lib, doc: 5,
        )
        self.assertEqual(run_check(sources=sources)["severity"], "ok")

    def test_exempt_docs_counted_and_visible_in_summary(self):
        """豁免篇数必须进汇总与摘要：stage 记录被弄丢时不能让体检静默转绿。"""
        sources = Sources(
            list_docs=lambda: [("omnidocbench", "od-1")],
            load_nodes=lambda lib, doc: [_node(plain_text="评测语料的正文内容足够长")],
            load_chunk_texts=lambda lib, doc: [],
            has_canonical=lambda lib, doc: False,
            count_vectors=lambda lib, doc: None,
            index_stage_state=lambda lib, doc: None,
        )
        result = run_check(sources=sources)
        self.assertEqual(result["docs_with_issues"], 0)
        self.assertEqual(result["severity"], "ok")
        self.assertEqual(result["totals"]["docs_index_not_planned"], 1)
        self.assertIn("未计划建索引", render_summary(result))

    def test_symbol_mismatch_counted_and_visible_in_summary(self):
        """符号改动要每晚报出计数与样例（数据质量信号），但不影响 severity。"""
        nodes = [{"block_type": "equation_interline", "plain_text": "V _ {s} = a + b",
                  "plain_text_corrected": "V = a + b", "symbol_mismatch": True,
                  "math_content": "V _ {s} = a + b", "math_content_corrected": "V = a + b"}]
        sources = Sources(
            list_docs=lambda: [("lib", "doc")],
            load_nodes=lambda lib, doc: nodes,
            load_chunk_texts=lambda lib, doc: ["V = a + b"],
            has_canonical=lambda lib, doc: True,
            count_vectors=lambda lib, doc: 3,
        )
        result = run_check(sources=sources)
        self.assertEqual(result["severity"], "ok")
        self.assertEqual(result["docs_with_issues"], 0)
        self.assertEqual(result["totals"]["blocks_symbol_mismatch"], 1)
        self.assertTrue(result["symbol_mismatch_samples"])
        summary = render_summary(result)
        self.assertIn("校正改动了公式符号", summary)
        self.assertIn("校正改符号", summary)

    def test_source_failure_returns_error_severity(self):
        def boom():
            raise RuntimeError("数据库不可用")

        sources = Sources(list_docs=boom, load_nodes=lambda l, d: [], load_chunk_texts=lambda l, d: [],
                          has_canonical=lambda l, d: False, count_vectors=lambda l, d: None)
        result = run_check(sources=sources)
        self.assertEqual(result["severity"], "error")
        self.assertIn("数据库不可用", result["detail"])


class NotifyLineTests(unittest.TestCase):
    """素材检查行要进 nightly 结论卡片（通过与否都要可见）。"""

    def test_material_line_appended_to_conclusion_card(self):
        from evals_core.nightly import notify
        from evals_core.nightly.pipeline import _material_line

        material = {"severity": "ok", "docs_checked": 200,
                    "totals": {"blocks_text_lost": 0, "blocks_uncovered": 3}}
        raw = {"started_at": "2026-09-13T00:34:00+08:00", "completed_at": "2026-09-13T04:10:00+08:00",
               "summary_scores": {"overall_score": 0.83, "correct": 437, "total": 526,
                                  "judge_failed_count": 2, "errored": 0}}
        text = notify.build_message(raw, {"matrix": {"pf": 5, "fp": 3}, "delta": 0.004}, "green",
                                   material_line=_material_line(material))
        lines = text.splitlines()
        self.assertIn("素材检查：ok（检查 200 篇，内容未落地 0 块，未进 chunk 3 块）", lines)
        # 必须独立成行（企微卡片按行渲染），且排在分析之后
        self.assertGreater(lines.index("素材检查：ok（检查 200 篇，内容未落地 0 块，未进 chunk 3 块）"),
                           max(i for i, ln in enumerate(lines) if ln.startswith("分析：")))

    def test_material_line_absent_by_default(self):
        from evals_core.nightly import notify

        text = notify.build_message(None, None, notify.STATE_ERROR, error_note="x")
        self.assertNotIn("素材检查", text)

    def test_material_line_reports_exempt_count(self):
        """豁免篇数要进卡片那一行，否则 stage 记录被弄丢时卡片看不出有篇数没被断言。"""
        from evals_core.nightly.pipeline import _material_line

        line = _material_line({"severity": "ok", "docs_checked": 200,
                               "totals": {"blocks_text_lost": 0, "blocks_uncovered": 0,
                                          "docs_index_not_planned": 11}})
        self.assertIn("11 篇未计划建索引已豁免", line)

    def test_material_line_reports_symbol_mismatch(self):
        from evals_core.nightly.pipeline import _material_line

        line = _material_line({"severity": "ok", "docs_checked": 20,
                               "totals": {"blocks_text_lost": 0, "blocks_uncovered": 0,
                                          "blocks_symbol_mismatch": 4}})
        self.assertIn("符号改动 4 块", line)

    def test_material_line_empty_when_disabled(self):
        from evals_core.nightly.pipeline import _material_line

        self.assertEqual(_material_line(None), "")


if __name__ == "__main__":
    unittest.main()

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


def _sources(nodes, chunk_texts, vectors=3, indexed=True):
    return Sources(
        list_docs=lambda: [("lib", "doc")],
        load_nodes=lambda lib, doc: nodes,
        load_chunk_texts=lambda lib, doc: chunk_texts,
        has_canonical=lambda lib, doc: indexed,
        count_vectors=lambda lib, doc: vectors,
    )


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
        self.assertIn("素材体检", text)
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

    def test_source_failure_returns_error_severity(self):
        def boom():
            raise RuntimeError("数据库不可用")

        sources = Sources(list_docs=boom, load_nodes=lambda l, d: [], load_chunk_texts=lambda l, d: [],
                          has_canonical=lambda l, d: False, count_vectors=lambda l, d: None)
        result = run_check(sources=sources)
        self.assertEqual(result["severity"], "error")
        self.assertIn("数据库不可用", result["detail"])


if __name__ == "__main__":
    unittest.main()

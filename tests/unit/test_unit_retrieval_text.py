# -*- coding: utf-8 -*-
"""检索文本处理与条款号直达的单元测试。

覆盖：
- build_cjk_ngram_text / _build_fts_match_query（CJK bigram 索引与查询构造）
- extract_clause_refs_strict（上下文门控的条款号抽取）
- list_blocks_by_clause_refs（clause_id 双向层级精确查询）
- search_chunk_fts（bigram 索引下的中文 FTS 召回）
"""
import tempfile
import unittest
from pathlib import Path

from docs_core.step05_sqlite_fts.store.canonical_sql_store import (
    CanonicalSQLiteStore,
    _build_fts_match_query,
    build_cjk_ngram_text,
)
from docs_core.step09_query.retrieval.clause_resolver import extract_clause_refs_strict
from docs_core.step09_query.retrieval.query_normalizer import extract_clause_refs, extract_query_signals


class TestCjkNgramText(unittest.TestCase):
    def test_cjk_run_expanded_to_bigrams(self):
        result = build_cjk_ngram_text("码头前沿")
        self.assertIn("码头", result.split())
        self.assertIn("头前", result.split())
        self.assertIn("前沿", result.split())

    def test_single_cjk_char_kept(self):
        result = build_cjk_ngram_text("高")
        self.assertIn("高", result.split())

    def test_non_cjk_preserved(self):
        result = build_cjk_ngram_text("H4%波高")
        self.assertIn("H4%", result)
        self.assertIn("波高", result.split())

    def test_empty_input(self):
        self.assertEqual(build_cjk_ngram_text(""), " ".join(build_cjk_ngram_text("").split()) or "")


class TestBuildFtsMatchQuery(unittest.TestCase):
    def test_cjk_query_expanded(self):
        match = _build_fts_match_query("底高程")
        self.assertIn('"底高"', match)
        self.assertIn('"高程"', match)

    def test_clause_number_quoted(self):
        match = _build_fts_match_query("第5.4.12条")
        self.assertIn('"5.4.12"', match)
        # 不应产生未加引号的点分编号（会触发 FTS 语法错误）
        self.assertNotIn(" OR 5.4.12", match)

    def test_empty_query(self):
        self.assertEqual(_build_fts_match_query(""), "")


class TestExtractClauseRefsStrict(unittest.TestCase):
    def test_context_gated_clause(self):
        self.assertEqual(extract_clause_refs_strict("第5.4.12条规定的富裕水深是多少"), ["5.4.12"])

    def test_measurement_not_extracted(self):
        self.assertEqual(extract_clause_refs_strict("允许停泊波高H4%为1.5m怎么取"), [])
        self.assertEqual(extract_clause_refs_strict("水深1.5m、流速2.0m/s"), [])

    def test_table_ref_normalized(self):
        self.assertEqual(extract_clause_refs_strict("表5.4.12-1中的系数"), ["5.4.12.1"])

    def test_appendix_ref(self):
        self.assertEqual(extract_clause_refs_strict("附录A.0.1 船型尺度"), ["A.0.1"])

    def test_bare_three_segment_dotted(self):
        self.assertEqual(extract_clause_refs_strict("按5.4.12.1款计算"), ["5.4.12.1"])

    def test_single_dot_requires_context(self):
        # 无上下文的单点分编号（可能是测量值）不应抽取
        self.assertEqual(extract_clause_refs_strict("取值3.5m是否合规"), [])


class TestFormulaNumberNotClauseRef(unittest.TestCase):
    """P0-1：公式号与条款号是两套编号体系，「式/公式X」的编号不得当条款号采信。

    实锤用例 q_028（run-5c37706a1f71）：「公式6.2.8 中时间富裕系数 Kt」被当条款号后，
    全库 5 篇文档的同号 6.2.8（低槛坝/灌水阀门/接岸结构）撞车上呈。
    公式标识符归 formula 路（extract_formula_identifiers / formula_refs）。
    """

    def test_strict_formula_prefixed_number_not_extracted(self):
        self.assertEqual(extract_clause_refs_strict("公式6.2.8中的时间富裕系数Kt怎么取"), [])

    def test_strict_inline_shi_number_not_extracted(self):
        # 「按式X计算」的式号同为公式编号
        self.assertEqual(extract_clause_refs_strict("排水量按式6.2.8计算"), [])

    def test_strict_bare_dotted_path_also_excludes_formula_number(self):
        # 6.2.8 是三段点分，会走裸号无门控路——公式前缀下同样不得采信
        self.assertEqual(extract_clause_refs_strict("公式 6.2.8 中的 Kt 取值"), [])

    def test_strict_table_and_tiao_still_extracted(self):
        self.assertEqual(extract_clause_refs_strict("表6.4.2中的系数"), ["6.4.2"])
        self.assertEqual(extract_clause_refs_strict("第6.2.8条的规定"), ["6.2.8"])

    def test_normalizer_formula_prefixed_number_not_extracted(self):
        self.assertEqual(extract_clause_refs("公式6.2.8中的时间富裕系数Kt"), [])

    def test_normalizer_mask_does_not_swallow_later_numbers(self):
        # 屏蔽只消耗公式号本身，同句后续条款号照常抽出
        self.assertEqual(extract_clause_refs("公式6.2.8及第5.4.12条"), ["5.4.12"])

    def test_normalizer_table_and_tiao_still_extracted(self):
        self.assertEqual(extract_clause_refs("第6.2.8条"), ["6.2.8"])
        self.assertEqual(extract_clause_refs("表6.4.2"), ["6.4.2"])

    def test_query_signals_formula_ref_keeps_full_dotted_number(self):
        # 公式路要接住完整公式号：条款路让位后，「公式6.2.8」若只交出 "6" 等于没承接
        sig = extract_query_signals("在公式6.2.8中，时间富裕系数Kt的取值范围是多少？")
        self.assertEqual(sig["question_type"], "locate_formula")
        self.assertIn("6.2.8", sig["formula_refs"])


def _node(node_id: str, title: str = None):
    from docs_core.step09_query.protocols.contracts import KnowledgeNode

    return KnowledgeNode(
        id=node_id, title=title or f"规范{node_id}", type="doc", library_id="default"
    )


def _clause_block(block_id: str, text: str, clause_id: str = "6.2.8"):
    return {
        "block_id": block_id,
        "block_type": "content",
        "clause_id": clause_id,
        "section_path": "6 枢纽水工建筑物 / 6.2 挡水和泄水建筑物",
        "text_clean": text,
        "page_idx": 1,
    }


class _FakeClausePort:
    """条款直达路唯一依赖 list_blocks_by_clause_refs，其余协议方法不参与本测试。"""

    def __init__(self, blocks_by_doc):
        self._blocks = blocks_by_doc

    def list_blocks_by_clause_refs(self, doc_id, clause_refs, limit):
        return list(self._blocks.get(doc_id, []))[:limit]


def _retrieve_clause(query: str, blocks_by_doc, nodes=None):
    from docs_core.step09_query.protocols.contracts import KnowledgeQueryRequest
    from docs_core.step09_query.retrieval.clause_resolver import ClauseResolver

    if nodes is None:
        nodes = [_node(doc_id) for doc_id in blocks_by_doc]
    return ClauseResolver(port=_FakeClausePort(blocks_by_doc)).retrieve(
        KnowledgeQueryRequest(query=query), nodes, "definition"
    )


class TestClauseTopicWeighting(unittest.TestCase):
    """P0-2：条款直达命中零主题判别——跨规范同号撞车时主题词必须参与排序。

    复现 q_028 形态：多个文档各有 6.2.8，只有一篇内容与题干主题相关。
    """

    def _retrieve(self, query: str, blocks):
        # 撞车形态如实分布在多文档上：每篇文档各携带同号条款
        return _retrieve_clause(
            query,
            {
                "doc-a": blocks[:2],
                "doc-b": blocks[2:3],
                "doc-c": blocks[3:],
            },
        )

    def test_topical_candidate_ranks_first_among_collisions(self):
        blocks = [
            _clause_block("b1", "6.2.8 低槛活动坝固定挡水部分高程直接影响泄洪能力。"),
            _clause_block("b2", "6.2.8 选用的灌水阀门断面往往比廊道断面小一些。"),
            _clause_block("b3", "6.2.8 接岸结构检测包括外观检查、倾斜位移测量。"),
            _clause_block("b4", "6.2.8 时间富裕系数Kt可取1.1~1.3。"),
        ]
        items = self._retrieve("第6.2.8条规定的时间富裕系数Kt取值范围", blocks)
        self.assertTrue(items)
        self.assertEqual(items[0].item_id, "b4", "主题相关的同号条款必须排首位")
        top = next(i for i in items if i.item_id == "b4")
        for other in items:
            if other.item_id != "b4":
                self.assertGreater(top.score, other.score)

    def test_topic_overlap_recorded_in_metadata(self):
        blocks = [
            _clause_block("b1", "6.2.8 低槛活动坝固定挡水部分高程直接影响泄洪能力。"),
            _clause_block("b4", "6.2.8 时间富裕系数Kt可取1.1~1.3。"),
        ]
        items = self._retrieve("第6.2.8条规定的时间富裕系数Kt取值范围", blocks)
        by_id = {i.item_id: i for i in items}
        self.assertGreater(by_id["b4"].metadata["topic_overlap"], 0.0)
        self.assertEqual(by_id["b1"].metadata["topic_overlap"], 0.0)

    def test_topic_terms_strip_numbers_and_generic_only(self):
        from docs_core.step09_query.retrieval.query_normalizer import extract_topic_terms

        terms = extract_topic_terms("在公式6.2.8中，时间富裕系数Kt的取值范围是多少？")
        self.assertIn("时间富裕系数", terms)
        self.assertTrue(all(not t.isdigit() for t in terms), "编号数字不得混入主题词")


_NOISE_BLOCKS = [
    _clause_block("b1", "6.2.8 低槛活动坝固定挡水部分高程直接影响泄洪能力。"),
    _clause_block("b2", "6.2.8 选用的灌水阀门断面往往比廊道断面小一些。"),
    _clause_block("b3", "6.2.8 接岸结构检测包括外观检查、倾斜位移测量。"),
]
_TOPICAL_BLOCK = _clause_block("b4", "6.2.8 时间富裕系数Kt可取1.1~1.3。")


class TestSpecNameGating(unittest.TestCase):
    """P1-1：题面点名《规范名》或规范编号时，条款直达只应取该文档的命中。"""

    BLOCKS = {
        "doc-harbor": [_clause_block("h1", "6.4.2 锚地可分避风锚地、避浪锚地。", "6.4.2")],
        "doc-dock": [_clause_block("d1", "6.4.2 船坞作业区的布置应符合下列规定。", "6.4.2")],
    }
    NODES = [
        _node("doc-harbor", title="《海港总体设计规范》"),
        _node("doc-dock", title="《船坞设计规范》"),
    ]

    def _retrieve(self, query):
        return _retrieve_clause(query, self.BLOCKS, self.NODES)

    def test_book_name_limits_to_named_spec(self):
        items = self._retrieve("《海港总体设计规范》6.4.2条中锚地可分避风锚地避浪锚地吗")
        self.assertTrue(items)
        self.assertEqual({i.doc_id for i in items}, {"doc-harbor"})

    def test_standard_code_limits_to_named_spec(self):
        nodes = [
            _node("doc-h", title="JTS 165-2021 海港总体设计规范"),
            _node("doc-d", title="JTS 166-2020 干船坞设计规范"),
        ]
        blocks = {
            "doc-h": [_clause_block("h1", "6.4.2 锚地可分避风锚地、避浪锚地。", "6.4.2")],
            "doc-d": [_clause_block("d1", "6.4.2 船坞作业区的布置应符合下列规定。", "6.4.2")],
        }
        items = _retrieve_clause(
            "按JTS 165-2021 的6.4.2条，锚地可分避风锚地避浪锚地吗", blocks, nodes
        )
        self.assertTrue(items)
        self.assertEqual({i.doc_id for i in items}, {"doc-h"})

    def test_no_spec_mention_returns_all_docs(self):
        items = self._retrieve("第6.4.2条中锚地可分避风锚地避浪锚地吗")
        self.assertEqual({i.doc_id for i in items}, {"doc-harbor", "doc-dock"})

    def test_unmatched_spec_mention_does_not_empty_recall(self):
        # 题面点名的规范不在库中 → 不得清空召回，退回不限域
        items = self._retrieve("《船闸设计规范》6.4.2条中锚地可分避风锚地避浪锚地吗")
        self.assertEqual({i.doc_id for i in items}, {"doc-harbor", "doc-dock"})


class TestClauseNoiseRejection(unittest.TestCase):
    """P1-2：条款直达命中主题校验全不符＝噪声证据，返回空让语义路接管。

    现状（需求 §2②）：撞车噪声以 12~14 分上呈，把模型逼向拒答。
    """

    def test_all_topic_mismatch_returns_empty(self):
        items = _retrieve_clause(
            "第6.2.8条规定的时间富裕系数取值范围", {"doc-a": _NOISE_BLOCKS}
        )
        self.assertEqual(items, [], "同号但主题全不符的条款不得作为证据上呈")

    def test_bare_clause_ref_not_killed_by_guard(self):
        # 裸条款号引用没有主题信号，守卫不得生效（否则误杀正常直达）
        items = _retrieve_clause("第6.2.8条", {"doc-a": _NOISE_BLOCKS})
        self.assertTrue(items)

    def test_partial_mismatch_keeps_all_ranked(self):
        # 部分相符时只靠排序压后噪声，不删除（现行口径）
        items = _retrieve_clause(
            "第6.2.8条规定的时间富裕系数Kt取值范围",
            {"doc-a": _NOISE_BLOCKS + [_TOPICAL_BLOCK]},
        )
        self.assertEqual(items[0].item_id, "b4")
        self.assertGreater(len(items), 1)


class TestEvidenceCarriesDocName(unittest.TestCase):
    """P1-3：条款直达证据必须带规范名——生成器与用户要能分辨这条 6.2.8 出自哪本规范。"""

    def test_title_and_metadata_carry_doc_name(self):
        items = _retrieve_clause(
            "第6.2.8条",
            {"doc-x": [_NOISE_BLOCKS[0]]},
            [_node("doc-x", title="《船闸设计规范》")],
        )
        self.assertTrue(items)
        self.assertEqual(items[0].metadata["doc_title"], "《船闸设计规范》")
        self.assertIn("《船闸设计规范》", items[0].title)


class TestClauseAndFtsStore(unittest.TestCase):
    def setUp(self):
        # Windows 下 WAL 模式的 SQLite 文件句柄释放有延迟，忽略清理期文件锁错误
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self._tmp.name) / "index.sqlite"
        self.store = CanonicalSQLiteStore(self.db_path)
        with self.store.connect() as conn:
            conn.executemany(
                """
                INSERT INTO canonical_blocks (
                    block_id, doc_id, page_idx, block_type, text, text_clean,
                    reading_order, section_path, clause_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("b1", "d1", 0, "content", "富裕水深应按下式计算", "富裕水深应按下式计算", 1, "5 通航 / 5.4", "5.4.12"),
                    ("b2", "d1", 0, "content", "通航水位的确定", "通航水位的确定", 2, "5 通航 / 5.4", "5.4.12.1"),
                    ("b3", "d1", 1, "content", "码头前沿底高程", "码头前沿底高程", 3, "5 通航 / 5.4", "5.4.13"),
                    ("b4", "d1", 2, "content", "总则以HHHHH", "总则其他内容", 4, "1 总则", "1.1"),
                ],
            )
            conn.executemany(
                """
                INSERT INTO canonical_chunks (
                    chunk_id, doc_id, chunk_type, text, text_clean, token_count,
                    section_path, page_start, page_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("c1", "d1", "content", "码头前沿底高程计算", "码头前沿底高程计算", 8, "5 通航", 0, 0),
                    ("c2", "d1", "content", "允许停泊波高限值", "允许停泊波高限值", 8, "5 通航", 1, 1),
                ],
            )
            conn.commit()
        # 触发 FTS 重建（走与入库相同的路径）
        self.store.rebuild_chunk_fts("d1")

    def tearDown(self):
        self._tmp.cleanup()

    def test_clause_exact_and_hierarchy(self):
        hits = self.store.list_blocks_by_clause_refs("d1", ["5.4.12"], limit=10)
        clause_ids = {h["clause_id"] for h in hits}
        # 5.4.12 精确命中 + 5.4.12.1 子条款命中；5.4.13 同级不命中；1.1 无关不命中
        self.assertIn("5.4.12", clause_ids)
        self.assertIn("5.4.12.1", clause_ids)
        self.assertNotIn("5.4.13", clause_ids)
        self.assertNotIn("1.1", clause_ids)

    def test_clause_ancestor_match(self):
        # 查询更细的编号，应命中其父级 block
        hits = self.store.list_blocks_by_clause_refs("d1", ["5.4.12.1"], limit=10)
        clause_ids = {h["clause_id"] for h in hits}
        self.assertIn("5.4.12.1", clause_ids)
        self.assertIn("5.4.12", clause_ids)

    def test_fts_two_char_cjk(self):
        hits = self.store.search_chunk_fts("d1", "波高", limit=5)
        self.assertTrue(any(h["chunk_id"] == "c2" for h in hits))

    def test_fts_three_char_cjk(self):
        hits = self.store.search_chunk_fts("d1", "底高程", limit=5)
        self.assertTrue(any(h["chunk_id"] == "c1" for h in hits))

    def test_fts_no_false_hit(self):
        hits = self.store.search_chunk_fts("d1", "防波堤", limit=5)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()

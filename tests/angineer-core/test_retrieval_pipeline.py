"""retrieval_pipeline 存活函数单测：rerank 入口与拒答校验。"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core.retrieval_pipeline import (  # noqa: E402
    _strip_absent_citations,
    find_unsupported_reference,
    has_unsupported_reference,
    llm_rerank_candidates,
    llm_second_rerank,
    rerank_candidates,
)


class RetrievalPipelineSharedTests(unittest.TestCase):
    def test_has_unsupported_reference_shared(self):
        self.assertTrue(has_unsupported_reference("依据 JTS 999-2020 计算", "只有一段正文"))
        self.assertFalse(has_unsupported_reference("依据 JTS 999-2020 计算", "JTS 999-2020 规定"))

    def test_book_title_all_absent_no_longer_hard(self):
        # 方案A（2026-10-08）：标题全核不到不再整答替换（has_*=False），
        # 转入剥标记三态（find_*=strip），由守卫摘除出处标记、保留正文
        self.assertFalse(
            has_unsupported_reference("根据《不存在的规范》第3.1节，答案是42。", "证据正文只讲别的内容")
        )
        self.assertEqual(
            find_unsupported_reference("根据《不存在的规范》第3.1节，答案是42。", "证据正文只讲别的内容"),
            ("strip", ["《不存在的规范》"]),
        )

    def test_book_title_grounded_by_doc_title_prefix(self):
        # 在库标题经装配前缀《doc_title》落在证据面 → 真引用放行
        self.assertFalse(
            has_unsupported_reference(
                "根据《2404.09358v3.pdf》第4节，答案是A。",
                "《2404.09358v3.pdf》 【相关性0.8】 正文片段",
            )
        )

    def test_book_title_case_whitespace_variant_grounded(self):
        # 大小写/空白变体（2026-10-07 1040 实测形态）归一后核到 → 放行
        self.assertFalse(
            has_unsupported_reference(
                "根据《ON PRO-CDH DESCENT ON DERIVED SCHEMES》的构造，答案是B。",
                "正文提到 On Pro-CDH  Descent on Derived Schemes 的方法。",
            )
        )

    def test_book_title_mixed_partial_grounded_passes(self):
        # 部分真（在库前缀）+ 部分次级引用（论文真题名/中译名）→ 放行，不逐条硬拦
        self.assertFalse(
            has_unsupported_reference(
                "根据《2404.09358v3.pdf》与《Thyroid disrupting effects of PFAS》得出结论。",
                "《2404.09358v3.pdf》 正文片段",
            )
        )

    def test_book_title_prose_mention_grounds(self):
        # 证据正文裸提标题（无书名号）也算核到——宽松方向防误杀
        self.assertFalse(
            has_unsupported_reference("根据《赫尔辛基宣言》……", "本研究遵循赫尔辛基宣言的伦理要求。")
        )

    def test_book_title_absent_but_section_verifiable_passes(self):
        # 方案 B（2026-10-07 OpenRAG -2.6pp 回归）：真题名 vs 文件名 doc_title 核不到标题时，
        # 引号章节名在证据里核到 → 放行（今晚 24 题误杀的标准形态）
        self.assertFalse(
            has_unsupported_reference(
                "根据《Two-Stage Estimators for Spatial Confounding with Point-Referenced Data》"
                "第“5. Discussion”章节，答案是C。",
                "《2404.09358v3.pdf》 正文片段\n5. Discussion\nWe conclude the method works.",
            )
        )

    def test_book_title_absent_bare_numeric_section_verifiable_passes(self):
        # 方案 B：裸数字条款号（无引号）核到 → 放行
        self.assertFalse(
            has_unsupported_reference(
                "根据《不存在的规范》第3.1节，答案是42。",
                "证据正文\n3.1 一般规定 内容如下",
            )
        )

    def test_book_title_absent_section_also_absent_strips(self):
        # 方案 B「不卸牙」升级为方案 A（2026-10-08）：标题与章节号双双核不到不再整答替换，
        # 降为剥标记（两晚 30+ 题好答案整答换拒答的代价大于收益，业主拍板）
        self.assertFalse(
            has_unsupported_reference(
                "根据《不存在的规范》第“9.9”节，答案是42。",
                "证据正文只讲别的内容",
            )
        )
        self.assertEqual(
            find_unsupported_reference(
                "根据《不存在的规范》第“9.9”节，答案是42。",
                "证据正文只讲别的内容",
            ),
            ("strip", ["《不存在的规范》"]),
        )

    def test_absent_title_with_fabricated_spec_number_hard(self):
        # 方案 A 不卸牙：标题核不到 + 规范编号编造 → hard 整答替换不变
        verdict, _ = find_unsupported_reference(
            "根据《不存在的规范》按 JTS 999-2020 计算得 42。",
            "证据正文只讲别的内容",
        )
        self.assertEqual(verdict, "hard")

    def test_grounded_title_with_absent_secondary_stays_clean(self):
        # 部分核到（在库 doc_title）时次级论文真题名维持放行，不进 strip
        self.assertEqual(
            find_unsupported_reference(
                "根据《2404.09358v3.pdf》与《Thyroid disrupting effects of PFAS》得出结论。",
                "《2404.09358v3.pdf》 正文片段",
            ),
            ("clean", []),
        )

    def test_strip_absent_citations_keeps_body(self):
        # 剥标记实例（生产误杀形态）：句首状语删除、正文事实保留
        body = _strip_absent_citations(
            "根据《Deep Learning》第2.2节，F-BIAS 指标定义为模型偏见差值。",
            ["《Deep Learning》"],
        )
        self.assertNotIn("《Deep Learning》", body)
        self.assertIn("F-BIAS 指标定义为模型偏见差值", body)

    def test_strip_absent_citations_marks_dangling_section(self):
        body = _strip_absent_citations(
            "结论可靠。根据《不存在的规范》第3.1节，答案是42。",
            ["《不存在的规范》"],
        )
        self.assertNotIn("《不存在的规范》", body)
        self.assertIn("第3.1节（⚠️出处待核）", body)
        self.assertIn("答案是42", body)

    def test_rerank_candidates_shared_is_callable(self):
        self.assertTrue(callable(rerank_candidates))

    @staticmethod
    def _make_item(item_id: str = "a", text: str = "候选内容") -> SimpleNamespace:
        return SimpleNamespace(
            item_id=item_id,
            title="条款",
            text=text,
            rerank_score=0.0,
            metadata={},
        )

    def test_llm_rerank_reorders_and_sets_scores(self):
        items = [self._make_item(str(i)) for i in range(4)]
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.return_value = SimpleNamespace(text='{"ranking": [3, 1, 0, 2]}')
            out = llm_rerank_candidates("查询", items, llm_client=object())
        self.assertEqual([item.item_id for item in out], ["3", "1", "0", "2"])
        scores = [item.rerank_score for item in out]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_llm_rerank_bad_output_returns_none(self):
        items = [self._make_item(str(i)) for i in range(4)]
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.return_value = SimpleNamespace(text="not json")
            self.assertIsNone(llm_rerank_candidates("查询", items, llm_client=object()))

    def test_llm_rerank_invalid_indices_are_skipped(self):
        items = [self._make_item(str(i)) for i in range(4)]
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.return_value = SimpleNamespace(text='{"ranking": [99, 1, -3, 2, 1]}')
            out = llm_rerank_candidates("查询", items, llm_client=object())
        self.assertEqual([item.item_id for item in out], ["1", "2", "0", "3"])

    def test_rerank_candidates_dense_degraded_uses_llm(self):
        items = [self._make_item(str(i)) for i in range(6)]
        runner = SimpleNamespace(reranker_configs=[], reranker_timeout_sec=1.0)
        with mock.patch(
            "angineer_core.base_config.get_config",
            return_value=SimpleNamespace(runner=runner),
        ):
            with mock.patch(
                "angineer_core.retrieval_pipeline.llm_rerank_candidates",
                return_value=items,
            ) as llm:
                out = rerank_candidates(
                    "查询",
                    items,
                    dense_degraded=True,
                    config_name="cfg-x",
                    mode="thinking",
                )
        llm.assert_called_once()
        self.assertEqual(llm.call_args.kwargs["config_name"], "cfg-x")
        self.assertEqual(llm.call_args.kwargs["mode"], "thinking")
        self.assertIs(out, items)

    def test_rerank_candidates_not_degraded_uses_local(self):
        items = [self._make_item(str(i)) for i in range(6)]
        runner = SimpleNamespace(reranker_configs=[], reranker_timeout_sec=1.0)
        # C1 解耦后引擎经 ports 注册表调本地 rerank：注册 fake 适配器替代原
        # mock docs_core.rerank_candidates 的方式（引擎不再 import docs-core）
        from angineer_core import ports

        calls: list = []

        def _fake_rerank(query: str, task_type: str, candidates: list) -> list:
            calls.append(1)
            return items

        ports.register_local_rerank(_fake_rerank)
        try:
            with mock.patch(
                "angineer_core.base_config.get_config",
                return_value=SimpleNamespace(runner=runner),
            ):
                out = rerank_candidates("查询", items, dense_degraded=False)
        finally:
            ports.register_local_rerank(None)
        self.assertEqual(len(calls), 1)
        self.assertIs(out, items)


class SecondRerankTests(unittest.TestCase):
    @staticmethod
    def _make_item(item_id: str, text: str = "候选内容") -> SimpleNamespace:
        return SimpleNamespace(
            item_id=item_id,
            title="条款",
            text=text,
            rerank_score=0.9,
            metadata={},
        )

    def _items(self, n: int = 6) -> list:
        return [self._make_item(str(i)) for i in range(n)]

    def test_wide_agrees_no_duel_order_unchanged(self):
        items = self._items()
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.return_value = SimpleNamespace(text='{"ranking": [0, 2, 1, 3, 4, 5]}')
            out = llm_second_rerank("查询", items, llm_client=object())
        self.assertEqual(guarded.call_count, 1)
        self.assertIs(out, items)
        self.assertEqual([i.item_id for i in out], ["0", "1", "2", "3", "4", "5"])
        self.assertTrue(all(i.rerank_score == 0.9 for i in out))

    def test_duel_confirms_override_reorders(self):
        items = self._items()
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.side_effect = [
                SimpleNamespace(text='{"ranking": [2, 0, 1, 3, 4, 5]}'),
                SimpleNamespace(text='{"winner": "B"}'),
            ]
            out = llm_second_rerank("查询", items, llm_client=object())
        self.assertEqual(guarded.call_count, 2)
        self.assertEqual(out[0].item_id, "2")
        scores = [i.rerank_score for i in out]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertGreater(out[0].rerank_score, 0.9)

    def test_duel_vetoes_override_order_unchanged(self):
        items = self._items()
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.side_effect = [
                SimpleNamespace(text='{"ranking": [2, 0, 1, 3, 4, 5]}'),
                SimpleNamespace(text='{"winner": "A"}'),
            ]
            out = llm_second_rerank("查询", items, llm_client=object())
        self.assertIs(out, items)
        self.assertEqual([i.item_id for i in out], ["0", "1", "2", "3", "4", "5"])
        self.assertTrue(all(i.rerank_score == 0.9 for i in out))

    def test_wide_failure_returns_unchanged(self):
        items = self._items()
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.return_value = SimpleNamespace(text="not json")
            out = llm_second_rerank("查询", items, llm_client=object())
        self.assertIs(out, items)

    def test_duel_failure_treated_as_veto(self):
        items = self._items()
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.side_effect = [
                SimpleNamespace(text='{"ranking": [3, 0, 1, 2, 4, 5]}'),
                SimpleNamespace(text="garbage"),
            ]
            out = llm_second_rerank("查询", items, llm_client=object())
        self.assertIs(out, items)

    def _online_rerank_ok(self, n: int):
        resp = mock.Mock()
        resp.status_code = 200
        resp.json.return_value = {
            "results": [{"index": i, "relevance_score": 0.9 - i * 0.001} for i in range(n)]
        }
        return resp

    def test_hook_applies_second_rerank_when_enabled(self):
        items = self._items(6)
        runner = SimpleNamespace(
            reranker_configs=[{"url": "http://fake-reranker"}],
            reranker_timeout_sec=1.0,
        )
        with mock.patch.dict(os.environ, {"ANGINEER_LLM_SECOND_RERANK": "1"}):
            with mock.patch(
                "angineer_core.base_config.get_config",
                return_value=SimpleNamespace(runner=runner),
            ), mock.patch("requests.post", return_value=self._online_rerank_ok(6)), \
                mock.patch(
                    "angineer_core.retrieval_pipeline.llm_second_rerank",
                    side_effect=lambda q, c, **kw: list(reversed(c)),
                ) as second:
                out = rerank_candidates("查询", items)
        second.assert_called_once()
        self.assertEqual([i.item_id for i in out], ["5", "4", "3", "2", "1", "0"])

    def test_hook_skips_second_rerank_when_disabled(self):
        items = self._items(6)
        runner = SimpleNamespace(
            reranker_configs=[{"url": "http://fake-reranker"}],
            reranker_timeout_sec=1.0,
        )
        with mock.patch.dict(os.environ, {"ANGINEER_LLM_SECOND_RERANK": "0"}):
            with mock.patch(
                "angineer_core.base_config.get_config",
                return_value=SimpleNamespace(runner=runner),
            ), mock.patch("requests.post", return_value=self._online_rerank_ok(6)), \
                mock.patch(
                    "angineer_core.retrieval_pipeline.llm_second_rerank",
                ) as second:
                out = rerank_candidates("查询", items)
        second.assert_not_called()
        self.assertEqual([i.item_id for i in out], ["0", "1", "2", "3", "4", "5"])


class HalfRefusalTests(unittest.TestCase):
    def test_half_refusal_flagged(self):
        from angineer_core.agent_messages import is_half_refusal_text

        half = (
            "证据不足，无法给出完整结论。但是根据检索到的内容，该算法的主要目的是利用多模态交互来增强视听目标说话人提取的性能 [K1]，"
            "具体包括对比学习引导时序交互、最大化目标语音与视觉特征同步性、联合训练损失函数设计等多个方面，"
            "这些内容在论文的第四章节中有详细说明，实验结果表明该方法在多个数据集上取得了显著提升。"
        )
        self.assertTrue(is_half_refusal_text(half))

    def test_plain_answer_ok(self):
        from angineer_core.agent_messages import is_half_refusal_text

        part = (
            "该算法的主要目的是利用多模态交互增强视听目标说话人提取性能 [K1]。"
            "证据中已支持对比学习引导与时序交互两部分内容，但证据未列出具体的损失函数设计细节。"
        )
        self.assertFalse(is_half_refusal_text(part))

    def test_declaration_without_cite_ok(self):
        from angineer_core.agent_messages import is_half_refusal_text

        decl = "证据不足，无法给出完整结论，当前检索到的片段仅能确认部分相关性，不足以安全地给出答案。"
        self.assertFalse(is_half_refusal_text(decl))


class PerDocBlockDedupTests(unittest.TestCase):
    def test_keep_per_doc_blocks_caps_and_dedups(self):
        from angineer_core.agent_tools import _keep_per_doc_blocks

        items = [
            SimpleNamespace(item_id="a1", doc_id="docA", text="", metadata={}),
            SimpleNamespace(item_id="a1", doc_id="docA", text="", metadata={}),
            SimpleNamespace(item_id="a2", doc_id="docA", text="", metadata={}),
            SimpleNamespace(item_id="a3", doc_id="docA", text="", metadata={}),
            SimpleNamespace(item_id="a4", doc_id="docA", text="", metadata={}),
            SimpleNamespace(item_id="b1", doc_id="docB", text="", metadata={}),
        ]
        kept = _keep_per_doc_blocks(items, total_cap=30)
        ids = [getattr(item, "item_id") for item in kept]
        self.assertEqual(ids, ["a1", "a2", "a3", "a4", "b1"])

    def test_keep_per_doc_blocks_total_cap(self):
        from angineer_core.agent_tools import _keep_per_doc_blocks

        items = [
            SimpleNamespace(item_id=f"d{i}x", doc_id=f"doc{i}", text="", metadata={})
            for i in range(40)
        ]
        kept = _keep_per_doc_blocks(items, total_cap=10)
        self.assertEqual(len(kept), 10)


class AdmissionTests(unittest.TestCase):
    """证据上桌 admit_evidence（plan-evidence-admission §1）：判官批量一枪、吵架保留、fail-open。"""

    @staticmethod
    def _item(item_id: str, score: float, text: str = "候选正文") -> SimpleNamespace:
        return SimpleNamespace(item_id=item_id, title="条款", text=text, rerank_score=score, metadata={})

    def _items(self) -> list:
        return [
            self._item("0", 0.70),   # 头部豁免（判官给 0 也保留）
            self._item("1", 0.50),   # 判 1 → 主桌
            self._item("2", 0.40),   # 判 0 且 ≥0.3 → 吵架保留进桌尾
            self._item("3", 0.10),   # 判 0 且 <0.3 → 一致丢弃
            self._item("4", 0.55),   # 判 0 且 ≥0.3 → 吵架保留
        ]

    _VERDICTS = '[{"i":0,"keep":0},{"i":1,"keep":1},{"i":2,"keep":0},{"i":3,"keep":0},{"i":4,"keep":0}]'

    def test_quarrel_matrix_head_exempt_and_ordering(self):
        from angineer_core.retrieval_pipeline import admit_evidence

        items = self._items()
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.return_value = SimpleNamespace(text=self._VERDICTS)
            out, block = admit_evidence("查询", items, llm_client=object())
        # 主桌（豁免+判1）按原序，吵架条贴尾
        self.assertEqual([item.item_id for item in out], ["0", "1", "2", "4"])
        self.assertEqual(block["kept"], 1)
        self.assertEqual(block["exempted"], 1)
        self.assertEqual(block["quarreled"], 2)
        self.assertEqual(block["dropped"], 1)
        self.assertFalse(block["fallback"])
        self.assertIsNotNone(block["judge_config"])
        self.assertIsInstance(block["judge_ms"], int)

    def test_empty_table_no_fallback(self):
        from angineer_core.retrieval_pipeline import admit_evidence

        items = [self._item(str(i), 0.1) for i in range(4)]
        verdicts = ",".join(f'{{"i":{i},"keep":0}}' for i in range(4))
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.return_value = SimpleNamespace(text=f"[{verdicts}]")
            out, block = admit_evidence("查询", items, llm_client=object())
        self.assertEqual(out, [])  # 空桌不回退：交给调用方走标准拒答
        self.assertEqual(block["dropped"], 4)
        self.assertFalse(block["fallback"])

    def test_judge_bad_output_fail_open(self):
        from angineer_core.retrieval_pipeline import admit_evidence

        items = self._items()
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.return_value = SimpleNamespace(text="我觉得都不错")
            out, block = admit_evidence("查询", items, llm_client=object())
        self.assertEqual([item.item_id for item in out], ["0", "1", "2", "3", "4"])
        self.assertTrue(block["fallback"])
        self.assertIsNone(block["kept"])
        self.assertIsNone(block["dropped"])

    def test_judge_exception_fail_open(self):
        from angineer_core.retrieval_pipeline import admit_evidence

        items = self._items()
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.side_effect = RuntimeError("端点炸了")
            out, block = admit_evidence("查询", items, llm_client=object())
        self.assertEqual(len(out), 5)
        self.assertTrue(block["fallback"])

    def test_missing_verdict_entries_treated_as_keep(self):
        from angineer_core.retrieval_pipeline import admit_evidence

        items = self._items()
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.return_value = SimpleNamespace(text='[{"i":3,"keep":0}]')  # 只回一条（且<0.3）
            out, block = admit_evidence("查询", items, llm_client=object())
        self.assertEqual([item.item_id for item in out], ["0", "1", "2", "4"])  # 缺席条目按判 1 放宽
        self.assertEqual(block["dropped"], 1)

    def test_wrapped_object_output_parsed(self):
        from angineer_core.retrieval_pipeline import admit_evidence

        items = self._items()
        with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
            guarded.return_value = SimpleNamespace(text='{"admission": %s}' % self._VERDICTS)
            out, block = admit_evidence("查询", items, llm_client=object())
        self.assertEqual(len(out), 4)
        self.assertFalse(block["fallback"])

    def test_excerpt_capped_and_config_overridable(self):
        from angineer_core.retrieval_pipeline import admit_evidence

        items = [self._item("0", 0.5, text="长" * 5000), self._item("1", 0.5)]
        with mock.patch.dict(os.environ, {"ANGINEER_ADMISSION_EXCERPT_CHARS": "300"}):
            with mock.patch("angineer_core.retrieval_pipeline.chat_result_guarded") as guarded:
                guarded.return_value = SimpleNamespace(text='[{"i":0,"keep":1},{"i":1,"keep":1}]')
                admit_evidence("查询", items, llm_client=object())
        user_message = guarded.call_args.args[1][1]["content"]
        self.assertLess(len(user_message), 300 * 3)  # 摘录 ≤300 字符/条，5000 字长文未整段进 prompt
        self.assertEqual(guarded.call_args.kwargs["config_name"], "Qwen3.8-Flash-Next")


if __name__ == "__main__":
    unittest.main()

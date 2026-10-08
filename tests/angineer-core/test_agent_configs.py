"""P3.1 build_qa_config 装配单测。"""
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_configs import (  # noqa: E402
    QA_AGENT_SYSTEM_PROMPT,
    build_chat_config,
    build_qa_config,
    make_final_answer_guard,
)
from angineer_core.agent_messages import AgentMessage  # noqa: E402
from angineer_core.agent_tools import MarkerAllocator, _assign_cites  # noqa: E402
from docs_core.step09_query.protocols.contracts import RetrievedItem  # noqa: E402
from angineer_core.prompts import load  # noqa: E402
from angineer_core.tool_codec import TextToolCallCodec  # noqa: E402


class QaConfigTests(unittest.TestCase):
    def test_build_qa_config_assembles_three_readonly_tools(self):
        config = build_qa_config(
            llm=Mock(),
            doc_nodes=[],
            library_id="default",
            doc_ids=["doc-1"],
            task_type="definition_qa",
        )
        self.assertEqual([tool.name for tool in config.tools], [
            "knowledge_search",
            "table_search",
            "entity_search",
            "knowledge_stats",  # 废 meta_query 路由（2026-10-02）下沉 L1 统一工具箱
        ])
        self.assertTrue(all(tool.read_only for tool in config.tools))
        self.assertEqual(config.max_turns, 3)
        self.assertIsInstance(config.codec, TextToolCallCodec)
        self.assertIn("检索证据", config.system_prompt)
        self.assertIn("没有检索到足够证据支持最终结论", config.system_prompt)

    def test_custom_tools_override(self):
        tool = Mock(name="custom_tool")
        config = build_qa_config(llm=Mock(), tools=[tool], max_turns=5)
        self.assertEqual(config.tools, [tool])
        self.assertEqual(config.max_turns, 5)

    def test_followup_rule_appended_when_env_true(self):
        with patch.dict(os.environ, {"ANGINEER_FOLLOWUP_QUESTION": "true"}, clear=False):
            config = build_qa_config(llm=Mock())
        self.assertIn("末尾追问规则", config.system_prompt)
        self.assertIs(config.followup_question, True)

    def test_followup_rule_absent_when_env_false(self):
        """关闭追问只移除追问规则，不回退到兼容导出的旧版提示词。"""
        with patch.dict(os.environ, {
            "ANGINEER_FOLLOWUP_QUESTION": "false",
            "ANGINEER_QA_PROMPT_VERSION": "latest",
        }, clear=False):
            config = build_qa_config(llm=Mock())
        self.assertEqual(config.system_prompt, load("agent_configs.qa_system_prompt"))
        self.assertIs(config.followup_question, False)

    def test_followup_defaults_on_and_explicit_param_wins(self):
        """显式关闭追问优先于环境开关，且保留所选 QA 版本。"""
        with patch.dict(os.environ, {
            "ANGINEER_FOLLOWUP_QUESTION": "true",
            "ANGINEER_QA_PROMPT_VERSION": "latest",
        }, clear=False):
            config_default = build_qa_config(llm=Mock())
            config_off = build_qa_config(llm=Mock(), followup_question=False)
        self.assertTrue(config_default.followup_question)
        self.assertFalse(config_off.followup_question)
        self.assertEqual(config_off.system_prompt, load("agent_configs.qa_system_prompt"))

    def test_guard_appends_followup_question_on_refusal_when_enabled(self):
        from angineer_core.agent_messages import REFUSAL_FOLLOWUP_QUESTION

        guard = make_final_answer_guard(enforce_evidence=True, followup_question=True)
        added = [
            AgentMessage(role="tool", content='{"items": []}', is_error=False),
            AgentMessage(role="assistant", content="测试答案"),
        ]
        result = guard(added)
        self.assertIsNotNone(result)
        answer, _note, code = result
        self.assertIn(REFUSAL_FOLLOWUP_QUESTION, answer)
        self.assertEqual(code, "no_evidence")

    def test_guard_refusal_plain_when_disabled(self):
        from angineer_core.qa_pipeline import REFUSAL_ANSWER_TEXT

        guard = make_final_answer_guard(enforce_evidence=True, followup_question=False)
        added = [
            AgentMessage(role="tool", content='{"items": []}', is_error=False),
            AgentMessage(role="assistant", content="测试答案"),
        ]
        result = guard(added)
        self.assertIsNotNone(result)
        answer, _note, code = result
        self.assertEqual(answer, REFUSAL_ANSWER_TEXT)
        self.assertEqual(code, "no_evidence")

    def test_guard_notes_refusal_kept_even_with_evidence(self):
        """有有效证据时模型仍拒答：守卫不替换内容，但留 trace 注记暴露异常。"""
        guard = make_final_answer_guard(enforce_evidence=True)
        added = [
            AgentMessage(
                role="tool",
                content='{"items": [{"item_id": "a", "text": "集成 17 类算法、12 个模型", "metadata": {"cite": "K1"}}]}',
                is_error=False,
            ),
            AgentMessage(role="assistant", content="没有检索到足够证据支持最终结论。"),
        ]
        result = guard(added)
        self.assertIsNotNone(result)
        answer, note, code = result
        self.assertEqual(answer, "没有检索到足够证据支持最终结论。")
        self.assertIn("拒答", note)
        self.assertEqual(code, "refusal_kept")

    def test_knowledge_search_and_table_search_use_separate_task_types(self):
        captured = {}

        def fake_knowledge(**kwargs):
            captured["knowledge"] = kwargs
            return Mock(name="knowledge_tool")

        def fake_table(**kwargs):
            captured["table"] = kwargs
            return Mock(name="table_tool")

        with patch(
            "angineer_core.agent_configs.RetrieverAdapter.knowledge_search",
            side_effect=fake_knowledge,
        ), patch(
            "angineer_core.agent_configs.RetrieverAdapter.table_search",
            side_effect=fake_table,
        ):
            build_qa_config(
                llm=Mock(),
                task_type="table_qa",
                knowledge_task_type="content_qa",
            )
        self.assertEqual(captured["knowledge"]["task_type"], "content_qa")
        # table_search 内部固定走 table_qa，不需要外部传入 task_type
        self.assertNotIn("task_type", captured["table"])

    def test_inline_citations_appended_to_prompt(self):
        config = build_qa_config(
            llm=Mock(),
            inline_citations=[
                {
                    "label": "S1",
                    "reference": {"docTitle": "规范A", "content": "5.4.12 条内容"},
                }
            ],
        )
        self.assertIn("规范A", config.system_prompt)
        self.assertIn("显式引用证据", config.system_prompt)

    def test_system_prompt_constant_documented(self):
        self.assertTrue(QA_AGENT_SYSTEM_PROMPT.startswith("你是一个工程规范领域"))

    def test_build_chat_config_has_no_tools(self):
        config = build_chat_config(llm=Mock())
        self.assertEqual(config.tools, [])
        self.assertEqual(config.max_turns, 1)
        self.assertIsInstance(config.codec, TextToolCallCodec)

    def test_cite_markers_assigned(self):
        items = [RetrievedItem(item_id="a", entity_type="content", doc_id="d",
                                title="t", text="x", score=1.0, metadata={}),
                 RetrievedItem(item_id="b", entity_type="content", doc_id="d",
                               title="t", text="y", score=1.0, metadata={})]
        allocator = MarkerAllocator()
        _assign_cites(items, allocator, "K")
        self.assertEqual(items[0].metadata["cite"], "K1")
        self.assertEqual(items[1].metadata["cite"], "K2")

    def test_allocator_unique_across_calls(self):
        allocator = MarkerAllocator()
        first = [RetrievedItem(item_id="a", entity_type="content", doc_id="d",
                               title="t", text="x", score=1.0, metadata={})]
        second = [RetrievedItem(item_id="b", entity_type="content", doc_id="d",
                                title="t", text="y", score=1.0, metadata={})]
        _assign_cites(first, allocator, "K")
        _assign_cites(second, allocator, "K")
        self.assertEqual(first[0].metadata["cite"], "K1")
        self.assertEqual(second[0].metadata["cite"], "K2")

    def test_qa_config_installs_guard_even_without_enforce_evidence(self):
        config = build_qa_config(llm=Mock(), enforce_evidence=False)
        self.assertIsNotNone(config.final_answer_guard)

    def test_build_qa_config_accepts_marker_allocator(self):
        config = build_qa_config(llm=Mock(), marker_allocator=MarkerAllocator())
        self.assertEqual([tool.name for tool in config.tools], [
            "knowledge_search",
            "table_search",
            "entity_search",
            "knowledge_stats",  # 废 meta_query 路由（2026-10-02）下沉 L1 统一工具箱
        ])

    def test_guard_removes_invalid_markers(self):
        guard = make_final_answer_guard(enforce_evidence=False)
        added = [AgentMessage(role="tool", content='{"items": [{"item_id":"a","text":"x","metadata":{"cite":"K1"}}]}')]
        new_answer, note, code = guard([*added, AgentMessage(role="assistant", content="依据 [K1] 和 [K9] 作答")])
        self.assertNotIn("[K9]", new_answer)
        self.assertIn("无效引用标记", note)
        self.assertEqual(code, "markers_cleaned")

    def test_guard_strips_markers_without_tool_messages(self):
        """模型没调工具却输出 [Kx] 时，视为编造标记并清理，但不强制拒答。"""
        guard = make_final_answer_guard(enforce_evidence=True)
        new_answer, note, code = guard([AgentMessage(role="assistant", content="航道水深由吃水加富裕深度确定 [K12]。")])
        self.assertNotIn("[K12]", new_answer)
        self.assertIn("无效引用标记", note)
        self.assertIn("吃水加富裕深度", new_answer)
        self.assertEqual(code, "markers_cleaned")


class HalfRefusalStripTests(unittest.TestCase):
    """P1：半拒答只删开头那句「没有检索到足够证据支持最终结论」，保留带引用的正文。

    「证据不足/部分未覆盖」这类软表述是 prompt 要求模型如实说明的部分覆盖提示，
    属于合法回答，不能删（旧实现 ANGINEER_GUARD_HALF_REFUSAL 整体替换成纯拒答，
    会把正文一起丢掉）。
    """

    EVIDENCE = (
        '{"items": [{"item_id": "a", "text": "王飞，2012 年 7 月入职，负责对外经营",'
        ' "metadata": {"cite": "K1"}}]}'
    )
    FACT = "王飞于 2012 年 7 月入职，并担任项目经理 [K1]。"

    def _added(self, answer):
        return [
            AgentMessage(role="tool", content=self.EVIDENCE, is_error=False),
            AgentMessage(role="assistant", content=answer),
        ]

    def test_guard_strips_hard_refusal_lead_and_keeps_body(self):
        guard = make_final_answer_guard(enforce_evidence=True)
        answer = "没有检索到足够证据支持最终结论。" + "已核对到的内容如下：" + self.FACT * 4
        self.assertGreater(len(answer), 120)  # is_half_refusal_text 的长度门槛

        result = guard(self._added(answer))
        self.assertIsNotNone(result)
        new_answer, note, code = result
        self.assertNotIn("没有检索到足够证据支持最终结论", new_answer)
        self.assertIn("[K1]", new_answer)
        self.assertIn("半拒答", note)
        self.assertEqual(code, "half_refusal_stripped")

    def test_guard_keeps_soft_partial_coverage_disclosure(self):
        guard = make_final_answer_guard(enforce_evidence=True)
        answer = "证据不足的部分未覆盖。" + "已支持的内容如下：" + self.FACT * 4
        self.assertGreater(len(answer), 120)

        self.assertIsNone(guard(self._added(answer)))

    def test_guard_keeps_reference_refusal_intact(self):
        """第三档拒答（拒答开头+「供参考」相邻片段，prompt 规则 16 的合法收尾）：
        不剥开头——剥掉会失去拒答标记，被评测当成幻觉作答判 0。"""
        guard = make_final_answer_guard(enforce_evidence=True)
        answer = (
            "没有检索到足够证据支持最终结论。未找到无冲突梯度的直接说明。"
            "以下相关信息供参考：" + self.FACT * 4
        )
        self.assertGreater(len(answer), 120)

        result = guard(self._added(answer))
        self.assertIsNotNone(result)
        new_answer, note, code = result
        self.assertEqual(new_answer, answer)
        self.assertIn("拒答", note)
        self.assertEqual(code, "refusal_kept")

    def test_strip_helper_leaves_normal_and_empty_untouched(self):
        from angineer_core.agent_messages import strip_half_refusal_lead

        normal = self.FACT * 5
        self.assertEqual(strip_half_refusal_lead(normal), normal)
        self.assertEqual(strip_half_refusal_lead(""), "")

    def test_strip_helper_leaves_reference_refusal_untouched(self):
        from angineer_core.agent_messages import strip_half_refusal_lead

        answer = (
            "没有检索到足够证据支持最终结论。未找到无冲突梯度的直接说明。"
            "以下相关信息供参考：" + self.FACT * 4
        )
        self.assertEqual(strip_half_refusal_lead(answer), answer)

    def test_reference_refusal_requires_both_signal_and_marker(self):
        """「供参考」单出现不算第三档（防误伤正常作答）；拒答标记单出现只是普通拒答。"""
        from angineer_core.agent_messages import is_reference_refusal

        self.assertFalse(is_reference_refusal("以下相关信息供参考：" + self.FACT * 4))
        self.assertFalse(is_reference_refusal("没有检索到足够证据支持最终结论。"))
        self.assertTrue(is_reference_refusal(
            "没有检索到足够证据支持最终结论。以下相关信息供参考：" + self.FACT
        ))


class JsonEnvelopeGuardTests(unittest.TestCase):
    """occamy 关思考实测（run-94c0ac9e9e3f / run-55a16e545304）的两类围栏 JSON 形态。

    模型把错误 JSON / {"answer": ...} 信封带 ```json 围栏当最终答案吐出：
    旧守卫 startswith("{") 落空全部漏检，用户直接看到 JSON 坨。
    """

    @staticmethod
    def _tool_with_k16():
        return AgentMessage(
            role="tool",
            content='{"items": [{"item_id":"a","text":"SI-SDR 从 14.67 升至 22.36","metadata":{"cite":"K16"}}]}',
            is_error=False,
        )

    def test_fenced_error_json_replaced_with_refusal(self):
        """生产真实原文形态：带围栏的空 error 模板必须换成标准拒答话术。"""
        guard = make_final_answer_guard(enforce_evidence=True)
        new_answer, note, code = guard([
            self._tool_with_k16(),
            AgentMessage(role="assistant", content='```json\n{"error": ""}\n```'),
        ])
        self.assertEqual(code, "tool_error_json")
        self.assertIn("没有检索到足够证据", new_answer)

    def test_single_key_answer_envelope_unwrapped(self):
        guard = make_final_answer_guard(enforce_evidence=False)
        new_answer, note, code = guard([
            self._tool_with_k16(),
            AgentMessage(role="assistant", content='```json\n{"answer": "SI-SDR 随信噪比升高而提升 [K16]。"}\n```'),
        ])
        self.assertEqual(code, "answer_envelope_unwrapped")
        self.assertEqual(new_answer, "SI-SDR 随信噪比升高而提升 [K16]。")

    def test_multi_key_or_bad_json_envelopes_pass_through(self):
        """三把锁负例：多键、非字符串值、坏 JSON 都原样放过（不误伤点名要 JSON 的输出）。"""
        guard = make_final_answer_guard(enforce_evidence=False)
        for content in (
            '```json\n{"answer": "x", "confidence": 0.9}\n```',
            '```json\n{"answer": {"nested": 1}}\n```',
            '```json\n{"answer": "未闭合的信封\n```',
        ):
            self.assertIsNone(guard([self._tool_with_k16(), AgentMessage(role="assistant", content=content)]), content[:40])

    def test_real_6d3204_envelope_end_to_end(self):
        """run-55a16e545304 真实原文：信封内文实为拒答+「供参考」，拆封后判分豁免须能认出。"""
        from angineer_core.agent_messages import is_substantive_refusal

        inner = (
            "检索后未覆盖：知识库中没有以“教室/课堂（classroom）”为直接陈述对象的 ASR 挑战证据。"
            "以下相邻内容供参考：\n- 社交/活动场景中，听觉环境常包含多个说话人混合 [K16]。"
        )
        import json as _json

        envelope = '```json\n%s\n```' % _json.dumps({"answer": inner}, ensure_ascii=False)
        guard = make_final_answer_guard(enforce_evidence=False)
        new_answer, note, code = guard([
            self._tool_with_k16(),
            AgentMessage(role="assistant", content=envelope),
        ])
        self.assertEqual(code, "answer_envelope_unwrapped")
        self.assertEqual(new_answer, inner)
        # 拆封后判分链路（refusal_expected=True 的实质拒答豁免）从「未覆盖」开篇认出拒答
        self.assertTrue(is_substantive_refusal(new_answer))


class RefusalKeptMarkerCleanTests(unittest.TestCase):
    """2026-10-04 验收（生产 session chat-mutxuj82-bwr5de seq 14）：L2→L1 回退段检索全空、
    守卫走 refusal_kept 保留「拒答头+相邻片段」原文——原文里跨轮照抄的 [K5]/[K4]
    （本轮无任何 cite 分配）必须剥净，不能裸给用户；证据内标记不得误剥。

    背景：用户实测拒答形态回答里 [K5]/[K1][K6] 裸标记未渲染成圆标；
    数据侧 meta.citations 为空（本轮零命中）、正文标记来自上一轮，前端无对应引用可渲染。
    """

    @staticmethod
    def _empty_tool():
        return AgentMessage(role="tool", content='{"items": [], "total": 0}', is_error=False)

    def test_refusal_kept_strips_bad_markers_when_evidence_empty(self):
        guard = make_final_answer_guard(enforce_evidence=False)
        answer = (
            "没有检索到足够证据支持最终结论。未找到关于“乘潮水位”具体计算方法或公式的直接证据。"
            "以下相关信息供参考：\n"
            "- 水运工程混凝土结构设计需考虑结构所处的环境条件…与潮汐作用密切相关 [K5]。\n"
            "- 需符合《海港工程混凝土结构防腐蚀技术规范》的相关规定 [K4]。"
        )
        new_answer, note, code = guard([
            self._empty_tool(),
            AgentMessage(role="assistant", content=answer),
        ])
        self.assertEqual(code, "refusal_kept")
        self.assertNotIn("[K5]", new_answer)
        self.assertNotIn("[K4]", new_answer)
        self.assertIn("没有检索到足够证据", new_answer)   # 拒答头保留
        self.assertIn("以下相关信息供参考", new_answer)     # 相邻片段形态保留

    def test_refusal_kept_keeps_valid_markers(self):
        guard = make_final_answer_guard(enforce_evidence=False)
        answer = "没有检索到足够证据支持最终结论。以下相关信息供参考：\n- 相邻片段 [K16]。"
        new_answer, note, code = guard([
            JsonEnvelopeGuardTests._tool_with_k16(),
            AgentMessage(role="assistant", content=answer),
        ])
        self.assertEqual(code, "refusal_kept")
        self.assertIn("[K16]", new_answer)  # 证据内标记不得误剥

    def test_half_refusal_stripped_cleans_bad_markers(self):
        guard = make_final_answer_guard(enforce_evidence=False)
        # 门槛：strip_half_refusal_lead 要求 >120 字且含引用（短文本不剥）；本条同时验证
        # 剥头后正文里的无效标记一并剥净、证据内标记保留
        answer = (
            "没有检索到足够证据支持最终结论。根据现有资料，水运工程混凝土结构的耐久性设计"
            "应结合环境条件与设计使用年限确定最低强度等级、最大水胶比与氯离子含量限制，"
            "构造措施上还需控制裂缝宽度并保证保护层厚度满足规范要求 [K16]；"
            "另有若干相邻条文涉及防腐蚀附加措施与施工阶段验算，可作延伸阅读 [K9]。"
        )
        new_answer, note, code = guard([
            JsonEnvelopeGuardTests._tool_with_k16(),
            AgentMessage(role="assistant", content=answer),
        ])
        self.assertEqual(code, "half_refusal_stripped")
        self.assertNotIn("[K9]", new_answer)
        self.assertIn("[K16]", new_answer)
        self.assertNotIn("没有检索到足够证据", new_answer)

    def test_end_to_end_l2_fallback_real_text(self):
        """生产真实原文（seq 14 节选）：空证据 + refusal_kept 路径按最终用户可见形态验证。"""
        guard = make_final_answer_guard(enforce_evidence=False)
        answer = (
            "没有检索到足够证据支持最终结论。未找到关于“乘潮水位”具体计算方法或公式的直接证据。"
            "以下相关信息供参考：\n\n"
            "- 水运工程混凝土结构设计需考虑结构所处的环境条件，包括海水环境中的水位变动区、"
            "浪溅区等，这些区域与潮汐作用密切相关 [K5]。\n"
            "- 对于有防腐蚀要求的构件，其设计需符合《海港工程混凝土结构防腐蚀技术规范》的"
            "相关规定 [K4]。\n"
            "- 水运工程混凝土施工与设计应遵循《水运工程混凝土结构设计规范》、"
            "《水运工程混凝土施工规范》等国家标准 [K1][K6]。"
        )
        new_answer, note, code = guard([
            self._empty_tool(),
            AgentMessage(role="assistant", content=answer),
        ])
        for marker in ("[K1]", "[K4]", "[K5]", "[K6]"):
            self.assertNotIn(marker, new_answer)
        self.assertIn("以下相关信息供参考", new_answer)


class ExternalCitationStripGuardTests(unittest.TestCase):
    """方案 A（2026-10-08，业主拍板）：外部文献名引用降为剥标记、不整答替换。

    生产误杀形态：v16 答案「根据《论文真题名》第Y节…」，证据 doc_title 是文件名
    （2404.09358v3.pdf）核不到标题、章节号也核不到——两晚 guard_replaced_unsupported_ref
    30+ 题好答案整答换拒答。现在只摘出处标记，正文照常作答。
    """

    @staticmethod
    def _tool_unrelated_evidence():
        return AgentMessage(
            role="tool",
            content='{"items": [{"item_id":"a","text":"该方法在基准测试上准确率为 87%","metadata":{"cite":"K1"}}]}',
            is_error=False,
        )

    def test_absent_paper_title_strips_marker_keeps_body(self):
        guard = make_final_answer_guard(enforce_evidence=True)
        new_answer, note, code = guard([
            self._tool_unrelated_evidence(),
            AgentMessage(role="assistant", content="根据《不存在的论文真题名》第3.1节，该方法准确率为 87% [K1]。"),
        ])
        self.assertEqual(code, "external_citation_stripped")
        self.assertNotIn("《不存在的论文真题名》", new_answer)
        self.assertIn("该方法准确率为 87%", new_answer)
        self.assertIn("[K1]", new_answer)
        self.assertIn("已摘除出处标记", note)

    def test_grounded_title_untouched(self):
        guard = make_final_answer_guard(enforce_evidence=True)
        added = [
            AgentMessage(
                role="tool",
                content='{"items": [{"item_id":"a","text":"《2404.09358v3.pdf》 正文片段","metadata":{"cite":"K1"}}]}',
                is_error=False,
            ),
            AgentMessage(role="assistant", content="根据《2404.09358v3.pdf》第4节，结论成立。"),
        ]
        self.assertIsNone(guard(added))

    def test_fabricated_spec_number_still_replaced(self):
        guard = make_final_answer_guard(enforce_evidence=True)
        new_answer, note, code = guard([
            self._tool_unrelated_evidence(),
            AgentMessage(role="assistant", content="依据 JTS 999-2020 第4.2条，答案为 42。"),
        ])
        self.assertEqual(code, "unsupported_reference")
        self.assertIn("没有检索到足够证据", new_answer)

    def test_stripped_answer_reaches_answer_branch_after_title_strip(self):
        """标题剥除与无效标记清理叠加：正文保留、[K9] 编造标记同场清掉。"""
        guard = make_final_answer_guard(enforce_evidence=True)
        new_answer, note, code = guard([
            self._tool_unrelated_evidence(),
            AgentMessage(role="assistant", content="根据《不存在的论文真题名》第3.1节，准确率为 87% [K1] [K9]。"),
        ])
        self.assertEqual(code, "external_citation_stripped")
        self.assertNotIn("[K9]", new_answer)
        self.assertIn("[K1]", new_answer)
        self.assertIn("无效引用标记", note)


if __name__ == "__main__":
    unittest.main()

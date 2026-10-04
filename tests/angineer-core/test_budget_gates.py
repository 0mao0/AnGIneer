"""P4.3 预算闸门：make_budget_transformer / make_budget_stopper 单元测试。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_configs import (  # noqa: E402
    make_budget_stopper,
    make_budget_transformer,
)
from angineer_core.agent_loop import TurnContext  # noqa: E402
from angineer_core.agent_messages import AgentMessage  # noqa: E402


def estimate(messages):
    return sum(len(m.content or "") for m in messages) // 2


class BudgetTransformerTests(unittest.TestCase):
    def test_under_budget_leaves_messages_unchanged(self):
        messages = [
            AgentMessage(role="user", content="问题"),
            AgentMessage(role="tool", name="knowledge_search", content="K" * 200, meta={"items": [], "total": 0}),
        ]
        transformer = make_budget_transformer(max_tokens_est=1000)
        out = transformer(messages)
        self.assertIs(out, messages)
        self.assertEqual(out[1].content, "K" * 200)

    def test_over_budget_compresses_oldest_first(self):
        messages = [
            AgentMessage(role="user", content="Q" * 1000),
            AgentMessage(role="tool", name="knowledge_search", content="K" * 5000, meta={"items": [{"item_id": "i1"}], "total": 1}),
            AgentMessage(role="tool", name="table_search", content="T" * 5000, meta={"items": [], "total": 0}),
        ]
        transformer = make_budget_transformer(max_tokens_est=2000)
        out = transformer(messages)
        self.assertLessEqual(estimate(out), 2000)
        self.assertTrue(out[1].content.startswith("[已压缩: 工具 knowledge_search 的结果"))
        self.assertTrue(out[2].content.startswith("[已压缩: 工具 table_search 的结果"))
        self.assertIn("检索到 1 条候选", out[1].content)

    def test_projection_does_not_mutate_history(self):
        """2026-09-24 投影式改造：压缩只作用于返回的副本，原消息列表/对象不动。"""
        original_tool = AgentMessage(
            role="tool", name="knowledge_search",
            content="K" * 5000, meta={"items": [{"item_id": "i1"}], "total": 1},
        )
        messages = [AgentMessage(role="user", content="Q" * 1000), original_tool]
        transformer = make_budget_transformer(max_tokens_est=100)
        out = transformer(messages)

        self.assertTrue(out[1].content.startswith("[已压缩:"))
        self.assertEqual(original_tool.content, "K" * 5000)  # 本体未被改写
        self.assertIsNot(out, messages)
        self.assertIsNot(out[1], original_tool)
        self.assertNotIn("_budget_summary", original_tool.meta)  # 摘要不再写进 meta

    def test_summary_cached_across_calls(self):
        """闭包缓存：同一批消息对象重复 transform，结果一致（摘要不重复计算）。"""
        messages = [
            AgentMessage(role="user", content="Q" * 1000),
            AgentMessage(role="tool", name="knowledge_search", content="K" * 5000, meta={"items": [{"item_id": "i1"}], "total": 1}),
        ]
        transformer = make_budget_transformer(max_tokens_est=100)
        out = transformer(messages)
        out2 = transformer(messages)
        self.assertEqual(out2[1].content, out[1].content)
        self.assertIn("检索到 1 条候选", out2[1].content)

    def test_sop_raw_summary_counts_successful_steps(self):
        messages = [
            AgentMessage(role="user", content="Q" * 1000),
            AgentMessage(
                role="tool",
                name="sop_execute",
                content="x" * 5000,
                meta={
                    "sop_id": "sop-1",
                    "sop_trace": [
                        {"step_id": "s1", "status": "success"},
                        {"step_id": "s2", "status": "failed"},
                    ],
                },
            ),
        ]
        transformer = make_budget_transformer(max_tokens_est=100)
        out = transformer(messages)
        self.assertIn("SOP sop-1 执行 2 步，成功 1 步", out[1].content)


class BudgetStopperTests(unittest.TestCase):
    def test_stops_when_over_threshold(self):
        stopper = make_budget_stopper(threshold=500)
        context = TurnContext(
            turn=2,
            messages=[AgentMessage(role="tool", content="X" * 2000)],
            tool_results=[],
            usage={},
        )
        self.assertTrue(stopper(context))

    def test_does_not_stop_under_threshold(self):
        stopper = make_budget_stopper(threshold=500)
        context = TurnContext(
            turn=1,
            messages=[AgentMessage(role="tool", content="x" * 100)],
            tool_results=[],
            usage={},
        )
        self.assertFalse(stopper(context))

    def test_default_threshold_reads_env(self):
        """plan-evidence-admission D：停止线 env 化（ANGINEER_BUDGET_STOPPER_EST），显式传参仍优先。"""
        context = TurnContext(
            turn=1,
            messages=[AgentMessage(role="tool", content="x" * 300)],  # est=150
            tool_results=[],
            usage={},
        )
        with mock.patch.dict(os.environ, {"ANGINEER_BUDGET_STOPPER_EST": "100"}):
            self.assertTrue(make_budget_stopper()(context))
            self.assertFalse(make_budget_stopper(threshold=10_000)(context))  # 显式参数优先

    def test_default_without_env_is_120k(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            context = TurnContext(
                turn=1,
                messages=[AgentMessage(role="tool", content="x" * 200_000)],  # est=100k
                tool_results=[],
                usage={},
            )
            self.assertFalse(make_budget_stopper()(context))  # 100k < 默认 120k


class QaProtectCurrentRunTests(unittest.TestCase):
    """需求 A1（QA 档）：当轮证据不压，只压跨 run 历史工具结果。"""

    def test_only_history_tools_compressed(self):
        history_tool = AgentMessage(
            role="tool", name="knowledge_search", content="K" * 5000,
            meta={"items": [{"item_id": "i1"}], "total": 1},
        )
        current_tool = AgentMessage(
            role="tool", name="knowledge_search", content="C" * 5000,
            meta={"items": [{"item_id": "i2"}], "total": 1},
        )
        messages = [
            AgentMessage(role="user", content="旧问题"),
            history_tool,
            AgentMessage(role="assistant", content="旧答案"),
            AgentMessage(role="user", content="新问题"),
            current_tool,
        ]
        transformer = make_budget_transformer(max_tokens_est=100, protect_current_run=True)
        out = transformer(messages)
        self.assertTrue(out[1].content.startswith("[已压缩:"))
        self.assertEqual(out[4].content, "C" * 5000)  # 本 run 证据必须完整在手
        self.assertEqual(out[0].content, "旧问题")
        self.assertEqual(out[2].content, "旧答案")
        self.assertEqual(history_tool.content, "K" * 5000)  # 投影式：本体不动

    def test_boundary_skips_injected_user_prompts(self):
        """req-chat-history-bloat §5.1.3：run 内 retry 注入的内部 user 提示不得把当轮边界后移。

        复现：当轮证据 tool 消息之后、retry 注入「已检索到有效证据…」提示，
        旧划界（最后一条 user）把边界移到注入提示处，当轮证据反落可压区。
        """
        current_tool = AgentMessage(
            role="tool", name="knowledge_search", content="C" * 5000,
            meta={"items": [{"item_id": "i2"}], "total": 1},
        )
        messages = [
            AgentMessage(role="user", content="新问题"),
            current_tool,
            AgentMessage(role="user", content="已检索到有效证据，请基于证据作答；若证据只覆盖部分内容，请回答已支持的部分并明确说明缺失项，不要整体拒答。"),
        ]
        transformer = make_budget_transformer(max_tokens_est=100, protect_current_run=True)
        out = transformer(messages)
        self.assertEqual(out[1].content, "C" * 5000)  # 当轮证据绝不可压
        self.assertEqual(current_tool.content, "C" * 5000)

    def test_boundary_still_protects_tools_after_real_user(self):
        """对照：注入提示之后新产出的工具结果同样受保护（边界仍在真实 user 处）。"""
        late_tool = AgentMessage(
            role="tool", name="knowledge_search", content="L" * 5000,
            meta={"items": [], "total": 0},
        )
        messages = [
            AgentMessage(role="user", content="旧问题"),
            AgentMessage(role="tool", name="knowledge_search", content="K" * 5000, meta={"items": [], "total": 0}),
            AgentMessage(role="user", content="新问题"),
            AgentMessage(role="user", content="请先调用检索工具获取证据后再回答"),
            late_tool,
        ]
        transformer = make_budget_transformer(max_tokens_est=100, protect_current_run=True)
        out = transformer(messages)
        self.assertTrue(out[1].content.startswith("[已压缩:"))  # 历史仍压
        self.assertEqual(out[4].content, "L" * 5000)  # 注入提示后的当轮证据不压

    def test_complex_default_still_compresses_all_tools(self):
        """complex 档（protect_current_run 默认 False）语义不变：run 内部也压最旧工具结果。"""
        current_tool = AgentMessage(
            role="tool", name="knowledge_search", content="C" * 5000,
            meta={"items": [], "total": 0},
        )
        messages = [AgentMessage(role="user", content="问题"), current_tool]
        transformer = make_budget_transformer(max_tokens_est=100)
        out = transformer(messages)
        self.assertTrue(out[1].content.startswith("[已压缩:"))


class QaBudgetMountTests(unittest.TestCase):
    """QA 档装配：默认挂投影预算闸，env 可改阈值/设 0 关闭。"""

    @staticmethod
    def _config(**kwargs):
        from agent_test_utils import MockLLM, text_events

        from angineer_core.agent_configs import build_qa_config

        llm = MockLLM(lambda messages, kw: text_events("答案"))
        return build_qa_config(llm=llm, config_name="t", library_id="default", **kwargs)

    def test_transformer_mounted_by_default(self):
        self.assertIsNotNone(self._config().transform_context)

    def test_env_zero_disables_mount(self):
        from unittest import mock

        with mock.patch.dict(os.environ, {"ANGINEER_QA_BUDGET_TOKENS_EST": "0"}):
            self.assertIsNone(self._config().transform_context)

    def test_mounted_transformer_uses_qa_threshold(self):
        """默认阈值：历史工具结果 ~70k 字符（est 35k）应触发压缩、当轮不压。"""
        config = self._config()
        transform = config.transform_context
        messages = [
            AgentMessage(role="user", content="旧问题"),
            AgentMessage(role="tool", name="knowledge_search", content="K" * 70000, meta={"items": [], "total": 0}),
            AgentMessage(role="assistant", content="旧答案"),
            AgentMessage(role="user", content="新问题"),
            AgentMessage(role="tool", name="knowledge_search", content="C" * 20000, meta={"items": [], "total": 0}),
        ]
        out = transform(messages)
        self.assertTrue(out[1].content.startswith("[已压缩:"))
        self.assertEqual(out[4].content, "C" * 20000)

    def test_env_parsing(self):
        from unittest import mock

        from angineer_core.agent_configs import _qa_budget_tokens_est

        with mock.patch.dict(os.environ, {"ANGINEER_QA_BUDGET_TOKENS_EST": "5000"}):
            self.assertEqual(_qa_budget_tokens_est(), 5000)
        with mock.patch.dict(os.environ, {"ANGINEER_QA_BUDGET_TOKENS_EST": "-9"}):
            self.assertEqual(_qa_budget_tokens_est(), 0)
        with mock.patch.dict(os.environ, {"ANGINEER_QA_BUDGET_TOKENS_EST": "abc"}):
            self.assertEqual(_qa_budget_tokens_est(), 16_000)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_qa_budget_tokens_est(), 16_000)

    def test_default_threshold_16k_est_from_ops_regression(self):
        """req-chat-history-bloat §5.1.3 定值：ops 回归 real/est p99=1.46，
        16k est × 1.46 ≈ 23.4k real < 25k 验收线。est 20k+ 桶 real p50 已 31.8k 超标。"""
        config = self._config()
        messages = [
            AgentMessage(role="user", content="旧问题"),
            AgentMessage(role="tool", name="knowledge_search", content="K" * 34000, meta={"items": [], "total": 0}),
            AgentMessage(role="user", content="新问题"),
        ]
        out = config.transform_context(messages)
        self.assertTrue(out[1].content.startswith("[已压缩:"))  # est 17k+ > 16k 必触发
        messages_under = [
            AgentMessage(role="user", content="旧问题"),
            AgentMessage(role="tool", name="knowledge_search", content="K" * 30000, meta={"items": [], "total": 0}),
            AgentMessage(role="user", content="新问题"),
        ]
        out2 = config.transform_context(messages_under)
        self.assertIs(out2, messages_under)  # est 15k < 16k 不触发


class ComplexBudgetMountTests(unittest.TestCase):
    """req-chat-history-bloat §5.1.4：complex 档 100k est 重估，env 可调。"""

    def test_complex_default_threshold_reduced(self):
        from unittest import mock

        from angineer_core.agent_configs import _complex_budget_tokens_est

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_complex_budget_tokens_est(), 24_000)

    def test_complex_env_override(self):
        from unittest import mock

        from angineer_core.agent_configs import _complex_budget_tokens_est

        with mock.patch.dict(os.environ, {"ANGINEER_COMPLEX_BUDGET_TOKENS_EST": "50000"}):
            self.assertEqual(_complex_budget_tokens_est(), 50_000)

    def test_complex_config_uses_env_default(self):
        """build_complex_config 不传 max_tokens_est 时走 env 默认值（est>24k 触发压缩）。"""
        from unittest import mock

        from angineer_core.agent_configs import build_complex_config

        with mock.patch.dict(os.environ, {}, clear=True):
            config = build_complex_config(llm=mock.Mock())
        messages = [
            AgentMessage(role="user", content="问题"),
            AgentMessage(role="tool", name="knowledge_search", content="K" * 60000, meta={"items": [], "total": 0}),
        ]
        out = config.transform_context(messages)
        self.assertTrue(out[1].content.startswith("[已压缩:"))  # est 30k > 24k 触发

    def test_complex_env_zero_disables_mount(self):
        from unittest import mock

        from angineer_core.agent_configs import build_complex_config

        with mock.patch.dict(os.environ, {"ANGINEER_COMPLEX_BUDGET_TOKENS_EST": "0"}):
            config = build_complex_config(llm=mock.Mock())
        self.assertIsNone(config.transform_context)

    def test_complex_explicit_param_still_wins(self):
        from unittest import mock

        from angineer_core.agent_configs import build_complex_config

        config = build_complex_config(llm=mock.Mock(), max_tokens_est=100_000)
        messages = [
            AgentMessage(role="user", content="问题"),
            AgentMessage(role="tool", name="knowledge_search", content="K" * 60000, meta={"items": [], "total": 0}),
        ]
        out = config.transform_context(messages)
        self.assertIs(out, messages)  # 显式 100k：est 30k 不触发


class ChatMetaBudgetMountTests(unittest.TestCase):
    """req-chat-history-bloat §5.1.1/5.1.2：L0 chat 与 meta 档补装投影预算闸。

    L0 无工具裸装即可；meta 有 knowledge_stats 工具（当轮统计结果在 user 之后），
    必须 protect_current_run=True，否则超阈值时当轮数字被压成摘要、统计答案失真。
    """

    def test_chat_mounts_transformer_by_default(self):
        from unittest import mock

        from angineer_core.agent_configs import build_chat_config

        config = build_chat_config(llm=mock.Mock(), config_name="t")
        self.assertIsNotNone(config.transform_context)

    def test_qa_mounts_transformer_by_default(self):
        from unittest import mock

        from angineer_core.agent_configs import build_qa_config

        config = build_qa_config(llm=mock.Mock(), config_name="t")
        self.assertIsNotNone(config.transform_context)

    def test_chat_env_zero_disables_mount(self):
        from unittest import mock

        from angineer_core.agent_configs import build_chat_config

        with mock.patch.dict(os.environ, {"ANGINEER_CHAT_BUDGET_TOKENS_EST": "0"}):
            config = build_chat_config(llm=mock.Mock(), config_name="t")
        self.assertIsNone(config.transform_context)

    def test_qa_env_zero_disables_mount(self):
        from unittest import mock

        from angineer_core.agent_configs import build_qa_config

        with mock.patch.dict(os.environ, {"ANGINEER_QA_BUDGET_TOKENS_EST": "0"}):
            config = build_qa_config(llm=mock.Mock(), config_name="t")
        self.assertIsNone(config.transform_context)

    def test_chat_transformer_compresses_history_tool_messages(self):
        """L0 闲聊轮：历史 QA 轮的检索证据被压掉（73k 重灾区的直接修复）。"""
        from unittest import mock

        from angineer_core.agent_configs import build_chat_config

        config = build_chat_config(llm=mock.Mock(), config_name="t")
        transform = config.transform_context
        messages = [
            AgentMessage(role="user", content="什么是乘潮水位？"),
            AgentMessage(role="tool", name="knowledge_search", content="K" * 70000, meta={"items": [], "total": 0}),
            AgentMessage(role="assistant", content="乘潮水位是……"),
            AgentMessage(role="user", content="你好，在么"),
        ]
        out = transform(messages)
        self.assertTrue(out[1].content.startswith("[已压缩:"))
        self.assertEqual(out[3].content, "你好，在么")

    def test_qa_transformer_protects_current_run_stats(self):
        """QA 档（knowledge_stats 下沉后，2026-10-02 废 meta 路由）：历史压、当轮 stats 结果不压。"""
        from unittest import mock

        from angineer_core.agent_configs import build_qa_config

        config = build_qa_config(llm=mock.Mock(), config_name="t")
        transform = config.transform_context
        messages = [
            AgentMessage(role="user", content="旧问题"),
            AgentMessage(role="tool", name="knowledge_search", content="K" * 70000, meta={"items": [], "total": 0}),
            AgentMessage(role="assistant", content="旧答案"),
            AgentMessage(role="user", content="库里有多少篇文档？"),
            AgentMessage(role="tool", name="knowledge_stats", content="S" * 20000, meta={"total": 42}),
        ]
        out = transform(messages)
        self.assertTrue(out[1].content.startswith("[已压缩:"))
        self.assertEqual(out[4].content, "S" * 20000)  # 当轮统计数字必须完整


class PointerSkeletonTests(unittest.TestCase):
    """臂 2「指针骨架」（docs/plan-blackboard-arms.md §1 变体 ii）。

    行为锁三件：① 开关默认关且关态与现状**逐字一致**（臂 1 可复现的前提）；
    ② 开态只在 base 之后追加，前缀与「检索到 N 条候选」不动（既有断言依赖）；
    ③ 指针有界（条数 + 总长），无可用字段时不追加（退化为现状）。
    """

    ITEMS = [
        {
            "doc_id": "doc-a",
            "title": "5 港口平面",
            "metadata": {
                "cite": "K1",
                "doc_title": "JTS 165-2013 海港总体设计规范",
                "section_path": "5 港口平面 / 5.3 港内水域",
                "clause_id": "JTS 165-2013 §5.3",
            },
        },
        {
            "doc_id": "doc-0cb1226b",
            "title": "表 3.2.6 作用分项系数表",
            "metadata": {"cite": "T1", "section_path": "表 3.2.6 作用分项系数表"},
        },
    ]

    def _compressed_tool_line(self, meta, name="knowledge_search"):
        """把单条 tool 消息压到超预算，取回压缩后的 content。"""
        messages = [
            AgentMessage(role="user", content="Q" * 1000),
            AgentMessage(role="tool", name=name, content="K" * 5000, meta=meta),
        ]
        out = make_budget_transformer(max_tokens_est=500)(messages)
        return out[1].content

    def test_switch_default_off_is_byte_identical(self):
        """未设开关：压缩行与现状逐字相同（这是「臂 1 = 现状」的机器化保证）。"""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANGINEER_POINTER_SKELETON", None)
            content = self._compressed_tool_line({"items": list(self.ITEMS), "total": 2})
        self.assertEqual(
            content,
            "[已压缩: 工具 knowledge_search 的结果，要点: 检索到 2 条候选]",
        )

    def test_switch_on_appends_pointers_keeping_prefix_and_base(self):
        """开态：前缀与「检索到 N 条候选」不动，其后才是指针；K/T 两类都要覆盖。"""
        with mock.patch.dict(os.environ, {"ANGINEER_POINTER_SKELETON": "1"}):
            content = self._compressed_tool_line({"items": list(self.ITEMS), "total": 2})
        self.assertTrue(content.startswith("[已压缩: 工具 knowledge_search 的结果，要点: 检索到 2 条候选"))
        self.assertIn("候选指针", content)
        # 实测规范名 23-26 字必须完整保留（20 字上限会把它截断，等于废掉指针的信息量）
        self.assertIn("K1=JTS 165-2013 海港总体设计规范/JTS 165-2013 §5.3", content)
        # table_search 无 doc_title → 退 doc_id，并带表名（section_path）
        self.assertIn("T1=doc-0cb1226b/表 3.2.6 作用分项系数表", content)
        self.assertTrue(content.endswith("]"))

    def test_switch_on_no_usable_pointer_falls_back_to_baseline(self):
        """开态但 item 无任何可用字段：不得吐出空的「候选指针」壳。"""
        meta = {"items": [{"item_id": "i1"}, {"item_id": "i2"}], "total": 2}
        with mock.patch.dict(os.environ, {"ANGINEER_POINTER_SKELETON": "1"}):
            content = self._compressed_tool_line(meta)
        self.assertEqual(content, "[已压缩: 工具 knowledge_search 的结果，要点: 检索到 2 条候选]")

    def test_switch_off_variants(self):
        """只有 true/1/yes/on 为开；其余值（含 off/0/空）一律关。"""
        for raw, expect_on in (("true", True), ("YES", True), ("on", True), ("1", True),
                               ("0", False), ("false", False), ("", False), ("off", False)):
            with mock.patch.dict(os.environ, {"ANGINEER_POINTER_SKELETON": raw}):
                content = self._compressed_tool_line({"items": list(self.ITEMS), "total": 2})
            self.assertEqual("候选指针" in content, expect_on, f"switch={raw!r}")

    def test_pointers_are_bounded(self):
        """条数 ≤5、总长有界：防长文档名把压缩行撑爆（预算闸的意义）。"""
        items = [
            {
                "doc_id": f"doc-{i}",
                "title": "很长的章节路径" * 6,
                "metadata": {"cite": f"K{i}", "doc_title": "超长文档名" * 8, "section_path": "深层章节" * 10},
            }
            for i in range(1, 21)
        ]
        with mock.patch.dict(os.environ, {"ANGINEER_POINTER_SKELETON": "1"}):
            content = self._compressed_tool_line({"items": items, "total": 20})
        self.assertLessEqual(content.count("="), 5)                 # 条数上限
        self.assertLessEqual(len(content), 280 + 80)                # 指针段总长上限（+模板与前缀）
        self.assertIn("…", content)                                 # 截断确实发生

    def test_doc_extension_stripped(self):
        """实测 98.3% 的 doc_title 带 `.pdf`：必须去掉，别让扩展名吃预算、也别进 prompt。"""
        meta = {"items": [{
            "doc_id": "d",
            "metadata": {
                "cite": "K1",
                "doc_title": "JTS 151-2011 水运工程混凝土结构设计规范.pdf",
                "section_path": "3 基本规定 / 3.4 耐久性规定",
            },
        }], "total": 1}
        with mock.patch.dict(os.environ, {"ANGINEER_POINTER_SKELETON": "1"}):
            content = self._compressed_tool_line(meta)
        self.assertIn("K1=JTS 151-2011 水运工程混凝土结构设计规范/3.4 耐久性规定", content)
        self.assertNotIn(".pdf", content)

    def test_section_path_uses_last_segment(self):
        """多段章节路径取最后一段：实测从头截断会保住泛化章节名、丢掉真正的条款号。"""
        meta = {"items": [{
            "doc_id": "d",
            "metadata": {
                "cite": "T1",
                "section_path": "7 斜坡式护岸设计 / 7.1 一般规定 / 7.2.2 斜坡式护岸顶高程的确定应符合下列规定。",
            },
        }], "total": 1}
        with mock.patch.dict(os.environ, {"ANGINEER_POINTER_SKELETON": "1"}):
            content = self._compressed_tool_line(meta, name="table_search")
        self.assertIn("7.2.2 斜坡式护岸顶高程的确定应符合下列规定", content)
        self.assertNotIn("7 斜坡式护岸设计", content)
        self.assertNotIn("规定。", content)  # 尾部句号裁掉

    def test_duplicate_body_merges_markers(self):
        """同 doc + 同 section 的重复条目：合并标记（T3,T4=…），而不是丢掉其中一个标记。

        标记是历史回答 `[Tx]` 的 join 键——整条去重会断掉被丢掉那个标记的引用链。
        """
        meta = {"items": [
            {"doc_id": "d", "metadata": {"cite": "T3", "section_path": "5 港口平面 / 5.10 陆域高程"}},
            {"doc_id": "d", "metadata": {"cite": "T4", "section_path": "5 港口平面 / 5.10 陆域高程"}},
            {"doc_id": "e", "metadata": {"cite": "T5", "section_path": "5 港口平面 / 5.11 码头面高程"}},
        ], "total": 3}
        with mock.patch.dict(os.environ, {"ANGINEER_POINTER_SKELETON": "1"}):
            content = self._compressed_tool_line(meta, name="table_search")
        self.assertIn("T3,T4=d/5.10 陆域高程", content)
        self.assertEqual(content.count("5.10 陆域高程"), 1)
        self.assertIn("T5=e/5.11 码头面高程", content)

    def test_budget_gate_still_satisfied_with_pointers(self):
        """开态下预算断言仍成立：指针不能让压缩失效。"""
        messages = [
            AgentMessage(role="user", content="Q" * 1000),
            AgentMessage(role="tool", name="knowledge_search",
                         content="K" * 5000, meta={"items": list(self.ITEMS), "total": 2}),
            AgentMessage(role="tool", name="table_search",
                         content="T" * 5000, meta={"items": list(self.ITEMS), "total": 2}),
        ]
        with mock.patch.dict(os.environ, {"ANGINEER_POINTER_SKELETON": "1"}):
            out = make_budget_transformer(max_tokens_est=2000)(messages)
        self.assertLessEqual(estimate(out), 2000)
        self.assertTrue(out[1].content.startswith("[已压缩: 工具 knowledge_search 的结果"))
        self.assertTrue(out[2].content.startswith("[已压缩: 工具 table_search 的结果"))

    def test_stats_and_entities_branches_unchanged(self):
        """非检索类分支不受影响：stats（无 items）与 entity_search（entities）不加指针。"""
        with mock.patch.dict(os.environ, {"ANGINEER_POINTER_SKELETON": "1"}):
            stats_line = self._compressed_tool_line({"total": 42, "name": "knowledge_stats"},
                                                    name="knowledge_stats")
            entity_line = self._compressed_tool_line({"entities": [{"id": "e1"}], "total": 1},
                                                     name="entity_search")
        self.assertNotIn("候选指针", stats_line)
        self.assertNotIn("候选指针", entity_line)
        self.assertIn("图谱检索到 1 个实体", entity_line)


if __name__ == "__main__":
    unittest.main()

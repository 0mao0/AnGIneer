"""P5 Prompt 资产化：loader / 迁移契约 / prompt_versions。"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.path.abspath(os.path.join(REPO_ROOT, "services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(REPO_ROOT, "services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(REPO_ROOT, "services/ai-inference/src")))
sys.path.insert(0, os.path.abspath(os.path.join(REPO_ROOT, "services/evals-core/src")))

from angineer_core.prompts import load, versions  # noqa: E402


class PromptsLoaderTests(unittest.TestCase):
    def test_load_returns_registered_prompt(self):
        text = load("dispatcher.chat_system_prompt")
        self.assertIn("你是 AnGIneer", text)

    def test_load_unknown_prompt_raises_keyerror(self):
        with self.assertRaises(KeyError):
            load("no_such_prompt")

    def test_load_specific_version(self):
        text = load("dispatcher.chat_system_prompt", version="v1")
        self.assertIn("工程规范领域", text)

    def test_versions_registry_non_empty(self):
        registry = versions()
        self.assertIsInstance(registry, dict)
        self.assertTrue(registry)
        for name, version in registry.items():
            self.assertIsInstance(name, str)
            self.assertTrue(version)


class PromptMigrationContractTests(unittest.TestCase):
    def test_dispatcher_dead_prompts_removed(self):
        """旧 Dispatcher 遗留 prompt 已清退：注册表不可加载，模块属性不存在。"""
        import angineer_core.prompts.dispatcher as dispatcher_module

        dead_registry_names = (
            "dispatcher.system_prompt_base",
            "dispatcher.system_prompt_rules_definition",
            "dispatcher.system_prompt_rules_locate",
            "dispatcher.system_prompt_rules_content",
            "dispatcher.system_prompt_choice_rules",
            "dispatcher.system_prompt_gap_analysis",
            "dispatcher.extract_system_prompt",
            "dispatcher.extract_user_choice",
            "dispatcher.extract_user_general",
            "dispatcher.judge_user_choice",
            "dispatcher.judge_user_choice_explicit",
            "dispatcher.judge_user_general",
            "dispatcher.judge_user_general_explicit",
            "dispatcher.sql_doc_qa_system_prompt",
            "dispatcher.sql_structured_qa_system_prompt",
            "dispatcher.sop_answer_compose_prompt",
            "dispatcher.sop_answer_system_prompt",
        )
        for name in dead_registry_names:
            with self.assertRaises(KeyError, msg=name):
                load(name)
        for attr in (
            "SYSTEM_PROMPT_BASE",
            "EXTRACT_SYSTEM_PROMPT",
            "SQL_DOC_QA_SYSTEM_PROMPT",
            "SOP_ANSWER_COMPOSE_PROMPT",
        ):
            self.assertFalse(hasattr(dispatcher_module, attr), attr)

    def test_dispatcher_smart_prompts_registered(self):
        from angineer_core.prompts.dispatcher import (
            SMART_EXECUTION_PROMPT,
            SMART_SELECT_TOOL_PROMPT,
            STEP_SUMMARY_PROMPT,
        )

        self.assertIn("intelligent agent dispatcher", SMART_SELECT_TOOL_PROMPT)
        self.assertIn("expert engineering calculation executor", SMART_EXECUTION_PROMPT)
        self.assertIn("专家系统的执行记录员", STEP_SUMMARY_PROMPT)

    def test_classifier_prompts_registered(self):
        from angineer_core.prompts.classifier import (
            CLASSIFY_INTENT_SYSTEM_PROMPT,
            ROUTE_SOP_SYSTEM_PROMPT,
        )

        self.assertIn("意图层级定义", CLASSIFY_INTENT_SYSTEM_PROMPT)
        self.assertIn("SOP 匹配器", ROUTE_SOP_SYSTEM_PROMPT)

    def test_agent_configs_reexports_prompts_constants(self):
        from angineer_core.agent_configs import (
            COMPLEX_AGENT_SYSTEM_PROMPT as COMPLEX,
            QA_AGENT_SYSTEM_PROMPT as QA,
        )
        from angineer_core.prompts.agent_configs import (
            COMPLEX_AGENT_SYSTEM_PROMPT as COMPLEX_SRC,
            QA_AGENT_SYSTEM_PROMPT as QA_SRC,
        )

        self.assertEqual(QA, QA_SRC)
        self.assertEqual(COMPLEX, COMPLEX_SRC)

    def test_qa_prompt_refusal_requires_tool_round_and_prefers_table_search(self):
        from angineer_core.prompts.agent_configs import QA_AGENT_SYSTEM_PROMPT as QA

        self.assertIn("调用检索工具后仍无有效证据时，直接回答：没有检索到足够证据支持最终结论", QA)
        self.assertIn("表格/公式定位类问题必须优先调用 table_search", QA)
        self.assertIn("条款/条文定位类问题必须优先调用 knowledge_search", QA)

    def test_qa_prompt_has_partial_evidence_rule(self):
        """证据只覆盖部分问题时，必须先答已支持部分并说明缺失项，禁止整体拒答。"""
        from angineer_core.prompts.agent_configs import QA_AGENT_SYSTEM_PROMPT as QA

        self.assertIn("只覆盖问题的部分内容", QA)
        self.assertIn("先回答证据已支持的部分", QA)
        self.assertIn("明确说明", QA)
        self.assertIn("禁止因答案不完整而整体拒答", QA)

    def test_followup_rule_avoids_leading_to_missing_content(self):
        from angineer_core.prompts.agent_configs import FOLLOWUP_QUESTION_RULE

        self.assertIn("已确认不存在", FOLLOWUP_QUESTION_RULE)
        self.assertIn("补充资料", FOLLOWUP_QUESTION_RULE)

    def test_followup_rule_requires_invitation_phrasing(self):
        """末尾追问必须是邀请式问句，不能写成向用户索取答案的内容问句。"""
        from angineer_core.prompts.agent_configs import FOLLOWUP_QUESTION_RULE

        self.assertIn("邀请式问句", FOLLOWUP_QUESTION_RULE)
        self.assertIn("您是否想知道", FOLLOWUP_QUESTION_RULE)
        self.assertIn("禁止写成向用户索取答案的内容问句", FOLLOWUP_QUESTION_RULE)

    def test_sop_routes_prompt_registered(self):
        from angineer_core.prompts.sop_routes import STEP_PARSE_SYSTEM_PROMPT

        self.assertIn("SOP 步骤结构化助手", STEP_PARSE_SYSTEM_PROMPT)

    def test_evals_routes_prompts_registered(self):
        from angineer_core.prompts.evals_routes import (
            COMPARE_ANALYSIS_SYSTEM_PROMPT,
            COMPARE_ANALYSIS_USER_TEMPLATE,
        )

        self.assertIn("评测结果分析专家", COMPARE_ANALYSIS_SYSTEM_PROMPT)
        self.assertIn("{question_id}", COMPARE_ANALYSIS_USER_TEMPLATE)

    def test_answer_eval_prompts_registered(self):
        from angineer_core.prompts.answer_eval import (
            SEMANTIC_EVAL_PROMPT,
            SEMANTIC_EVAL_SYSTEM_PROMPT,
        )

        self.assertIn("评测助手", SEMANTIC_EVAL_PROMPT)
        self.assertIn("严格的评测助手", SEMANTIC_EVAL_SYSTEM_PROMPT)

    def test_followup_question_rule_registered(self):
        from angineer_core.prompts.agent_configs import FOLLOWUP_QUESTION_RULE

        text = load("agent_configs.followup_question_rule")
        self.assertEqual(text, FOLLOWUP_QUESTION_RULE)
        self.assertIn("末尾追加", text)
        self.assertIn("不加导语", text)


class PromptVersionInPredictionTests(unittest.TestCase):
    def test_policy_query_result_carries_prompt_versions(self):
        from types import SimpleNamespace

        from agent_test_utils import MockLLM, text_events
        from angineer_core.agent_loop import AgentLoopConfig, AttemptConfig
        from angineer_core.policy_query import run_policy_query

        llm = MockLLM(lambda messages, kwargs: text_events("测试答案"))
        attempt = AttemptConfig(
            name="L1 语义检索",
            config_factory=lambda: AgentLoopConfig(llm=llm, tools=[], system_prompt="p", max_turns=1),
        )
        intent_result = SimpleNamespace(
            intent_level="L1", primary_level="L1", intent_type="concept_resolution",
            service_mode="semantic_retrieval", reason="规则命中",
            execution_plan=["semantic_retrieval"], final_path="semantic_retrieval",
            parameters={}, required_capabilities=["retrieval"], matched_sop=None,
            fallback_reason=None, attempted_paths=[],
        )
        with patch("angineer_core.classifier.IntentClassifier") as classifier_cls:
            classifier_cls.return_value.classify_intent.return_value = intent_result
            with patch("angineer_core.policy_query._load_doc_nodes", return_value=[]):
                with patch("ai_inference.llm_client.get_llm_client", return_value=llm):
                    with patch("angineer_core.agent_policy.build_attempts", return_value=[attempt]):
                        result = run_policy_query("什么是港口吞吐量？")
        self.assertIn("prompt_versions", result)
        self.assertIsInstance(result["prompt_versions"], dict)
        self.assertTrue(result["prompt_versions"])

    def test_run_prediction_carries_prompt_versions(self):
        from evals_core.runner.answer_eval import AnswerEvaluator

        data = {
            "answer": "测试答案",
            "citations": [],
            "retrieved_items": [],
            "system_prompt": "sys",
            "prompt_versions": {"dispatcher.chat_system_prompt": "v1"},
        }
        with patch("evals_core.runner.answer_eval.run_eval_query", return_value=data):
            prediction = AnswerEvaluator().run_prediction(
                {"question_id": "q1", "question": "测试问题"}
            )
        self.assertEqual(
            prediction["prompt_versions"],
            {"dispatcher.chat_system_prompt": "v1"},
        )


if __name__ == "__main__":
    unittest.main()

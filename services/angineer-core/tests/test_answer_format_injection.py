"""answer_format 注入穿线（OfficeQA 注入实验 §7.7）：None 逐字节不变 / 非 None 精确追加到末尾。

预注册穿线点 = build_attempts → QA 档（L1/L2）与 L3 复杂档系统提示词各追加同一条规则；
L0 闲聊档与 chat 装配不在注入范围。判据「默认 None＝现行为逐字节不变」在此文件锁死。
"""
from types import SimpleNamespace

from angineer_core.agent_configs import build_complex_config, build_qa_config
from angineer_core.agent_policy import build_attempts

INJECT = "若问题是数值/计算类：正文照常给出依据与推理；最后必须另起一行，只写最终答案本身。"


def _intent(level, service_mode):
    return SimpleNamespace(intent_level=level, service_mode=service_mode, intent_type="")


def _factory_prompt(**over):
    attempts = build_attempts(
        intent_result=over.pop("intent_result"), scene="docs",
        library_id="libA", doc_ids=[], load_nodes=lambda: [], llm_factory=lambda: None,
        **over,
    )
    return [attempt.config_factory().system_prompt for attempt in attempts]


class TestBuilderLevel:
    def test_qa_none_is_baseline(self):
        assert build_qa_config(llm=None).system_prompt == build_qa_config(llm=None, answer_format=None).system_prompt

    def test_qa_appends_exactly(self):
        base = build_qa_config(llm=None).system_prompt
        injected = build_qa_config(llm=None, answer_format=INJECT).system_prompt
        assert injected == base + "\n\n" + INJECT

    def test_complex_appends_exactly(self):
        base = build_complex_config(llm=None).system_prompt
        injected = build_complex_config(llm=None, answer_format=INJECT).system_prompt
        assert injected == base + "\n\n" + INJECT


class TestAttemptsThreading:
    def test_l1_injected_at_tail(self):
        prompts = _factory_prompt(intent_result=_intent("L1", "semantic_retrieval"), answer_format=INJECT)
        assert prompts[0].endswith("\n\n" + INJECT)

    def test_l2_both_attempts_injected(self):
        prompts = _factory_prompt(intent_result=_intent("L2", "structured_lookup"), answer_format=INJECT)
        assert len(prompts) == 2
        assert all(p.endswith("\n\n" + INJECT) for p in prompts)

    def test_l3_complex_injected(self):
        prompts = _factory_prompt(intent_result=_intent("L3", "dynamic_orchestration"), answer_format=INJECT)
        assert prompts[0].endswith("\n\n" + INJECT)

    def test_l0_not_injected(self):
        # L0 闲聊直答档不接注入（预注册范围＝QA 档与 L3 复杂档）
        prompts = _factory_prompt(intent_result=_intent("L0", "casual_chat"), answer_format=INJECT)
        assert INJECT not in prompts[0]

    def test_omitted_prompt_has_no_injection(self):
        prompts = _factory_prompt(intent_result=_intent("L1", "semantic_retrieval"))
        assert INJECT not in prompts[0]

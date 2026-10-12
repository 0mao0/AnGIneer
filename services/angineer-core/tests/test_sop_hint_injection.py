"""sop_hint 注入穿线（L3 轻量引导，选 B）：None 逐字节不变 / 粗筛命中才注入 / 开关可关。

预注册判据：①sop_hint=None → 复杂档提示词与现行为逐字节一致；
②L3 + query 粗筛 top-1 ≥ 0.10 → 末尾追加引导句（含 SOP 名与 sop_execute）；
③ANGINEER_SOP_L3_HINT=0 / query 空 / 无命中 → 不注入；L0/L1/L2 档不注入。
实测锚（真实 56 条库，2026-10-12）：命中题 top1=0.1958；「今天天气怎么样」0 命中。
"""
from types import SimpleNamespace

from angineer_core.agent_configs import build_complex_config
from angineer_core.agent_policy import build_attempts
from angineer_core.base_contracts import SOP, Step

QUERY_HIT = (
    "某海港码头工程，掩护情况为部分掩护。设计高水位 4.5 m，码头前沿底高程 −10.0 m，"
    "设计波高 H=2.5 m，波长 L=45 m，码头上部结构高度 h=3.0 m，"
    "波峰面高出上部结构底面的高度 h0=0.5 m。请计算该码头前沿顶高程。"
)
QUERY_MISS = "今天天气怎么样"
HINT_MARK = "sop_execute 执行标准流程"


def _make_sop(sop_id, name, desc):
    return SOP(
        id=sop_id,
        name_zh=name,
        description=desc,
        steps=[Step(id="s1", tool="calculator", description={"content": "计算", "citations": []})],
        blackboard={"required": ["H"], "outputs": ["E"], "all": ["H", "E"]},
        status="published",
    )


def _sops():
    # 多文档语料：单文档时 TF-IDF 的 IDF 退化为零（dot=0 伪影），必须带干扰项
    return [
        _make_sop("海港码头前沿顶高程计算", "海港码头前沿顶高程计算", "码头前沿顶高程标准计算流程"),
        _make_sop("直立式防波堤设计波高确定流程", "直立式防波堤设计波高确定流程", "防波堤波高确定"),
        _make_sop("航道边坡", "航道边坡", "航道边坡坡度计算"),
        _make_sop("通航宽度", "通航宽度", "航道通航宽度计算"),
    ]


def _intent(level="L3", service_mode="standard_sop"):
    return SimpleNamespace(intent_level=level, service_mode=service_mode, intent_type="")


def _prompts(query, intent_result=None):
    attempts = build_attempts(
        intent_result=intent_result or _intent(),
        query=query,
        scene="docs",
        library_id="libA",
        doc_ids=[],
        load_nodes=lambda: [],
        llm_factory=lambda: None,
        sop_loader=SimpleNamespace(load_all=lambda: _sops()),
    )
    return [attempt.config_factory().system_prompt for attempt in attempts]


class TestBuilderLevel:
    def test_none_is_baseline(self):
        assert (
            build_complex_config(llm=None).system_prompt
            == build_complex_config(llm=None, sop_hint=None).system_prompt
        )

    def test_appends_exactly(self):
        base = build_complex_config(llm=None).system_prompt
        injected = build_complex_config(llm=None, sop_hint=HINT_MARK).system_prompt
        assert injected == base + "\n\n" + HINT_MARK


class TestAttemptsThreading:
    def test_l3_hit_injects_hint(self):
        prompts = _prompts(QUERY_HIT)
        assert HINT_MARK in prompts[0]
        assert "海港码头前沿顶高程计算" in prompts[0]

    def test_miss_no_hint(self):
        assert HINT_MARK not in _prompts(QUERY_MISS)[0]

    def test_no_query_no_hint(self):
        assert HINT_MARK not in _prompts(None)[0]

    def test_switch_off(self, monkeypatch):
        # 开关关 = 提示词逐字节回现状（选 B 的逃生门）
        monkeypatch.setenv("ANGINEER_SOP_L3_HINT", "0")
        assert HINT_MARK not in _prompts(QUERY_HIT)[0]

    def test_l1_not_injected(self):
        prompts = _prompts(QUERY_HIT, intent_result=_intent("L1", "semantic_retrieval"))
        assert HINT_MARK not in prompts[0]

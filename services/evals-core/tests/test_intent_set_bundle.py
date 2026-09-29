# -*- coding: utf-8 -*-
"""intent-router-v1 题集自检：把题集的质量约束纳入 CI，防止手改 bundle 悄悄跑偏。

真相源是 scripts/build_intent_set.py（题面与金标都在里面，脚本自身带机械校验）；
本测试直接加载那个脚本的内存产物，因此**不依赖 data/ 下的 bundle 文件**（data/ 不入 git）。
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BUILDER = REPO / "scripts" / "build_intent_set.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_intent_set", BUILDER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_intent_set"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_builder_exists():
    assert BUILDER.is_file(), "题集构建器必须在 scripts/（.gitignore 白名单已放行）"


def test_set_passes_its_own_validation():
    """构建器自带的机械校验必须全过（结构不变量 + 条款号族规则对账）。"""
    mod = _load_builder()
    bundle = mod.build()
    problems = mod.validate(bundle)
    assert problems == [], "题集校验未通过：" + "; ".join(problems)


def test_shape_is_100_items_covering_l0_to_l4():
    mod = _load_builder()
    items = mod.build()["items"]
    assert len(items) == 100
    levels = {i["intent"]["level"] for i in items}
    assert levels == {"L0", "L1", "L2", "L3", "L4"}, f"层级覆盖不全: {levels}"


def test_every_item_self_documents_gold():
    """每题必须带 trap 与 rationale：复核者不回读 prompt 也能审金标。"""
    mod = _load_builder()
    for it in mod.build()["items"]:
        g = it["intent"]
        assert g["trap"].strip(), f"{it['question_id']} 缺 trap"
        assert g["rationale"].strip(), f"{it['question_id']} 缺 rationale"
        assert g["family"].strip(), f"{it['question_id']} 缺 family"
        assert g["rule_hit"] in ("model", "rule_L0", "rule_meta", "rule_clause", "unknown")


def test_route_derivation_matches_evaluator():
    """构建器的 route 派生必须与评测器同源，否则金标与断言会各说各话。"""
    sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))
    from evals_core.runner.intent_eval import derive_route as eval_derive

    mod = _load_builder()
    for it in mod.build()["items"]:
        g = it["intent"]
        assert g["route"] == eval_derive(g["level"], g["mode"]), it["question_id"]


def test_gray_zone_concept_compare_items_are_unambiguous():
    """L1_concept_compare 必须只问概念/构造差异，不得含选型/比选类 L4 措辞。

    2026-09-29 首版这 3 题用「两者的区别是什么」措辞，同时命中 L1 关键词与本分类法的
    「多方案比较=L4」，读法不同会反转头名（docs/req-intent-classify-latency.md §10.6）。
    """
    mod = _load_builder()
    banned = ("选型", "比选", "方案论证", "技术经济比较")
    items = [i for i in mod.build()["items"] if i["intent"]["family"] == "L1_concept_compare"]
    assert len(items) == 3
    for it in items:
        for word in banned:
            assert word not in it["question"], f"{it['question_id']} 含 L4 措辞「{word}」：{it['question']}"


def test_new_trap_families_present():
    """三个后补陷阱族必须在位（它们各自对应一类过度触发）。"""
    mod = _load_builder()
    fams = {i["intent"]["family"] for i in mod.build()["items"]}
    for fam in ("L1_stdcode_trap", "L1_numbered", "L3_mixed_signal", "L1_trap_stat", "L2_clause_number"):
        assert fam in fams, f"缺陷阱族 {fam}"

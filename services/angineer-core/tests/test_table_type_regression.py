"""表型回归集（P2 表格簇）——真表快照上的预注册判据。

夹具：``tests/fixtures/table_type_regression_v1.json``
- 生成器：``tests/fixtures/build_table_type_regression.py``（9 张真表快照 + 13 条用例，期望值人工按快照核定）
- 语料对账：``tests/fixtures/check_table_type_regression_drift.py``（重解析后快照是否过期）

判据（与夹具 meta.how 同口径）：
1. **选表**：两通道离线都断——top-1 候选必须是被声明的表且编号分 >0。
   读表通道的选表分就来自 ``_score_table_reference_match``（P2-4 踩过 caption 丢表号 → score=0）。
2. **取值**：
   - ``table_lookup``（确定性引擎）：离线断值。``status=fixed`` 断 expected；
     ``status=xfail`` 断 baseline（修复前实测值），一旦实得 expected 即 fail 并提示改 ``fixed``
     ——这是把「修好了」变成必须显式登记的动作。
   - ``table_read``（LLM 判读）：离线跳过（LLM 依赖），``P2_FIXTURE_LIVE=1`` 时用夹具自带
     provider 走真 LLM 断 expected。
3. **夹具自检**：expected 必须能在所声明的表快照里找到（防手写期望值笔误）。

为什么这么立：P2-1/P2-2/P2-3/P2-7 都是「改引擎行为」的活，先写死期望与修复前基线，
改完再看哪几条翻绿——避免改完拿新行为当判据（仓规：基线对比预注册纪律）。
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from angineer_core import ports  # noqa: E402
from angineer_core.table_query_engine import (  # noqa: E402
    _score_table_reference_match,
    query_tables,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "table_type_regression_v1.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
TABLES = {t["table_id"]: t for t in FIXTURE["tables"]}
CASES = FIXTURE["cases"]
CASE_IDS = [c["case_id"] for c in CASES]


def _candidates():
    return [
        {
            "table_id": t["table_id"],
            "doc_id": t["doc_id"],
            "header_rows": t["header_rows"],
            "rows": t["body_rows"],
            "context": t["title"],
            "page_idx": t["page"],
        }
        for t in FIXTURE["tables"]
    ]


def _same(a, b) -> bool:
    """宽容比较：数值与数字字符串等价（0.30=="0.3"），其余 ==。"""
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        try:
            return abs(float(a) - float(b)) < 1e-9
        except (TypeError, ValueError):
            return a == b
    return a == b


def _top1(table_name):
    ranked = sorted(
        _candidates(),
        key=lambda c: _score_table_reference_match(table_name, c["context"]),
        reverse=True,
    )
    return ranked[0], _score_table_reference_match(table_name, ranked[0]["context"])


def _table_text(table_id: str) -> str:
    t = TABLES[table_id]
    parts = [str(c) for row in (t["header_rows"] or []) for c in row]
    parts += [str(c) for row in (t["body_rows"] or []) for c in row]
    return " | ".join(parts)


# ── 1) 选表（两通道通用、离线） ──────────────────────────────────────────────

@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_selection_picks_declared_table(case):
    best, score = _top1(case["table_name"])
    assert score > 0, (
        f"{case['case_id']}: 表名 {case['table_name']!r} 在夹具候选里编号分=0 —— "
        f"读表/查表都会选不中（P2-4 的 caption 丢表号即此形态）"
    )
    assert best["table_id"] == case["table_id"], (
        f"{case['case_id']}: top-1 选到 {best['table_id']}（score={score}），"
        f"应为 {case['table_id']}"
    )


def _meets_expected(result, out, case) -> bool:
    """按用例判据判断期望是否达成（no_scalar=不得静默返回标量）。"""
    exp = case["expected"]
    if exp == "no_scalar":
        return result is None or isinstance(result, (dict, list)) or bool(out.get("error"))
    return _same(result, exp)


# ── 2) 确定性通道取值（离线） ────────────────────────────────────────────────

@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_lookup_value(case):
    if case["channel"] != "table_lookup":
        pytest.skip("读表通道：取值需真 LLM，见 test_read_value_live")
    out = query_tables(
        _candidates(),
        table_name=case["table_name"],
        query_conditions=case["conditions"],
        target_column=case["target_column"],
    )
    result = out.get("result")

    if case["status"] == "fixed":
        assert _meets_expected(result, out, case), (
            f"{case['case_id']}: 期望 {case['expected']!r}（{case['expected_why']}），"
            f"实得 {result!r}；trace={out.get('_trace')}"
        )
        return

    # status == "xfail"：先登记缺陷，再锁修复前基线——两条都要显式处理
    if _meets_expected(result, out, case):
        pytest.fail(
            f"{case['case_id']}: 行为已修好（实得 {result!r} 达成期望 {case['expected']!r}）——"
            f"请把夹具里该用例 status 改为 fixed 并更新 baseline"
        )
    if not _same(result, case["baseline"]):
        pytest.fail(
            f"{case['case_id']}: 基线漂移——夹具记 {case['baseline']!r}，实得 {result!r}。"
            f"若是有意修复：改 status=fixed；若是别的改动连带：先查清再更新 baseline。"
            f"trace={out.get('_trace')}"
        )
    pytest.xfail(f"已知缺陷·{case['note']}：实得 {result!r}，期望 {case['expected']!r}")


# ── 3) 读表通道取值（真 LLM，P2_FIXTURE_LIVE=1） ────────────────────────────

@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_read_value_live(case):
    if case["channel"] != "table_read":
        pytest.skip("非读表通道用例")
    if not os.environ.get("P2_FIXTURE_LIVE"):
        pytest.skip("读表取值需真 LLM：P2_FIXTURE_LIVE=1 再跑")

    from angineer_core.canonical_table_lookup import canonical_table_read

    blocks = [
        {
            "doc_id": t["doc_id"],
            "header_rows": t["header_rows"],
            "rows": t["body_rows"],
            "context": t["title"],
            "page_idx": t["page"],
            "library_id": "fixture",
        }
        for t in FIXTURE["tables"]
    ]
    ports.register_agent_search(table_blocks=lambda library_id="fixture", doc_ids=None: blocks)
    out = canonical_table_read(
        table_name=case["table_name"],
        query_conditions=case["conditions"],
        target_column=case["target_column"],
        library_id="fixture",
    )
    detail = (
        f"实得 {out.get('result')!r}，期望 {case['expected']!r}（{case['expected_why']}）；"
        f"cell={out.get('_read_cell')!r} quote={out.get('_read_quote')!r} err={out.get('error')!r}"
    )
    if case["status"] == "fixed":
        assert _meets_expected(out.get("result"), out, case), f"{case['case_id']}: {detail}"
        return
    if case["status"] == "xfail":
        if _meets_expected(out.get("result"), out, case):
            pytest.fail(
                f"{case['case_id']}: 读表判读已达期望——请把夹具里该用例 status 改为 fixed。{detail}"
            )
        pytest.xfail(f"已知缺陷·{case['note']}：{detail}")
    # status == "probe"：首测（本次读数供人工登记 fixed/xfail）
    if _meets_expected(out.get("result"), out, case):
        return
    pytest.xfail(f"首测未达标（待登记）·{case['note']}：{detail}")


# ── 4) 夹具自检 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_expected_appears_in_snapshot(case):
    """期望值必须能在快照里找到——防手写期望值笔误把夹具本身写成错的。"""
    if case["expected"] == "no_scalar":
        pytest.skip("no_scalar 模式无具体期望值")
    text = _table_text(case["table_id"])
    needle = str(case["expected"])
    if isinstance(case["expected"], float) and needle.endswith(".0"):
        needle = needle[:-2]
    assert needle in text, (
        f"{case['case_id']}: 期望值 {case['expected']!r} 在表 {case['table_id']} 快照里找不到——"
        f"先核对该用例的 expected_why"
    )

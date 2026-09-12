"""scripts/open_ragbench/compare_runs._load_from_sqlite 回归（2026-09-12 钉基线 WAL 实踩）。

只读 URI 连接在 WAL 库上读不到未 checkpoint 行（容器权限场景静默 0 行）→ 改读写连接
+query_only；并加"终态 run 明细非零"断言，防再出现空快照被钉成基线。
"""
import os
import sqlite3
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))

from open_ragbench import compare_runs as cr  # noqa: E402


def _mk_db(tmp_path, status="completed", details=0):
    p = str(tmp_path / "evals.sqlite")
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE eval_run (run_id TEXT, dataset_id TEXT, status TEXT, total_questions INT,"
                 " completed_questions INT, started_at TEXT, completed_at TEXT, run_name TEXT,"
                 " is_full_run INT, owner_pid INT, config_snapshot TEXT, summary_scores TEXT)")
    conn.execute("CREATE TABLE eval_run_detail (id INTEGER PRIMARY KEY, run_id TEXT, question_id TEXT,"
                 " status TEXT, quality TEXT, prediction TEXT, scores TEXT, all_scores TEXT,"
                 " error TEXT, latency_ms INT)")
    conn.execute("INSERT INTO eval_run VALUES ('run-x','ds',?,2,2,'','',1,1,0,NULL,'{}')", (status,))
    for i in range(details):
        conn.execute("INSERT INTO eval_run_detail (run_id,question_id,status,quality,prediction,scores,all_scores)"
                     " VALUES ('run-x',?,'completed','correct','{\"answer\":\"a\"}','{\"score\":1}','{}')",
                     (f"q{i}",))
    conn.commit()
    conn.close()
    return p


def test_completed_run_with_zero_details_raises(tmp_path):
    db = _mk_db(tmp_path, details=0)
    with pytest.raises(RuntimeError, match="明细 0 行"):
        cr._load_from_sqlite(db, "run-x")


def test_completed_run_loads_and_parses(tmp_path):
    run = cr._load_from_sqlite(_mk_db(tmp_path, details=2), "run-x")
    assert len(run["details"]) == 2
    assert run["details"][0]["prediction"] == {"answer": "a"}
    assert "summary_scores" not in run


def test_running_run_may_legitimately_have_no_details_yet(tmp_path):
    # 起跑瞬间 total>0 且 0 明细是合法中间态——断言只约束终态，不误伤轮询路径
    run = cr._load_from_sqlite(_mk_db(tmp_path, status="running", details=0), "run-x")
    assert run["details"] == []

"""解析重试的 resume 语义（2026-09-15 实踩：12 篇卡在「服务重启中断」，MinerU 产物完整，
但管理后台「解析」只会整条重跑含 MinerU；唯一的断点入口 v1 /resume 要求 api_key 归属，
管理员上传（api_key_id=NULL）永远 403——错误文案给的出路对管理员不存在）。

覆盖：
- compute_resume_stages("all")：补全流水线顺序里 pending/failed/queued/缺行/依赖连带 skipped；
  completed 与合法 skipped 不重跑；figure_describe 在缺行时也被补（旧 docs-api 复制版漂移就漏它）
- v1 空 requested 语义不变：行内出现过的阶段 ∪ structure；无任何行 → ["structure"]
- retry_parse_task：raw_parse completed → 只排缺的阶段；无缺口 → 按阶段记录同步终态、不建任务；
  raw_parse 未完成/无阶段记录 → 维持全量重跑
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from docs_core.parse_pipeline import ParseOrchestrator, compute_resume_stages


def _row(stage, status, message=""):
    return {"stage": stage, "status": status, "message": message}


# 2026-09-15 服务器 doc-a8854774（JTJ 307）实况：structure 后全被重启打断
ROWS_INTERRUPTED = [
    _row("source_prep", "completed"),
    _row("convert", "skipped", "PDF 输入无需转换"),
    _row("raw_parse", "completed"),
    _row("popo", "completed"),
    _row("structure", "completed"),
    _row("figure_describe", "queued"),
    _row("fts", "pending"),
    _row("vectors", "skipped", "前置硬阶段 fts 未完成"),
    _row("graph", "pending"),
]

ROWS_ALL_DONE = [_row(s, "completed") for s in
                 ("source_prep", "convert", "raw_parse", "popo", "structure",
                  "figure_describe", "fts", "vectors", "graph")]


# ---- compute_resume_stages ----

def test_resume_all_order_completes_interrupted():
    remaining = compute_resume_stages("all", ROWS_INTERRUPTED)
    assert remaining == ["figure_describe", "fts", "vectors", "graph"], \
        "缺的阶段按流水线顺序补；completed 与合法 skipped（convert）不重跑"


def test_resume_all_includes_missing_figure_describe_row():
    # 存量老文档没有 figure_describe 行：全量语义下它算未完成（旧 docs-api 复制版的顺序缺它，已漂移）
    rows = [r for r in ROWS_ALL_DONE if r["stage"] != "figure_describe"]
    assert compute_resume_stages("all", rows) == ["figure_describe"]


def test_resume_dependency_skip_is_requeued():
    rows = [_row("fts", "failed"), _row("vectors", "skipped", "前置硬阶段失败连带跳过")]
    assert "vectors" in compute_resume_stages("all", rows)


def test_resume_v1_default_semantics_unchanged():
    rows = [_row("source_prep", "completed"), _row("raw_parse", "completed"),
            _row("structure", "failed")]
    assert compute_resume_stages("", rows) == ["structure"], \
        "v1 语义：范围=行内出现过的阶段 ∪ structure，其中已 completed 的跳过"
    # 范围不扩到全流水线：行里没出现 fts/vectors/graph 时不补它们
    assert "fts" not in compute_resume_stages("", rows)
    assert compute_resume_stages("", []) == ["structure"]


# ---- retry_parse_task 接线 ----

class _FakeMeta:
    def __init__(self, rows):
        self._rows = rows

    def list_parse_stages(self, doc_id):
        return list(self._rows)


class _FakeKS:
    def __init__(self, rows, node):
        self.meta_store = _FakeMeta(rows)
        self._node = node
        self.node_updates = []
        self.task_updates = []

    def get_node(self, doc_id):
        return self._node

    def update_node(self, doc_id, **kw):
        self.node_updates.append(kw)

    def update_parse_task(self, task_id, **kw):
        self.task_updates.append((task_id, kw))


def _node(**over):
    base = dict(file_path="/data/x.pdf", library_id="default", status="failed",
                parse_task_id="parse-old1")
    base.update(over)
    return SimpleNamespace(**base)


def _orchestrator(rows, node, recorder):
    ks = _FakeKS(rows, node)
    orch = ParseOrchestrator(record_updater=recorder)
    return ks, orch


def test_retry_resumes_missing_stages_only():
    calls = []
    ks, orch = _orchestrator(ROWS_INTERRUPTED, _node(), lambda *a: None)
    with patch("docs_core.parse_pipeline.get_docs_service", return_value=ks), \
            patch.object(orch, "create_parse_task",
                         side_effect=lambda **kw: calls.append(kw) or {"task_id": "parse-new", "status": "queued"}):
        result = orch.retry_parse_task("doc-x")
    assert len(calls) == 1
    assert calls[0]["parse_options"] == {"stages": ["figure_describe", "fts", "vectors", "graph"]}, \
        "MinerU 产物已存在时不得整条重跑"
    assert result["task_id"] == "parse-new"


def test_retry_syncs_status_when_nothing_left():
    # 启动自愈把已完成文档标 failed：retry 不应再跑任何阶段，而是按阶段记录把状态同步正
    rec = []
    ks, orch = _orchestrator(ROWS_ALL_DONE, _node(),
                             lambda task_id, doc_id, status, error=None: rec.append((task_id, status)))
    with patch("docs_core.parse_pipeline.get_docs_service", return_value=ks), \
            patch.object(orch, "create_parse_task",
                         side_effect=AssertionError("不该建任务")):
        result = orch.retry_parse_task("doc-x")
    assert result["status"] == "completed"
    assert ks.node_updates and ks.node_updates[-1]["status"] == "completed"
    assert ks.task_updates and ks.task_updates[-1][1]["status"] == "completed"
    assert rec and rec[-1][1] == "completed"


def test_retry_full_rerun_when_raw_parse_not_completed():
    calls = []
    rows = [_row("source_prep", "completed"), _row("raw_parse", "failed")]
    ks, orch = _orchestrator(rows, _node(), lambda *a: None)
    with patch("docs_core.parse_pipeline.get_docs_service", return_value=ks), \
            patch.object(orch, "create_parse_task",
                         side_effect=lambda **kw: calls.append(kw) or {"task_id": "parse-new", "status": "queued"}):
        orch.retry_parse_task("doc-x")
    assert calls[0].get("parse_options") in (None, {}), "MinerU 未完成 → 维持全量重跑"


def test_retry_full_rerun_when_no_stage_rows():
    calls = []
    ks, orch = _orchestrator([], _node(), lambda *a: None)
    with patch("docs_core.parse_pipeline.get_docs_service", return_value=ks), \
            patch.object(orch, "create_parse_task",
                         side_effect=lambda **kw: calls.append(kw) or {"task_id": "parse-new", "status": "queued"}):
        orch.retry_parse_task("doc-x")
    assert calls[0].get("parse_options") in (None, {})

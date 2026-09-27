"""表格检索打分产物缓存与行级候选聚合的回归测试（2026-09-26 表格检索提速）。

- 缓存恒等性：ANGINEER_TABLE_TEXT_CACHE 开/关，retrieve 结果逐位一致（纯记忆化不变量）。
- 内容指纹失效：同一 (doc_id, table_id) 但行数变化时重建产物，不返回陈旧缓存。
- 行级候选聚合：ANGINEER_TABLE_ROW_AGG=1 时每表只保留最相关一行（同表多行只发一个候选）。
"""

import importlib
import os

import pytest

from docs_core.models.types import CanonicalTable
from docs_core.step09_query.protocols.contracts import KnowledgeNode, KnowledgeQueryRequest

# retrieval/__init__ 以同名导出 TableRetriever 实例，必须取模块本体才能摸到缓存与开关
tr = importlib.import_module("docs_core.step09_query.retrieval.table_retriever")


def _make_table(table_id: str, doc_id: str, body_rows: list[list[object]], table_type: str = "numeric_dense") -> CanonicalTable:
    return CanonicalTable(
        table_id=table_id,
        doc_id=doc_id,
        page_start=1,
        page_end=1,
        title="船型尺度表",
        caption="表4.1.2 设计船型尺度",
        table_type=table_type,
        header_rows=[["船舶吨级", "总长L(m)", "型宽B(m)"]],
        body_rows=body_rows,
        row_count=len(body_rows),
        col_count=3,
        summary="设计船型尺度取值表",
    )


def _make_node() -> KnowledgeNode:
    return KnowledgeNode(id="doc-1", title="海港总体设计规范", type="document", library_id="default")


class _SingleDocPort:
    """只服务一张表的假端口，按引用返回最新表对象（不缓存表内容）。"""

    def __init__(self) -> None:
        self.table: CanonicalTable | None = None

    def list_canonical_tables(self, **kwargs):
        return [self.table] if self.table is not None else []


@pytest.fixture(autouse=True)
def _clear_artifact_cache():
    with tr._TABLE_ARTIFACT_CACHE_LOCK:
        tr._TABLE_ARTIFACT_CACHE.clear()
    yield
    with tr._TABLE_ARTIFACT_CACHE_LOCK:
        tr._TABLE_ARTIFACT_CACHE.clear()
    for key in ("ANGINEER_TABLE_TEXT_CACHE", "ANGINEER_TABLE_ROW_AGG"):
        os.environ.pop(key, None)


def _retrieve(port: _SingleDocPort, query: str, top_k: int = 20):
    request = KnowledgeQueryRequest(query=query, library_id="default", doc_ids=[], top_k=top_k, filters=None)
    node = _make_node()
    return tr.TableRetriever(port=port).retrieve(request, [node])


def _sig(items):
    return [
        (i.item_id, round(float(i.score or 0.0), 9), (i.metadata or {}).get("row_index"), len(str(i.text or "")))
        for i in items
    ]


def test_cache_on_off_produce_identical_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    port = _SingleDocPort()
    port.table = _make_table(
        "t-1", "doc-1",
        [["10000", "150", "20.4"], ["20000", "180", "24.6"], ["50000", "230", "32.3"]],
    )
    monkeypatch.setenv("ANGINEER_TABLE_TEXT_CACHE", "0")
    off = _sig(_retrieve(port, "依据《海港总体设计规范》确定5万吨级散货船的设计船型尺度"))
    monkeypatch.setenv("ANGINEER_TABLE_TEXT_CACHE", "1")
    on_first = _sig(_retrieve(port, "依据《海港总体设计规范》确定5万吨级散货船的设计船型尺度"))
    on_warm = _sig(_retrieve(port, "依据《海港总体设计规范》确定5万吨级散货船的设计船型尺度"))
    assert off == on_first == on_warm
    assert off, "命中行级候选应非空"


def test_artifact_cache_invalidated_by_content_change(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANGINEER_TABLE_TEXT_CACHE", "1")
    port = _SingleDocPort()

    def neutral_table(body_rows):
        return CanonicalTable(
            table_id="t-1",
            doc_id="doc-1",
            page_start=1,
            page_end=1,
            title="附录对照表",
            table_type="numeric_dense",
            header_rows=[["代号", "数值"]],
            body_rows=body_rows,
            row_count=len(body_rows),
            col_count=2,
        )

    port.table = neutral_table([["x1", "10"]])
    query = "50000 散货船 船型尺度"
    assert _retrieve(port, query) == [], "首态（无 50000 行）不应有命中"
    port.table = neutral_table([["x1", "10"], ["50000", "230"]])
    hits = _retrieve(port, query)
    assert hits, "行数变化（指纹不同）必须重建产物，不得返回陈旧缓存"


def test_row_agg_keeps_single_candidate_per_table(monkeypatch: pytest.MonkeyPatch) -> None:
    query = "50000 散货船 船型尺度"
    port = _SingleDocPort()
    port.table = _make_table(
        "t-1", "doc-1",
        [["50000", "230", "32.3"], ["50000", "235", "32.9"], ["30000", "190", "26.0"]],
    )
    monkeypatch.setenv("ANGINEER_TABLE_ROW_AGG", "0")
    per_row = _retrieve(port, query)
    row_key_items = [i for i in per_row if (i.metadata or {}).get("chunk_type") == "table_row_key"]
    assert len(row_key_items) >= 2, "聚合关闭时应逐命中行发候选"

    monkeypatch.setenv("ANGINEER_TABLE_ROW_AGG", "1")
    agg = _retrieve(port, query)
    row_key_items = [i for i in agg if (i.metadata or {}).get("chunk_type") == "table_row_key"]
    assert len(row_key_items) == 1, "聚合开启时同表行级候选只保留一条"
    best_score = max(float(i.score or 0.0) for i in row_key_items)
    assert row_key_items[0].metadata["row_index"] == 0, "最相关行（首个最高分行）应被保留"
    assert abs(float(row_key_items[0].score or 0.0) - best_score) < 1e-9

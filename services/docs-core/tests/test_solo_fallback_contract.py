"""阶段四契约测试：solo → jsonl 投影 + 05 重建 + 分层加固 + auto 降级（G7）。"""

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from docs_core.step04_structure.solo_engine import StructuredResult


def _sample_result() -> StructuredResult:
    return StructuredResult(
        nodes=[
            {
                "block_uid": "t1", "block_type": "title", "page_idx": 0, "block_seq": 1,
                "plain_text": "5.1 一般规定", "bbox": [0.0, 0.0, 1.0, 1.0],
                "derived_level": 2, "title_path": "5.1 一般规定", "parent_uid": None,
            },
            {
                "block_uid": "tab1", "block_type": "table", "page_idx": 1, "block_seq": 2,
                "plain_text": "表 1 参数表 注：单位 mm",
                "bbox": [0.1, 0.1, 0.9, 0.5],
                "derived_level": None, "title_path": "5.1 一般规定",
                "parent_uid": "t1",
                "table_html": "<table><tr><td>参数</td><td>数值</td></tr>"
                              "<tr><td>高度</td><td>100</td></tr></table>",
            },
            {
                "block_uid": "eq1", "block_type": "equation_interline", "page_idx": 1, "block_seq": 3,
                "plain_text": "F = ma", "bbox": [0.1, 0.5, 0.9, 0.7],
                "derived_level": None, "title_path": "5.1 一般规定", "parent_uid": "t1",
            },
        ],
        edges=[],
        index_rows=[],
        stats={"derived_rows": []},
    )


def test_solo2json_projection_carries_fields_to_jsonl(monkeypatch, tmp_path) -> None:
    """StructuredResult → solo2json 投影 → jsonl 节点字段（04 落盘真相）。"""
    import docs_core.paths as paths
    from docs_core.step04_structure import solo2json_pipeline

    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    parsed = tmp_path / "libraries" / "lib" / "documents" / "doc" / "parsed"
    parsed.mkdir(parents=True, exist_ok=True)
    (parsed / "content.md").write_text("正文", encoding="utf-8")
    solo2json_pipeline._save_doc_blocks_graph("lib", "doc", _sample_result())
    nodes = []
    with open(paths.get_graph_jsonl_path("lib", "doc"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                nodes.append(json.loads(line))
    by_id = {node["block_uid"]: node for node in nodes}
    assert by_id["t1"]["derived_level"] == 2
    assert by_id["t1"]["title_path"] == "5.1 一般规定"
    assert by_id["t1"]["block_type"] == "title"
    assert by_id["tab1"]["block_type"] == "table"
    assert by_id["tab1"]["table_html"] and "<table" in by_id["tab1"]["table_html"]
    assert by_id["tab1"]["parent_uid"] == "t1"
    assert by_id["eq1"]["block_type"] == "equation_interline"


def test_rebuild_from_solo_jsonl_produces_tables_and_outlines(monkeypatch, tmp_path) -> None:
    """jsonl → rebuild_canonical_document_from_graph：tables/outlines/chunks 非空（05 真实行为）。"""
    import docs_core.paths as paths
    from docs_core.step04_structure import solo2json_pipeline
    from docs_core.step04_structure.shared.jsonl_io import get_doc_blocks_graph
    from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import rebuild_canonical_document_from_graph

    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    parsed = tmp_path / "libraries" / "lib" / "documents" / "doc" / "parsed"
    parsed.mkdir(parents=True, exist_ok=True)
    (parsed / "content.md").write_text("正文", encoding="utf-8")
    solo2json_pipeline._save_doc_blocks_graph("lib", "doc", _sample_result())
    graph = get_doc_blocks_graph("lib", "doc")
    assert graph is not None
    document = rebuild_canonical_document_from_graph("lib-1", "doc-1", graph, title="示例")
    assert document.tables, "solo 适配器路径 canonical_tables 必须非空"
    assert document.tables[0].row_count == 1
    assert document.outlines, "solo 适配器路径必须生成 outline"
    assert document.chunks
    formula_block = next(b for b in document.blocks if b.block_id == "eq1")
    assert formula_block.block_type == "formula"


def test_query_layer_does_not_import_read_or_ingest_producers() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "docs_core" / "step09_query"
    offenders = []
    for py in root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if (
            "docs_core.read." in text
            or "docs_core.step04_structure" in text
        ):
            offenders.append(str(py))
    assert not offenders, f"query 层不得 import read/ingest 生产模块: {offenders}"
    # docs_core.models（共享契约）属合法白名单；step05 共享工具（sqlite_utils 等）不在此守护范围


def test_semantics_layer_does_not_import_backend_modules() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "docs_core" / "step04_structure" / "shared" / "enrich"
    offenders = []
    for py in root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if any(
            marker in text
            for marker in (
                "docs_core.step04_structure.popo",
                "docs_core.step04_structure.solo_engine",
                "docs_core.step04_structure.solo2json",
                "docs_core.step05_sqlite_fts",
            )
        ):
            offenders.append(str(py))
    assert not offenders, f"enrich 语义层不得 import 后端/05+ 模块: {offenders}"


def test_upsert_parse_stage_records_fallback(tmp_path) -> None:
    from docs_core.step05_sqlite_fts.store.blocks_sql_store import KnowledgeMetaStore

    store = KnowledgeMetaStore(db_path=tmp_path / "meta.sqlite", schema_version="1.0.0")
    store.upsert_parse_stage(
        "doc-1", "popo", status="failed", error="4B API down",
        fallback="solo",
    )
    rows = store.list_parse_stages("doc-1")
    assert rows and rows[0]["stage"] == "popo"
    assert rows[0]["fallback"] == "solo"
    # 旧库迁移：无 fallback 列时 init 自动 ALTER
    import sqlite3

    old_db = tmp_path / "old_meta.sqlite"
    conn = sqlite3.connect(old_db)
    try:
        conn.execute(
            """CREATE TABLE doc_parse_stages (
                doc_id TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL,
                message TEXT DEFAULT '', error TEXT DEFAULT '',
                started_at TEXT, finished_at TEXT, updated_at TEXT NOT NULL,
                PRIMARY KEY (doc_id, stage)
            )"""
        )
        conn.commit()
    finally:
        conn.close()
    migrated = KnowledgeMetaStore(db_path=old_db, schema_version="1.0.0")
    migrated.upsert_parse_stage("old", "structure", status="completed", fallback="")
    rows = migrated.list_parse_stages("old")
    assert "fallback" in rows[0]


def _fake_file_storage(tmp_path):
    """构造 KNOWLEDGE_BASE_DIR 布局下的文档目录（与 docs_core.paths 一致）。"""
    parsed = tmp_path / "libraries" / "lib" / "documents" / "doc" / "parsed"
    popo_dir = parsed / "popo"
    mineru_raw = parsed / "mineru_raw"
    source = tmp_path / "libraries" / "lib" / "documents" / "doc" / "source"
    popo_dir.mkdir(parents=True, exist_ok=True)
    mineru_raw.mkdir(parents=True, exist_ok=True)
    parsed.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)
    (popo_dir / "enriched_blocks.json").write_text("[]", encoding="utf-8")
    (mineru_raw / "content.md").write_text("MinerU 原文", encoding="utf-8")
    (parsed / "content.md").write_text("popo 改写版", encoding="utf-8")

    class _FS:
        def get_popo_dir(self, library_id, doc_id):
            return popo_dir

        def get_mineru_raw_dir(self, library_id, doc_id):
            return mineru_raw

        def get_parsed_dir(self, library_id, doc_id):
            return parsed

        def get_source_dir(self, library_id, doc_id):
            return source

    return _FS()


def test_rollback_popo_products(monkeypatch, tmp_path) -> None:
    import docs_core.docs_file_io as afs

    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    fake_fs = _fake_file_storage(tmp_path)
    monkeypatch.setattr(afs, "file_storage", fake_fs)
    cleared = []

    class _IndexStore:
        def clear_doc_blocks(self, doc_id):
            cleared.append(doc_id)

    fake_ks = SimpleNamespace(index_store=_IndexStore())
    ks_module = importlib.import_module("docs_core.docs_service")
    monkeypatch.setattr(ks_module, "_docs_service", fake_ks)

    from docs_core.parse_pipeline import _rollback_popo_products, StageContext

    ctx = StageContext(task_id="t", library_id="lib", doc_id="doc", file_path="x.pdf")
    _rollback_popo_products(ctx)
    assert not (tmp_path / "libraries" / "lib" / "documents" / "doc" / "parsed" / "popo").exists(), "popo 半成品目录必须删除"
    assert cleared == ["doc"]
    assert (tmp_path / "libraries" / "lib" / "documents" / "doc" / "parsed" / "content.md").read_text(encoding="utf-8") == "MinerU 原文"


def test_popo_failure_rolls_back_and_sets_fallback_target(monkeypatch, tmp_path) -> None:
    import docs_core.docs_file_io as afs

    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    monkeypatch.setattr(afs, "file_storage", _fake_file_storage(tmp_path))

    import docs_core.step03_mineru_parse.popo_enhance as popo_pkg

    class _BoomPipeline:
        def run_full_pipeline(self, **kwargs):
            raise RuntimeError("4B API down")

    monkeypatch.setattr(popo_pkg, "get_popo_pipeline", lambda: _BoomPipeline())

    from docs_core import parse_pipeline as pp

    ctx = pp.StageContext(task_id="t", library_id="lib", doc_id="doc", file_path="x.pdf")
    with pytest.raises(RuntimeError, match="4B API down"):
        pp._run_popo(ctx)
    assert ctx.fallback_target == "solo"
    assert not (tmp_path / "libraries" / "lib" / "documents" / "doc" / "parsed" / "popo").exists()


def test_runner_records_fallback_and_structure_completes(monkeypatch, tmp_path) -> None:
    import docs_core.docs_file_io as afs

    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    monkeypatch.setattr(afs, "file_storage", _fake_file_storage(tmp_path))

    import docs_core.step03_mineru_parse.popo_enhance as popo_pkg
    from docs_core import parse_pipeline as pp

    class _BoomPipeline:
        def run_full_pipeline(self, **kwargs):
            raise RuntimeError("4B API down")

    monkeypatch.setattr(popo_pkg, "get_popo_pipeline", lambda: _BoomPipeline())
    # run_pipeline 经 STAGE_REGISTRY 持有函数引用，需 patch 注册表条目而非模块属性
    monkeypatch.setattr(pp.STAGE_REGISTRY["structure"], "run", lambda ctx: "solo ok")

    class _MetaStore:
        def __init__(self):
            self.updates = []

        def upsert_parse_stage(self, doc_id, key, **kwargs):
            self.updates.append((key, kwargs))

    meta = _MetaStore()
    ctx = pp.StageContext(task_id="t", library_id="lib", doc_id="doc", file_path="x.pdf")
    results = pp.run_pipeline(ctx, ["popo", "structure"], meta_store=meta)
    assert results["popo"] == "failed"
    assert results["structure"] == "completed"
    popo_updates = [u for u in meta.updates if u[0] == "popo"]
    assert popo_updates[-1][1]["status"] == "failed"
    assert popo_updates[-1][1]["fallback"] == "solo"
    assert ctx.fallback_target is None
    # 兜底语义：popo failed + structure completed → 整体 completed（不视为 partial）
    full = {
        "source_prep": "completed", "convert": "completed", "raw_parse": "completed",
        "popo": "failed", "structure": "completed",
        "fts": "completed", "vectors": "skipped", "graph": "completed",
    }
    assert pp.derive_overall_status(full) == "completed"
    # hard 阶段（structure）失败 → failed；soft 阶段（vectors）失败 → partial
    assert pp.derive_overall_status(dict(full, structure="failed")) == "failed"
    assert pp.derive_overall_status(dict(full, vectors="failed")) == "partial"


def test_structure_always_runs_solo(monkeypatch, tmp_path) -> None:
    """单管线：_run_structure 永远走 Solo（PoPo 只作信号注入源）。"""
    from docs_core import parse_pipeline as pp

    def fake_solo(ctx, **kwargs):
        return "solo backend"

    monkeypatch.setattr(pp, "_run_structure_solo", fake_solo)
    ctx = pp.StageContext(task_id="t", library_id="lib", doc_id="doc", file_path="x.pdf")
    assert pp._run_structure(ctx) == "solo backend"
    assert not hasattr(pp, "_run_structure_from_popo"), "popo 后端入口已退役"

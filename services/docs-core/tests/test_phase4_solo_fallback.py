"""阶段四契约测试：solo→CanonicalBlock 适配器（G3）+ 分层加固 + auto 降级（G7）。"""

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from docs_core.ingest.structure.solo import (
    StructuredResult,
    structured_result_to_canonical_blocks,
)
from docs_core.ingest.canonical.builder import build_canonical_document_from_blocks


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


def test_solo_adapter_carries_fields_to_canonical_blocks() -> None:
    blocks = structured_result_to_canonical_blocks("doc-1", _sample_result())
    by_id = {block.block_id: block for block in blocks}
    assert by_id["t1"].title_level == 2
    assert by_id["t1"].section_path == "5.1 一般规定"
    assert by_id["tab1"].block_type == "table"
    assert by_id["tab1"].table_html and "<table" in by_id["tab1"].table_html
    assert by_id["tab1"].parent_block_id == "t1"
    assert by_id["eq1"].block_type == "formula"
    assert by_id["eq1"].text == "F = ma"
    assert by_id["tab1"].bbox is not None


def test_build_canonical_document_from_blocks_produces_tables_and_outlines(tmp_path) -> None:
    blocks = structured_result_to_canonical_blocks("doc-1", _sample_result())
    document = build_canonical_document_from_blocks(
        library_id="lib-1", doc_id="doc-1", title="示例", blocks=blocks,
    )
    assert document.tables, "solo 适配器路径 canonical_tables 必须非空"
    assert document.tables[0].row_count == 1
    assert document.outlines, "solo 适配器路径必须生成 outline"
    assert document.chunks


def test_query_layer_does_not_import_read_or_ingest_producers() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "docs_core" / "query"
    offenders = []
    for py in root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if (
            "docs_core.read." in text
            or "docs_core.ingest.structure" in text
            or "docs_core.ingest.semantics" in text
        ):
            offenders.append(str(py))
    assert not offenders, f"query 层不得 import read/ingest 生产模块: {offenders}"


def test_semantics_layer_does_not_import_backend_modules() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "docs_core" / "ingest" / "semantics"
    offenders = []
    for py in root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if any(marker in text for marker in ("docs_core.read", "ingest.structure")):
            offenders.append(str(py))
    assert not offenders, f"semantics 层不得 import read/结构层: {offenders}"


def test_upsert_parse_stage_records_fallback(tmp_path) -> None:
    from docs_core.write.store.blocks_sql_store import KnowledgeMetaStore

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
    import docs_core.write.store.assets_file_store as afs

    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    fake_fs = _fake_file_storage(tmp_path)
    monkeypatch.setattr(afs, "file_storage", fake_fs)
    cleared = []

    class _IndexStore:
        def clear_doc_blocks(self, doc_id):
            cleared.append(doc_id)

    fake_ks = SimpleNamespace(index_store=_IndexStore())
    ks_module = importlib.import_module("docs_core.knowledge_service")
    monkeypatch.setattr(ks_module, "_knowledge_service", fake_ks)

    from parse_pipeline import _rollback_popo_products, StageContext

    ctx = StageContext(task_id="t", library_id="lib", doc_id="doc", file_path="x.pdf")
    _rollback_popo_products(ctx)
    assert not (tmp_path / "libraries" / "lib" / "documents" / "doc" / "parsed" / "popo").exists(), "popo 半成品目录必须删除"
    assert cleared == ["doc"]
    assert (tmp_path / "libraries" / "lib" / "documents" / "doc" / "parsed" / "content.md").read_text(encoding="utf-8") == "MinerU 原文"


def test_popo_failure_sets_fallback_target_in_auto_mode(monkeypatch, tmp_path) -> None:
    import docs_core.write.store.assets_file_store as afs

    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    monkeypatch.setattr(afs, "file_storage", _fake_file_storage(tmp_path))
    monkeypatch.setenv("DOCS_CORE_NORMALIZER_BACKEND", "auto")

    import docs_core.read.popo_enhance as popo_pkg

    class _BoomPipeline:
        def run_full_pipeline(self, **kwargs):
            raise RuntimeError("4B API down")

    monkeypatch.setattr(popo_pkg, "get_popo_pipeline", lambda: _BoomPipeline())

    import parse_pipeline as pp

    ctx = pp.StageContext(task_id="t", library_id="lib", doc_id="doc", file_path="x.pdf")
    with pytest.raises(RuntimeError, match="4B API down"):
        pp._run_popo(ctx)
    assert ctx.fallback_target == "solo"
    assert not (tmp_path / "libraries" / "lib" / "documents" / "doc" / "parsed" / "popo").exists()


def test_runner_records_fallback_and_structure_completes(monkeypatch, tmp_path) -> None:
    import docs_core.write.store.assets_file_store as afs

    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    monkeypatch.setattr(afs, "file_storage", _fake_file_storage(tmp_path))
    monkeypatch.setenv("DOCS_CORE_NORMALIZER_BACKEND", "auto")

    import docs_core.read.popo_enhance as popo_pkg
    import parse_pipeline as pp

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


def test_structure_picks_backend_by_enriched_existence(monkeypatch, tmp_path) -> None:
    import docs_core.write.store.assets_file_store as afs
    import parse_pipeline as pp

    class _FSWithPopo:
        def __init__(self, has_popo):
            self.has_popo = has_popo

        def read_popo_enriched_blocks(self, library_id, doc_id):
            if not self.has_popo:
                raise FileNotFoundError("no popo")
            return [{"id": 1}]

    monkeypatch.setattr(afs, "file_storage", _FSWithPopo(has_popo=True))
    calls = {"popo": 0, "solo": 0}

    def fake_popo(ctx, enriched, **kwargs):
        calls["popo"] += 1
        return "popo backend"

    def fake_solo(ctx, **kwargs):
        calls["solo"] += 1
        return "solo backend"

    monkeypatch.setattr(pp, "_run_structure_from_popo", fake_popo)
    monkeypatch.setattr(pp, "_run_structure_solo", fake_solo)
    ctx = pp.StageContext(task_id="t", library_id="lib", doc_id="doc", file_path="x.pdf")
    assert pp._run_structure(ctx) == "popo backend"

    monkeypatch.setattr(afs, "file_storage", _FSWithPopo(has_popo=False))
    assert pp._run_structure(ctx) == "solo backend"
    assert calls == {"popo": 1, "solo": 1}

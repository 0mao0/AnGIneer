"""KB_STACK=pg 档位集成测试（PostgreSQL+pgvector）。

需要本机可用的 pgvector 实例（默认经 ``KB_PG_TEST_DSN`` 指定 maintenance 库，
默认 ``postgresql://postgres:postgres@localhost:5433/postgres``）；不可达时整文件 skip。

每个 session 建独立临时 database（kbtest_<uuid>），测完 DROP——与 legacy 测试的
tmp_path 隔离同等级。覆盖（迁移方案 §5.5 对应项）：
- ensure_pg_ready 建库建表幂等（档位 fail-fast）
- registry / meta / doc_blocks / segments 行级 round-trip（适配器方言：INSERT OR
  REPLACE→ON CONFLICT、LIKE→ILIKE、AUTOINCREMENT、last_insert_rowid）
- canonical save/get round-trip + 中文 bigram FTS（含空查询、排序方向、library 过滤）
- PgVectorStore 全契约（upsert strict 维度、search score=1-distance、collection 隔离、
  delete/clear/stats/set_payload/iter_records）
- 中性包导出（pg 源）→ 导入（pg 目标）→ 对账
- startup_guard pg 分支
"""

from __future__ import annotations

import os
import uuid
import urllib.request
import urllib.error

import pytest

_MAINTENANCE_DSN = os.getenv(
    "KB_PG_TEST_DSN", "postgresql://postgres:postgres@localhost:5433/postgres")


def _pg_reachable() -> bool:
    try:
        import psycopg

        conn = psycopg.connect(_MAINTENANCE_DSN, connect_timeout=3)
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _pg_reachable(), reason="pgvector 测试实例不可达")


@pytest.fixture(scope="module")
def pg_env(tmp_path_factory):
    """独立临时库 + KB_STACK=pg 环境变量（module 级：文件结束即恢复，不污染同进程后续文件）。"""
    import psycopg

    dbname = f"kbtest_{uuid.uuid4().hex[:10]}"
    conn = psycopg.connect(_MAINTENANCE_DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{dbname}"')
    conn.close()

    base = _MAINTENANCE_DSN.rsplit("/", 1)[0]  # 保留 scheme://user:pass@host:port
    dsn = f"{base}/{dbname}"
    saved = {k: os.environ.get(k) for k in (
        "KB_STACK", "KNOWLEDGE_PG_DSN", "KNOWLEDGE_PG_VECTOR_DIM",
        "DOCS_VECTORSTORE_PROVIDER", "ANGINEER_DATA_ROOT")}
    os.environ["KB_STACK"] = "pg"
    os.environ["KNOWLEDGE_PG_DSN"] = dsn
    os.environ["KNOWLEDGE_PG_VECTOR_DIM"] = "8"  # 测试用小维度，加快 upsert/search
    os.environ["DOCS_VECTORSTORE_PROVIDER"] = "qdrant"  # pg 档位下应被忽略
    tmp = tmp_path_factory.mktemp("pg-data")
    os.environ["ANGINEER_DATA_ROOT"] = str(tmp)
    os.environ.setdefault("ANGINEER_REGISTRY_DB", "")
    yield {"dsn": dsn, "dbname": dbname, "data_root": tmp}

    # 清理：断开全部连接后 DROP；环境变量恢复现场（session fixture 与同进程后续测试隔离）
    conn = psycopg.connect(_MAINTENANCE_DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()", (dbname,))
        cur.execute(f'DROP DATABASE "{dbname}"')
    conn.close()
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(scope="module")
def ready(pg_env):
    from docs_core.pg_support import ensure_pg_ready

    ensure_pg_ready()
    ensure_pg_ready()  # 幂等
    return pg_env


# ---------------------------------------------------------------------------
# registry / meta / index 行级 round-trip
# ---------------------------------------------------------------------------


def test_registry_roundtrip(ready):
    from docs_core import library_registry
    from docs_core.pg_support import kb_stack

    assert kb_stack() == "pg"
    record = library_registry.register_library(
        "lib-pg-a", name="PG测试库", group_name="system", collection="lib-pg-a")
    assert record.library_id == "lib-pg-a"
    assert library_registry.get_library("lib-pg-a").name == "PG测试库"
    # 幂等 upsert
    library_registry.register_library("lib-pg-a", name="PG测试库2", group_name="system")
    assert library_registry.get_library("lib-pg-a").name == "PG测试库2"
    assert any(r.library_id == "lib-pg-a" for r in library_registry.list_libraries())


def test_custom_group_in_knowledge_schema(ready):
    """自定义组必须按 search_path 找表（默认 schema=dredge_knowledge）。

    2026-10-30 回归：_groups_table_missing 写死 table_schema='public'，
    建组写入成功后回读判「表不存在」→ create_group 断言必挂、list_custom_groups 恒空。
    """
    from docs_core import library_registry

    created = library_registry.create_group("bridge", "桥梁组")
    assert created.group_name == "bridge" and created.display_name == "桥梁组"
    assert library_registry.get_custom_group("bridge") is not None
    assert "bridge" in {g.group_name for g in library_registry.list_custom_groups()}
    # 幂等 upsert：同组重建成更新 display_name
    assert library_registry.create_group("bridge", "桥梁工程").display_name == "桥梁工程"
    # 组内挂库 + 改组：自定义组合法性判据同样走 get_custom_group
    record = library_registry.register_library(
        "lib-pg-bridge", name="桥梁库", group_name="bridge")
    assert record.group_name == "bridge" and record.collection == "bridge"
    library_registry.register_library("lib-pg-move", name="待迁库", group_name="system")
    assert library_registry.set_group("lib-pg-move", "bridge").group_name == "bridge"


def test_meta_store_roundtrip(ready):
    from docs_core.step05_sqlite_fts.store.pg_stores import PgKnowledgeMetaStore
    from datetime import datetime
    from types import SimpleNamespace

    store = PgKnowledgeMetaStore()
    store.upsert_library(SimpleNamespace(
        id="lib-pg-meta", name="元数据库", description="",
        created_at=datetime.now(), updated_at=datetime.now()))
    store.upsert_node(SimpleNamespace(
        id="doc-pg-1", title="疏浚工程规范", type="document",
        visible=True, library_id="lib-pg-meta", file_path=None,
        parent_id=None, sort_order=0, deleted=False,
        status="completed", parse_progress=100, parse_stage=None,
        parse_error=None, parse_task_id=None, strategy="doc_blocks_graph_v1",
        schema_version="1.0.0", created_at=datetime.now(),
        updated_at=datetime.now()))
    nodes = store.list_nodes("lib-pg-meta")
    assert [n["id"] for n in nodes] == ["doc-pg-1"]
    assert nodes[0]["title"] == "疏浚工程规范"
    # LIKE→ILIKE 搜索（软删除标记前验证）
    hits = store.search_nodes_by_title("疏浚")
    assert any(h["id"] == "doc-pg-1" for h in hits)
    # 软删除标记后搜索排除、meta 反查仍在
    store.mark_nodes_deleted(["doc-pg-1"], True)
    assert store.get_node_library_id("doc-pg-1") == "lib-pg-meta"
    assert not any(h["id"] == "doc-pg-1" for h in store.search_nodes_by_title("疏浚"))


def test_index_store_roundtrip(ready):
    from docs_core.step05_sqlite_fts.store.pg_stores import PgKnowledgeIndexStore

    store = PgKnowledgeIndexStore()
    inserted = store.insert_doc_blocks_base_rows([{
        "doc_id": "doc-pg-1", "doc_name": "规范.pdf", "page_idx": 0,
        "page_width": 595.0, "page_height": 842.0, "block_seq": 0,
        "block_uid": "uid-pg-1", "block_type": "title", "content_json": {},
        "plain_text": "总则", "created_at": "2026-10-29T00:00:00",
        "updated_at": "2026-10-29T00:00:00",
    }])
    assert inserted == 1
    updated = store.update_doc_blocks_derived_rows([{
        "block_uid": "uid-pg-1", "title_path": "第1章/总则", "is_active": 1,
        "updated_at": "2026-10-29T00:00:01",
    }])
    assert updated == 1
    rows = store.query_doc_blocks("doc-pg-1")
    assert rows[0]["title_path"] == "第1章/总则"
    count = store.save_document_segments(
        "doc-pg-1", "lib-pg-meta", "standard", [
            {"id": "seg-1", "item_type": "segment", "content": "总则内容", "meta": {}},
        ])
    assert count == 1
    segs = store.list_document_segments("doc-pg-1", "standard")
    assert segs[0]["content"] == "总则内容"


# ---------------------------------------------------------------------------
# canonical + FTS
# ---------------------------------------------------------------------------


def _make_document(doc_id: str, library_id: str):
    from docs_core.models.types import (
        BoundingBox, CanonicalBlock, CanonicalChunk, CanonicalDocument,
        CanonicalPage, CitationTarget,
    )

    return CanonicalDocument(
        doc_id=doc_id,
        library_id=library_id,
        title="疏浚与吹填工程设计规范",
        source_file_name="jtg-d64.pdf",
        source_file_type="pdf",
        schema_version="1.0.0",
        parse_version="0.1.0",
        language="zh",
        page_count=2,
        status="completed",
        pages=[
            CanonicalPage(doc_id=doc_id, page_idx=0, width=595.0, height=842.0,
                          rotation=0, image_path=None, printed_page_label="1"),
            CanonicalPage(doc_id=doc_id, page_idx=1, width=595.0, height=842.0,
                          rotation=0, image_path=None, printed_page_label="2"),
        ],
        blocks=[
            CanonicalBlock(
                block_id=f"{doc_id}-b1", doc_id=doc_id, page_idx=0, block_type="title",
                text="第4章 挖槽设计", text_clean="第4章 挖槽设计",
                bbox=BoundingBox(x1=10, y1=20, x2=500, y2=40),
                reading_order=0, title_level=1, section_path="第4章 挖槽设计",
                source="mineru", source_ref=None, parent_block_id=None,
                entity_tags=[], conditions=[], exam_tags=[], clause_id="4.1",
                contd_target_id=None, image_assoc_id=None, table_merge_id=None,
                raw_type=None, page_bboxes=[], merged_from=[],
            ),
        ],
        chunks=[
            CanonicalChunk(
                chunk_id=f"{doc_id}-c1", doc_id=doc_id, chunk_type="content",
                text="挖槽边坡坡度应根据土质确定，宜采用1:3～1:5。",
                text_clean="挖槽边坡坡度应根据土质确定，宜采用1:3～1:5。",
                token_count=24, section_path="第4章 挖槽设计", page_start=0, page_end=0,
                source_block_ids=[f"{doc_id}-b1"],
                citation_targets=[
                    CitationTarget(
                        target_id=f"{doc_id}-b1", target_type="block", doc_id=doc_id,
                        page_idx=0, bbox=BoundingBox(x1=10, y1=20, x2=500, y2=40),
                        section_path="第4章 挖槽设计", display_title="挖槽设计",
                        snippet="挖槽边坡", printed_page_label="1",
                    ),
                ],
                version="0.1.0", inherited_chapter=None, entity_tags=[],
                conditions=[], exam_tags=[], clause_id="4.1",
            ),
            CanonicalChunk(
                chunk_id=f"{doc_id}-c2", doc_id=doc_id, chunk_type="content",
                text="备淤深度应根据回淤强度确定。",
                text_clean="备淤深度应根据回淤强度确定。",
                token_count=14, section_path="第5章 备淤深度", page_start=1, page_end=1,
                source_block_ids=[], citation_targets=[], version="0.1.0",
                inherited_chapter=None, entity_tags=[], conditions=[], exam_tags=[],
                clause_id="5.2",
            ),
        ],
        tables=[],
        outlines=[],
    )


def test_canonical_roundtrip_and_fts(ready):
    from docs_core.step05_sqlite_fts.store.pg_stores import PgCanonicalSQLiteStore

    store = PgCanonicalSQLiteStore()
    doc = _make_document("doc-pg-1", "lib-pg-meta")
    counts = store.save_document(doc)
    assert counts["chunks"] == 2

    loaded = store.get_document("doc-pg-1")
    assert loaded is not None
    assert loaded.title == doc.title
    assert [c.chunk_id for c in loaded.chunks] == ["doc-pg-1-c1", "doc-pg-1-c2"]
    assert loaded.chunks[0].citation_targets[0].display_title == "挖槽设计"
    assert loaded.blocks[0].bbox.x1 == 10
    assert loaded.pages[0].printed_page_label == "1"

    # 中文 bigram FTS：整词命中
    hits = store.search_chunk_fts(None, "挖槽边坡坡度", library_ids=["lib-pg-meta"])
    assert [h["chunk_id"] for h in hits] == ["doc-pg-1-c1"]
    assert hits[0]["bm25_score"] <= 0  # 方向语义：越小越相关（-ts_rank）
    # 备淤命中 c2，且与 c1 无关
    hits2 = store.search_chunk_fts(None, "备淤深度", library_ids=["lib-pg-meta"])
    assert [h["chunk_id"] for h in hits2] == ["doc-pg-1-c2"]
    # 空查询 / 纯标点 → 空结果
    assert store.search_chunk_fts(None, "  ") == []
    assert store.search_chunk_fts(None, "、。！") == []
    # doc_id 限定
    hits3 = store.search_chunk_fts("doc-pg-1", "挖槽边坡")
    assert [h["chunk_id"] for h in hits3] == ["doc-pg-1-c1"]
    # clear+重写幂等
    store.save_document(doc)
    assert len(store.get_document("doc-pg-1").chunks) == 2

    # list_chunks / clause 双向匹配
    assert len(store.list_chunks("doc-pg-1")) == 2
    refs = store.list_blocks_by_clause_refs("doc-pg-1", ["4", "4.1.1"])
    assert refs and refs[0]["clause_id"] == "4.1"


# ---------------------------------------------------------------------------
# PgVectorStore 全契约
# ---------------------------------------------------------------------------


def _vec(seed: float, dim: int = 8) -> list:
    import math

    base = [math.sin(seed + i / dim) for i in range(dim)]
    norm = math.sqrt(sum(b * b for b in base)) or 1.0
    return [b / norm for b in base]


def test_pg_vector_store_contract(ready):
    from docs_core.step06_vectors.pg_vector_store import PgVectorStore
    from docs_core.step06_vectors.vector_store import VectorRecord

    store = PgVectorStore(collection="vtest-default")
    dim = 8
    records_a = [
        VectorRecord(record_id="ra1", doc_id="doc-a", entity_type="chunk",
                     entity_id="chunk-1", content="挖槽设计条款", embedding=_vec(0.1, dim),
                     library_id="lib-a"),
        VectorRecord(record_id="ra2", doc_id="doc-a", entity_type="chunk",
                     entity_id="chunk-2", content="备淤深度条款内容更长一些",
                     embedding=_vec(0.2, dim), library_id="lib-a"),
    ]
    records_b = [
        VectorRecord(record_id="rb1", doc_id="doc-b", entity_type="chunk",
                     entity_id="chunk-1", content="另一库的记录", embedding=_vec(0.3, dim),
                     library_id="lib-b"),
    ]
    assert store.upsert_records(records_a, collection="vtest-a") == 2
    assert store.upsert_records(records_b, collection="vtest-b") == 1
    # 幂等 upsert
    assert store.upsert_records(records_a, collection="vtest-a") == 2

    # 检索：collection 隔离（vtest-a 搜不到 lib-b 的点）
    hits = store.search(_vec(0.15, dim), top_k=5, collection="vtest-a")
    assert {h.record_id for h in hits} == {"ra1", "ra2"}
    assert all(0.0 <= h.score <= 1.0 for h in hits)
    assert hits[0].score >= hits[1].score  # 相似度降序
    # 更近的向量排第一
    assert hits[0].record_id in ("ra1", "ra2")
    hits_b = store.search(_vec(0.3, dim), top_k=5, collection="vtest-b")
    assert [h.record_id for h in hits_b] == ["rb1"]

    # 默认 collection 回退
    assert store.upsert_records(records_a) >= 2
    assert store.count_records() >= 2

    # 维度守卫
    with pytest.raises(ValueError):
        store.upsert_records([VectorRecord(
            record_id="rbad", doc_id="doc-a", entity_type="chunk", entity_id="x",
            embedding=[0.1] * 5)], collection="vtest-a")

    # stats / counts
    stats = store.get_document_stats("doc-a", collection="vtest-a")
    assert stats["total_count"] == 2
    assert stats["by_entity_type"]["chunk"]["count"] == 2
    glob = store.get_global_stats(collection="vtest-a")
    assert glob["total_rows"] == 2
    assert glob["expected_dimension"] == 8

    # set_payload_by_docs（merge + library_id 列同步）
    changed = store.set_payload_by_docs(
        ["doc-a"], {"library_id": "lib-a2"}, collection="vtest-a")
    assert changed == 2
    assert store.search(_vec(0.1, dim), top_k=10, collection="vtest-a")[-1].library_id == "lib-a2"

    # iter_records（导出通道）
    exported = {r.record_id for r in store.iter_records(collection="vtest-a")}
    assert exported == {"ra1", "ra2"}

    # delete_records / clear_document / clear_library
    assert store.delete_records("doc-a", ["chunk-1"], collection="vtest-a") >= 1
    assert store.count_points_for_doc("doc-a", collection="vtest-a") >= 1
    assert store.clear_document("doc-a", collection="vtest-a") >= 1
    assert store.count_points_for_doc("doc-a", collection="vtest-a") == 0
    assert store.delete_collection("vtest-b") is True
    assert store.count_records("vtest-b") == 0


# ---------------------------------------------------------------------------
# 中性包导出（pg 源）→ 导入（pg 目标）round-trip
# ---------------------------------------------------------------------------


def test_neutral_bundle_pg_to_pg(ready, tmp_path):
    from docs_core import library_registry
    from docs_core.corpus_export_neutral import export_neutral_bundle
    from docs_core.corpus_import_neutral import import_neutral_bundle
    from docs_core.pg_support import pg_connect
    from docs_core.step05_sqlite_fts.store.pg_stores import (
        PgCanonicalSQLiteStore, PgKnowledgeIndexStore,
    )
    from docs_core.step06_vectors.pg_vector_store import PgVectorStore
    from docs_core.step06_vectors.vector_store import VectorRecord
    from datetime import datetime

    library_registry.register_library(
        "lib-pg-src", name="中性包源库", group_name="system",
        sqlite_file=library_registry._DEFAULT_SQLITE_FILE, collection="lib-pg-src")

    store = PgCanonicalSQLiteStore()
    store.save_document(_make_document("doc-neu-1", "lib-pg-src"))
    index_store = PgKnowledgeIndexStore()
    index_store.insert_doc_blocks_base_rows([{
        "doc_id": "doc-neu-1", "doc_name": "规范.pdf", "page_idx": 0,
        "page_width": 595.0, "page_height": 842.0, "block_seq": 0,
        "block_uid": "uid-neu-1", "block_type": "title", "content_json": {},
        "plain_text": "总则", "created_at": "2026-10-29T00:00:00",
        "updated_at": "2026-10-29T00:00:00",
    }])
    index_store.save_document_segments(
        "doc-neu-1", "lib-pg-src", "standard",
        [{"id": "seg-neu-1", "item_type": "segment", "content": "总则", "meta": {}}])
    vstore = PgVectorStore(collection="lib-pg-src")
    vstore.upsert_records([
        VectorRecord(record_id="vec-1", doc_id="doc-neu-1", entity_type="chunk",
                     entity_id="doc-neu-1-c1", content="挖槽边坡", embedding=_vec(0.5),
                     library_id="lib-pg-src"),
    ], collection="lib-pg-src")
    # meta 行
    conn = pg_connect()
    try:
        conn.execute(
            "INSERT INTO nodes (id, title, type, visible, library_id, file_path, status, "
            "parse_progress, parse_stage, parse_error, parse_task_id, strategy, "
            "schema_version, created_at, updated_at) VALUES "
            "('doc-neu-1', '中性包文档', 'document', 1, 'lib-pg-src', NULL, 'completed', "
            "100, NULL, NULL, NULL, 'doc_blocks_graph_v1', '1.0.0', ?, ?)",
            (datetime.now().isoformat(), datetime.now().isoformat()),
        )
        conn.execute(
            "INSERT INTO libraries (id, name, description, created_at, updated_at) VALUES "
            "('lib-pg-src', '中性包源库', '', ?, ?)",
            (datetime.now().isoformat(), datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    # 导出（pg 源）
    pkg = tmp_path / "neutral.zip"
    export_neutral_bundle(["lib-pg-src"], pkg,
                          on_stage=lambda n, m: None)
    assert pkg.exists() and pkg.stat().st_size > 0

    # 导入前注销源库注册行（同 stack 导入：源=目标库，冲突闸要求目标无同 id 活跃行）
    from docs_core.pg_support import pg_connect as _pgc

    conn = _pgc()
    try:
        conn.execute("DELETE FROM library_registry WHERE library_id = 'lib-pg-src'")
        conn.commit()
    finally:
        conn.close()

    # 导入（pg 目标，同 stack）：dry-run → apply
    dry = import_neutral_bundle(pkg, apply=False)
    assert dry["mode"] == "dry-run" and dry["libraries"][0]["library_id"] == "lib-pg-src"

    from docs_core import docs_service as ds

    ds._docs_service = None  # 重置单例，让导入侧重建 store（确保无残留状态）
    result = import_neutral_bundle(pkg, apply=True, with_vectors=True)
    assert result["mode"] == "applied"
    verify = result["verify"]["lib-pg-src"]
    assert verify["docs"] == 1 and verify["chunks"] == 2 and verify["vectors"] == 1
    assert verify["doc_blocks"] == 1 and verify["segments"] == 1

    # 冲突闸：同 id 再导拒绝
    with pytest.raises(Exception):
        import_neutral_bundle(pkg, apply=True)


# ---------------------------------------------------------------------------
# 装配 / 守卫
# ---------------------------------------------------------------------------


def test_provider_ignored_and_guard(ready):
    from docs_core.step06_vectors.config import get_vectorstore_provider_name

    # KB_STACK=pg 下 provider 键被忽略，恒返回 pgvector
    assert get_vectorstore_provider_name() == "pgvector"

    from docs_core.startup_guard import run_vector_startup_guard

    report = run_vector_startup_guard()
    # 有向量数据（vtest-default 残留）或空库都是可接受状态；只断言 pg 分支没有 error
    # （embedding 探针会因无端点报错——排除该类）
    non_probe_errors = [e for e in report.errors if "embedding" not in e]
    assert not non_probe_errors, report.errors


def test_kb_migrator_rejected(ready):
    from docs_core.kb_migrator import KbMigrator

    with pytest.raises(NotImplementedError):
        KbMigrator()

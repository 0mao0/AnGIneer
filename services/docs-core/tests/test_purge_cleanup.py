"""文档删除清理覆盖：parse_task_steps / doc_parse_stages / knowledge_graph.sqlite。"""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from docs_core.docs_service import DocsService
from docs_core.write.graph.config import EntityLayer, RelationType
from docs_core.write.graph.graph_store import GraphStore
from docs_core.write.store.blocks_sql_store import KnowledgeMetaStore


def test_meta_store_delete_tasks_clears_steps_and_stages(tmp_path) -> None:
    store = KnowledgeMetaStore(db_path=tmp_path / "meta.sqlite", schema_version="1.0.0")
    now = datetime.now()
    task = SimpleNamespace(
        id="t1", library_id="lib", doc_id="doc-x", status="completed", progress=100,
        stage="graph", stage_message=None, error="", schema_version="1.0.0",
        created_at=now, updated_at=now,
    )
    store.upsert_parse_task(task)
    store.insert_parse_task_step("t1", "doc-x", "structure", 50)
    store.upsert_parse_stage("doc-x", "structure", status="completed")

    assert len(store.get_parse_task_steps("t1")) == 1
    assert len(store.list_parse_stages("doc-x")) == 1

    store.delete_parse_tasks_by_doc_ids(["doc-x"])
    store.clear_parse_stages("doc-x")

    assert store.list_parse_tasks() == []
    assert store.get_parse_task_steps("t1") == []
    assert store.list_parse_stages("doc-x") == []


def _seed_graph(store: GraphStore) -> dict:
    a = store.upsert_entity_by_name("实体A", layer=EntityLayer.CONCEPT, source_doc="doc-x")
    b = store.upsert_entity_by_name("实体B", layer=EntityLayer.CONDITION, source_doc="doc-x")
    c = store.upsert_entity_by_name("实体C", layer=EntityLayer.ACTION, source_doc="doc-y")
    store.add_relation_by_names("实体A", "实体B", RelationType.REQUIRES, library_id="lib", doc_id="doc-x")
    store.add_relation_by_names("实体A", "实体C", RelationType.VERIFIES, library_id="lib", doc_id="doc-y")
    store.add_framework("流程X", "[]", "", "1.1", [], "lib", "doc-x")
    principle_id = store.add_principle("原则X", "mandatory", ["实体A"], "1.1", "quote", "lib", "doc-x")
    example_id = store.add_example("示例X", "{}", "1+1", ["实体A"], "1.1", "lib", "doc-x")
    return {"a": a, "b": b, "c": c, "principle_id": principle_id, "example_id": example_id}


def test_graph_store_delete_document(tmp_path) -> None:
    store = GraphStore(str(tmp_path / "graph.sqlite"))
    seeded = _seed_graph(store)

    removed = store.delete_document("doc-x")

    assert removed > 0
    assert store.get_relations_by_doc("lib", "doc-x") == []
    assert store.get_relations_by_doc("lib", "doc-y")  # 其他文档保留
    assert store.get_frameworks_by_doc("lib", "doc-x") == []
    assert store.get_principles_by_entity_ids([seeded["a"].entity_id]) == []
    assert store.get_examples_by_entity_ids([seeded["a"].entity_id]) == []
    # 实体为全局共享，保留
    assert store.get_entity_by_name("实体A") is not None
    assert store.get_entity_by_name("实体C") is not None
    # 关联表无残留
    with store._connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM principle_entities WHERE principle_id = ?", (seeded["principle_id"],)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM example_entities WHERE example_id = ?", (seeded["example_id"],)
        ).fetchone()[0] == 0


def test_purge_document_artifacts_cleans_stages_steps_and_graph(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DOCS_VECTORSTORE_PROVIDER", "sqlite")

    import docs_core.paths as paths_module
    import docs_core.write.store.assets_file_store as afs

    graph_db = tmp_path / "knowledge_graph.sqlite"
    gs = GraphStore(str(graph_db))
    _seed_graph(gs)
    monkeypatch.setattr(paths_module, "resolve_graph_db_path", lambda: graph_db)

    deleted: list = []

    class _FakeFS:
        def delete_document(self, library_id: str, doc_id: str) -> bool:
            deleted.append((library_id, doc_id))
            return True

    monkeypatch.setattr(afs, "file_storage", _FakeFS())

    ks = DocsService()
    task = ks.create_parse_task("t1", "lib", "doc-x")
    ks.meta_store.insert_parse_task_step(task.id, "doc-x", "structure", 50)
    ks.meta_store.upsert_parse_stage("doc-x", "structure", status="completed")

    ks._purge_document_artifacts([SimpleNamespace(id="doc-x", library_id="lib")])

    assert deleted == [("lib", "doc-x")]
    assert ks.meta_store.list_parse_tasks() == []
    assert ks.meta_store.get_parse_task_steps(task.id) == []
    assert ks.meta_store.list_parse_stages("doc-x") == []
    assert gs.get_relations_by_doc("lib", "doc-x") == []
    assert gs.get_frameworks_by_doc("lib", "doc-x") == []
    assert gs.get_relations_by_doc("lib", "doc-y")  # 其他文档保留

import pytest
from docs_core.step07_graph.graph_store import GraphStore, GraphEntity
from docs_core.step07_graph.config import EntityLayer, RelationType


@pytest.fixture
def store(tmp_path):
    return GraphStore(str(tmp_path / "graph.sqlite"))


def _mk(store, name, lib):
    return store.upsert_entity(
        GraphEntity(name=name, layer=EntityLayer.CONCEPT, library_id=lib)
    ).entity_id


def test_exclusive_entity_moves(store):
    e = _mk(store, "独占实体", "lib-a")
    store.add_relation(e, e, RelationType.REQUIRES, library_id="lib-a", doc_id="d1")
    stats = store.move_doc_graph("lib-a", "lib-b", ["d1"])
    assert stats["entities_moved"] == 1
    rows = store.list_library_entities("lib-b")
    assert [r.name for r in rows] == ["独占实体"]
    assert store.list_library_entities("lib-a") == []


def test_shared_entity_copied_and_relations_repointed(store):
    shared = _mk(store, "共享实体", "lib-a")
    solo = _mk(store, "独占", "lib-a")
    other = _mk(store, "留守", "lib-a")
    # d1（要迁走）引用 shared→solo；d2（留下）引用 shared→other（评审 P1-7③：避免 solo 也变共享）
    store.add_relation(shared, solo, RelationType.REQUIRES, library_id="lib-a", doc_id="d1")
    store.add_relation(shared, other, RelationType.CONSTRAINS, library_id="lib-a", doc_id="d2")
    stats = store.move_doc_graph("lib-a", "lib-b", ["d1"])
    assert stats["entities_copied"] == 1 and stats["entities_moved"] == 1
    # 源库共享实体仍在；新库有副本
    assert len(store.list_library_entities("lib-a")) == 2  # N1 修正：独占件已移走，lib-a 只剩 共享实体+留守
    names_b = sorted(e.name for e in store.list_library_entities("lib-b"))
    assert names_b == ["共享实体", "独占"]
    # d1 的关系改标到 lib-b 且指向副本；d2 的关系不动
    with store._connect() as conn:
        r_b = conn.execute(
            "SELECT source_id FROM graph_relations WHERE library_id='lib-b' AND doc_id='d1'"
        ).fetchone()
        copy_id = conn.execute(
            "SELECT entity_id FROM graph_entities WHERE library_id='lib-b' AND name='共享实体'"
        ).fetchone()["entity_id"]
    assert r_b["source_id"] == copy_id


def test_merge_same_name_converges(store):
    a = _mk(store, "同名", "lib-a")
    b = _mk(store, "同名", "lib-b")
    store.add_relation(a, a, RelationType.VERIFIES, library_id="lib-a", doc_id="d1")
    stats = store.move_doc_graph("lib-a", "lib-b", ["d1"])
    assert stats["entities_merged"] == 1
    assert len(store.list_library_entities("lib-b")) == 1  # 只剩 lib-b 原行
    with store._connect() as conn:
        r = conn.execute("SELECT source_id FROM graph_relations WHERE doc_id='d1'").fetchone()
    assert r["source_id"] == b


def test_idempotent_rerun(store):
    e = _mk(store, "x", "lib-a")
    store.add_relation(e, e, RelationType.DEFINES, library_id="lib-a", doc_id="d1")
    store.move_doc_graph("lib-a", "lib-b", ["d1"])
    stats2 = store.move_doc_graph("lib-a", "lib-b", ["d1"])  # 重跑无害
    assert stats2["entities_moved"] == 0 and stats2["entities_copied"] == 0
    assert len(store.list_library_entities("lib-b")) == 1

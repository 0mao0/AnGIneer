"""graph_entities 状态字段与迁移覆盖。"""

from docs_core.step07_graph.config import EntityLayer, EntityStatus, RelationType
from docs_core.step07_graph.graph_store import GraphEntity, GraphStore


def test_new_graph_entity_has_status_column(tmp_path) -> None:
    store = GraphStore(str(tmp_path / "graph.sqlite"))
    entity = store.upsert_entity(GraphEntity(
        name="承载力验算",
        layer=EntityLayer.ACTION,
        status=EntityStatus.PENDING,
    ))
    assert entity.status == EntityStatus.PENDING

    row = store.get_entity_by_name("承载力验算")
    assert row is not None
    assert row.status == EntityStatus.PENDING


def _seed_status_entities(store: GraphStore) -> dict:
    a = store.upsert_entity(GraphEntity(name="已批准实体", layer=EntityLayer.CONCEPT, library_id="lib", status=EntityStatus.APPROVED))
    p = store.upsert_entity(GraphEntity(name="待审实体", layer=EntityLayer.CONCEPT, library_id="lib", status=EntityStatus.PENDING))
    r = store.upsert_entity(GraphEntity(name="被拒实体", layer=EntityLayer.CONCEPT, library_id="lib", status=EntityStatus.REJECTED))
    store.add_relation_by_names("已批准实体", "待审实体", RelationType.REQUIRES, library_id="lib", doc_id="doc-a")
    store.add_relation_by_names("待审实体", "被拒实体", RelationType.CONSTRAINS, library_id="lib", doc_id="doc-a")
    return {"a": a, "p": p, "r": r}


def test_list_entities_by_doc_excludes_rejected(tmp_path) -> None:
    store = GraphStore(str(tmp_path / "graph.sqlite"))
    _seed_status_entities(store)

    names = [e.name for e in store.list_entities_by_doc("lib", "doc-a")]
    assert "已批准实体" in names
    assert "待审实体" in names
    assert "被拒实体" not in names


def test_list_entities_by_status(tmp_path) -> None:
    store = GraphStore(str(tmp_path / "graph.sqlite"))
    _seed_status_entities(store)

    pending = store.list_entities_by_status("lib", EntityStatus.PENDING)
    assert [e.name for e in pending] == ["待审实体"]

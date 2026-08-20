"""实体审批、拒绝与关系清理覆盖。"""

from docs_core.step07_graph.config import EntityLayer, EntityStatus, RelationType
from docs_core.step07_graph.graph_store import GraphEntity, GraphStore


def _seed(store: GraphStore):
    a = store.upsert_entity(GraphEntity(name="待审实体", layer=EntityLayer.CONCEPT, library_id="lib", status=EntityStatus.PENDING))
    b = store.upsert_entity(GraphEntity(name="正式实体", layer=EntityLayer.CONDITION, library_id="lib", status=EntityStatus.APPROVED))
    store.add_relation_by_names("待审实体", "正式实体", RelationType.REQUIRES, library_id="lib", doc_id="doc-a")
    return a, b


def test_approve_entity(tmp_path) -> None:
    store = GraphStore(str(tmp_path / "graph.sqlite"))
    a, _ = _seed(store)

    assert store.approve_entity(a.entity_id, reviewer="admin") is True
    entity = store.get_entity(a.entity_id)
    assert entity.status == EntityStatus.APPROVED
    assert entity.reviewed_by == "admin"
    assert entity.reviewed_at


def test_reject_entity_and_delete_relations(tmp_path) -> None:
    store = GraphStore(str(tmp_path / "graph.sqlite"))
    a, _ = _seed(store)

    docs = store.get_docs_referencing_entity(a.entity_id)
    assert docs == [("lib", "doc-a")]

    assert store.reject_entity(a.entity_id, reason="不通用", reviewer="admin") is True
    entity = store.get_entity(a.entity_id)
    assert entity.status == EntityStatus.REJECTED
    assert entity.reject_reason == "不通用"

    removed = store.delete_relations_for_entity(a.entity_id)
    assert removed == 1
    assert store.get_relations_by_doc("lib", "doc-a") == []


def test_find_existing_entity_alias_and_normalized(tmp_path) -> None:
    from docs_core.step07_graph.entity_dedup import find_existing_entity
    store = GraphStore(str(tmp_path / "graph.sqlite"))
    store.upsert_entity(GraphEntity(name="承载力验算", layer=EntityLayer.ACTION, library_id="lib",
                                    aliases=["承载力"], status=EntityStatus.APPROVED))

    assert find_existing_entity(store, "承载力", "lib").name == "承载力验算"
    assert find_existing_entity(store, "承载力 验算", "lib").name == "承载力验算"
    assert find_existing_entity(store, "完全不同的实体", "lib") is None


def test_delete_entity_removes_and_blacklists(tmp_path) -> None:
    store = GraphStore(str(tmp_path / "graph.sqlite"))
    a, _ = _seed(store)

    assert store.delete_entity(a.entity_id) is True
    assert store.get_entity(a.entity_id) is None
    assert store.get_relations_by_doc("lib", "doc-a") == []
    assert store.is_entity_deleted("lib", "待审实体") is True

    # 再次删除不存在实体返回 False
    assert store.delete_entity(a.entity_id) is False


def test_list_and_restore_deleted_entities(tmp_path) -> None:
    store = GraphStore(str(tmp_path / "graph.sqlite"))
    a, _ = _seed(store)

    store.delete_entity(a.entity_id)
    deleted = store.list_deleted_entities("lib")
    assert any(item["name"] == "待审实体" for item in deleted)

    assert store.restore_deleted_entity("lib", "待审实体") is True
    assert store.is_entity_deleted("lib", "待审实体") is False
    assert store.restore_deleted_entity("lib", "待审实体") is False

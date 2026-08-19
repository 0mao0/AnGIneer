"""graph_entities 状态字段与迁移覆盖。"""

from docs_core.step07_graph.config import EntityLayer, EntityStatus
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

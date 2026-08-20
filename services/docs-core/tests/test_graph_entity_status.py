"""graph_entities 状态字段与迁移覆盖。"""

import sqlite3

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


def test_expand_all_packets_ignores_rejected_names(tmp_path, monkeypatch) -> None:
    from docs_core.step07_graph.evidence_builder import EvidencePacket
    from docs_core.step07_graph.graph_orchestrator import GraphOrchestrator

    store = GraphStore(str(tmp_path / "graph.sqlite"))
    orch = GraphOrchestrator(store)
    orch.load_seed_entities()

    class _FakeExtractor:
        def find_seed_occurrences(self, text, seeds):
            return [("设计高水位", 0)]
        def find_related_entities(self, text, seed_name, seeds):
            return ["新型防波堤材料"]
        def classify_entity(self, name):
            return EntityLayer.CONCEPT

    orch.extractor = _FakeExtractor()
    packet = EvidencePacket(
        packet_id="p1", library_id="lib", doc_id="doc-x", doc_title="测试文档",
        section_path="1.1", raw_text="设计高水位 影响 新型防波堤材料",
    )
    orch.expand_all_packets([packet], enable_llm=False, ignored_entity_names=["新型防波堤材料"])

    assert store.get_entity_by_name("新型防波堤材料") is None


def test_expand_all_packets_llm_new_entity_is_pending(tmp_path) -> None:
    from docs_core.step07_graph.evidence_builder import EvidencePacket
    from docs_core.step07_graph.graph_orchestrator import GraphOrchestrator

    store = GraphStore(str(tmp_path / "graph.sqlite"))
    orch = GraphOrchestrator(store)
    orch.load_seed_entities()
    orch._link_zettelkasten = lambda *a, **k: {"relations_added": 0}
    orch._run_extractors = lambda *a, **k: {"entities_updated": 0}

    class _FakeExtractor:
        def find_seed_occurrences(self, text, seeds):
            return [("设计高水位", 0)]
        def find_related_entities(self, text, seed_name, seeds):
            return []
        def classify_entity(self, name):
            return EntityLayer.CONCEPT
        def extract_from_packet(self, text, section, seed_names):
            return {"entities": [{"name": "新型防波堤材料", "layer": "concept", "evidence": "x"}], "relationships": []}

    orch.extractor = _FakeExtractor()
    packet = EvidencePacket(
        packet_id="p1", library_id="lib", doc_id="doc-x", doc_title="测试文档",
        section_path="1.1", raw_text="设计高水位 影响 新型防波堤材料",
    )
    orch.expand_all_packets([packet], enable_llm=True)

    entity = store.get_entity_by_name("新型防波堤材料")
    assert entity is not None
    assert entity.status == EntityStatus.PENDING
    assert entity.proposed_doc_id == "doc-x"


def test_push_to_graph_accepts_enable_llm(tmp_path, monkeypatch) -> None:
    from docs_core.step07_graph.push_to_graph import push_to_graph

    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    calls = {}

    def fake_push(library_id, doc_id, graph_db_path=None, enable_llm=False, ignored_entity_names=None):
        calls["enable_llm"] = enable_llm
        calls["ignored"] = ignored_entity_names
        return {"pushed": True, "total_entities_found": 1, "total_relations_added": 2}

    monkeypatch.setattr("docs_core.step07_graph.push_to_graph._run_push", fake_push)

    result = push_to_graph("lib", "doc-x", enable_llm=True, ignored_entity_names=["被拒实体"])
    assert calls["enable_llm"] is True
    assert calls["ignored"] == ["被拒实体"]
    assert result["entities_count"] == 1
    assert result["relations_count"] == 2


def test_old_graph_entities_schema_migrates_status(tmp_path) -> None:
    db_path = str(tmp_path / "graph.sqlite")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE graph_entities (
            entity_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            layer TEXT NOT NULL,
            aliases_json TEXT DEFAULT '[]',
            description TEXT DEFAULT '',
            source_doc TEXT DEFAULT '',
            source_clause TEXT DEFAULT '',
            library_id TEXT NOT NULL DEFAULT 'default',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(name, library_id)
        );
    """)
    conn.commit()
    conn.close()

    store = GraphStore(db_path)
    cols = [r[1] for r in store._connect().execute("PRAGMA table_info(graph_entities)")]
    assert "status" in cols
    assert "proposed_doc_id" in cols
    entity = store.upsert_entity(GraphEntity(name="迁移实体", layer=EntityLayer.CONCEPT, library_id="lib"))
    assert entity.status == EntityStatus.APPROVED


def test_expand_all_packets_skips_deleted_entity(tmp_path) -> None:
    from docs_core.step07_graph.evidence_builder import EvidencePacket
    from docs_core.step07_graph.graph_orchestrator import GraphOrchestrator

    store = GraphStore(str(tmp_path / "graph.sqlite"))
    deleted = store.upsert_entity(GraphEntity(name="已删除实体", layer=EntityLayer.CONCEPT, library_id="lib"))
    store.delete_entity(deleted.entity_id)

    orch = GraphOrchestrator(store)
    orch.load_seed_entities()

    class _FakeExtractor:
        def find_seed_occurrences(self, text, seeds):
            return [("设计高水位", 0)]
        def find_related_entities(self, text, seed_name, seeds):
            return ["已删除实体"]
        def classify_entity(self, name):
            return EntityLayer.CONCEPT

    orch.extractor = _FakeExtractor()
    packet = EvidencePacket(
        packet_id="p1", library_id="lib", doc_id="doc-x", doc_title="测试文档",
        section_path="1.1", raw_text="设计高水位 影响 已删除实体",
    )
    orch.expand_all_packets([packet], enable_llm=False)

    assert store.get_entity_by_name("已删除实体", "lib") is None

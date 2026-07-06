import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from knowledge_graph.config import EntityLayer, RelationType


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_aliases(aliases: List[str]) -> str:
    return json.dumps(aliases, ensure_ascii=False)


def _deserialize_aliases(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return json.loads(raw)


@dataclass
class GraphEntity:
    name: str
    layer: EntityLayer
    entity_id: str = field(default_factory=_generate_id)
    aliases: List[str] = field(default_factory=list)
    description: str = ""
    source_doc: str = ""
    source_clause: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "GraphEntity":
        return cls(
            entity_id=row["entity_id"],
            name=row["name"],
            layer=EntityLayer(row["layer"]),
            aliases=_deserialize_aliases(row["aliases_json"]),
            description=row["description"],
            source_doc=row["source_doc"],
            source_clause=row["source_clause"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class GraphRelation:
    source_id: str
    target_id: str
    relation_type: RelationType
    relation_id: str = field(default_factory=_generate_id)
    confidence: float = 0.3
    evidence_text: str = ""
    source_clause: str = ""
    conflict_note: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "GraphRelation":
        return cls(
            relation_id=row["relation_id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            relation_type=RelationType(row["relation_type"]),
            confidence=row["confidence"],
            evidence_text=row["evidence_text"],
            source_clause=row["source_clause"],
            conflict_note=row["conflict_note"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class GraphStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def close(self):
        pass

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS graph_entities (
                    entity_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    layer TEXT NOT NULL CHECK(layer IN ('concept','condition','action')),
                    aliases_json TEXT DEFAULT '[]',
                    description TEXT DEFAULT '',
                    source_doc TEXT DEFAULT '',
                    source_clause TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS graph_relations (
                    relation_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES graph_entities(entity_id),
                    target_id TEXT NOT NULL REFERENCES graph_entities(entity_id),
                    relation_type TEXT NOT NULL CHECK(relation_type IN ('defines','requires','constrains','conditions_on','computes_from','verifies')),
                    confidence REAL NOT NULL DEFAULT 0.3,
                    evidence_text TEXT DEFAULT '',
                    source_clause TEXT DEFAULT '',
                    conflict_note TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_id, target_id, relation_type)
                );

                CREATE INDEX IF NOT EXISTS idx_entities_name ON graph_entities(name);
                CREATE INDEX IF NOT EXISTS idx_entities_layer ON graph_entities(layer);
                CREATE INDEX IF NOT EXISTS idx_relations_source ON graph_relations(source_id);
                CREATE INDEX IF NOT EXISTS idx_relations_target ON graph_relations(target_id);
                CREATE INDEX IF NOT EXISTS idx_relations_type ON graph_relations(relation_type);
            """)

    def upsert_entity(self, entity: GraphEntity) -> GraphEntity:
        now = _now()
        existing = self.get_entity_by_name(entity.name)
        with self._connect() as conn:
            if existing:
                merged_aliases = list(set(existing.aliases + entity.aliases))
                entity.entity_id = existing.entity_id
                entity.created_at = existing.created_at
                entity.updated_at = now
                entity.aliases = merged_aliases
                conn.execute(
                    """UPDATE graph_entities SET
                        layer=?, aliases_json=?, description=?,
                        source_doc=?, source_clause=?, updated_at=?
                    WHERE entity_id=?""",
                    (
                        entity.layer.value,
                        _serialize_aliases(merged_aliases),
                        entity.description,
                        entity.source_doc,
                        entity.source_clause,
                        now,
                        existing.entity_id,
                    ),
                )
            else:
                entity.entity_id = entity.entity_id or _generate_id()
                entity.created_at = now
                entity.updated_at = now
                conn.execute(
                    """INSERT INTO graph_entities
                        (entity_id, name, layer, aliases_json, description, source_doc, source_clause, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        entity.entity_id,
                        entity.name,
                        entity.layer.value,
                        _serialize_aliases(entity.aliases),
                        entity.description,
                        entity.source_doc,
                        entity.source_clause,
                        now,
                        now,
                    ),
                )
        return entity

    def get_entity_by_name(self, name: str) -> Optional[GraphEntity]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM graph_entities WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                return None
            return GraphEntity.from_row(row)

    def get_entity(self, entity_id: str) -> Optional[GraphEntity]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM graph_entities WHERE entity_id = ?", (entity_id,)
            ).fetchone()
            if row is None:
                return None
            return GraphEntity.from_row(row)

    def search_entities(self, query: str, limit: int = 20) -> List[GraphEntity]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM graph_entities WHERE name LIKE ? LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
            return [GraphEntity.from_row(r) for r in rows]

    def list_entities_by_layer(self, layer: EntityLayer) -> List[GraphEntity]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM graph_entities WHERE layer = ?", (layer.value,)
            ).fetchall()
            return [GraphEntity.from_row(r) for r in rows]

    def list_all_entities(self) -> List[GraphEntity]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM graph_entities").fetchall()
            return [GraphEntity.from_row(r) for r in rows]

    def add_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        confidence: float = 0.3,
        evidence_text: str = "",
        source_clause: str = "",
    ) -> GraphRelation:
        now = _now()
        existing = self._get_relation_by_triple(source_id, target_id, relation_type)
        with self._connect() as conn:
            if existing:
                new_confidence = max(existing.confidence, confidence)
                merged_evidence = existing.evidence_text
                if evidence_text and evidence_text not in merged_evidence:
                    merged_evidence = evidence_text
                merged_clause = existing.source_clause
                if source_clause and source_clause not in merged_clause:
                    merged_clause = source_clause
                conn.execute(
                    """UPDATE graph_relations SET
                        confidence=?, evidence_text=?, source_clause=?, updated_at=?
                    WHERE relation_id=?""",
                    (new_confidence, merged_evidence, merged_clause, now, existing.relation_id),
                )
                existing.confidence = new_confidence
                existing.evidence_text = merged_evidence
                existing.source_clause = merged_clause
                existing.updated_at = now
                return existing
            else:
                relation_id = _generate_id()
                conn.execute(
                    """INSERT INTO graph_relations
                        (relation_id, source_id, target_id, relation_type, confidence, evidence_text, source_clause, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        relation_id,
                        source_id,
                        target_id,
                        relation_type.value,
                        confidence,
                        evidence_text,
                        source_clause,
                        now,
                        now,
                    ),
                )
                return GraphRelation(
                    relation_id=relation_id,
                    source_id=source_id,
                    target_id=target_id,
                    relation_type=relation_type,
                    confidence=confidence,
                    evidence_text=evidence_text,
                    source_clause=source_clause,
                    created_at=now,
                    updated_at=now,
                )

    def _get_relation_by_triple(
        self, source_id: str, target_id: str, relation_type: RelationType
    ) -> Optional[GraphRelation]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM graph_relations WHERE source_id=? AND target_id=? AND relation_type=?",
                (source_id, target_id, relation_type.value),
            ).fetchone()
            if row is None:
                return None
            return GraphRelation.from_row(row)

    def get_relation(self, relation_id: str) -> Optional[GraphRelation]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM graph_relations WHERE relation_id = ?", (relation_id,)
            ).fetchone()
            if row is None:
                return None
            return GraphRelation.from_row(row)

    def get_relations_by_entity(
        self, entity_id: str, direction: str = "both"
    ) -> List[GraphRelation]:
        with self._connect() as conn:
            if direction == "outgoing":
                rows = conn.execute(
                    "SELECT * FROM graph_relations WHERE source_id = ?", (entity_id,)
                ).fetchall()
            elif direction == "incoming":
                rows = conn.execute(
                    "SELECT * FROM graph_relations WHERE target_id = ?", (entity_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM graph_relations WHERE source_id = ? OR target_id = ?",
                    (entity_id, entity_id),
                ).fetchall()
            return [GraphRelation.from_row(r) for r in rows]

    def mark_relation_conflict(self, relation_id: str, note: str) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """UPDATE graph_relations SET confidence=?, conflict_note=?, updated_at=?
                WHERE relation_id=?""",
                (-1.0, note, now, relation_id),
            )

    def get_stats(self) -> Dict[str, Any]:
        with self._connect() as conn:
            entity_count = conn.execute(
                "SELECT COUNT(*) FROM graph_entities"
            ).fetchone()[0]
            relation_count = conn.execute(
                "SELECT COUNT(*) FROM graph_relations"
            ).fetchone()[0]
            entities_by_layer = {
                r["layer"]: r["cnt"]
                for r in conn.execute(
                    "SELECT layer, COUNT(*) as cnt FROM graph_entities GROUP BY layer"
                ).fetchall()
            }
            relations_by_type = {
                r["relation_type"]: r["cnt"]
                for r in conn.execute(
                    "SELECT relation_type, COUNT(*) as cnt FROM graph_relations GROUP BY relation_type"
                ).fetchall()
            }
        return {
            "entity_count": entity_count,
            "relation_count": relation_count,
            "entities_by_layer": entities_by_layer,
            "relations_by_type": relations_by_type,
        }

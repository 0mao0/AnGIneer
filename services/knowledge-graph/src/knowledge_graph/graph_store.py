import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from knowledge_graph.config import Confidence, EntityLayer, RelationType


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
class PrincipleData:
    principle_id: str = field(default_factory=_generate_id)
    principle_text: str = ""
    category: str = ""
    source_clause: str = ""
    evidence_quote: str = ""
    library_id: str = ""
    doc_id: str = ""
    created_at: str = field(default_factory=_now)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "PrincipleData":
        return cls(
            principle_id=row["principle_id"],
            principle_text=row["principle_text"],
            category=row["category"],
            source_clause=row["source_clause"],
            evidence_quote=row["evidence_quote"],
            library_id=row["library_id"],
            doc_id=row["doc_id"],
            created_at=row["created_at"],
        )


@dataclass
class Example:
    example_id: str = field(default_factory=_generate_id)
    title: str = ""
    inputs_json: str = "{}"
    computation_text: str = ""
    source_section: str = ""
    library_id: str = ""
    doc_id: str = ""
    created_at: str = field(default_factory=_now)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Example":
        return cls(
            example_id=row["example_id"],
            title=row["title"],
            inputs_json=row["inputs_json"],
            computation_text=row["computation_text"],
            source_section=row["source_section"],
            library_id=row["library_id"],
            doc_id=row["doc_id"],
            created_at=row["created_at"],
        )


@dataclass
class WarningItem:
    warning_id: str = field(default_factory=_generate_id)
    warning_text: str = ""
    category: str = ""
    severity: str = ""
    source_section: str = ""
    library_id: str = ""
    doc_id: str = ""
    created_at: str = field(default_factory=_now)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "PrincipleData":
        return cls(
            principle_id=row["principle_id"],
            principle_text=row["principle_text"],
            category=row["category"],
            source_clause=row["source_clause"],
            evidence_quote=row["evidence_quote"],
            library_id=row["library_id"],
            doc_id=row["doc_id"],
            created_at=row["created_at"],
        )


@dataclass
class Framework:
    framework_id: str = field(default_factory=_generate_id)
    name: str = ""
    steps_json: str = "[]"
    entry_condition: str = ""
    source_section: str = ""
    entity_path: str = "[]"
    library_id: str = ""
    doc_id: str = ""
    created_at: str = field(default_factory=_now)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Framework":
        return cls(
            framework_id=row["framework_id"],
            name=row["name"],
            steps_json=row["steps_json"],
            entry_condition=row["entry_condition"],
            source_section=row["source_section"],
            entity_path=row["entity_path"],
            library_id=row["library_id"],
            doc_id=row["doc_id"],
            created_at=row["created_at"],
        )


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
    library_id: str = ""
    doc_id: str = ""
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
            library_id=row["library_id"],
            doc_id=row["doc_id"],
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
                    library_id TEXT DEFAULT '',
                    doc_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_id, target_id, relation_type, library_id, doc_id)
                );

                CREATE INDEX IF NOT EXISTS idx_entities_name ON graph_entities(name);
                CREATE INDEX IF NOT EXISTS idx_entities_layer ON graph_entities(layer);
                CREATE INDEX IF NOT EXISTS idx_relations_source ON graph_relations(source_id);
                CREATE INDEX IF NOT EXISTS idx_relations_target ON graph_relations(target_id);
                CREATE INDEX IF NOT EXISTS idx_relations_type ON graph_relations(relation_type);
                CREATE INDEX IF NOT EXISTS idx_relations_doc ON graph_relations(library_id, doc_id);

                CREATE TABLE IF NOT EXISTS graph_principles (
                    principle_id TEXT PRIMARY KEY,
                    principle_text TEXT NOT NULL,
                    category TEXT DEFAULT 'mandatory',
                    source_clause TEXT DEFAULT '',
                    evidence_quote TEXT DEFAULT '',
                    library_id TEXT DEFAULT '',
                    doc_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS principle_entities (
                    principle_id TEXT NOT NULL REFERENCES graph_principles(principle_id),
                    entity_id TEXT NOT NULL REFERENCES graph_entities(entity_id),
                    UNIQUE(principle_id, entity_id)
                );

                CREATE TABLE IF NOT EXISTS graph_examples (
                    example_id TEXT PRIMARY KEY,
                    title TEXT DEFAULT '',
                    inputs_json TEXT DEFAULT '{}',
                    computation_text TEXT DEFAULT '',
                    source_section TEXT DEFAULT '',
                    library_id TEXT DEFAULT '',
                    doc_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS example_entities (
                    example_id TEXT NOT NULL REFERENCES graph_examples(example_id),
                    entity_id TEXT NOT NULL REFERENCES graph_entities(entity_id),
                    UNIQUE(example_id, entity_id)
                );

                CREATE TABLE IF NOT EXISTS graph_warnings (
                    warning_id TEXT PRIMARY KEY,
                    warning_text TEXT NOT NULL,
                    category TEXT DEFAULT '',
                    severity TEXT DEFAULT 'quality',
                    source_section TEXT DEFAULT '',
                    library_id TEXT DEFAULT '',
                    doc_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS warning_entities (
                    warning_id TEXT NOT NULL REFERENCES graph_warnings(warning_id),
                    entity_id TEXT NOT NULL REFERENCES graph_entities(entity_id),
                    UNIQUE(warning_id, entity_id)
                );

                CREATE TABLE IF NOT EXISTS graph_frameworks (
                    framework_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    steps_json TEXT DEFAULT '[]',
                    entry_condition TEXT DEFAULT '',
                    source_section TEXT DEFAULT '',
                    entity_path TEXT DEFAULT '[]',
                    library_id TEXT DEFAULT '',
                    doc_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_principles_doc ON graph_principles(library_id, doc_id);
                CREATE INDEX IF NOT EXISTS idx_examples_doc ON graph_examples(library_id, doc_id);
                CREATE INDEX IF NOT EXISTS idx_warnings_doc ON graph_warnings(library_id, doc_id);
                CREATE INDEX IF NOT EXISTS idx_frameworks_doc ON graph_frameworks(library_id, doc_id);
            """)

    def upsert_entity(self, entity: GraphEntity) -> GraphEntity:
        now = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM graph_entities WHERE name = ?", (entity.name,)
            ).fetchone()
            if row:
                existing = GraphEntity.from_row(row)
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
                "SELECT * FROM graph_entities WHERE name LIKE ? OR aliases_json LIKE ? LIMIT ?",
                (f"%{query}%", f"%{query}%", limit),
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
        library_id: str = "",
        doc_id: str = "",
    ) -> GraphRelation:
        now = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM graph_relations WHERE source_id=? AND target_id=? AND relation_type=? AND library_id=? AND doc_id=?",
                (source_id, target_id, relation_type.value, library_id, doc_id),
            ).fetchone()
            if row:
                existing = GraphRelation.from_row(row)
                new_confidence = max(existing.confidence, confidence)
                merged_evidence = existing.evidence_text
                if evidence_text and evidence_text != merged_evidence:
                    merged_evidence = evidence_text
                merged_clause = existing.source_clause
                if source_clause and source_clause != merged_clause:
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
                        (relation_id, source_id, target_id, relation_type, confidence, evidence_text, source_clause, library_id, doc_id, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        relation_id,
                        source_id,
                        target_id,
                        relation_type.value,
                        confidence,
                        evidence_text,
                        source_clause,
                        library_id,
                        doc_id,
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
                    library_id=library_id,
                    doc_id=doc_id,
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

    def get_relations_by_doc(self, library_id: str, doc_id: str) -> List[GraphRelation]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM graph_relations WHERE library_id=? AND doc_id=?",
                (library_id, doc_id),
            ).fetchall()
            return [GraphRelation.from_row(r) for r in rows]

    def list_entities_by_doc(self, library_id: str, doc_id: str) -> List[GraphEntity]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT DISTINCT e.* FROM graph_entities e
                   JOIN graph_relations r ON (e.entity_id = r.source_id OR e.entity_id = r.target_id)
                   WHERE r.library_id=? AND r.doc_id=?""",
                (library_id, doc_id),
            ).fetchall()
            return [GraphEntity.from_row(r) for r in rows]

    def upsert_entity_by_name(
        self, name: str, layer: str, source_doc: str = "", source_clause: str = "",
        description: str = "", aliases: Optional[List[str]] = None,
    ) -> GraphEntity:
        entity = GraphEntity(
            name=name,
            layer=EntityLayer(layer) if isinstance(layer, str) else layer,
            source_doc=source_doc,
            source_clause=source_clause,
            description=description,
            aliases=aliases or [],
        )
        return self.upsert_entity(entity)

    def add_relation_by_names(
        self, source_name: str, target_name: str, relation_type: RelationType,
        confidence: float = 0.3, evidence_text: str = "", source_clause: str = "",
        library_id: str = "", doc_id: str = "",
    ) -> Optional[GraphRelation]:
        src = self.get_entity_by_name(source_name)
        tgt = self.get_entity_by_name(target_name)
        if src and tgt:
            return self.add_relation(
                source_id=src.entity_id, target_id=tgt.entity_id,
                relation_type=relation_type, confidence=confidence,
                evidence_text=evidence_text, source_clause=source_clause,
                library_id=library_id, doc_id=doc_id,
            )
        return None

    def mark_relation_conflict(self, relation_id: str, note: str) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """UPDATE graph_relations SET confidence=?, conflict_note=?, updated_at=?
                WHERE relation_id=?""",
                (Confidence.CONFLICT, note, now, relation_id),
            )

    def add_framework(self, name: str, steps_json: str, entry_condition: str, source_section: str,
                      entity_path: List[str], library_id: str, doc_id: str) -> str:
        fw_id = _generate_id()
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO graph_frameworks
                   (framework_id, name, steps_json, entry_condition, source_section, entity_path, library_id, doc_id, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (fw_id, name, steps_json, entry_condition, source_section,
                 json.dumps(entity_path, ensure_ascii=False), library_id, doc_id, now),
            )
        return fw_id

    def get_frameworks_by_doc(self, library_id: str, doc_id: str) -> List[Framework]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM graph_frameworks WHERE library_id=? AND doc_id=?",
                (library_id, doc_id),
            ).fetchall()
        return [Framework.from_row(r) for r in rows]

    def add_principle(self, principle_text: str, category: str, entity_names: List[str],
                      source_clause: str, evidence_quote: str, library_id: str, doc_id: str) -> str:
        pr_id = _generate_id()
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO graph_principles
                   (principle_id, principle_text, category, source_clause, evidence_quote, library_id, doc_id, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (pr_id, principle_text, category[:50], source_clause, evidence_quote, library_id, doc_id, now),
            )
            for name in entity_names:
                entity = conn.execute("SELECT entity_id FROM graph_entities WHERE name=?", (name,)).fetchone()
                if entity:
                    conn.execute(
                        "INSERT OR IGNORE INTO principle_entities (principle_id, entity_id) VALUES (?,?)",
                        (pr_id, entity["entity_id"]),
                    )
        return pr_id

    def get_principles_by_entity_ids(self, entity_ids: List[str]) -> List[PrincipleData]:
        if not entity_ids:
            return []
        placeholders = ",".join("?" * len(entity_ids))
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT DISTINCT p.* FROM graph_principles p
                    JOIN principle_entities pe ON p.principle_id = pe.principle_id
                    WHERE pe.entity_id IN ({placeholders})""",
                entity_ids,
            ).fetchall()
        return [PrincipleData.from_row(r) for r in rows]

    def add_example(self, title: str, inputs_json: str, computation_text: str,
                    entity_names: List[str], source_section: str, library_id: str, doc_id: str) -> str:
        ex_id = _generate_id()
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO graph_examples
                   (example_id, title, inputs_json, computation_text, source_section, library_id, doc_id, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (ex_id, title, inputs_json, computation_text, source_section, library_id, doc_id, now),
            )
            for name in entity_names:
                entity_id = conn.execute("SELECT entity_id FROM graph_entities WHERE name=?", (name,)).fetchone()
                if entity_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO example_entities (example_id, entity_id) VALUES (?,?)",
                        (ex_id, entity_id["entity_id"]),
                    )
        return ex_id

    def get_examples_by_entity_ids(self, entity_ids: List[str]) -> List[Example]:
        if not entity_ids:
            return []
        placeholders = ",".join("?" * len(entity_ids))
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT DISTINCT e.* FROM graph_examples e
                    JOIN example_entities ee ON e.example_id = ee.example_id
                    WHERE ee.entity_id IN ({placeholders})""",
                entity_ids,
            ).fetchall()
        return [Example.from_row(r) for r in rows]

    def add_warning(self, warning_text: str, category: str, severity: str,
                    entity_names: List[str], source_section: str, library_id: str, doc_id: str) -> str:
        w_id = _generate_id()
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO graph_warnings
                   (warning_id, warning_text, category, severity, source_section, library_id, doc_id, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (w_id, warning_text, category[:50], severity[:50], source_section, library_id, doc_id, now),
            )
            for name in entity_names:
                entity_id = conn.execute("SELECT entity_id FROM graph_entities WHERE name=?", (name,)).fetchone()
                if entity_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO warning_entities (warning_id, entity_id) VALUES (?,?)",
                        (w_id, entity_id["entity_id"]),
                    )
        return w_id

    def get_warnings_by_entity_ids(self, entity_ids: List[str]) -> List[WarningItem]:
        if not entity_ids:
            return []
        placeholders = ",".join("?" * len(entity_ids))
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT DISTINCT w.* FROM graph_warnings w
                    JOIN warning_entities we ON w.warning_id = we.warning_id
                    WHERE we.entity_id IN ({placeholders})""",
                entity_ids,
            ).fetchall()
        return [WarningItem.from_row(r) for r in rows]

    def update_entity_glossary(self, term: str, definition: str, aliases: List[str], source_section: str) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM graph_entities WHERE name=?", (term,)).fetchone()
            if row:
                existing = GraphEntity.from_row(row)
                merged_aliases = list(set(existing.aliases + aliases))
                new_desc = existing.description
                note = f"[{source_section}] {definition}"
                if note not in new_desc:
                    new_desc = (new_desc + "\n" + note).strip()
                conn.execute(
                    """UPDATE graph_entities SET description=?, aliases_json=?, updated_at=?
                    WHERE entity_id=?""",
                    (new_desc, _serialize_aliases(merged_aliases), _now(), existing.entity_id),
                )

    def get_stats(self, library_id: Optional[str] = None, doc_id: Optional[str] = None) -> Dict[str, Any]:
        with self._connect() as conn:
            if library_id and doc_id:
                entity_count = conn.execute(
                    """SELECT COUNT(DISTINCT e.entity_id) FROM graph_entities e
                       JOIN graph_relations r ON (e.entity_id = r.source_id OR e.entity_id = r.target_id)
                       WHERE r.library_id=? AND r.doc_id=?""",
                    (library_id, doc_id),
                ).fetchone()[0]
                relation_count = conn.execute(
                    "SELECT COUNT(*) FROM graph_relations WHERE library_id=? AND doc_id=?",
                    (library_id, doc_id),
                ).fetchone()[0]
                entities_by_layer = {
                    r["layer"]: r["cnt"]
                    for r in conn.execute(
                        """SELECT e.layer, COUNT(DISTINCT e.entity_id) as cnt FROM graph_entities e
                           JOIN graph_relations r ON (e.entity_id = r.source_id OR e.entity_id = r.target_id)
                           WHERE r.library_id=? AND r.doc_id=?
                           GROUP BY e.layer""",
                        (library_id, doc_id),
                    ).fetchall()
                }
                relations_by_type = {
                    r["relation_type"]: r["cnt"]
                    for r in conn.execute(
                        "SELECT relation_type, COUNT(*) as cnt FROM graph_relations WHERE library_id=? AND doc_id=? GROUP BY relation_type",
                        (library_id, doc_id),
                    ).fetchall()
                }
            else:
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

    def get_docs_with_graph(self, library_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT library_id, doc_id, COUNT(*) as relation_count
                   FROM graph_relations WHERE library_id=?
                   GROUP BY library_id, doc_id ORDER BY doc_id""",
                (library_id,),
            ).fetchall()
        return [{"library_id": r["library_id"], "doc_id": r["doc_id"], "relation_count": r["relation_count"]} for r in rows]

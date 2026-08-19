# 知识图谱通用实体库与管理员审批 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每个 library 拥有带审批状态的通用实体库：新 PDF 解析后自动跑 LLM 抽取，新实体进入 pending，管理员批准或拒绝，拒绝后重抽受影响文档。

**Architecture:** 在现有 `docs_core.step07_graph` 上扩展：`graph_entities` 增加实体状态字段；`GraphStore` 统一状态过滤；`GraphOrchestrator` 新实体写入 pending 并支持忽略名单；新增后台 LLM 抽取线程；docs-api 增加审批接口；admin-web 增加实体审核抽屉。

**Tech Stack:** Python 3 / SQLite / FastAPI / Vue 3 + Ant Design Vue

---

## 文件结构

**后端**
- 修改：`services/docs-core/src/docs_core/step07_graph/config.py`
- 修改：`services/docs-core/src/docs_core/step07_graph/__init__.py`
- 修改：`services/docs-core/src/docs_core/step07_graph/graph_store.py`
- 新建：`services/docs-core/src/docs_core/step07_graph/entity_dedup.py`
- 修改：`services/docs-core/src/docs_core/step07_graph/graph_orchestrator.py`
- 修改：`services/docs-core/src/docs_core/step07_graph/push_to_graph.py`
- 新建：`services/docs-core/src/docs_core/step07_graph/auto_extract.py`
- 修改：`services/docs-core/src/docs_core/parse_pipeline.py`
- 修改：`services/docs-api/graph_routes.py`
- 测试：`services/docs-core/tests/test_graph_entity_status.py`
- 测试：`services/docs-core/tests/test_graph_entity_approval.py`

**前端**
- 修改：`apps/admin-web/src/api/knowledge.ts`
- 新建：`apps/admin-web/src/components/EntityReviewDrawer.vue`
- 修改：`apps/admin-web/src/components/KnowledgeStats.vue`
- 修改：`packages/docs-ui/src/components/common/index/Preview_KnowledgeGraph.vue`

---

### Task 1: 实体状态枚举与数据模型

**Files:**
- Modify: `services/docs-core/src/docs_core/step07_graph/config.py`
- Modify: `services/docs-core/src/docs_core/step07_graph/__init__.py`
- Modify: `services/docs-core/src/docs_core/step07_graph/graph_store.py`
- Test: `services/docs-core/tests/test_graph_entity_status.py`

- [ ] **Step 1: 写失败测试**

新建 `services/docs-core/tests/test_graph_entity_status.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest services/docs-core/tests/test_graph_entity_status.py -v`
Expected: FAIL，`GraphEntity.__init__()` 出现 unexpected keyword argument `status` 或 `status` 列不存在。

- [ ] **Step 3: 增加 EntityStatus 枚举**

修改 `services/docs-core/src/docs_core/step07_graph/config.py`，在 `RelationType` 后加入：

```python
class EntityStatus(str, Enum):
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"
```

修改 `services/docs-core/src/docs_core/step07_graph/__init__.py` 第 3 行：

```python
from .config import EntityLayer, EntityStatus, RelationType, EntitySeed, Confidence, load_seed_entities, DEFAULT_SEED_ENTITIES, DEFAULT_LLM_CONFIG
```

- [ ] **Step 4: GraphEntity 增加 status 字段**

修改 `services/docs-core/src/docs_core/step07_graph/graph_store.py`，在 `GraphEntity` dataclass 的 `library_id` 字段后加入：

```python
    status: EntityStatus = EntityStatus.APPROVED
    proposed_doc_id: str = ""
    proposed_by: str = ""
    reject_reason: str = ""
    reviewed_at: str = ""
    reviewed_by: str = ""
```

顶部 import 增加 `EntityStatus`：

```python
from docs_core.step07_graph.config import Confidence, EntityLayer, EntityStatus, RelationType
```

- [ ] **Step 5: 更新建表语句与迁移**

修改 `_ENTITIES_TABLE_SQL` 为：

```python
_ENTITIES_TABLE_SQL = """
                CREATE TABLE IF NOT EXISTS graph_entities (
                    entity_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    layer TEXT NOT NULL CHECK(layer IN ('concept','condition','action')),
                    aliases_json TEXT DEFAULT '[]',
                    description TEXT DEFAULT '',
                    source_doc TEXT DEFAULT '',
                    source_clause TEXT DEFAULT '',
                    library_id TEXT NOT NULL DEFAULT 'default',
                    status TEXT NOT NULL DEFAULT 'approved',
                    proposed_doc_id TEXT DEFAULT '',
                    proposed_by TEXT DEFAULT '',
                    reject_reason TEXT DEFAULT '',
                    reviewed_at TEXT DEFAULT '',
                    reviewed_by TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(name, library_id)
                );
"""
```

修改 `_init_schema` 中旧表迁移的 `INSERT OR IGNORE INTO graph_entities_new` 部分，为新增列提供默认值。把该段替换为：

```python
                        conn.execute("""
                            INSERT OR IGNORE INTO graph_entities_new
                                (entity_id, name, layer, aliases_json, description, source_doc, source_clause, library_id,
                                 status, proposed_doc_id, proposed_by, reject_reason, reviewed_at, reviewed_by, created_at, updated_at)
                            SELECT entity_id, name, layer, aliases_json, description, source_doc, source_clause, 'default',
                                 'approved', '', '', '', '', '', created_at, updated_at
                            FROM graph_entities
                        """)
```

在 `conn.executescript(...)` 之前，加入对“已存在且有 library_id 但没有 status 列”的旧表迁移：

```python
            entity_cols = [r[1] for r in conn.execute("PRAGMA table_info(graph_entities)")]
            for col_name, ddl in (
                ("status", "status TEXT NOT NULL DEFAULT 'approved'"),
                ("proposed_doc_id", "proposed_doc_id TEXT DEFAULT ''"),
                ("proposed_by", "proposed_by TEXT DEFAULT ''"),
                ("reject_reason", "reject_reason TEXT DEFAULT ''"),
                ("reviewed_at", "reviewed_at TEXT DEFAULT ''"),
                ("reviewed_by", "reviewed_by TEXT DEFAULT ''"),
            ):
                if col_name not in entity_cols:
                    conn.execute(f"ALTER TABLE graph_entities ADD COLUMN {ddl}")
```

在 `conn.executescript` 的索引部分加入：

```sql
                CREATE INDEX IF NOT EXISTS idx_entities_status ON graph_entities(library_id, status);
                CREATE INDEX IF NOT EXISTS idx_entities_proposed_doc ON graph_entities(library_id, proposed_doc_id);
```

- [ ] **Step 6: 更新 from_row 与 upsert**

修改 `GraphEntity.from_row`，在 `library_id=row["library_id"]` 后加入：

```python
            status=EntityStatus(row["status"]),
            proposed_doc_id=row["proposed_doc_id"],
            proposed_by=row["proposed_by"],
            reject_reason=row["reject_reason"],
            reviewed_at=row["reviewed_at"],
            reviewed_by=row["reviewed_by"],
```

修改 `upsert_entity` 的 INSERT 语句，使新实体落库 status 等新列：

```python
                conn.execute(
                    """INSERT INTO graph_entities
                        (entity_id, name, layer, aliases_json, description, source_doc, source_clause, library_id,
                         status, proposed_doc_id, proposed_by, reject_reason, reviewed_at, reviewed_by, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        entity.entity_id,
                        entity.name,
                        entity.layer.value,
                        _serialize_aliases(entity.aliases),
                        entity.description,
                        entity.source_doc,
                        entity.source_clause,
                        entity.library_id,
                        entity.status.value,
                        entity.proposed_doc_id,
                        entity.proposed_by,
                        entity.reject_reason,
                        entity.reviewed_at,
                        entity.reviewed_by,
                        now,
                        now,
                    ),
                )
```

UPDATE 语句保持不动，即**已存在实体不覆盖 status/review 字段**。

- [ ] **Step 7: 运行测试确认通过**

Run: `pytest services/docs-core/tests/test_graph_entity_status.py -v`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add services/docs-core/src/docs_core/step07_graph/config.py services/docs-core/src/docs_core/step07_graph/__init__.py services/docs-core/src/docs_core/step07_graph/graph_store.py services/docs-core/tests/test_graph_entity_status.py
git commit -m "feat: graph_entities 增加实体状态字段与迁移"
```

---

### Task 2: GraphStore 状态过滤查询

**Files:**
- Modify: `services/docs-core/src/docs_core/step07_graph/graph_store.py`
- Test: `services/docs-core/tests/test_graph_entity_status.py`

- [ ] **Step 1: 写失败测试**

追加到 `services/docs-core/tests/test_graph_entity_status.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest services/docs-core/tests/test_graph_entity_status.py::test_list_entities_by_doc_excludes_rejected services/docs-core/tests/test_graph_entity_status.py::test_list_entities_by_status -v`
Expected: FAIL，`list_entities_by_status` 不存在；`list_entities_by_doc` 未排除 rejected。

- [ ] **Step 3: 实现状态过滤方法**

修改 `services/docs-core/src/docs_core/step07_graph/graph_store.py`。

`list_entities_by_doc` 的 SQL 增加状态过滤：

```python
    def list_entities_by_doc(self, library_id: str, doc_id: str) -> List[GraphEntity]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT DISTINCT e.* FROM graph_entities e
                   JOIN graph_relations r ON (e.entity_id = r.source_id OR e.entity_id = r.target_id)
                   WHERE r.library_id=? AND r.doc_id=? AND e.status != 'rejected'""",
                (library_id, doc_id),
            ).fetchall()
            return [GraphEntity.from_row(r) for r in rows]
```

在 `list_entities_by_layer` 后新增：

```python
    def list_entities_by_status(self, library_id: str, status: EntityStatus) -> List[GraphEntity]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM graph_entities WHERE library_id=? AND status=? ORDER BY created_at DESC",
                (library_id, status.value),
            ).fetchall()
            return [GraphEntity.from_row(r) for r in rows]
```

修改 `search_entities`，增加 status 过滤：

```python
    def search_entities(self, query: str, limit: int = 20, library_id: Optional[str] = None,
                        status: Optional[EntityStatus] = None) -> List[GraphEntity]:
        clauses = ["(name LIKE ? OR aliases_json LIKE ?)"]
        args: List[Any] = [f"%{query}%", f"%{query}%"]
        if library_id is not None:
            clauses.append("library_id = ?")
            args.append(library_id)
        if status is not None:
            clauses.append("status = ?")
            args.append(status.value)
        where = " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM graph_entities WHERE {where} LIMIT ?",
                (*args, limit),
            ).fetchall()
            return [GraphEntity.from_row(r) for r in rows]
```

修改 `get_stats`：全局统计只数 approved；文档统计排除 rejected。将两个分支中的实体计数 SQL 替换为：

- 文档分支：

```python
                entity_count = conn.execute(
                    """SELECT COUNT(DISTINCT e.entity_id) FROM graph_entities e
                       JOIN graph_relations r ON (e.entity_id = r.source_id OR e.entity_id = r.target_id)
                       WHERE r.library_id=? AND r.doc_id=? AND e.status != 'rejected'""",
                    (library_id, doc_id),
                ).fetchone()[0]
```

以及 `entities_by_layer` 子查询加入 `AND e.status != 'rejected'`。

- 全局分支：

```python
                entity_count = conn.execute(
                    "SELECT COUNT(*) FROM graph_entities WHERE status='approved'"
                ).fetchone()[0]
```

以及 `entities_by_layer` 全局 SQL 改为 `WHERE status='approved' GROUP BY layer`。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest services/docs-core/tests/test_graph_entity_status.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add services/docs-core/src/docs_core/step07_graph/graph_store.py services/docs-core/tests/test_graph_entity_status.py
git commit -m "feat: GraphStore 状态过滤查询"
```

---

### Task 3: 审批与拒绝相关的存储方法

**Files:**
- Modify: `services/docs-core/src/docs_core/step07_graph/graph_store.py`
- Test: `services/docs-core/tests/test_graph_entity_approval.py`

- [ ] **Step 1: 写失败测试**

新建 `services/docs-core/tests/test_graph_entity_approval.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest services/docs-core/tests/test_graph_entity_approval.py -v`
Expected: FAIL，`approve_entity` 等属性不存在。

- [ ] **Step 3: 实现审批/拒绝/关系清理方法**

在 `services/docs-core/src/docs_core/step07_graph/graph_store.py` 的 `GraphStore` 类中，`update_entity_glossary` 后新增：

```python
    def approve_entity(self, entity_id: str, reviewer: str = "") -> bool:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE graph_entities SET status='approved', reviewed_at=?, reviewed_by=?, reject_reason=''
                   WHERE entity_id=?""",
                (now, reviewer, entity_id),
            )
            return int(cur.rowcount or 0) > 0

    def reject_entity(self, entity_id: str, reason: str, reviewer: str = "") -> bool:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE graph_entities SET status='rejected', reviewed_at=?, reviewed_by=?, reject_reason=?
                   WHERE entity_id=?""",
                (now, reviewer, reason, entity_id),
            )
            return int(cur.rowcount or 0) > 0

    def get_docs_referencing_entity(self, entity_id: str) -> List[tuple]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT DISTINCT library_id, doc_id FROM graph_relations
                   WHERE (source_id=? OR target_id=?) AND library_id != '' AND doc_id != ''""",
                (entity_id, entity_id),
            ).fetchall()
            return [(r["library_id"], r["doc_id"]) for r in rows]

    def delete_relations_for_entity(self, entity_id: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM graph_relations WHERE source_id=? OR target_id=?",
                (entity_id, entity_id),
            )
            return int(cur.rowcount or 0)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest services/docs-core/tests/test_graph_entity_approval.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add services/docs-core/src/docs_core/step07_graph/graph_store.py services/docs-core/tests/test_graph_entity_approval.py
git commit -m "feat: 实体审批/拒绝与关系清理"
```

---

### Task 4: 实体去重/别名归并

**Files:**
- Create: `services/docs-core/src/docs_core/step07_graph/entity_dedup.py`
- Test: `services/docs-core/tests/test_graph_entity_approval.py`

- [ ] **Step 1: 写失败测试**

追加到 `services/docs-core/tests/test_graph_entity_approval.py`：

```python
def test_find_existing_entity_alias_and_normalized(tmp_path) -> None:
    from docs_core.step07_graph.entity_dedup import find_existing_entity
    store = GraphStore(str(tmp_path / "graph.sqlite"))
    store.upsert_entity(GraphEntity(name="承载力验算", layer=EntityLayer.ACTION, library_id="lib",
                                    aliases=["承载力"], status=EntityStatus.APPROVED))

    assert find_existing_entity(store, "承载力", "lib").name == "承载力验算"
    assert find_existing_entity(store, "承载力 验算", "lib").name == "承载力验算"
    assert find_existing_entity(store, "完全不同的实体", "lib") is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest services/docs-core/tests/test_graph_entity_approval.py::test_find_existing_entity_alias_and_normalized -v`
Expected: FAIL，`ModuleNotFoundError: docs_core.step07_graph.entity_dedup`

- [ ] **Step 3: 实现归一化与查找**

新建 `services/docs-core/src/docs_core/step07_graph/entity_dedup.py`：

```python
"""实体去重/别名归并：优先精确，其次归一化，最后模糊相似。"""

import re
from difflib import SequenceMatcher
from typing import Optional

from docs_core.step07_graph.graph_store import GraphEntity, GraphStore

_SIMILARITY_THRESHOLD = 0.92


def normalize_entity_name(name: str) -> str:
    """归一化：去空白、全角转半角、统一小写。"""
    if not name:
        return ""
    text = str(name).strip()
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", "", text)
    for full, half in zip("（）ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ０１２３４５６７８９",
                          "()ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"):
        text = text.replace(full, half)
    return text.lower()


def find_existing_entity(store: GraphStore, name: str, library_id: str) -> Optional[GraphEntity]:
    """在 library 范围内查找可复用的已有实体（排除 rejected）。"""
    if not name or not name.strip():
        return None
    target = str(name).strip()

    exact = store.get_entity_by_name(target, library_id)
    if exact is not None and exact.status.value != "rejected":
        return exact

    norm_target = normalize_entity_name(target)
    best: Optional[GraphEntity] = None
    best_score = 0.0

    for entity in store.list_library_entities(library_id):
        if entity.status.value == "rejected":
            continue
        if entity.name == target:
            return entity
        if any(alias == target for alias in (entity.aliases or [])):
            return entity
        norm_name = normalize_entity_name(entity.name)
        if norm_name and norm_name == norm_target:
            return entity
        if any(normalize_entity_name(a) == norm_target for a in (entity.aliases or [])):
            return entity
        score = SequenceMatcher(None, norm_name, norm_target).ratio()
        if score >= _SIMILARITY_THRESHOLD and score > best_score:
            best = entity
            best_score = score

    return best
```

- [ ] **Step 4: 在 GraphStore 增加 `list_library_entities`**

修改 `services/docs-core/src/docs_core/step07_graph/graph_store.py`，在 `list_entities_by_status` 后新增：

```python
    def list_library_entities(self, library_id: str) -> List[GraphEntity]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM graph_entities WHERE library_id=? ORDER BY created_at DESC",
                (library_id,),
            ).fetchall()
            return [GraphEntity.from_row(r) for r in rows]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest services/docs-core/tests/test_graph_entity_approval.py -v`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add services/docs-core/src/docs_core/step07_graph/entity_dedup.py services/docs-core/src/docs_core/step07_graph/graph_store.py services/docs-core/tests/test_graph_entity_approval.py
git commit -m "feat: 实体去重与别名归并"
```

---

### Task 5: Orchestrator 新实体入池与忽略名单

**Files:**
- Modify: `services/docs-core/src/docs_core/step07_graph/graph_orchestrator.py`
- Test: `services/docs-core/tests/test_graph_entity_status.py`

- [ ] **Step 1: 写失败测试**

追加到 `services/docs-core/tests/test_graph_entity_status.py`：

```python
def test_expand_from_packet_new_llm_entity_is_pending(tmp_path, monkeypatch) -> None:
    from docs_core.step07_graph.evidence_builder import EvidencePacket
    from docs_core.step07_graph.graph_orchestrator import GraphOrchestrator

    store = GraphStore(str(tmp_path / "graph.sqlite"))
    orch = GraphOrchestrator(store)
    orch.load_seed_entities()

    packet = EvidencePacket(
        packet_id="p1", library_id="lib", doc_id="doc-x", doc_title="测试文档",
        section_path="1.1", raw_text="设计高水位 影响 承载力验算",
    )

    class _FakeExtractor:
        def find_seed_occurrences(self, text, seeds):
            return [("设计高水位", 0), ("承载力验算", 8)]
        def find_related_entities(self, text, seed_name, seeds):
            return ["承载力验算"] if seed_name == "设计高水位" else []
        def classify_entity(self, name):
            return EntityLayer.ACTION

    orch.extractor = _FakeExtractor()
    orch.expand_from_packet(packet, enable_llm=False)

    entity = store.get_entity_by_name("承载力验算")
    assert entity is not None
    assert entity.status == EntityStatus.APPROVED  # 种子实体保持 approved
```

（本测试只验证种子基线不破坏状态；LLM 路径测试在 Task 6 的 push_to_graph 测试中覆盖。）

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest services/docs-core/tests/test_graph_entity_status.py::test_expand_from_packet_new_llm_entity_is_pending -v`
Expected: 通过？此测试在 Task 1/2 后应已通过。**此任务实际需要追加的是忽略名单测试**，先追加下面测试并确认失败：

```python
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
            return ["承载力验算"]
        def classify_entity(self, name):
            return EntityLayer.ACTION

    orch.extractor = _FakeExtractor()
    packet = EvidencePacket(
        packet_id="p1", library_id="lib", doc_id="doc-x", doc_title="测试文档",
        section_path="1.1", raw_text="设计高水位 影响 承载力验算",
    )
    orch.expand_all_packets([packet], enable_llm=False, ignored_entity_names=["承载力验算"])

    assert store.get_entity_by_name("承载力验算") is None
```

Run: `pytest services/docs-core/tests/test_graph_entity_status.py::test_expand_all_packets_ignores_rejected_names -v`
Expected: FAIL（`expand_all_packets` 不支持 `ignored_entity_names`）。

- [ ] **Step 3: 修改 `expand_from_packet` 支持忽略名单并修正种子状态**

修改 `services/docs-core/src/docs_core/step07_graph/graph_orchestrator.py` 的 import：

```python
from docs_core.step07_graph.config import Confidence, EntityLayer, EntityStatus, EntitySeed, RelationType, load_seed_entities
from docs_core.step07_graph.entity_dedup import find_existing_entity
```

修改 `expand_from_packet` 签名与相关逻辑：

```python
    def expand_from_packet(
        self,
        packet: EvidencePacket,
        seed_entity_name: Optional[str] = None,
        enable_llm: bool = False,
        ignored_entity_names: Optional[set] = None,
    ) -> Dict[str, Any]:
        text = packet.raw_text
        doc_title = packet.doc_title or packet.doc_id
        ignored = ignored_entity_names or set()

        if seed_entity_name:
            seed_entities = [s for s in load_seed_entities() if s.name == seed_entity_name]
        else:
            seed_entities = load_seed_entities()

        occurrences = self.extractor.find_seed_occurrences(text, seed_entities)
        if not occurrences:
            return {"packet_id": packet.packet_id, "entities_found": 0, "relations_added": 0}

        entity_count = 0
        relation_count = 0

        for seed_name, _ in occurrences:
            seed = next((s for s in seed_entities if s.name == seed_name), None)
            if seed is None:
                continue

            related = self.extractor.find_related_entities(text, seed.name, seed_entities)
            related = [n for n in related if n not in ignored]

            for entity_name in related:
                layer = self.extractor.classify_entity(entity_name)
                self.store.upsert_entity(GraphEntity(
                    name=entity_name,
                    layer=layer,
                    source_doc=doc_title,
                    source_clause=packet.section_path,
                    library_id=getattr(packet, 'library_id', '') or 'default',
                    status=EntityStatus.APPROVED,
                ))
                entity_count += 1
```

（注意：种子共现发现的 related 都是种子表中的术语，因此状态为 APPROVED。）

修改 `_llm_extract` 的实体入库与忽略逻辑。将实体创建段替换为：

```python
        for ent in llm_entities:
            name = ent.get("name", "").strip()
            if not name or name in ignored_entity_names:
                continue
            existing = find_existing_entity(self.store, name, getattr(packet, 'library_id', '') or 'default')
            if existing is not None:
                continue
            layer_str = ent.get("layer", "")
            try:
                layer = EntityLayer(layer_str)
            except ValueError:
                layer = self.extractor.classify_entity(name)
            self.store.upsert_entity(GraphEntity(
                name=name,
                layer=layer,
                source_doc=doc_title,
                source_clause=packet.section_path,
                library_id=getattr(packet, 'library_id', '') or 'default',
                status=EntityStatus.PENDING,
                proposed_doc_id=packet.doc_id,
                proposed_by="llm_extraction",
            ))
            entity_count += 1
```

`_llm_extract` 签名增加 `ignored_entity_names: Optional[set] = None`，内部 `ignored = ignored_entity_names or set()`。

`expand_from_packet` 调用 `_llm_extract` 时传入：

```python
            llm_result = self._llm_extract(packet, [s[0] for s in occurrences], ignored_entity_names=ignored_entity_names)
```

`_verify_relations` 中也需要跳过 ignored 实体。在 `_verify_relations` 开头加入：

```python
        relations = [r for r in relations
                     if r.get("from", "") not in seed_names and r.get("to", "") not in seed_names
                     and r.get("from", "") not in (ignored_entity_names or set())
                     and r.get("to", "") not in (ignored_entity_names or set())]
```

同时修改 `_verify_relations` 签名增加 `ignored_entity_names: Optional[set] = None`，并在 `_llm_extract` 调用处传入。

- [ ] **Step 4: 修改 `expand_all_packets` 支持忽略名单**

```python
    def expand_all_packets(
        self,
        packets: List[EvidencePacket],
        enable_llm: bool = False,
        ignored_entity_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        total_entities = 0
        total_relations = 0
        ignored_set = set(ignored_entity_names or [])
        for packet in packets:
            result = self.expand_from_packet(packet, enable_llm=enable_llm,
                                             ignored_entity_names=ignored_set)
            total_entities += result.get("entities_found", 0)
            total_relations += result.get("relations_added", 0)
```

Zettelkasten 段落的 `_link_zettelkasten` 调用前过滤掉忽略实体：

```python
            entity_names = [e.name for e in all_entities if e.name not in ignored_set]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest services/docs-core/tests/test_graph_entity_status.py -v`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add services/docs-core/src/docs_core/step07_graph/graph_orchestrator.py services/docs-core/tests/test_graph_entity_status.py
git commit -m "feat: 图谱抽取支持忽略名单，LLM 新实体进入 pending"
```

---

### Task 6: push_to_graph 支持 LLM 与后台自动抽取

**Files:**
- Modify: `services/docs-core/src/docs_core/step07_graph/push_to_graph.py`
- Create: `services/docs-core/src/docs_core/step07_graph/auto_extract.py`
- Modify: `services/docs-core/src/docs_core/parse_pipeline.py`
- Test: `services/docs-core/tests/test_graph_entity_status.py`

- [ ] **Step 1: 写失败测试**

追加到 `services/docs-core/tests/test_graph_entity_status.py`：

```python
def test_push_to_graph_accepts_enable_llm(tmp_path, monkeypatch) -> None:
    from docs_core.step07_graph import push_to_graph

    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    calls = {}

    def fake_push(library_id, doc_id, enable_llm=False, ignored_entity_names=None):
        calls["enable_llm"] = enable_llm
        calls["ignored"] = ignored_entity_names
        return {"pushed": True, "total_entities_found": 1, "total_relations_added": 2}

    monkeypatch.setattr("docs_core.step07_graph.push_to_graph._run_push", fake_push)

    result = push_to_graph("lib", "doc-x", enable_llm=True, ignored_entity_names=["被拒实体"])
    assert calls["enable_llm"] is True
    assert calls["ignored"] == ["被拒实体"]
    assert result["entities_count"] == 1
    assert result["relations_count"] == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest services/docs-core/tests/test_graph_entity_status.py::test_push_to_graph_accepts_enable_llm -v`
Expected: FAIL（`push_to_graph` 不支持 `enable_llm`；`_run_push` 不存在）。

- [ ] **Step 3: 重构 `push_to_graph`**

将 `services/docs-core/src/docs_core/step07_graph/push_to_graph.py` 整体替换为：

```python
"""把解析产物的 blocks 推入知识图谱（实体提取 + 关系推断）。"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _run_push(
    library_id: str,
    doc_id: str,
    graph_db_path: Optional[str] = None,
    enable_llm: bool = False,
    ignored_entity_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    from docs_core.paths import resolve_graph_db_path
    from docs_core.step04_structure.shared.jsonl_io import get_doc_blocks_graph
    from docs_core.docs_file_io import file_storage
    from docs_core.step07_graph.evidence_builder import build_evidence_packets
    from docs_core.step07_graph.graph_orchestrator import GraphOrchestrator
    from docs_core.step07_graph.graph_store import GraphStore

    db_path = graph_db_path or str(resolve_graph_db_path())
    content = file_storage.read_markdown(library_id, doc_id) or ""
    graph = get_doc_blocks_graph(library_id, doc_id)
    structured_items = (
        [
            node
            for node in graph.get("nodes", [])
            if str(node.get("layout_category") or "") != "attachment"
        ]
        if graph
        else []
    )

    packets = build_evidence_packets(
        library_id=library_id,
        doc_id=doc_id,
        doc_title=doc_id,
        document_content=content,
        structured_items=structured_items,
        doc_blocks_graph=graph,
    )

    store = GraphStore(db_path)
    orchestrator = GraphOrchestrator(store)
    orchestrator.load_seed_entities()
    result = orchestrator.expand_all_packets(
        packets, enable_llm=enable_llm, ignored_entity_names=ignored_entity_names or []
    )
    return {"pushed": True, **result}


def push_to_graph(
    library_id: str,
    doc_id: str,
    graph_db_path: Optional[str] = None,
    enable_llm: bool = False,
    ignored_entity_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Push a parsed document's blocks to the knowledge graph for entity extraction."""
    try:
        result = _run_push(
            library_id=library_id,
            doc_id=doc_id,
            graph_db_path=graph_db_path,
            enable_llm=enable_llm,
            ignored_entity_names=ignored_entity_names,
        )
    except ImportError as e:
        logger.warning("knowledge-graph module not available: %s", e)
        return {"pushed": False, "error": str(e)}
    except Exception as e:
        logger.exception("push_to_graph failed for %s/%s: %s", library_id, doc_id, e)
        return {"pushed": False, "error": str(e)}

    result["entities_count"] = result.get("total_entities_found", 0)
    result["relations_count"] = result.get("total_relations_added", 0)
    return result


__all__ = ["push_to_graph"]
```

- [ ] **Step 4: 新建后台自动抽取模块**

新建 `services/docs-core/src/docs_core/step07_graph/auto_extract.py`：

```python
"""解析完成后自动跑 LLM 图谱抽取的后台线程。"""

import logging
import os
import threading
from typing import List, Optional

logger = logging.getLogger(__name__)


def auto_llm_enabled() -> bool:
    """是否自动跑 LLM 抽取；默认开启，可用环境变量 GRAPH_AUTO_LLM=0 关闭。"""
    return os.environ.get("GRAPH_AUTO_LLM", "1") not in ("0", "false", "False")


def spawn_llm_graph_extraction(
    library_id: str,
    doc_id: str,
    ignored_entity_names: Optional[List[str]] = None,
) -> threading.Thread:
    """启动 daemon 线程执行 LLM 抽取，不阻塞解析主流程。"""
    from docs_core.step07_graph.push_to_graph import push_to_graph

    def _worker() -> None:
        try:
            result = push_to_graph(
                library_id, doc_id, enable_llm=True, ignored_entity_names=ignored_entity_names
            )
            if not result.get("pushed"):
                logger.warning("LLM 图谱抽取失败 %s/%s: %s", library_id, doc_id, result.get("error"))
        except Exception:
            logger.exception("LLM 图谱抽取异常 %s/%s", library_id, doc_id)

    thread = threading.Thread(target=_worker, daemon=True, name=f"kg-llm-{doc_id}")
    thread.start()
    return thread
```

- [ ] **Step 5: 在 `_run_graph` 末尾触发自动抽取**

修改 `services/docs-core/src/docs_core/parse_pipeline.py` 的 `_run_graph`：

```python
def _run_graph(ctx: StageContext) -> str:
    from docs_core.step07_graph.push_to_graph import push_to_graph
    from docs_core.step07_graph.auto_extract import auto_llm_enabled, spawn_llm_graph_extraction

    result = push_to_graph(ctx.library_id, ctx.doc_id)
    if not result.get("pushed"):
        error = result.get("error", "未知错误")
        raise RuntimeError(f"图谱构建失败: {error}")

    import docs_core.paths as paths
    ctx.input_summary = str(paths.get_graph_jsonl_path(ctx.library_id, ctx.doc_id))
    ctx.output_summary = "knowledge_graph.sqlite (entities + relations)"

    entities = result.get("entities_count", 0)
    relations = result.get("relations_count", 0)

    if auto_llm_enabled():
        spawn_llm_graph_extraction(ctx.library_id, ctx.doc_id)

    return f"图谱完成，{entities} 实体，{relations} 关系"
```

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest services/docs-core/tests/test_graph_entity_status.py::test_push_to_graph_accepts_enable_llm -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add services/docs-core/src/docs_core/step07_graph/push_to_graph.py services/docs-core/src/docs_core/step07_graph/auto_extract.py services/docs-core/src/docs_core/parse_pipeline.py services/docs-core/tests/test_graph_entity_status.py
git commit -m "feat: 解析后自动异步跑 LLM 图谱抽取"
```

---

### Task 7: 图谱 API 增加审批与状态过滤

**Files:**
- Modify: `services/docs-api/graph_routes.py`
- Test: `services/docs-core/tests/test_graph_entity_approval.py`

- [ ] **Step 1: 写失败测试（存储层支撑）**

追加到 `services/docs-core/tests/test_graph_entity_approval.py`：

```python
def test_pending_entities_sorted(tmp_path) -> None:
    store = GraphStore(str(tmp_path / "graph.sqlite"))
    p1 = store.upsert_entity(GraphEntity(name="待审一", layer=EntityLayer.CONCEPT, library_id="lib", status=EntityStatus.PENDING))
    p2 = store.upsert_entity(GraphEntity(name="待审二", layer=EntityLayer.CONDITION, library_id="lib", status=EntityStatus.PENDING))
    store.upsert_entity(GraphEntity(name="正式", layer=EntityLayer.CONCEPT, library_id="lib", status=EntityStatus.APPROVED))

    pending = store.list_entities_by_status("lib", EntityStatus.PENDING)
    names = [e.name for e in pending]
    assert p1.name in names and p2.name in names
    assert "正式" not in names
```

Run: `pytest services/docs-core/tests/test_graph_entity_approval.py::test_pending_entities_sorted -v`
Expected: PASS（Task 3 已实现）。

- [ ] **Step 2: 修改 API 路由**

修改 `services/docs-api/graph_routes.py`。

顶部 import 增加：

```python
from docs_core.step07_graph.config import EntityStatus
from docs_core.step07_graph.auto_extract import spawn_llm_graph_extraction
```

在 `HumanReviewRequest` 后新增请求模型：

```python
class EntityReviewRequest(BaseModel):
    reason: str = ""
    reviewer: str = "admin"
```

修改 `GET /graph/entities`，默认只返回 approved：

```python
@graph_router.get("/entities")
async def list_entities(layer: Optional[str] = None):
    store = _get_store()
    if layer:
        from docs_core.step07_graph.config import EntityLayer
        entities = store.list_entities_by_layer(EntityLayer(layer))
    else:
        entities = store.list_all_entities()
    return [
        {"entity_id": e.entity_id, "name": e.name, "layer": e.layer.value, "aliases": e.aliases,
         "status": e.status.value}
        for e in entities
        if getattr(e, "status", EntityStatus.APPROVED) == EntityStatus.APPROVED
    ]
```

> 说明：这里用最保守的实现——返回全量后再过滤 approved，保证不改变 `list_entities_by_layer` 的语义。后续可按需替换为 SQL 级过滤。

在 `/graph/entities/search` 的返回中增加 status 字段，并在函数内使用 `status=EntityStatus.APPROVED` 过滤：

```python
@graph_router.get("/entities/search")
async def search_entities(q: str):
    store = _get_store()
    results = store.search_entities(q, status=EntityStatus.APPROVED)
    return [
        {"entity_id": e.entity_id, "name": e.name, "layer": e.layer.value, "status": e.status.value}
        for e in results
    ]
```

新增审批端点（放在 `search_entities` 之后）：

```python
@graph_router.get("/entities/pending")
async def list_pending_entities(library_id: str = "default"):
    store = _get_store()
    entities = store.list_entities_by_status(library_id, EntityStatus.PENDING)
    return [
        {
            "entity_id": e.entity_id,
            "name": e.name,
            "layer": e.layer.value,
            "aliases": e.aliases,
            "source_clause": e.source_clause,
            "proposed_doc_id": e.proposed_doc_id,
            "created_at": e.created_at,
        }
        for e in entities
    ]


@graph_router.post("/entities/{entity_id}/approve")
async def approve_entity(entity_id: str, req: EntityReviewRequest):
    store = _get_store()
    entity = store.get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    store.approve_entity(entity_id, reviewer=req.reviewer)
    return {"status": "ok"}


@graph_router.post("/entities/{entity_id}/reject")
async def reject_entity(entity_id: str, req: EntityReviewRequest):
    store = _get_store()
    entity = store.get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    docs = store.get_docs_referencing_entity(entity_id)
    store.reject_entity(entity_id, reason=req.reason or "管理员拒绝", reviewer=req.reviewer)
    store.delete_relations_for_entity(entity_id)
    for library_id, doc_id in docs:
        if library_id == entity.library_id:
            spawn_llm_graph_extraction(library_id, doc_id, ignored_entity_names=[entity.name])
    return {"status": "ok", "rescheduled_docs": docs}
```

修改 `GET /graph/snapshot` 的 `get_graph_snapshot` 返回中携带 status（由 orchestrator 修改，见下）。

- [ ] **Step 3: 修改 Orchestrator 快照过滤**

修改 `services/docs-core/src/docs_core/step07_graph/graph_orchestrator.py` 的 `get_graph_snapshot`：

- `entity_map` 构建加入 `"status": e.status.value`：

```python
        entity_map = {
            e.entity_id: {"id": e.entity_id, "name": e.name, "layer": e.layer.value,
                          "aliases": e.aliases, "source_clause": e.source_clause,
                          "status": e.status.value}
            for e in entities
        }
```

- 关系循环开头跳过任一端不在 `entity_map` 的关系：

```python
        for rel in relations:
            if rel.source_id not in entity_map or rel.target_id not in entity_map:
                continue
            if rel.relation_type == "constrains":
                continue
```

- [ ] **Step 4: 运行存储层测试**

Run: `pytest services/docs-core/tests/test_graph_entity_approval.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add services/docs-api/graph_routes.py services/docs-core/src/docs_core/step07_graph/graph_orchestrator.py services/docs-core/tests/test_graph_entity_approval.py
git commit -m "feat: 图谱 API 审批端点与状态过滤"
```

---

### Task 8: admin-web API 客户端

**Files:**
- Modify: `apps/admin-web/src/api/knowledge.ts`

- [ ] **Step 1: 在 `knowledgeApi` 中增加图谱实体审批方法**

在 `knowledgeApi` 的 `buildGraphFromDoc` 之后加入：

```ts
  getPendingGraphEntities: (libraryId: string) =>
    api.get('/graph/entities/pending', { params: { library_id: libraryId } }) as Promise<{
      entity_id: string
      name: string
      layer: string
      aliases: string[]
      source_clause: string
      proposed_doc_id: string
      created_at: string
    }[]>,
  approveGraphEntity: (entityId: string, reviewer?: string) =>
    api.post(`/graph/entities/${entityId}/approve`, { reviewer: reviewer || 'admin' }) as Promise<{ status: string }>,
  rejectGraphEntity: (entityId: string, reason: string, reviewer?: string) =>
    api.post(`/graph/entities/${entityId}/reject`, { reason, reviewer: reviewer || 'admin' }) as Promise<{
      status: string
      rescheduled_docs: Array<[string, string]>
    }>,
```

- [ ] **Step 2: 类型检查**

Run: `pnpm --filter @angineer/admin-web build`
Expected: 通过（如果没有其它未提交改动导致的错误）

- [ ] **Step 3: 提交**

```bash
git add apps/admin-web/src/api/knowledge.ts
git commit -m "feat: admin-web 图谱实体审批 API 客户端"
```

---

### Task 9: 管理后台实体审核抽屉

**Files:**
- Create: `apps/admin-web/src/components/EntityReviewDrawer.vue`
- Modify: `apps/admin-web/src/components/KnowledgeStats.vue`

- [ ] **Step 1: 新建 `EntityReviewDrawer.vue`**

完整文件内容：

```vue
<template>
  <a-drawer
    :open="open"
    title="实体审核"
    placement="right"
    :width="720"
    @close="emit('update:open', false)"
  >
    <div class="entity-review-drawer">
      <div class="entity-review-toolbar">
        <a-typography-text type="secondary">
          待审核实体仅 LLM 抽取出的新实体；通过后进入通用实体库，拒绝后将从相关文档图谱移除并重抽。
        </a-typography-text>
        <a-button size="small" :loading="loading" @click="loadPending">刷新</a-button>
      </div>

      <a-table
        :columns="columns"
        :data-source="entities"
        :loading="loading"
        row-key="entity_id"
        size="middle"
        :pagination="{ pageSize: 10, showSizeChanger: true }"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'layer'">
            <a-tag>{{ record.layer }}</a-tag>
          </template>
          <template v-if="column.key === 'source'">
            <div>{{ record.source_clause || '-' }}</div>
            <div class="entity-review-sub">{{ record.proposed_doc_id || '' }}</div>
          </template>
          <template v-if="column.key === 'action'">
            <a-button type="link" size="small" @click="approve(record)">通过</a-button>
            <a-divider type="vertical" />
            <a-button type="link" size="small" danger @click="openReject(record)">拒绝</a-button>
          </template>
        </template>
      </a-table>

      <a-modal
        v-model:open="rejectModalOpen"
        title="拒绝实体"
        :width="480"
        ok-text="拒绝"
        ok-danger
        :ok-button-props="{ disabled: !rejectReason.trim() }"
        @ok="confirmReject"
        @cancel="rejectReason = ''"
      >
        <p>确定拒绝实体「{{ rejectTarget?.name }}」？拒绝后将从相关文档图谱中移除并触发重新抽取。</p>
        <a-textarea
          v-model:value="rejectReason"
          :rows="3"
          placeholder="请填写拒绝原因（必填）"
        />
      </a-modal>
    </div>
  </a-drawer>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { knowledgeApi } from '@/api/knowledge'

interface PendingEntity {
  entity_id: string
  name: string
  layer: string
  aliases: string[]
  source_clause: string
  proposed_doc_id: string
  created_at: string
}

const props = defineProps<{
  open: boolean
  libraryId: string
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'changed'): void
}>()

const loading = ref(false)
const entities = ref<PendingEntity[]>([])
const rejectModalOpen = ref(false)
const rejectTarget = ref<PendingEntity | null>(null)
const rejectReason = ref('')

const columns = [
  { title: '实体名', dataIndex: 'name', key: 'name', width: 180 },
  { title: '层级', dataIndex: 'layer', key: 'layer', width: 90 },
  { title: '来源', key: 'source' },
  { title: '操作', key: 'action', width: 140 },
]

async function loadPending() {
  if (!props.libraryId) return
  loading.value = true
  try {
    entities.value = await knowledgeApi.getPendingGraphEntities(props.libraryId)
  } catch (e: any) {
    message.error(e?.message || '加载待审核实体失败')
  } finally {
    loading.value = false
  }
}

async function approve(record: PendingEntity) {
  try {
    await knowledgeApi.approveGraphEntity(record.entity_id)
    message.success(`已通过「${record.name}」`)
    emit('changed')
    await loadPending()
  } catch (e: any) {
    message.error(e?.message || '审批失败')
  }
}

function openReject(record: PendingEntity) {
  rejectTarget.value = record
  rejectReason.value = ''
  rejectModalOpen.value = true
}

async function confirmReject() {
  if (!rejectTarget.value || !rejectReason.value.trim()) return
  try {
    await knowledgeApi.rejectGraphEntity(rejectTarget.value.entity_id, rejectReason.value.trim())
    message.success(`已拒绝「${rejectTarget.value.name}」`)
    rejectModalOpen.value = false
    rejectReason.value = ''
    emit('changed')
    await loadPending()
  } catch (e: any) {
    message.error(e?.message || '拒绝失败')
  }
}

watch(() => props.open, (val) => {
  if (val) loadPending()
})

watch(() => props.libraryId, () => {
  if (props.open) loadPending()
})
</script>

<style lang="less" scoped>
.entity-review-drawer {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.entity-review-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.entity-review-sub {
  font-size: 12px;
  color: var(--text-secondary);
}
</style>
```

- [ ] **Step 2: 在 `KnowledgeStats.vue` 挂载抽屉**

修改 `apps/admin-web/src/components/KnowledgeStats.vue`。

在 `.stats-actions` 的 `LibrarySelect` 后加入按钮：

```html
        <LibrarySelect style="margin-right: 12px" />
        <a-button size="small" @click="entityReviewOpen = true">实体审核</a-button>
```

在模板末尾 `</div>` 之前、`adminDeleteModalOpen` 的 modal 之后加入：

```html
    <EntityReviewDrawer
      v-model:open="entityReviewOpen"
      :library-id="libraryStore.libraryId || 'default'"
      @changed="loadRecords"
    />
```

在 script 中引入组件并增加状态：

```ts
import EntityReviewDrawer from '@/components/EntityReviewDrawer.vue'
```

在 `const libraryStore = useLibraryStore()` 之后加入：

```ts
const entityReviewOpen = ref(false)
```

- [ ] **Step 3: 构建验证**

Run: `pnpm --filter @angineer/admin-web build`
Expected: 通过

- [ ] **Step 4: 提交**

```bash
git add apps/admin-web/src/components/EntityReviewDrawer.vue apps/admin-web/src/components/KnowledgeStats.vue
git commit -m "feat: 管理后台实体审核抽屉"
```

---

### Task 10: 图谱组件展示 pending 状态

**Files:**
- Modify: `packages/docs-ui/src/components/common/index/Preview_KnowledgeGraph.vue`

- [ ] **Step 1: 扩展实体接口与节点提示**

修改 `GraphEntity` 接口：

```ts
interface GraphEntity {
  id: string
  name: string
  layer: string
  aliases: string[]
  source_clause?: string
  status?: 'approved' | 'pending' | 'rejected'
}
```

修改 `buildVisNodes` 的 `title` 行，加入状态：

```ts
      title: `${e.name} [${e.layer}]${e.status === 'pending' ? '\n状态: 待审核' : ''}${e.aliases?.length ? '\n别名: ' + e.aliases.join(', ') : ''}`,
```

- [ ] **Step 2: 实体详情增加待审核标记**

在实体详情 drawer 的 `<h3>{{ selectedEntity.name }}</h3>` 后加入：

```html
          <a-tag v-if="selectedEntity.status === 'pending'" color="orange">待审核</a-tag>
```

- [ ] **Step 3: 构建验证**

Run: `pnpm --filter @angineer/admin-web build`
Expected: 通过

- [ ] **Step 4: 提交**

```bash
git add packages/docs-ui/src/components/common/index/Preview_KnowledgeGraph.vue
git commit -m "feat: 图谱节点展示待审核状态"
```

---

### Task 11: 全量验证与收尾

- [ ] **Step 1: 后端全量测试**

Run: `pytest services/docs-core/tests/test_graph_entity_status.py services/docs-core/tests/test_graph_entity_approval.py -v`
Expected: 全部 PASS

- [ ] **Step 2: 后端既有图谱相关测试回归**

Run: `pytest services/docs-core/tests/test_purge_cleanup.py services/docs-core/tests/test_smoke.py -v`
Expected: 全部 PASS

- [ ] **Step 3: 前端构建**

Run: `pnpm --filter @angineer/admin-web build`
Expected: 通过

- [ ] **Step 4: 手动验证脚本**

启动 docs-api 后执行：

```bash
curl -s "http://127.0.0.1:8790/api/graph/entities/pending?library_id=default"
curl -s -X POST "http://127.0.0.1:8790/api/graph/entities/<entity_id>/approve" -H "Content-Type: application/json" -d '{"reviewer":"admin"}'
curl -s -X POST "http://127.0.0.1:8790/api/graph/entities/<entity_id>/reject" -H "Content-Type: application/json" -d '{"reason":"不通用","reviewer":"admin"}'
```

Expected：pending 列表返回实体；approve 后状态变为 approved；reject 后返回 `rescheduled_docs`，随后该文档图谱重抽完成且被拒实体不再出现。

- [ ] **Step 5: 提交（如有未提交内容）**

```bash
git add -A
git commit -m "chore: 图谱实体审批功能收尾"
```

---

## 自审记录

- 规格覆盖：实体状态字段/迁移（Task 1）、状态过滤（Task 2）、审批/拒绝/清理（Task 3）、去重归并（Task 4）、LLM 新实体 pending 与忽略名单（Task 5）、自动异步抽取（Task 6）、API（Task 7）、前端 API（Task 8）、审核抽屉（Task 9）、图谱 pending 展示（Task 10）、验证（Task 11）。
- 类型一致性：`EntityStatus` 在 config 定义，GraphStore/GraphEntity/GraphOrchestrator 统一引用；`list_entities_by_status(library_id, status)` 签名前后一致；`push_to_graph(..., enable_llm=, ignored_entity_names=)` 与 `_run_push` 签名一致；`spawn_llm_graph_extraction` 调用参数一致。

"""PG 版关系层 store（KB_STACK=pg 档位）。

与 SQLite 版类一一对应，覆写点收敛为四类，其余方法（标准 SQL）原样经
``pg_support.PgConnection`` 适配器复用：

1. ``connect()`` → pg_connect()（建表/建库由 pg_support.ensure_pg_ready 统一做）
2. ``init_schema()`` / 迁移钩子 → 空操作（PG DDL 见 pg_support.iter_pg_ddl）
3. ``search_chunk_fts()`` → tsvector 版检索（语义对齐 FTS5 + bm25，见方案 §4.3）：
   - 索引内容：text_ngrams（Python 写入侧 bigram 展开，与 SQLite 同一
     ``build_cjk_ngram_text``）+ section_path，tsvector 生成列 + GIN；
   - 查询构造：同一 bigram 展开 → ``to_tsquery('simple', 'tok1 | tok2')``；
   - 空查询：无有效 token 直接返回空，不进 SQL；
   - 排序：SQLite ``bm25 ASC``（越小越好）⇄ PG ``ts_rank DESC``，返回
     ``bm25_score = -ts_rank`` 保持「升序 = 相关优先」的既有调用方语义不变。
4. ``db_path`` → 哨兵路径（run_with_write_lock 的进程内锁 key 用，无磁盘 IO）。

组文件路由：PG 档位下 registry.resolve_index_db_path 恒返回默认路径，
docs_service 的组缓存自然收敛到本体单例（共库表自带 library_id/doc_id 列）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...pg_support import PG_SENTINEL_DB_PATH, pg_connect
from .canonical_sql_store import CanonicalSQLiteStore, _build_fts_match_query
from .blocks_sql_store import KnowledgeIndexStore, KnowledgeMetaStore

_FTS_TOKEN_CLEAN_RE = re.compile(r"[^\w\u4e00-\u9fff]+")


class PgKnowledgeMetaStore(KnowledgeMetaStore):
    """业务元数据（libraries/nodes/parse_tasks/tree_node）PG 版。"""

    def __init__(self, db_path: Optional[Path] = None, schema_version: str = "1.0.0") -> None:
        # PG 档位路径概念仅保留给锁 key 与调用方日志
        self.db_path = db_path or PG_SENTINEL_DB_PATH
        self.schema_version = schema_version
        self.init_schema()

    def connect(self):
        return pg_connect()

    def init_schema(self) -> None:
        # 表结构统一由 pg_support.ensure_pg_ready 建立（幂等），此处不做迁移
        return

    def _migrate_if_needed(self, conn) -> None:  # pragma: no cover - 兼容签名
        return


class PgKnowledgeIndexStore(KnowledgeIndexStore):
    """块索引/片段投影（doc_blocks/document_segments）PG 版。"""

    def __init__(self, db_path: Optional[Path] = None, schema_version: str = "1.0.0") -> None:
        self.db_path = db_path or PG_SENTINEL_DB_PATH
        self.schema_version = schema_version
        self.init_schema()

    def connect(self):
        return pg_connect()

    def init_schema(self) -> None:
        return


class PgCanonicalSQLiteStore(CanonicalSQLiteStore):
    """canonical 文档/块/片段/表/引用 + chunk FTS 的 PG 版。"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or PG_SENTINEL_DB_PATH
        self.init_schema()

    def connect(self):
        return pg_connect()

    def init_schema(self) -> None:
        return

    def _migrate_add_business_columns(self, conn) -> None:  # pragma: no cover
        return

    def _migrate_chunk_fts_ngrams(self, conn) -> None:  # pragma: no cover
        return

    def search_chunk_fts(
        self,
        doc_id: Optional[str],
        query: str,
        limit: int = 20,
        library_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        normalized_query = " ".join(str(query or "").split()).strip()
        if not normalized_query:
            return []
        match_query = _build_fts_match_query(normalized_query)
        if not match_query:
            return []
        # FTS5 MATCH 串 → tsquery token 串（引号内 token 净化为字/数字/汉字）
        tokens = re.findall(r'"([^"]*)"', match_query)
        cleaned = []
        seen = set()
        for token in tokens:
            token = _FTS_TOKEN_CLEAN_RE.sub("", token)
            if token and token not in seen:
                seen.add(token)
                cleaned.append(token)
        if not cleaned:
            return []
        tsquery = " | ".join(cleaned)

        doc_filter = "f.doc_id = ?" if doc_id else "1 = 1"
        params: List[object] = [tsquery]  # FROM 里 to_tsquery 占位符在最前
        if doc_id:
            params.append(doc_id)
        lib_filter = ""
        if library_ids:
            placeholders = ", ".join("?" for _ in library_ids)
            lib_filter = (
                " AND f.doc_id IN (SELECT doc_id FROM canonical_documents"
                f" WHERE library_id IN ({placeholders}))"
            )
            params.extend(library_ids)
        params.append(max(1, min(200, limit)))
        # 占位符顺序：FROM to_tsquery(?) → doc_filter → lib_filter → LIMIT
        sql = (
            "SELECT f.chunk_id, f.doc_id, f.chunk_type, f.section_path, f.text_clean, "
            "-ts_rank(f.fts, q.tsq) AS bm25_score "
            "FROM canonical_chunk_fts f, to_tsquery('simple', ?) AS q(tsq) "
            f"WHERE {doc_filter}{lib_filter} AND f.fts @@ q.tsq "
            "ORDER BY bm25_score ASC, f.chunk_id ASC LIMIT ?"
        )
        conn = self.connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return [
            {
                "chunk_id": row["chunk_id"],
                "doc_id": row["doc_id"],
                "chunk_type": row["chunk_type"],
                "section_path": row["section_path"] or "",
                "text_clean": row["text_clean"] or "",
                "bm25_score": float(row["bm25_score"] or 0.0),
            }
            for row in rows
        ]

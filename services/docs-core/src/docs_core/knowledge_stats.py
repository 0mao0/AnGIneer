"""知识库统计聚合——docs-api ``GET /api/knowledge/stats`` 与 retrieval-api 壳共用唯一实现。

2026-10-12 独立壳交付时自 ``services/docs-api/docs_routes.py`` 抽出（逐字迁移），
docs-api 路由改为调用本函数；壳（``docs_core.server``）直接调用。

口径：文档以 nodes 表为准（deleted=0 排除软删）；上传/存储以 parse_records 为准
（status<>'deleted'）。parse_records 库路径经 ``parse_records_store.db_path()``
（``PARSE_RECORDS_DB_PATH`` > ``ANGINEER_DATA_ROOT``/knowledge > 仓库 data）。
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .docs_service import get_docs_service
from .parse_records_store import db_path as _parse_records_db_path


def compute_knowledge_stats(library_id: Optional[str] = None) -> Dict[str, Any]:
    """知识库统计聚合（实时查询）：文档总数/状态分布/库分布/上传趋势/页数/存储。"""
    ks = get_docs_service()
    lib_clause = " AND library_id = ?" if library_id else ""
    lib_params: tuple = (library_id,) if library_id else ()

    with ks.meta_store.connect() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM nodes WHERE deleted=0{lib_clause}", lib_params
        ).fetchone()[0]
        deleted = conn.execute(
            f"SELECT COUNT(*) FROM nodes WHERE deleted=1{lib_clause}", lib_params
        ).fetchone()[0]
        by_status = {
            r[0]: r[1]
            for r in conn.execute(
                f"SELECT status, COUNT(*) FROM nodes WHERE deleted=0{lib_clause} GROUP BY status",
                lib_params,
            )
        }
        by_library = [
            {"library_id": r[0], "library_name": r[1] or r[0], "count": r[2]}
            for r in conn.execute(
                "SELECT n.library_id, l.name, COUNT(*) FROM nodes n"
                " LEFT JOIN libraries l ON n.library_id = l.id"
                f" WHERE n.deleted=0{lib_clause.replace('library_id', 'n.library_id')}"
                " GROUP BY n.library_id ORDER BY COUNT(*) DESC",
                lib_params,
            )
        ]
        pages_row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(s.page_count),0), COALESCE(AVG(s.page_count),0)"
            " FROM doc_parse_stages s JOIN nodes n ON s.doc_id = n.id"
            f" WHERE s.stage='raw_parse' AND n.deleted=0{lib_clause.replace('library_id', 'n.library_id')}",
            lib_params,
        ).fetchone()
        max_page_row = conn.execute(
            "SELECT n.id, n.title, s.page_count"
            " FROM doc_parse_stages s JOIN nodes n ON s.doc_id = n.id"
            f" WHERE s.stage='raw_parse' AND n.deleted=0{lib_clause.replace('library_id', 'n.library_id')}"
            " ORDER BY s.page_count DESC LIMIT 1",
            lib_params,
        ).fetchone()
        min_page_row = conn.execute(
            "SELECT n.id, n.title, s.page_count"
            " FROM doc_parse_stages s JOIN nodes n ON s.doc_id = n.id"
            f" WHERE s.stage='raw_parse' AND n.deleted=0 AND s.page_count > 0{lib_clause.replace('library_id', 'n.library_id')}"
            " ORDER BY s.page_count ASC LIMIT 1",
            lib_params,
        ).fetchone()
        # 标题清单：供 agent knowledge_stats 工具回答"有哪些文章/规范"类列举型元数据问题
        title_rows = conn.execute(
            f"SELECT title, status FROM nodes WHERE deleted=0{lib_clause} ORDER BY title LIMIT 101",
            lib_params,
        ).fetchall()

    # parse_records 是独立 SQLite 文件，单独连接聚合（不与 meta 库跨库 JOIN）
    rconn = sqlite3.connect(_parse_records_db_path())
    rconn.row_factory = sqlite3.Row
    try:
        rec_base = "status<>'deleted'" + lib_clause
        now = datetime.now(timezone.utc)
        recent_7d = rconn.execute(
            f"SELECT COUNT(*) FROM parse_records WHERE {rec_base} AND created_at >= ?",
            lib_params + ((now - timedelta(days=7)).isoformat(),),
        ).fetchone()[0]
        recent_30d = rconn.execute(
            f"SELECT COUNT(*) FROM parse_records WHERE {rec_base} AND created_at >= ?",
            lib_params + ((now - timedelta(days=30)).isoformat(),),
        ).fetchone()[0]
        by_month = [
            {"month": r[0], "count": r[1]}
            for r in rconn.execute(
                f"SELECT substr(created_at,1,7), COUNT(*) FROM parse_records WHERE {rec_base}"
                " GROUP BY substr(created_at,1,7) ORDER BY 1",
                lib_params,
            )
        ]
        by_format = [
            {"format": (r[0] or "unknown").lstrip(".").lower() or "unknown", "count": r[1]}
            for r in rconn.execute(
                f"SELECT file_format, COUNT(*) FROM parse_records WHERE {rec_base} GROUP BY file_format ORDER BY 2 DESC",
                lib_params,
            )
        ]
        size_row = rconn.execute(
            f"SELECT COALESCE(SUM(file_size),0) FROM parse_records WHERE {rec_base}", lib_params
        ).fetchone()
    finally:
        rconn.close()

    # matter 清单（等价于对 DMS 做一次 ls）：只有回填过 doc_catalog 的库才有；
    # 枚举题需要「库里有哪些 matter」，这条不依赖检索，成本一条 GROUP BY。
    matters: Dict[str, Any] = {"catalog": False, "total": 0, "matters": []}
    if library_id:
        try:
            from docs_core.step09_query.doc_search import list_matters

            matters = list_matters(library_id)
        except Exception:  # noqa: BLE001 —— catalog 缺失/查询失败不影响其它统计
            pass

    return {
        "library_id": library_id,
        "generated_at": now.isoformat(),
        "matters": matters,
        "documents": {
            "total": total,
            "deleted": deleted,
            "by_status": by_status,
            "by_library": by_library,
            "titles_total": total,
            "titles_truncated": len(title_rows) > 100,
            "titles": [{"title": r[0], "status": r[1]} for r in title_rows[:100]],
        },
        "uploads": {
            "recent_7d": recent_7d,
            "recent_30d": recent_30d,
            "by_month": by_month,
            "by_format": by_format,
        },
        "pages": {
            "docs_with_pages": pages_row[0],
            "total": pages_row[1],
            "avg_per_doc": round(pages_row[2], 1) if pages_row[2] else 0,
            "max": (
                {"doc_id": max_page_row[0], "title": max_page_row[1], "pages": max_page_row[2]}
                if max_page_row
                else None
            ),
            "min": (
                {"doc_id": min_page_row[0], "title": min_page_row[1], "pages": min_page_row[2]}
                if min_page_row
                else None
            ),
        },
        "storage": {"total_file_size_mb": round(size_row[0] / 1024 / 1024, 1)},
    }

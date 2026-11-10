"""解析记录（上传台账）包内门面——存储经 ``docs_core.parse_records_store`` 档位适配层。

宿主版（services/docs-api/models/parse_record.py）自带 sqlite 直连；包内版本全部改走
``parse_records_store``（其 ``connect()`` 按 ``KB_STACK`` 分流 sqlite / PG），这是
DredgeAI docs-api 进包需求 3.1「记录存储走档位适配层」的落点：

- legacy：``<data_root>/knowledge/parse_records.sqlite``；
- pg：``dredge_knowledge.parse_records``（DDL 见 ``pg_support.iter_pg_ddl``）。

差异（相对宿主版）：不做 api_keys 库 join（键管理体系不进包）；不提供统计聚合
（``get_statistics`` 是管理端诉求）。
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from docs_core.parse_records_store import (
    init_schema,
    list_by_doc_id,
    list_records as _store_list_records,
    soft_delete_record as _store_soft_delete_record,
    sync_record_for_task as _store_sync_record_for_task,
    update_status as _store_update_status,
    connect,
)

__all__ = [
    "ParseRecord",
    "insert_record",
    "update_record_status",
    "list_records",
    "list_by_doc_id",
    "soft_delete_record",
    "sync_record_for_task",
]


@dataclass
class ParseRecord:
    id: Optional[int] = None
    doc_id: str = ""
    task_id: str = ""
    uploaded_by: str = ""
    api_key_id: Optional[int] = None
    file_name: str = ""
    file_format: str = ""
    file_size: int = 0
    status: str = "queued"
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    library_id: str = "default"
    stages: str = ""


def insert_record(record: ParseRecord) -> int:
    """插入 pending 占位行（create_parse_task 后经 sync_record_for_task 改名回填 task_id）。"""
    conn = connect()
    try:
        init_schema(conn)
        conn.execute(
            """INSERT INTO parse_records (doc_id, task_id, uploaded_by, api_key_id,
               file_name, file_format, file_size, status, error, created_at, library_id, stages)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record.doc_id, record.task_id, record.uploaded_by, record.api_key_id,
             record.file_name, record.file_format, record.file_size,
             record.status, record.error, record.created_at, record.library_id, record.stages),
        )
        conn.commit()
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    finally:
        conn.close()


def update_record_status(task_id: str, status: str, error: Optional[str] = None) -> bool:
    """按 task_id 更新状态（启动自愈与终态回写入口）。"""
    return _store_update_status(task_id, status, error)


def list_records(
    status_filter: Optional[str] = None,
    deleted_filter: bool = False,
    limit: int = 500,
    offset: int = 0,
) -> List[dict]:
    return _store_list_records(
        status_filter=status_filter, deleted_filter=deleted_filter,
        limit=limit, offset=offset,
    )


def soft_delete_record(doc_id: str) -> bool:
    return _store_soft_delete_record(doc_id)


def sync_record_for_task(task_id: str, doc_id: str, status: str,
                         error: Optional[str] = None) -> None:
    """编排器记录同步回调（钩子契约 task_id/doc_id/status/error 与宿主一致）。"""
    _store_sync_record_for_task(task_id, doc_id, status, error)

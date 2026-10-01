"""canonical 精确查表：scope 感知的 table_lookup 新实现。

替代老 TableLookupTool（engtools 文件系实现）：候选表格不再从整份 .md 抽取，
改由 table_blocks 端口按 library/doc_ids scope 批量取 canonical 表格块
（header_rows/body_rows 已解析），候选选择与单元格提取走 table_query_engine
（与老工具结构化模式逐行对齐的纯函数管线）。

SOP 的 table_lookup 步骤迁移到本实现后，老类在 commit 2b 删除。
"""
import logging
from typing import Any, Dict, List, Optional

from angineer_core import ports
from angineer_core.table_query_engine import query_tables

logger = logging.getLogger(__name__)


def canonical_table_lookup(
    *,
    table_name: str,
    query_conditions: Any,
    target_column: Optional[str] = None,
    library_id: str = "default",
    doc_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """按 scope 精确查表。返回形态对齐老工具结构化模式（{"result": ...} 或 {"error": ...}）。"""
    if not str(table_name or "").strip():
        return {"error": "缺少 table_name（表名）"}
    provider = ports.get_table_blocks_provider()
    if provider is None:
        logger.warning("table_blocks 端口未注册（组装层应注入 docs-core 适配器）")
        return {"error": "表格块读取不可用（端口未注册）"}
    try:
        blocks = provider(library_id, doc_ids)
    except Exception as exc:  # noqa: BLE001
        logger.warning("canonical 表格块读取失败: %s", exc)
        return {"error": f"表格块读取失败: {exc}"}
    candidates = [
        {
            "header_rows": block.get("header_rows") or [],
            "headers": block.get("headers"),
            "rows": block.get("rows") or [],
            "context": block.get("context") or "",
            "doc_id": block.get("doc_id"),
            "page_idx": block.get("page_idx"),
        }
        for block in (blocks or [])
        if (block.get("rows") or block.get("header_rows") or block.get("headers"))
    ]
    if not candidates:
        return {
            "error": "当前文档范围内没有可用的表格块",
            "_diagnostic_info": {
                "library_id": library_id,
                "doc_ids": list(doc_ids or []),
                "suggestions": [
                    "确认文档已解析入库且包含表格",
                    "如指定了 doc_ids，确认 scope 内文档确实含目标表格",
                ],
            },
        }
    result = query_tables(
        candidates,
        table_name=table_name,
        query_conditions=query_conditions,
        target_column=target_column,
    )
    result["_source"] = "canonical"
    return result

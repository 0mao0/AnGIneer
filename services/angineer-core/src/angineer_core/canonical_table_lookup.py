"""canonical 精确查表：scope 感知的 table_lookup 新实现。

替代老 TableLookupTool（engtools 文件系实现）：候选表格不再从整份 .md 抽取，
改由 table_blocks 端口按 library/doc_ids scope 批量取 canonical 表格块
（header_rows/body_rows 已解析），候选选择与单元格提取走 table_query_engine
（与老工具结构化模式逐行对齐的纯函数管线）。

SOP 存量步骤写死 file_name（规范标题），经本模块转译为 doc_ids scope
（标题宽松匹配，移植自 engtools KnowledgeTool 的同名逻辑），老 SOP 零改动。
"""
import logging
import re
from typing import Any, Dict, List, Optional

from angineer_core import ports
from angineer_core.table_query_engine import query_tables

logger = logging.getLogger(__name__)


def _normalize_doc_title(raw: str) -> str:
    """规范化文档标题用于匹配，去除路径前缀、扩展名、年份后缀、统一空格/下划线。"""
    t = raw
    if t.startswith("markdown/"):
        t = t[len("markdown/"):]
    if t.endswith(".md"):
        t = t[:-3]
    if t.endswith(".pdf"):
        t = t[:-4]
    t = t.replace("_", " ").replace("—", "-").replace("–", "-")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _title_matches(query_title: str, node_title: str) -> bool:
    """宽松匹配文档标题，忽略年份/版本号后缀差异。"""
    q = query_title.lower()
    nt = node_title.lower()
    if q in nt or nt in q:
        return True
    q_no_year = re.sub(r"[-_]\d{4}\s*$", "", q).strip()
    nt_no_year = re.sub(r"[-_]\d{4}\s*$", "", nt).strip()
    if q_no_year and (q_no_year in nt_no_year or nt_no_year in q_no_year):
        return True
    q_prefix = q[:15] if len(q) > 15 else q
    if q_prefix and nt.startswith(q_prefix):
        return True
    # 提取规范编号模式如 JTS 165 进行匹配
    q_code = re.search(r"(jts|jtj|gb|jgj)\s*\d+", q)
    nt_code = re.search(r"(jts|jtj|gb|jgj)\s*\d+", nt)
    if q_code and nt_code and q_code.group(0) == nt_code.group(0):
        return True
    return False


def _resolve_doc_ids_by_file_name(library_id: str, file_name: str) -> Optional[List[str]]:
    """file_name（规范标题）→ doc_ids：经 local_nodes_loader 端口取库内文档做标题匹配。"""
    loader = ports.get_local_nodes_loader()
    if loader is None:
        return None
    normalized = _normalize_doc_title(file_name)
    if not normalized:
        return None
    try:
        nodes = loader(library_id, None) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("文档节点加载失败（library=%s）: %s", library_id, exc)
        return None
    for node in nodes:
        node_title = _normalize_doc_title(str(getattr(node, "title", "") or ""))
        if node_title and _title_matches(normalized, node_title):
            node_id = str(getattr(node, "id", "") or "")
            if node_id:
                return [node_id]
    return None


def canonical_table_lookup(
    *,
    table_name: str,
    query_conditions: Any,
    target_column: Optional[str] = None,
    library_id: str = "default",
    doc_ids: Optional[List[str]] = None,
    file_name: Optional[str] = None,
) -> Dict[str, Any]:
    """按 scope 精确查表。返回形态对齐老工具结构化模式（{"result": ...} 或 {"error": ...}）。

    file_name 为 SOP 存量兼容参数：给出时优先转译为 doc_ids（覆盖入参 doc_ids），
    无法解析时返回明确 error，不静默退化为全库扫描。
    """
    if not str(table_name or "").strip():
        return {"error": "缺少 table_name（表名）"}
    if file_name and str(file_name).strip():
        resolved = _resolve_doc_ids_by_file_name(library_id, str(file_name).strip())
        if not resolved:
            return {"error": f"未找到知识库文件: {file_name}（在当前库内无法解析为文档）"}
        doc_ids = resolved
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

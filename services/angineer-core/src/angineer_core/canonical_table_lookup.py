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
from typing import Any, Dict, List, Optional, Tuple

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


_SPEC_SUFFIX_WORDS = (
    "设计规范", "施工规范", "技术规范", "规范", "标准", "规程", "导则", "规定",
    "技术细则", "细则", "指南", "技术要求",
)


def _extract_spec_code(title: str):
    """提取规范编号（前缀, 主号, 分册号）；负号后 4 位视为年份、不参与分册比较。

    返回 None 表示无编号。JTS 165-2013 → ("jts","165",None)；JTS 165-5-2016 → ("jts","165","5")。
    """
    m = re.search(r"(jts|jtj|gb|jgj)\s*[/\-]?\s*(\d+)(?:\s*-\s*(\d+))?", title)
    if not m:
        return None
    prefix, main, sub = m.group(1), m.group(2), m.group(3)
    if sub and re.fullmatch(r"(19|20)\d{2}", sub):
        sub = None
    return (prefix, main, sub)


def _core_name(title: str) -> str:
    """标题主名：去规范编号、去常见后缀词与标点后的字符序列（用于重叠校验）。"""
    t = re.sub(r"(jts|jtj|gb|jgj)\s*[/\-]?\s*\d+(?:\s*-\s*\d+)*", " ", title)
    for w in _SPEC_SUFFIX_WORDS:
        t = t.replace(w, " ")
    return re.sub(r"[^0-9a-zA-Z一-鿿]", "", t)


def _name_overlap(q: str, nt: str) -> bool:
    """主名字符 2-gram 有交集即相关（覆盖版本/附条文说明等后缀差异）。"""
    cq, cn = _core_name(q), _core_name(nt)
    if not cq or not cn:
        return False

    def bigrams(s: str) -> set:
        return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}

    return bool(bigrams(cq) & bigrams(cn))


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
    # 规范编号匹配：分册号必须一致（JTS 165 ≠ JTS 165-5），编号一致后还要标题主名
    # 有实质重叠（防「同编号前缀挂不同名称」错配，2026-10-12 LNG 实踩）
    q_code = _extract_spec_code(q)
    nt_code = _extract_spec_code(nt)
    if q_code and nt_code and q_code == nt_code and _name_overlap(q, nt):
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


def _scope_libraries(library_id: Optional[str], library_ids: Optional[List[str]]) -> List[str]:
    """归一库作用域：library_ids 优先（多库并联），否则退单库，缺省 default；去重保序。"""
    libs = [str(x).strip() for x in (library_ids or []) if str(x).strip()]
    if not libs and library_id:
        libs = [str(library_id).strip()]
    seen, out = set(), []
    for lib in libs:
        if lib not in seen:
            seen.add(lib)
            out.append(lib)
    return out or ["default"]


def _tag_candidates(blocks: Any, library: str) -> List[Dict[str, Any]]:
    """给候选表打库标（判读溯源用）；非 dict 项剔除。"""
    out: List[Dict[str, Any]] = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        item = dict(block)
        item.setdefault("library_id", library)
        out.append(item)
    return out


def _resolve_file_across_libs(
    libraries: List[str], file_name: Optional[str]
) -> Optional[Tuple[str, List[str]]]:
    """file_name 逐库解析：返回首个命中 (library_id, doc_ids)；未命中/未给返回 None。"""
    if not (file_name and str(file_name).strip()):
        return None
    for lib in libraries:
        found = _resolve_doc_ids_by_file_name(lib, str(file_name).strip())
        if found:
            return lib, found
    return None


def _collect_candidates_multi(
    provider: Any,
    libraries: List[str],
    doc_ids: Optional[List[str]],
    file_name: Optional[str],
    file_resolved: Optional[Tuple[str, List[str]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """跨库取表候选（表格面多库并联，2026-10-13 业主定）。

    - file_name 给定：逐库解析标题，**首个命中库收敛为精确 scope**（SOP 存量写死
      规范名的步骤从此不受「作用域首库」限制——实踩：多库同选且首库非水运时，
      海港规范查表整链失败）；
    - doc_ids 给定：维持单库语义（doc_ids 归属首库），行为与旧实现逐位一致；
    - 都不给定：多库扇出合并候选（各方括号按候选打分择优）。
    返回 (candidates, meta)；file_name 全库未命中时 meta.file_name_missing=True。
    """
    if file_name and str(file_name).strip():
        resolved = file_resolved or _resolve_file_across_libs(libraries, file_name)
        if resolved is None:
            return [], {"file_name_missing": True}
        lib, docs = resolved
        blocks = provider(lib, docs) or []
        return (
            _tag_candidates(blocks, lib),
            {"resolved_library_id": lib, "resolved_libraries": [lib]},
        )
    if doc_ids:
        lib = libraries[0]
        blocks = provider(lib, doc_ids) or []
        return _tag_candidates(blocks, lib), {"resolved_library_id": lib, "resolved_libraries": [lib]}
    merged: List[Dict[str, Any]] = []
    for lib in libraries:
        try:
            blocks = provider(lib, None) or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("多库表格块读取失败（library=%s）: %s", lib, exc)
            continue
        merged.extend(_tag_candidates(blocks, lib))
    return merged, {"resolved_libraries": list(libraries)}


def _unresolved_condition_names(query_conditions: Any) -> List[str]:
    """收集条件值里未解析的 ${name} 模板变量（嵌套一层 dict/list 也扫）。

    命中即「题面缺参」：必须在读表/查表前拦截——否则读表判读的 LLM 会自行
    挑选行/列（2026-10-13 实踩：航速未给时读表自行按 >6kn 取 0.75B 出 W=310.03，
    编造选定档位；业主纪律=如实报缺，不臆造）。
    """
    names: List[str] = []
    if query_conditions is None:
        return names
    items = query_conditions.values() if isinstance(query_conditions, dict) else [query_conditions]
    for value in items:
        candidates = value if isinstance(value, (list, tuple)) else [value]
        for candidate in candidates:
            if isinstance(candidate, str):
                for name in re.findall(r"\$\{([^}]+)\}", candidate):
                    if name not in names:
                        names.append(name)
            elif isinstance(candidate, dict):
                for name in re.findall(r"\$\{([^}]+)\}", str(candidate)):
                    if name not in names:
                        names.append(name)
    return names


def canonical_table_lookup(
    *,
    table_name: str,
    query_conditions: Any,
    target_column: Optional[str] = None,
    library_id: str = "default",
    doc_ids: Optional[List[str]] = None,
    file_name: Optional[str] = None,
    library_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """按 scope 精确查表。返回形态对齐老工具结构化模式（{"result": ...} 或 {"error": ...}）。

    file_name 为 SOP 存量兼容参数：给出时优先转译为 doc_ids（覆盖入参 doc_ids），
    无法解析时返回明确 error，不静默退化为全库扫描。
    library_ids 为多库并联 scope（表格面，2026-10-13）：file_name 逐库解析收敛精确库；
    无 file_name/doc_ids 时跨库合并候选。
    """
    if not str(table_name or "").strip():
        return {"error": "缺少 table_name（表名）"}
    missing_cond = _unresolved_condition_names(query_conditions)
    if missing_cond:
        return {
            "error": f"查表缺参：{'、'.join(missing_cond)} 未提供，条件无法确定（系统不臆造取值）",
            "missing_params": missing_cond,
            "_table_name": table_name,
        }
    libraries = _scope_libraries(library_id, library_ids)
    file_resolved = _resolve_file_across_libs(libraries, file_name)
    if file_name and str(file_name).strip() and file_resolved is None:
        return {"error": f"未找到知识库文件: {file_name}（在 {'、'.join(libraries)} 内均无法解析为文档）"}
    provider = ports.get_table_blocks_provider()
    if provider is None:
        logger.warning("table_blocks 端口未注册（组装层应注入 docs-core 适配器）")
        return {"error": "表格块读取不可用（端口未注册）"}
    try:
        blocks, scope_meta = _collect_candidates_multi(provider, libraries, doc_ids, file_name, file_resolved)
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
            "library_id": block.get("library_id"),
        }
        for block in (blocks or [])
        if (block.get("rows") or block.get("header_rows") or block.get("headers"))
    ]
    if not candidates:
        return {
            "error": "当前文档范围内没有可用的表格块",
            "_diagnostic_info": {
                "library_id": library_id,
                "resolved_libraries": scope_meta.get("resolved_libraries"),
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


def _render_table_text(headers: List[Any], rows: List[Any]) -> str:
    """把 header_rows/body_rows 渲染为逐行文本（行首标注行标签，供判读引用）。"""
    lines: List[str] = []
    if headers:
        lines.append("表头: " + " | ".join(str(h) for h in headers))
    for row in rows:
        if not isinstance(row, (list, tuple)) or not row:
            continue
        label = str(row[0])
        cells = " | ".join(str(c) for c in row)
        lines.append(f"[{label}] {cells}")
    return "\n".join(lines)


def _loads_lenient(fragment: str) -> dict:
    """宽松 JSON 解析：修掉 LLM 回抄 LaTeX 时未转义的反斜杠。

    2026-10-15 实踩（P2-4 验收轮）：表头/行标签含 LaTeX（$Z_{2}/H_{4\\%} (\\overline{T}…)$）时，
    判读模型会把行标签原样抄进 cell/quote，单个反斜杠是非法 JSON 转义 → json.loads 抛
    "Invalid \\escape" → 整步失败（值其实已读对）。只补未成对的反斜杠，不碰合法转义。
    """
    import json as _json2

    try:
        return _json2.loads(fragment)
    except Exception:
        return _json2.loads(re.sub(r'\\(?![\\"/bfnrtu])', r"\\\\", fragment))


def canonical_table_read(
    *,
    table_name: str,
    query_conditions: Any = None,
    target_column: Optional[str] = None,
    library_id: str = "default",
    doc_ids: Optional[List[str]] = None,
    file_name: Optional[str] = None,
    config_name: Optional[str] = None,
    mode: str = "instruct",
    library_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """矩阵/双层表头表的「读表判读」通道（方案 B，plan-sop-l4 后续项）。

    与 canonical_table_lookup 的分工：**选表仍走确定性匹配**（编号打分，同引擎），
    但**取值**不做条件行/列定位（引擎对「指标行 × 区间列」矩阵与双层表头不支持），
    改为把整表文本 + 取值要求交给一次 LLM 抽取，返回 value + 单元格引用（可审计）。
    library_ids 为多库并联 scope（表格面，2026-10-13）：file_name 逐库解析收敛精确库；
    无 file_name/doc_ids 时跨库合并候选后按编号打分择优。
    """
    missing_cond = _unresolved_condition_names(query_conditions)
    if missing_cond:
        return {
            "error": f"读表缺参：{'、'.join(missing_cond)} 未提供，无法按条件定位取值（系统不臆造取值）",
            "missing_params": missing_cond,
            "_table_name": table_name,
        }

    libraries = _scope_libraries(library_id, library_ids)
    file_resolved = _resolve_file_across_libs(libraries, file_name)
    if file_name and str(file_name).strip() and file_resolved is None:
        return {"error": f"未找到知识库文件: {file_name}（在 {'、'.join(libraries)} 内均无法解析为文档）"}
    provider = ports.get_table_blocks_provider()
    if provider is None:
        return {"error": "表格数据端口未注册（table_blocks_provider）"}
    try:
        candidates, scope_meta = _collect_candidates_multi(provider, libraries, doc_ids, file_name, file_resolved)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"表格候选获取失败: {exc}"}
    if not candidates:
        return {"error": "scope 内无表格候选"}

    from angineer_core.table_query_engine import _score_table_reference_match, flatten_header_rows

    scored = sorted(
        candidates,
        key=lambda c: _score_table_reference_match(table_name, c.get("context") or ""),
        reverse=True,
    )
    best = scored[0]
    score = _score_table_reference_match(table_name, best.get("context") or "")
    if score <= 0:
        return {"error": f"scope 内 {len(candidates)} 个表格块均无编号『{table_name}』"}

    headers = best.get("headers") or flatten_header_rows(best.get("header_rows") or [])
    table_text = _render_table_text(headers, best.get("rows") or [])

    import json as _json

    from ai_inference.llm_client import chat_result_guarded, get_llm_client

    cond_desc = _json.dumps(query_conditions, ensure_ascii=False, default=str) if query_conditions else "（未给出，按表名与目标字段判断）"
    target_desc = target_column or "按表名语义确定的目标值"
    prompt = (
        "你在做规范表格的精确读值。下表为全文（行首 [标签] 为行名）：\n"
        f"表：{best.get('context')}\n{table_text}\n\n"
        f"请在表中依据条件 {cond_desc} 读出「{target_desc}」的值。\n"
        "输出严格 JSON，且只输出 JSON：\n"
        '{"value": <值；若目标含多个名称（以「；」或逗号分隔），为 {"名称": 值, ...} 对象；读不到则 null>, '
        '"cell": "<行标签×列标签的定位描述>", "quote": "<所依据单元格/文字的原文片段，≤60字>"}'
    )
    try:
        result = chat_result_guarded(
            get_llm_client(),
            [{"role": "system", "content": prompt}],
            mode=mode,
            config_name=config_name,
            max_tokens=512,
        )
        raw = (result.text or "").strip()
        start, end = raw.find("{"), raw.rfind("}")
        parsed = _loads_lenient(raw[start:end + 1]) if start >= 0 and end > start else {}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"读表判读失败: {exc}"}

    value = parsed.get("value")
    if value is None:
        return {"error": f"读表判读未能得到「{target_desc}」的值（表：{table_name}）",
                "_table_context": best.get("context"), "_read_raw": parsed}

    return {
        "result": value,
        "_table_name": table_name,
        "_table_context": best.get("context"),
        "_library_id": best.get("library_id"),
        "_read_cell": parsed.get("cell"),
        "_read_quote": parsed.get("quote"),
        "_method": "llm_read",
        "_source": "canonical_table_read",
        "_trace": [f"选表 score={score}（确定性匹配）", f"候选库：{scope_meta.get('resolved_libraries')}", "取值=LLM 判读"],
    }

"""canonical 精确查表引擎：从 engtools TableTool 结构化模式移植的纯函数管线。

移植自 services/engtools/src/engtools/TableTool.py（demo 时代文件系实现），
输入从「整份 .md 文件」换成「canonical 表格块的 header_rows/body_rows」，
候选选择、条件过滤、行打分、目标列解析逻辑与原实现逐行对齐（A/B 对齐基线）。

与原实现的有意差异：
- 候选统一为 rows 形态（canonical 侧 CanonicalTable 已解析好行列，不再需要 BS4）；
- 原「未找到匹配表格」分支引用了未定义变量 md_candidates（NameError），此处修正；
- LLM 选表/LLM 抽取路径不移植（SOP 场景 use_llm=False 是唯一消费方）。
"""
import json
import logging
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _normalize_text(text: str) -> str:
    """标准化文本用于匹配。"""
    return re.sub(r"\s+", "", (text or "")).lower()


def _normalize_table_ref(text: str) -> str:
    """标准化表号引用，统一空格、波浪线与大小写格式。"""
    normalized = _normalize_text(text)
    normalized = normalized.replace("～", "~").replace("—", "-").replace("–", "-")
    return normalized


def _extract_table_refs(text: str) -> List[str]:
    """从标题或上下文中提取表号引用列表。"""
    refs = re.findall(r"(?:表|图)\s*[A-Za-z0-9.]+(?:-\d+)?", text or "", re.IGNORECASE)
    return [_normalize_table_ref(item) for item in refs]


def _expand_match_variants(text: str) -> List[str]:
    """为文本匹配生成若干归一化变体，提升领域词的召回鲁棒性。"""
    base = _normalize_text(text)
    variants = {base}
    if not base:
        return []
    variants.add(re.sub(r"[或和及的]", "", base))
    for suffix in ["条件", "情况", "类型", "类别", "参数", "数值", "值", "海底", "底质", "设计"]:
        if suffix in base:
            variants.add(base.replace(suffix, ""))
    if base.endswith("船") and len(base) > 1:
        variants.add(base[:-1])
    if "干散货船" in base:
        variants.add(base.replace("干散货船", "散货船"))
    if "液体散货船" in base:
        variants.add(base.replace("液体散货船", "散货船"))
    if "货物滚装船" in base:
        variants.add(base.replace("货物滚装船", "滚装船"))
    return [item for item in variants if item]


def _text_condition_matches(cell_text: str, condition_text: str) -> bool:
    """判断文本条件是否可视为命中，兼容包含关系与近似措辞。"""
    cell_variants = _expand_match_variants(cell_text)
    cond_variants = _expand_match_variants(condition_text)
    for cond in cond_variants:
        for cell in cell_variants:
            if cond in cell or cell in cond:
                return True
            if len(cond) >= 3 and len(cell) >= 3 and SequenceMatcher(None, cond, cell).ratio() >= 0.62:
                return True
    return False


def _parse_query_conditions(query_conditions: Any) -> Dict[str, Any]:
    """解析查询条件为字典。"""
    if isinstance(query_conditions, dict):
        return query_conditions
    if isinstance(query_conditions, str):
        text = query_conditions.strip()
        if not text:
            return {}
        if text.startswith("{") and text.endswith("}"):
            try:
                return json.loads(text)
            except Exception:
                return {}
        match = re.match(r"^\s*([^=:/]+)\s*[:=]\s*([^\s]+)\s*$", text)
        if match:
            return {match.group(1).strip(): match.group(2).strip()}
    return {}


def _extract_first_number(text: str) -> Optional[float]:
    """提取文本中的首个数值。"""
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text or "")
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def _parse_range(text: str) -> Optional[tuple]:
    """解析区间表达式并返回 (low, high)。"""
    if not text:
        return None
    t = text.strip()
    t = t.replace("～", "-").replace("—", "-").replace("~", "-")
    match = re.search(r"(\d+(?:\.\d+)?)\s*≤\s*[A-Za-z]*\s*<\s*(\d+(?:\.\d+)?)", t)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    match = re.search(r"(\d+(?:\.\d+)?)\s*<\s*[A-Za-z]*\s*≤\s*(\d+(?:\.\d+)?)", t)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    match = re.search(r"(\d+(?:\.\d+)?)\s*<=\s*[A-Za-z]*\s*<\s*(\d+(?:\.\d+)?)", t)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    match = re.search(r"(\d+(?:\.\d+)?)\s*<\s*[A-Za-z]*\s*<=\s*(\d+(?:\.\d+)?)", t)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", t)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    match = re.search(r"(?:≤|<=)\s*(\d+(?:\.\d+)?)", t)
    if match:
        return (float("-inf"), float(match.group(1)))
    match = re.search(r"<\s*(\d+(?:\.\d+)?)", t)
    if match:
        return (float("-inf"), float(match.group(1)))
    match = re.search(r"(?:≥|>=)\s*(\d+(?:\.\d+)?)", t)
    if match:
        return (float(match.group(1)), float("inf"))
    match = re.search(r">\s*(\d+(?:\.\d+)?)", t)
    if match:
        return (float(match.group(1)), float("inf"))
    return None


def _find_column_index(headers: List[str], key: str, synonyms: Optional[List[str]] = None) -> Optional[int]:
    """在表头中匹配列索引。跳过维度标注列（如"船舶航速（kn）"）。"""
    if not headers or not key:
        return None

    dimension_patterns = ['航速', '水深', '波长', '周期', '吃水', 'dwt']

    candidates = [key] + (synonyms or [])
    for candidate in candidates:
        cand_variants = _expand_match_variants(candidate)
        for idx, header in enumerate(headers):
            header_norm = _normalize_text(header)
            # 跳过维度标注列（如 "船舶航速（kn）"）
            if any(dim in header_norm for dim in dimension_patterns) and not re.search(r'\d', header):
                continue
            for cand_norm in cand_variants:
                if cand_norm and (cand_norm in header_norm or header_norm in cand_norm):
                    return idx

    # 如果没有匹配到，尝试提取关键词进行模糊匹配
    key_parts = re.findall(r'[Z-z]\d*|下沉|富裕|吃水', key)
    if key_parts:
        for idx, header in enumerate(headers):
            header_norm = _normalize_text(header)
            for part in key_parts:
                if part.lower() in header_norm or header_norm in part.lower():
                    return idx

    return None


def _find_column_indices(headers: List[str], key: str, synonyms: Optional[List[str]] = None) -> List[int]:
    """返回所有可能命中的列索引，支持成对重复列的表格匹配。"""
    indices: List[int] = []
    for idx, header in enumerate(headers):
        if _find_column_index([header], key, synonyms) == 0:
            indices.append(idx)
    return indices


def _detect_table_range(table_name: str) -> Optional[tuple]:
    """检测表格名称是否为范围模式（如 "表A.0.2-1~表A.0.2-14"）。返回 (prefix, start_num, end_num) 或 None。"""
    pattern = r'(表|图)([A-Za-z0-9.]+)-(\d+)~\1\2-(\d+)'
    match = re.search(pattern, table_name.strip())
    if not match:
        return None
    prefix = f"{match.group(1)}{match.group(2)}"
    start_num = int(match.group(3))
    end_num = int(match.group(4))
    if end_num <= start_num:
        return None
    return (prefix, start_num, end_num)


def _score_table_reference_match(table_name: str, context: str) -> int:
    """计算查询表名与候选上下文的标题匹配分数。"""
    table_ref = _normalize_table_ref(table_name)
    context_ref_list = _extract_table_refs(context)
    if context_ref_list:
        if table_ref in context_ref_list:
            return 300
        range_info = _detect_table_range(table_name)
        if range_info:
            prefix, start_num, end_num = range_info
            prefix_norm = _normalize_table_ref(prefix)
            for ref in context_ref_list:
                match = re.search(rf"{re.escape(prefix_norm)}-(\d+)", ref)
                if match and start_num <= int(match.group(1)) <= end_num:
                    return 280
    context_norm = _normalize_table_ref(context)
    if table_ref and table_ref in context_norm:
        return 220
    return 0


def _score_numeric_fit_for_candidate(cand: Dict[str, Any], conditions: Dict[str, Any]) -> int:
    """根据数值条件粗评候选表适配度，用于区分续表或分段表。"""
    if not conditions:
        return 0
    numeric_targets = []
    for value in conditions.values():
        parsed = _extract_first_number(str(value))
        if parsed is not None:
            numeric_targets.append(parsed)
    if not numeric_targets:
        return 0
    headers = cand.get("headers") or []
    rows = cand.get("rows") or []
    tonnage_col = _find_column_index(headers, "吨级", ["船舶吨级", "DWT", "GT"])
    if tonnage_col is None:
        return 0
    best_distance = float("inf")
    for row in rows:
        if tonnage_col >= len(row):
            continue
        range_value = _parse_range(row[tonnage_col])
        if range_value:
            target = numeric_targets[0]
            if range_value[0] <= target <= range_value[1]:
                return 60
            distance = min(abs(target - range_value[0]), abs(target - range_value[1]))
        else:
            cell_num = _extract_first_number(row[tonnage_col])
            if cell_num is None:
                continue
            distance = abs(numeric_targets[0] - cell_num)
        best_distance = min(best_distance, distance)
    if best_distance == float("inf"):
        return 0
    if best_distance <= 1:
        return 50
    if best_distance <= 1000:
        return 35
    if best_distance <= 10000:
        return 20
    return 5


def flatten_header_rows(header_rows: List[List[str]]) -> List[str]:
    """把 canonical 多行表头压平为单行：逐列拼接各层非空文本（去重保序）。

    老工具从 HTML 解析出的表头是单行；canonical header_rows 可能是两层
    （如 ["船舶吨级", "DWT(t)"] 上下两行），压平成 "船舶吨级 DWT(t)" 保证
    列匹配对任一层文本都能命中。
    """
    if not header_rows:
        return []
    width = max(len(row) for row in header_rows)
    flat: List[str] = []
    for col in range(width):
        parts: List[str] = []
        for row in header_rows:
            cell = str(row[col]).strip() if col < len(row) else ""
            if cell and cell not in parts:
                parts.append(cell)
        flat.append(" ".join(parts))
    return flat


def query_tables(
    candidates: List[Dict[str, Any]],
    *,
    table_name: str,
    query_conditions: Any,
    target_column: Optional[str] = None,
) -> Dict[str, Any]:
    """结构化精确查表管线（移植自 TableTool.run 的 use_llm=False 分支）。

    candidates: [{"headers": [...] 或 "header_rows": [[...]], "rows": [[...]], "context": str}]
    返回形态与原实现一致：{"result": 值或行字典, "method", "_table_name", "_table_headers",
    "_table_context", "_trace"} 或 {"error", ...}。
    """
    trace: List[str] = []
    normalized_candidates: List[Dict[str, Any]] = []
    for idx, cand in enumerate(candidates):
        headers = cand.get("headers")
        if headers is None:
            headers = flatten_header_rows(cand.get("header_rows") or [])
        normalized_candidates.append({
            "headers": headers,
            "rows": cand.get("rows") or [],
            "context": cand.get("context") or "",
            "index": idx,
            "doc_id": cand.get("doc_id"),
            "page_idx": cand.get("page_idx"),
        })

    conditions = _parse_query_conditions(query_conditions)

    name_norm = _normalize_text(table_name)

    # 优先选择 Context 中包含查询条件值的表格
    condition_values = []
    if conditions:
        for v in conditions.values():
            if isinstance(v, str) and len(v) > 1:
                condition_values.append(str(v))

    def score_candidate(cand):
        score = 0
        ctx = cand.get("context", "")
        score += _score_table_reference_match(table_name, ctx)
        score += _score_numeric_fit_for_candidate(cand, conditions)
        ctx_norm = _normalize_text(ctx)
        for val in condition_values:
            if any(variant in ctx_norm for variant in _expand_match_variants(val)):
                score += 12
        if name_norm and name_norm in ctx_norm:
            score += 50
        return score

    normalized_candidates.sort(key=score_candidate, reverse=True)

    target_table = None
    explicit_candidates = [cand for cand in normalized_candidates if _score_table_reference_match(table_name, cand.get("context", "")) > 0]
    if explicit_candidates:
        explicit_candidates.sort(key=score_candidate, reverse=True)
        target_table = explicit_candidates[0]
        explicit_score = _score_table_reference_match(table_name, target_table.get("context", ""))
        if explicit_score >= 300:
            trace.append("表格选择策略: 标题精确匹配")
        elif explicit_score >= 280:
            trace.append("表格选择策略: 范围表名匹配")
        else:
            trace.append("表格选择策略: 标题归一化匹配")
    if not target_table:
        for cand in normalized_candidates:
            ctx_norm = _normalize_text(cand["context"])
            if name_norm and name_norm in ctx_norm:
                target_table = cand
                trace.append("表格选择策略: 上下文全匹配")
                break
    if not target_table:
        name_words = re.findall(r"[一-鿿]+|[A-Za-z0-9]+", table_name)
        for cand in normalized_candidates:
            ctx = cand["context"] or ""
            if any(w and w in ctx for w in name_words):
                target_table = cand
                trace.append("表格选择策略: 上下文部分匹配")
                break
    if not target_table:
        # 对齐老工具「HTML 内容包含表名」兜底：表名出现在表头/前几行内容里
        for cand in normalized_candidates:
            haystack = " ".join(cand["headers"]) + " " + " ".join(
                " ".join(str(cell) for cell in row) for row in (cand["rows"] or [])[:3]
            )
            if table_name and table_name in haystack:
                target_table = cand
                trace.append("表格选择策略: 表格内容包含表名")
                break
    if not target_table:
        return {
            "error": f"未找到匹配表格: {table_name}",
            "_diagnostic_info": {
                "table_name": table_name,
                "total_candidates": len(normalized_candidates),
                "suggestions": [
                    "请确认表格名称是否与文档中的标题一致",
                    "尝试使用更具体的表名，或检查表格是否在当前文档范围内",
                ],
            },
        }

    headers = target_table.get("headers") or []
    rows = target_table.get("rows") or []
    trace.append(f"匹配表名: {table_name}")
    trace.append(f"匹配表格上下文: {target_table['context']}")
    trace.append(f"解析表头: {headers}")

    if not conditions:
        return {
            "error": "查询条件为空",
            "_table_name": table_name,
            "_table_context": target_table["context"],
            "_table_headers": headers,
            "_diagnostic_info": {
                "raw_query_conditions": query_conditions,
                "suggestions": [
                    "请提供至少一个查询条件（如列名=值）",
                    "检查 query_conditions 参数格式是否正确",
                ],
            },
        }

    # 分离文本和数值条件
    numeric_conditions = {}
    text_conditions = {}
    for k, v in conditions.items():
        val_num = _extract_first_number(str(v))
        if val_num is not None:
            numeric_conditions[k] = val_num
        else:
            text_conditions[k] = str(v)

    trace.append(f"文本条件过滤: {text_conditions}")

    # 筛选行（文本条件）
    rows_to_scan = rows
    if text_conditions:
        filtered_rows = []
        for row in rows:
            match = True
            for k, v in text_conditions.items():
                col_indices = _find_column_indices(headers, k, [k])
                if col_indices:
                    if not any(idx < len(row) and _text_condition_matches(row[idx], v) for idx in col_indices):
                        match = False
                        break
                else:
                    if _detect_table_range(table_name):
                        continue
                    if _text_condition_matches(target_table.get("context", ""), v):
                        continue
                    row_str = " ".join(row)
                    if not _text_condition_matches(row_str, v):
                        match = False
                        break
            if match:
                filtered_rows.append(row)
        rows_to_scan = filtered_rows

    if not rows_to_scan:
        return {"error": "未找到符合文本条件的行", "_table_name": table_name, "_table_context": target_table["context"], "_table_headers": headers}

    # 数值条件处理（多条件最佳匹配）
    col_conditions = {}  # col_idx -> target_value
    header_lookup_conditions = {}  # key -> target_value（没找到列名的）

    for k, v in numeric_conditions.items():
        idx = _find_column_index(headers, k, [k])
        if idx is not None:
            col_conditions[idx] = v
            trace.append(f"条件列匹配: {k} -> Col {idx}, Val {v}")
        else:
            header_lookup_conditions[k] = v
            trace.append(f"条件列未匹配(可能是表头查找): {k}={v}")

    best_row = None

    if col_conditions:
        scored_rows = []
        for row in rows_to_scan:
            dist = 0
            valid = True
            for col_idx, target_val in col_conditions.items():
                if col_idx >= len(row):
                    valid = False
                    break
                cell_val = _extract_first_number(row[col_idx])
                if cell_val is None:
                    rng = _parse_range(row[col_idx])
                    if rng:
                        if rng[0] <= target_val <= rng[1]:
                            dist += 0
                        else:
                            dist += min(abs(target_val - rng[0]), abs(target_val - rng[1])) * 10
                    else:
                        valid = False
                        break
                else:
                    dist += abs(cell_val - target_val)

            if valid:
                scored_rows.append((dist, row))

        if scored_rows:
            scored_rows.sort(key=lambda x: x[0])
            best_dist, best_row = scored_rows[0]
            trace.append(f"最佳行匹配距离: {best_dist}")
        else:
            return {
                "error": "数值条件无法匹配任何行",
                "_table_name": table_name,
                "_table_headers": headers,
                "_diagnostic_info": {
                    "numeric_conditions": list(numeric_conditions.items()),
                    "col_conditions": {str(k): v for k, v in col_conditions.items()},
                    "rows_scanned": len(rows_to_scan),
                    "suggestions": [
                        "检查数值条件是否在表格的数据范围内",
                        "如表格数值范围与条件不重叠，请确认参数是否正确",
                    ],
                },
            }
    else:
        if rows_to_scan:
            best_row = rows_to_scan[0]

    if not best_row:
        return {
            "error": "无法确定目标行",
            "_table_name": table_name,
            "_table_headers": headers,
            "_diagnostic_info": {
                "text_conditions": list(text_conditions.items()) if text_conditions else [],
                "numeric_conditions": list(numeric_conditions.items()) if numeric_conditions else [],
                "rows_available": len(rows_to_scan),
                "suggestions": [
                    "文本和数值条件均未能定位到具体行",
                    "检查查询条件是否过于严格，或尝试放宽条件",
                ],
            },
        }

    # 确定目标列
    final_target_col_idx = None

    if target_column:
        final_target_col_idx = _find_column_index(headers, target_column, [target_column])

    # 对 "条件列-结果列" 成对出现的横向表，优先返回命中的相邻数值列
    if final_target_col_idx is None and text_conditions:
        for key, value in text_conditions.items():
            candidate_indices = _find_column_indices(headers, key, [key])
            for idx in candidate_indices:
                if idx < len(best_row) and _text_condition_matches(best_row[idx], value):
                    if idx + 1 < len(best_row):
                        final_target_col_idx = idx + 1
                        trace.append(f"根据成对列匹配到目标列: {headers[final_target_col_idx]}")
                        break
            if final_target_col_idx is not None:
                break

    # Header Lookup Conditions（根据值查找列）
    if final_target_col_idx is None and header_lookup_conditions:
        k, v = next(iter(header_lookup_conditions.items()))
        best_header_dist = float('inf')
        best_header_idx = -1

        for i, h in enumerate(headers):
            if i in col_conditions:
                continue
            h_val = _extract_first_number(h)
            if h_val is not None:
                d = abs(h_val - v)
                if d < best_header_dist:
                    best_header_dist = d
                    best_header_idx = i
            else:
                rng = _parse_range(h)
                if rng:
                    if rng[0] <= v <= rng[1]:
                        d = 0
                    else:
                        d = min(abs(v - rng[0]), abs(v - rng[1]))
                    if d < best_header_dist:
                        best_header_dist = d
                        best_header_idx = i

        if best_header_idx != -1:
            final_target_col_idx = best_header_idx
            trace.append(f"根据表头值 {k}={v} 匹配到列: {headers[best_header_idx]}")

    # Auto Target：如果只有一个剩余列
    if final_target_col_idx is None:
        all_indices = set(range(len(headers)))
        used_indices = set(col_conditions.keys())
        for k in text_conditions:
            idx = _find_column_index(headers, k, [k])
            if idx is not None:
                used_indices.add(idx)

        remaining = list(all_indices - used_indices)
        if len(remaining) == 1:
            final_target_col_idx = remaining[0]
            trace.append(f"自动推断目标列: {headers[final_target_col_idx]}")
        elif len(remaining) > 1:
            candidates_cols = [i for i in remaining if headers[i] not in ["序号", "备注", "说明"]]
            if len(candidates_cols) == 1:
                final_target_col_idx = candidates_cols[0]
                trace.append(f"自动推断目标列(排除杂项): {headers[final_target_col_idx]}")

    # 构建返回值
    result: Dict[str, Any] = {}
    result["_table_name"] = table_name
    result["_table_headers"] = headers
    result["_table_context"] = target_table["context"]
    if target_table.get("doc_id"):
        result["_doc_id"] = target_table["doc_id"]
    if target_table.get("page_idx") is not None:
        result["_page_idx"] = target_table["page_idx"]
    result["_trace"] = trace

    if final_target_col_idx is not None and final_target_col_idx < len(best_row):
        val_text = best_row[final_target_col_idx]
        val_num = _extract_first_number(val_text)
        result["result"] = val_num if val_num is not None else val_text
        result["method"] = "best_match_value"
    else:
        # 重复表头名（canonical 合并单元格展开会产生同名列）去重命名，避免同键覆盖错位
        row_map = {}
        for i, cell in enumerate(best_row):
            if i < len(headers):
                key = headers[i]
                if key in row_map:
                    suffix = 2
                    while f"{key}#{suffix}" in row_map:
                        suffix += 1
                    key = f"{key}#{suffix}"
                row_map[key] = cell
            else:
                row_map[f"col_{i}"] = cell
        result["result"] = row_map

    return result

import os
import re
import json
import sys
import logging
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from difflib import SequenceMatcher
from bs4 import BeautifulSoup
from .BaseTool import BaseTool, register_tool
from .config import KNOWLEDGE_DIR
from ai_inference.llm_client import get_llm_client

logger = logging.getLogger(__name__)

_LLM_TIMEOUT_SECONDS = 60


# ============================================================================
# 第一部分：通用工具函数
# ============================================================================

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


def _llm_chat_with_timeout(model: str = None, messages: List[Dict] = None, timeout: int = None) -> str:
    """
    带超时保护的 LLM 调用，防止模型响应慢导致整个链路卡死。
    """
    if timeout is None:
        timeout = _LLM_TIMEOUT_SECONDS
    llm_client = get_llm_client()

    def _do_chat():
        return llm_client.chat(model=model, messages=messages)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_chat)
            return future.result(timeout=timeout)
    except FuturesTimeoutError:
        logger.warning(f"[TableTool] LLM 调用超时 ({timeout}s)，使用默认策略")
        raise TimeoutError(f"LLM call timed out after {timeout}s")
    except Exception as exc:
        logger.warning(f"[TableTool] LLM 调用异常: {exc}")
        raise


# ============================================================================
# 第二部分：数值解析工具
# ============================================================================

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


# ============================================================================
# 第三部分：表格解析工具（用于结构化模式）
# ============================================================================

def _get_table_context(table) -> str:
    """获取表格附近的标题或段落文本（兼容 Markdown 原始文本）。"""
    # 先尝试查找 HTML 标签
    prev = table.find_previous(lambda tag: getattr(tag, "name", None) in ["h1", "h2", "h3", "h4", "h5", "h6", "p"])
    if prev and prev.get_text(strip=True):
        return prev.get_text(strip=True)
    
    # 查找前面的兄弟节点（包括纯文本）
    texts = []
    for sib in getattr(table, "previous_siblings", []):
        try:
            if hasattr(sib, "get_text"):
                t = sib.get_text(strip=True)
            elif hasattr(sib, "strip"):
                t = sib.strip()
            else:
                t = str(sib).strip()
        except Exception:
            t = ""
        if t:
            texts.append(t)
            if len(texts) >= 2:
                break
    
    if texts:
        return " / ".join(texts[:2])
    
    # 最后尝试：直接获取表格前面所有文本内容
    try:
        parent = table.parent
        if parent:
            table_str = str(table)
            parent_str = str(parent)
            idx = parent_str.find(table_str)
            if idx > 0:
                before_text = parent_str[:idx]
                # 提取最后一行非空文本
                lines = [ln.strip() for ln in before_text.split('\n') if ln.strip()]
                if lines:
                    return lines[-1]
    except Exception:
        pass
    
    return ""


def _parse_table_headers(table) -> List[str]:
    """解析表格表头，处理 rowspan 和 colspan 合并单元格。"""
    thead = table.find("thead")
    if thead:
        ths = thead.find_all(["th", "td"])
        if ths:
            return [th.get_text(strip=True) for th in ths]
    
    # 获取前两行，处理合并单元格
    rows = table.find_all("tr")
    if not rows:
        return []
    if _infer_header_row_count(rows) == 1:
        return [cell.get_text(strip=True) for cell in rows[0].find_all(["th", "td"])]
    
    # 解析前两行
    row1_cells = rows[0].find_all(["th", "td"]) if rows[0] else []
    row2_cells = rows[1].find_all(["th", "td"]) if len(rows) > 1 and rows[1] else []
    
    # 构建完整表头
    headers = []
    row1_idx = 0
    row2_idx = 0
    
    # 处理第一行
    for cell in row1_cells:
        text = cell.get_text(strip=True)
        rowspan = int(cell.get("rowspan", 1))
        colspan = int(cell.get("colspan", 1))
        
        if rowspan > 1:
            # 跨行单元格，直接添加
            headers.append(text)
        else:
            # 不跨行，需要从第二行补充
            headers.append(text)
            # 跳过第二行对应的列（因为第一行占了位置）
    
    # 如果第一行有跨行单元格，第二行的表头需要插入到正确位置
    if row2_cells:
        # 重新构建表头：跨行的保留，不跨行的用第二行替换
        final_headers = []
        row1_idx = 0
        row2_idx = 0
        
        for cell in row1_cells:
            rowspan = int(cell.get("rowspan", 1))
            text = cell.get_text(strip=True)
            
            if rowspan > 1:
                # 跨行，保留第一行的文本
                final_headers.append(text)
            else:
                # 不跨行，用第二行的文本替换
                if row2_idx < len(row2_cells):
                    final_headers.append(row2_cells[row2_idx].get_text(strip=True))
                    row2_idx += 1
        
        # 添加第二行剩余的单元格
        while row2_idx < len(row2_cells):
            final_headers.append(row2_cells[row2_idx].get_text(strip=True))
            row2_idx += 1
        
        return final_headers
    
    return [cell.get_text(strip=True) for cell in row1_cells]


def _parse_table_rows(table) -> List[List[str]]:
    """解析表格数据行。"""
    tbody = table.find("tbody")
    if tbody:
        rows = tbody.find_all("tr")
    else:
        all_rows = table.find_all("tr")
        header_row_count = _infer_header_row_count(all_rows)
        rows = all_rows[header_row_count:]
    parsed = []
    for row in rows:
        cells = [cell.get_text(strip=True) for cell in row.find_all(["th", "td"])]
        if cells:
            parsed.append(cells)
    return parsed


def _infer_header_row_count(rows: List[Any]) -> int:
    """推断无 thead 表格的表头行数，避免把首条数据误识别成表头。"""
    if not rows:
        return 0
    if len(rows) == 1:
        return 1
    first_row_cells = rows[0].find_all(["th", "td"])
    if any(int(cell.get("rowspan", 1)) > 1 or int(cell.get("colspan", 1)) > 1 for cell in first_row_cells):
        return 2
    if any(getattr(cell, "name", None) == "th" for cell in rows[1].find_all(["th", "td"])):
        return 2
    return 1


def _split_md_row(line: str) -> List[str]:
    parts = [p.strip() for p in line.strip().strip("|").split("|")]
    return [p for p in parts if p != ""]


def _is_md_sep(line: str) -> bool:
    if "|" not in line:
        return False
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if not cells:
        return False
    return all(re.match(r"^:?-{3,}:?$", cell) for cell in cells)


# ============================================================================
# 第四部分：Markdown 表格解析工具
# ============================================================================

def _extract_markdown_tables(content: str) -> List[Dict[str, Any]]:
    lines = content.splitlines()
    tables = []
    i = 0
    while i < len(lines) - 1:
        line = lines[i]
        next_line = lines[i + 1]
        if "|" in line and _is_md_sep(next_line):
            headers = _split_md_row(line)
            rows = []
            j = i + 2
            while j < len(lines):
                row_line = lines[j]
                if "|" not in row_line:
                    break
                if _is_md_sep(row_line):
                    j += 1
                    continue
                row = _split_md_row(row_line)
                if row:
                    rows.append(row)
                j += 1
            context = ""
            k = i - 1
            while k >= 0:
                ctx_line = lines[k].strip()
                if ctx_line:
                    context = re.sub(r"[*_`]+", "", ctx_line)
                    break
                k -= 1
            tables.append({"headers": headers, "rows": rows, "context": context})
            i = j
            continue
        i += 1
    return tables


# ============================================================================
# 第五部分：列索引查找工具（用于结构化模式）
# ============================================================================

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


# ============================================================================
# 第六部分：LLM 查询工具（用于 LLM 模式，默认）
# ============================================================================

def _llm_normalize_for_matching(text: str) -> str:
    """标准化文本用于 LLM 表格匹配。"""
    if not text:
        return ""
    text = text.replace('Ψ', 'Psi')
    return re.sub(r'[^0-9a-zA-Z\u4e00-\u9fa5]', '', text)


def _llm_find_table(all_tables: List[Dict], table_hint: str) -> Optional[Dict]:
    """根据表格提示找到匹配的表格。"""
    hint_normalized = _llm_normalize_for_matching(table_hint)
    for table in all_tables:
        caption_normalized = _llm_normalize_for_matching(table.get('caption', ''))
        if hint_normalized in caption_normalized or caption_normalized in hint_normalized:
            return table
    return None


def _detect_table_range(table_name: str) -> Optional[tuple]:
    """
    检测表格名称是否为范围模式（如 "表A.0.2-1~表A.0.2-14"）。
    返回 (prefix, start_num, end_num) 或 None。
    """
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
    if cand.get("headers") is not None:
        headers = cand.get("headers") or []
        rows = cand.get("rows") or []
    else:
        table = cand.get("table")
        if table is None:
            return 0
        headers = _parse_table_headers(table)
        rows = _parse_table_rows(table)
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


def _extract_table_number(caption: str, prefix: str) -> Optional[int]:
    """
    从表格标题中提取编号。如 prefix="表A.0.2", caption="表A.0.2-7 xxx" → 7。
    """
    escaped = re.escape(prefix)
    match = re.search(rf'{escaped}-(\d+)', caption)
    if match:
        return int(match.group(1))
    return None


def _expand_range_candidates(all_tables: List[Dict], prefix: str, start_num: int, end_num: int) -> List[Dict]:
    """
    从文档所有表格中筛选出匹配前缀+编号范围的候选表。
    """
    candidates = []
    for table in all_tables:
        num = _extract_table_number(table.get('caption', ''), prefix)
        if num is not None and start_num <= num <= end_num:
            candidates.append({**table, "_range_num": num})
    candidates.sort(key=lambda t: t.get("_range_num", 0))
    return candidates


def _llm_select_table(candidates: List[Dict], query_conditions: Any, model: str = None) -> Optional[Dict]:
    """
    使用 LLM 根据查询条件从候选表格中选择最合适的一个。
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    candidate_lines = []
    for idx, t in enumerate(candidates):
        caption = t.get('caption', '').strip()
        candidate_lines.append(f"{idx + 1}. {caption}")

    conditions_text = ""
    if isinstance(query_conditions, dict):
        conditions_text = "\n".join(f"- {k}: {v}" for k, v in query_conditions.items())
    elif isinstance(query_conditions, str):
        conditions_text = query_conditions

    prompt = (
        "你是港口工程规范专家。根据以下查询条件从候选表格中选择最合适的一个。\n\n"
        "候选表格：\n" +
        "\n".join(candidate_lines) +
        "\n\n查询条件：\n" +
        conditions_text +
        "\n\n请返回所选表格的编号（纯数字）。只返回数字，不要其他内容。"
    )

    try:
        response = _llm_chat_with_timeout(model=model, messages=[{"role": "user", "content": prompt}])
        selected = re.search(r'\d+', response.strip())
        if selected:
            choice_idx = int(selected.group()) - 1
            if 0 <= choice_idx < len(candidates):
                return candidates[choice_idx]
    except (TimeoutError, Exception) as exc:
        logger.warning(f"[TableTool] LLM 选表失败: {exc}")

    return candidates[0]


def _inject_fallback_meta(result: Dict[str, Any], target_table: Dict, fallback_used: bool) -> Dict[str, Any]:
    """在结果中注入 fallback 追踪信息。"""
    if fallback_used:
        result["_mode"] = "llm_fallback"
        result["_fallback_reason"] = "range_pattern_detected"
        result["_selected_table_index"] = target_table.get("index")
        result["_selected_table_caption"] = target_table.get("caption", "")
    return result


def _llm_query_table(html_content: str, table_hint: str, query: str, query_conditions: Any = None, model: str = None) -> Dict[str, Any]:
    """
    两阶段表格查询：
    阶段1：使用 LLM 语义定位最相关的表格
    阶段2：使用结构化解析在定位的表格内查找行和列
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    html_tables = soup.find_all('table')
    table_titles = re.findall(r'([^<\n]+?)\s*<table', html_content)
    
    # 构建所有候选表格
    all_tables = []
    for i, table in enumerate(html_tables):
        caption = table_titles[i] if i < len(table_titles) else f"表格 {i+1}"
        all_tables.append({
            "index": i + 1,
            "caption": caption,
            "html": str(table),
            "table": table,
            "type": "html"
        })
    
    # ========== 阶段1：LLM 定位表格 ==========
    target_table = _llm_find_table(all_tables, table_hint)
    fallback_used = False
    if not target_table:
        range_info = _detect_table_range(table_hint)
        if range_info:
            candidates = _expand_range_candidates(all_tables, *range_info)
            if candidates:
                target_table = _llm_select_table(candidates, query_conditions, model)
                fallback_used = True

    if not target_table:
        return {
            "error": f"未找到匹配的表格: {table_hint}",
            "_diagnostic_info": {
                "table_hint": table_hint,
                "available_table_count": len(all_tables),
                "available_captions": [t["caption"] for t in all_tables[:10]],
                "suggestions": [
                    f"共找到 {len(all_tables)} 个表格，请确认表名是否匹配",
                    "尝试使用更具体的表格名称或直接指定 file_name",
                ],
            },
        }
    
    # ========== 阶段2：结构化解析查行 ==========
    # 解析表头和行
    headers = _parse_table_headers(target_table["table"])
    rows = _parse_table_rows(target_table["table"])
    
    if not headers or not rows:
        # 结构化解析失败，回退到 LLM 提取
        return _llm_extract_from_table_html(target_table, query, fallback_used)
    
    # 解析查询条件
    conditions = _parse_query_conditions(query_conditions)
    trace = [f"LLM定位表格: {target_table['caption']}", f"解析表头: {headers}"]
    
    # 分离文本和数值条件
    numeric_conditions = {}
    text_conditions = {}
    for k, v in conditions.items():
        val_num = _extract_first_number(str(v))
        if val_num is not None:
            numeric_conditions[k] = val_num
        else:
            text_conditions[k] = str(v)
    
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
                    row_str = " ".join(row)
                    if not _text_condition_matches(row_str, v):
                        match = False
                        break
            if match:
                filtered_rows.append(row)
        rows_to_scan = filtered_rows if filtered_rows else rows
        trace.append(f"文本条件过滤后剩余行数: {len(rows_to_scan)}")
    
    if not rows_to_scan:
        return {
            "error": "未找到符合文本条件的行",
            "_table_name": table_hint,
            "_table_context": target_table['caption'],
            "_table_headers": headers,
            "_diagnostic_info": {
                "text_conditions": list(text_conditions.items()) if text_conditions else [],
                "headers_available": headers,
                "rows_total": len(rows),
                "rows_after_text_filter": 0,
                "suggestions": [
                    f"检查列名是否在表头 {headers} 中",
                    f"共扫描 {len(rows)} 行，文本条件过滤后无匹配行",
                    "确认表格中是否存在对应文本值的行，或尝试 LLM 模式",
                ],
            },
        }
    
    # 数值条件匹配（找最佳行）
    best_row = None
    if numeric_conditions:
        scored_rows = []
        for row in rows_to_scan:
            dist = 0
            valid = True
            for k, target_val in numeric_conditions.items():
                col_idx = _find_column_index(headers, k, [k])
                if col_idx is not None and col_idx < len(row):
                    cell_val = _extract_first_number(row[col_idx])
                    if cell_val is not None:
                        dist += abs(cell_val - target_val)
                    else:
                        rng = _parse_range(row[col_idx])
                        if rng and rng[0] <= target_val <= rng[1]:
                            dist += 0
                        else:
                            valid = False
                            break
                else:
                    # 未找到对应列，尝试在全行中匹配
                    row_str = " ".join(row)
                    cell_val = _extract_first_number(row_str)
                    if cell_val is not None:
                        dist += abs(cell_val - target_val)
            if valid:
                scored_rows.append((dist, row))
        
        if scored_rows:
            scored_rows.sort(key=lambda x: x[0])
            best_row = scored_rows[0][1]
            trace.append(f"最佳行匹配距离: {scored_rows[0][0]}")
    
    if not best_row:
        best_row = rows_to_scan[0]
        trace.append("无数值条件，取第一行")
    
    # 确定目标列
    final_target_col_idx = None
    # 从 query 中提取目标列
    target_col_candidates = []
    if isinstance(query_conditions, dict):
        # query_conditions 的键是条件列，值不是目标列
        # 尝试从 query 字符串中提取目标列
        pass
    
    # 尝试从 query 中识别目标列名（如 "查B值"、"求T"）
    target_col_patterns = [
        r'查\s*([A-Za-zα-ωΑ-Ω][a-zA-Zα-ωΑ-Ω_]*)\s*值?',
        r'求\s*([A-Za-zα-ωΑ-Ω][a-zA-Zα-ωΑ-Ω_]*)',
        r'([A-Za-zα-ωΑ-Ω][a-zA-Zα-ωΑ-Ω_]*)\s*是多少',
    ]
    for pattern in target_col_patterns:
        match = re.search(pattern, query)
        if match:
            target_col_candidates.append(match.group(1))
    
    if target_col_candidates:
        for col_name in target_col_candidates:
            idx = _find_column_index(headers, col_name, [col_name])
            if idx is not None:
                final_target_col_idx = idx
                trace.append(f"从查询中提取目标列: {col_name} -> 列{idx}")
                break
    
    # 如果未找到目标列，尝试自动推断
    if final_target_col_idx is None:
        # 排除已用作条件的列
        used_indices = set()
        for k in conditions:
            idx = _find_column_index(headers, k, [k])
            if idx is not None:
                used_indices.add(idx)
        
        remaining = [i for i in range(len(headers)) if i not in used_indices]
        # 排除常见非目标列
        remaining = [i for i in remaining if headers[i] not in ["序号", "备注", "说明"]]
        
        if len(remaining) == 1:
            final_target_col_idx = remaining[0]
            trace.append(f"自动推断目标列: {headers[remaining[0]]}")
        elif len(remaining) > 1 and numeric_conditions:
            # 如果有数值条件，优先返回数值列
            for i in remaining:
                val = _extract_first_number(best_row[i]) if i < len(best_row) else None
                if val is not None:
                    final_target_col_idx = i
                    trace.append(f"自动推断目标列(数值优先): {headers[i]}")
                    break
    
    # 构建结果
    result = {
        "_table_name": table_hint,
        "_table_context": target_table['caption'],
        "_table_headers": headers,
        "_trace": trace,
        "_mode": "structured" if not fallback_used else "structured_fallback"
    }
    
    if final_target_col_idx is not None and final_target_col_idx < len(best_row):
        val_text = best_row[final_target_col_idx]
        val_num = _extract_first_number(val_text)
        result["result"] = val_num if val_num is not None else val_text
        result["description"] = f"从表格 {target_table['caption']} 的 {headers[final_target_col_idx]} 列获取"
    else:
        # 未找到目标列，返回整行
        result["result"] = None
        result["description"] = f"未确定目标列，最佳匹配行: {best_row}"
        result["_best_row"] = best_row
    
    return result


def _llm_extract_from_table_html(target_table: Dict, query: str, fallback_used: bool = False) -> Dict[str, Any]:
    """当结构化解析失败时，回退到 LLM 从 HTML 中提取数值。"""
    table_text = f"表格 {target_table['index']}: {target_table['caption']}\n"
    table_text += target_table['html']
    
    prompt = f"""你是一个港口工程专家。请根据以下表格内容回答问题。

表格内容：
{table_text}

问题: {query}

请从表格中提取数值并按以下 JSON 格式返回：
{{"result": <数值>, "description": "<简单描述>"}}

如果无法提取数值，请返回 {{
  "result": null, 
  "error": "<原因>", 
  "description": "<描述>"
}}"""

    try:
        response = _llm_chat_with_timeout(
            messages=[{"role": "user", "content": prompt}]
        )
    except (TimeoutError, Exception) as exc:
        logger.warning(f"[TableTool] LLM 查表数据失败: {exc}")
        return {
            "result": None,
            "error": f"LLM 查询超时或异常: {exc}",
            "description": "",
            "table_index": target_table['index'],
            "table_caption": target_table['caption']
        }
    
    # 尝试解析 JSON
    try:
        json_match = re.search(r'\{[^{}]*"result"[^{}]*\}', response, re.DOTALL)
        if json_match:
            result_data = json.loads(json_match.group())
            result = {
                "result": result_data.get("result"),
                "description": result_data.get("description", ""),
                "raw_response": response,
                "table_index": target_table['index'],
                "table_caption": target_table['caption']
            }
            return _inject_fallback_meta(result, target_table, fallback_used)
    except Exception:
        pass

    # 兜底：尝试提取数值
    number_match = re.search(r'(\d+\.?\d*)\s*(?:m|米)?', response)
    if number_match:
        result = {
            "result": float(number_match.group(1)),
            "description": response,
            "raw_response": response,
            "table_index": target_table['index'],
            "table_caption": target_table['caption']
        }
        return _inject_fallback_meta(result, target_table, fallback_used)

    result = {
        "result": None,
        "description": response,
        "raw_response": response,
        "table_index": target_table['index'],
        "table_caption": target_table['caption']
    }
    return _inject_fallback_meta(result, target_table, fallback_used)


# ============================================================================
# 第七部分：TableLookupTool 工具类
# ============================================================================

@register_tool
class TableLookupTool(BaseTool):
    name = "table_lookup"
    description_en = "Queries structured table data from specifications. Inputs: table_name (str), query_conditions (str/dict), file_name (str, optional), target_column (str, optional)"
    description_zh = "查询规范表格数据。根据表格名称（或描述）和行查询条件，返回对应的数值。输入参数：table_name (str), query_conditions (str/dict), file_name (str, optional), target_column (str, optional)"
    
    knowledge_dir: str = KNOWLEDGE_DIR

    def __init__(self, knowledge_dir: str = None, **data):
        super().__init__(**data)
        if knowledge_dir:
            self.knowledge_dir = knowledge_dir

    def _resolve_file(self, file_name: str) -> Optional[str]:
        """
        解析知识库文件路径。
        优先从数据库中查找，如果失败则回退到文件系统。
        """
        doc_title = file_name
        if doc_title.startswith("markdown/"):
            doc_title = doc_title[len("markdown/"):]
        if doc_title.endswith(".md"):
            doc_title = doc_title[:-3]
        if doc_title.endswith(".pdf"):
            doc_title = doc_title[:-4]
        normalized = doc_title.replace("_", " ").replace("—", "-").replace("–", "-")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized:
            return None
        
        # 阶段1：从数据库查找
        try:
            from docs_core.ingest.store.assets_file_store import file_storage
            from docs_core.knowledge_service import knowledge_service as ks
            nodes = ks.list_nodes("default")
            for node in nodes:
                if node.type != "document":
                    continue
                node_title = node.title.replace("_", " ").replace("—", "-").replace("–", "-")
                node_title = re.sub(r"\s+", " ", node_title).strip()
                if node_title.endswith(".pdf"):
                    node_title = node_title[:-4]
                if node_title.endswith(".md"):
                    node_title = node_title[:-3]
                q = normalized.lower()
                nt = node_title.lower()
                match = False
                if q in nt or nt in q:
                    match = True
                if not match:
                    q_no_year = re.sub(r"[-_]\d{4}\s*$", "", q).strip()
                    nt_no_year = re.sub(r"[-_]\d{4}\s*$", "", nt).strip()
                    if q_no_year and (q_no_year in nt_no_year or nt_no_year in q_no_year):
                        match = True
                if not match:
                    q_prefix = q[:15] if len(q) > 15 else q
                    if q_prefix and nt.startswith(q_prefix):
                        match = True
                if not match:
                    q_code = re.search(r"(jts|jtj|gb|jgj)\s*\d+", q)
                    nt_code = re.search(r"(jts|jtj|gb|jgj)\s*\d+", nt)
                    if q_code and nt_code and q_code.group(0) == nt_code.group(0):
                        match = True
                if match:
                    content_path = file_storage.get_parsed_markdown_path("default", node.id)
                    if content_path.exists():
                        return str(content_path)
                    edited_path = file_storage.get_edited_markdown_path("default", node.id)
                    if edited_path.exists():
                        return str(edited_path)
        except Exception as e:
            logger.warning(f"[TableTool] 数据库查找失败: {e}，尝试文件系统回退")
        
        # 阶段2：回退到文件系统
        try:
            knowledge_dir = self.knowledge_dir or KNOWLEDGE_DIR
            if os.path.isdir(knowledge_dir):
                # 直接匹配文件名
                for fname in os.listdir(knowledge_dir):
                    if not fname.endswith(".md"):
                        continue
                    fbase = fname[:-3].replace("_", " ").replace("—", "-").replace("–", "-")
                    fbase = re.sub(r"\s+", " ", fbase).strip().lower()
                    if normalized.lower() in fbase or fbase in normalized.lower():
                        return os.path.join(knowledge_dir, fname)
                # 递归查找子目录
                for root, dirs, files in os.walk(knowledge_dir):
                    for fname in files:
                        if not fname.endswith(".md"):
                            continue
                        fbase = fname[:-3].replace("_", " ").replace("—", "-").replace("–", "-")
                        fbase = re.sub(r"\s+", " ", fbase).strip().lower()
                        if normalized.lower() in fbase or fbase in normalized.lower():
                            return os.path.join(root, fname)
        except Exception as e:
            logger.warning(f"[TableTool] 文件系统查找失败: {e}")
        
        return None

    def run(self, table_name: str, query_conditions: Any, file_name: str = "《海港水文规范》.md", target_column: str = None, config_name: str = None, mode: str = "instruct", use_llm: bool = True, **kwargs) -> Any:
        """从结构化表格中查询。
        
        Args:
            use_llm: 是否使用 LLM 查询（默认 True）。设为 False 则使用结构化解析。
        """
        # LLM 模式（默认）
        if use_llm:
            file_name = file_name.replace("《", "").replace("》", "")
            knowledge_file = self._resolve_file(file_name)
            if not knowledge_file:
                return {"error": f"未找到知识库文件: {file_name}"}
            with open(knowledge_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 将 query_conditions 转换为自然语言查询
            if isinstance(query_conditions, dict):
                parts = [f"{k}={v}" for k, v in query_conditions.items()]
                query_text = f"{table_name}的{', '.join(parts)}"
            else:
                query_text = f"{table_name}的{query_conditions}"
            
            # 添加目标列信息
            if target_column:
                query_text = f"{query_text}，查询{target_column}"
            
            result = _llm_query_table(content, table_name, query_text, query_conditions=query_conditions)
            if "_mode" not in result:
                result["_mode"] = "llm"
            return result
        
        # 结构化解析模式（原有逻辑）
        file_name = file_name.replace("《", "").replace("》", "")

        use_color = sys.stdout is not None and sys.stdout.isatty() and not os.getenv("NO_COLOR")
        color = "\033[33m" if use_color else ""
        reset = "\033[0m" if use_color else ""
        print(f"{color}  [表格查询] 正在查找表格 '{table_name}'，查询条件: {query_conditions}，来源: {file_name}{reset}")
        trace = []
        knowledge_file = self._resolve_file(file_name)
        if not knowledge_file:
            return {"error": f"未找到知识库文件: {file_name}"}
        
        try:
            with open(knowledge_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            return {"error": f"无法读取文件: {str(e)}"}

        trace.append(f"加载知识库文件: {file_name}")
        soup = BeautifulSoup(content, 'html.parser')
        html_tables = soup.find_all('table')
        candidates = []
        for idx, tbl in enumerate(html_tables):
            table_html = str(tbl)
            context_text = _get_table_context(tbl)
            if context_text:
                lines = [ln.strip() for ln in context_text.splitlines() if ln.strip()]
                if lines:
                    preferred = next((ln for ln in reversed(lines) if "图" in ln or "表" in ln or "Table" in ln), None)
                    context_text = preferred or lines[-1]
                if context_text:
                    match = re.search(r"((?:图|Figure)\s*[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*(?:-\d+)?[^\n]*)", context_text, re.IGNORECASE)
                    if not match:
                        match = re.search(r"((?:表|Table)\s*[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*(?:-\d+)?[^\n]*)", context_text, re.IGNORECASE)
                    if match:
                        context_text = match.group(1).strip()
                        context_text = re.split(r"\s*/\s*", context_text, maxsplit=1)[0].strip()
                        concise_match = re.search(r"((?:图|表)\s*[A-Za-z0-9.]+(?:-\d+)?[^/\n]{0,24})", context_text)
                        if concise_match:
                            context_text = concise_match.group(1).strip()
                        context_text = re.sub(r"[)\]）】〉》>]+$", "", context_text).strip()
            # 不再截断上下文，保留完整表名用于匹配
            candidates.append({
                "html": table_html,
                "context": context_text,
                "index": idx,
                "table": tbl,
                "type": "html"
            })
        markdown_tables = _extract_markdown_tables(content)
        for idx, tbl in enumerate(markdown_tables, start=len(candidates)):
            candidates.append({
                "html": "",
                "context": tbl.get("context", ""),
                "index": idx,
                "headers": tbl.get("headers", []),
                "rows": tbl.get("rows", []),
                "type": "markdown"
            })

        conditions = _parse_query_conditions(query_conditions)
        
        # 预先计算标准化表名，用于后续匹配
        name_norm = _normalize_text(table_name)
        name_words = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", table_name)
        kind_token = "图" if "图" in table_name else ("表" if "表" in table_name else None)
        
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
            # Also prefer if table name is in context (use normalized matching)
            if name_norm and name_norm in ctx_norm:
                score += 50
            return score

        # Sort candidates by score descending
        candidates.sort(key=score_candidate, reverse=True)

        target_table = None
        explicit_candidates = [cand for cand in candidates if _score_table_reference_match(table_name, cand.get("context", "")) > 0]
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
        markdown_candidates = [c for c in candidates if c.get("type") == "markdown"]
        html_candidates = [c for c in candidates if c.get("type") == "html"]
        if not target_table:
            for cand in markdown_candidates:
                if kind_token and kind_token not in (cand["context"] or ""):
                    continue
                ctx_norm = _normalize_text(cand["context"])
                if name_norm and name_norm in ctx_norm:
                    target_table = cand
                    trace.append("表格选择策略: Markdown 上下文全匹配")
                    break
        if not target_table:
            for cand in markdown_candidates:
                if kind_token and kind_token not in (cand["context"] or ""):
                    continue
                ctx = cand["context"] or ""
                if any(w and w in ctx for w in name_words):
                    target_table = cand
                    trace.append("表格选择策略: Markdown 上下文部分匹配")
                    break
        if not target_table:
            for cand in html_candidates:
                if kind_token and kind_token not in (cand["context"] or ""):
                    continue
                ctx_norm = _normalize_text(cand["context"])
                if name_norm and name_norm in ctx_norm:
                    target_table = cand
                    trace.append("表格选择策略: HTML 上下文全匹配")
                    break
        if not target_table:
            for cand in html_candidates:
                if kind_token and kind_token not in (cand["context"] or ""):
                    continue
                ctx = cand["context"] or ""
                if any(w and w in ctx for w in name_words):
                    target_table = cand
                    trace.append("表格选择策略: HTML 上下文部分匹配")
                    break
        if not target_table:
            for cand in html_candidates:
                if table_name in cand["html"]:
                    target_table = cand
                    trace.append("表格选择策略: HTML 内容包含表名")
                    break
        if not target_table:
            return {
                "error": f"未找到匹配表格: {table_name}",
                "_diagnostic_info": {
                    "table_name": table_name,
                    "total_candidates": len(html_candidates) + len(md_candidates),
                    "suggestions": [
                        "请确认表格名称是否与文档中的标题一致",
                        "尝试使用更具体的表名，或检查表格是否存在于指定的知识库文件中",
                    ],
                },
            }

        if target_table.get("headers") is not None:
            headers = target_table.get("headers") or []
            rows = target_table.get("rows") or []
        else:
            headers = _parse_table_headers(target_table["table"])
            rows = _parse_table_rows(target_table["table"])
        trace.append(f"匹配表名: {table_name}")
        trace.append(f"匹配表格上下文: {target_table['context']}")
        trace.append(f"解析表头: {headers}")

        # 2. 解析查询条件
        conditions = _parse_query_conditions(query_conditions)
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
            # 尝试解析为数字
            val_num = _extract_first_number(str(v))
            if val_num is not None:
                numeric_conditions[k] = val_num
            else:
                text_conditions[k] = str(v)

        trace.append(f"文本条件过滤: {text_conditions}")
        
        # 3. 筛选行 (文本条件)
        rows_to_scan = rows
        if text_conditions:
            filtered_rows = []
            for row in rows:
                match = True
                for k, v in text_conditions.items():
                    # 找到对应的列
                    col_indices = _find_column_indices(headers, k, [k])
                    if col_indices:
                        if not any(idx < len(row) and _text_condition_matches(row[idx], v) for idx in col_indices):
                            match = False
                            break
                    # 如果找不到列，暂时忽略该文本条件？或者视为不匹配？
                    # 这是一个策略选择。为了鲁棒性，如果列名不匹配，我们尝试在全行中搜索文本
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

        # 4. 数值条件处理 (多条件最佳匹配)
        # 策略：计算每行的“不匹配度” (Distance)
        # 能够匹配列的条件，计算 abs(cell - target)
        # 不能匹配列的条件，可能是 Header Range Lookup (例如列头是数值)
        
        col_conditions = {} # col_idx -> target_value
        header_lookup_conditions = {} # key -> target_value (没找到列名的)
        
        for k, v in numeric_conditions.items():
            idx = _find_column_index(headers, k, [k])
            if idx is not None:
                col_conditions[idx] = v
                trace.append(f"条件列匹配: {k} -> Col {idx}, Val {v}")
            else:
                header_lookup_conditions[k] = v
                trace.append(f"条件列未匹配(可能是表头查找): {k}={v}")

        # 如果有列条件，进行行打分
        best_row = None
        best_row_idx = -1
        
        if col_conditions:
            scored_rows = []
            for i, row in enumerate(rows_to_scan):
                dist = 0
                valid = True
                for col_idx, target_val in col_conditions.items():
                    if col_idx >= len(row):
                        valid = False
                        break
                    cell_val = _extract_first_number(row[col_idx])
                    if cell_val is None:
                        # 尝试解析区间
                        rng = _parse_range(row[col_idx])
                        if rng:
                            if rng[0] <= target_val <= rng[1]:
                                dist += 0 # 在区间内，距离为0
                            else:
                                dist += min(abs(target_val - rng[0]), abs(target_val - rng[1])) * 10 # 区间外惩罚
                        else:
                            valid = False # 非数字非区间，跳过
                            break
                    else:
                        dist += abs(cell_val - target_val)
                
                if valid:
                    scored_rows.append((dist, row))
            
            if scored_rows:
                # 按距离排序
                scored_rows.sort(key=lambda x: x[0])
                best_dist, best_row = scored_rows[0]
                trace.append(f"最佳行匹配距离: {best_dist}")
                # 如果有多个最佳匹配（例如距离都是0），如何处理？目前取第一个。
                # 对于插值，如果正好落在两个档位之间... 这里简化处理，取最近。
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
                             "考虑使用 LLM 模式 (use_llm=True) 进行语义查找",
                         ],
                     },
                 }
        else:
            # 如果没有列条件（只有文本条件或Header Lookup），默认取第一行（如果有文本筛选）
            # 或者如果 Header Lookup 存在，我们可能不需要特定行（如果表只有一行数据？）
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
                         "考虑使用 LLM 模式进行语义行匹配",
                     ],
                 },
             }

        # 5. 确定目标列 (Target Column)
        final_target_col_idx = None
        
        # 5.1 如果显式指定了 target_column
        if target_column:
            final_target_col_idx = _find_column_index(headers, target_column, [target_column])

        # 5.1.1 对 "条件列-结果列" 成对出现的横向表，优先返回命中的相邻数值列
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
        
        # 5.2 如果存在 Header Lookup Conditions (即根据值查找列)
        # 例如: 水深=15. Headers: [10, 20, 30]. Find closest header.
        if final_target_col_idx is None and header_lookup_conditions:
            # 取第一个未匹配的条件作为列查找依据
            # 假设只有一个维度是列查找
            k, v = next(iter(header_lookup_conditions.items()))
            
            # 扫描表头，寻找数值或区间
            best_header_dist = float('inf')
            best_header_idx = -1
            
            for i, h in enumerate(headers):
                # 跳过已经是条件的列
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

        # 5.3 Auto Target: 如果只有一个剩余列
        if final_target_col_idx is None:
            # 所有列索引集合
            all_indices = set(range(len(headers)))
            # 已用作条件的列索引
            used_indices = set(col_conditions.keys())
            # 文本条件使用的列
            for k in text_conditions:
                idx = _find_column_index(headers, k, [k])
                if idx is not None:
                    used_indices.add(idx)
            
            remaining = list(all_indices - used_indices)
            if len(remaining) == 1:
                final_target_col_idx = remaining[0]
                trace.append(f"自动推断目标列: {headers[final_target_col_idx]}")
            elif len(remaining) > 1:
                # 尝试排除常见的非目标列名 (如 "序号", "备注")
                candidates = [i for i in remaining if headers[i] not in ["序号", "备注", "说明"]]
                if len(candidates) == 1:
                     final_target_col_idx = candidates[0]
                     trace.append(f"自动推断目标列(排除杂项): {headers[final_target_col_idx]}")

        # 6. 构建返回值
        result = {}
        result["_source_html"] = target_table["html"]
        result["_table_name"] = table_name
        result["_table_headers"] = headers
        result["_table_context"] = target_table["context"]
        result["_trace"] = trace
        
        if final_target_col_idx is not None and final_target_col_idx < len(best_row):
            # 返回单一值
            val_text = best_row[final_target_col_idx]
            val_num = _extract_first_number(val_text)
            result["result"] = val_num if val_num is not None else val_text
            result["method"] = "best_match_value"
        else:
            # 返回整行字典
            row_map = {}
            for i, cell in enumerate(best_row):
                if i < len(headers):
                    row_map[headers[i]] = cell
                else:
                    row_map[f"col_{i}"] = cell
            result["result"] = row_map
            result["method"] = "best_match_row"

        return result

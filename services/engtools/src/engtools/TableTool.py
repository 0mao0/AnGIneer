import os
import re
import json
import sys
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from .BaseTool import BaseTool, register_tool
from angineer_core.config import KNOWLEDGE_DIR


def _normalize_text(text: str) -> str:
    """标准化文本用于匹配。"""
    return re.sub(r"\s+", "", (text or "")).lower()


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


def _get_table_context(table) -> str:
    """获取表格附近的标题或段落文本（兼容 Markdown 原始文本）。"""
    prev = table.find_previous(lambda tag: getattr(tag, "name", None) in ["h1", "h2", "h3", "h4", "h5", "h6", "p"])
    if prev and prev.get_text(strip=True):
        return prev.get_text(strip=True)
    texts = []
    for sib in getattr(table, "previous_siblings", []):
        try:
            if hasattr(sib, "get_text"):
                t = sib.get_text(strip=True)
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
    return ""


def _parse_table_headers(table) -> List[str]:
    """解析表格表头。"""
    thead = table.find("thead")
    if thead:
        ths = thead.find_all(["th", "td"])
        if ths:
            return [th.get_text(strip=True) for th in ths]
    first_row = table.find("tr")
    if first_row:
        cells = first_row.find_all(["th", "td"])
        return [cell.get_text(strip=True) for cell in cells]
    return []


def _parse_table_rows(table) -> List[List[str]]:
    """解析表格数据行。"""
    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]
    parsed = []
    for row in rows:
        cells = [cell.get_text(strip=True) for cell in row.find_all(["th", "td"])]
        if cells:
            parsed.append(cells)
    return parsed


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


def _find_column_index(headers: List[str], key: str, synonyms: Optional[List[str]] = None) -> Optional[int]:
    """在表头中匹配列索引。"""
    if not headers or not key:
        return None
    candidates = [key] + (synonyms or [])
    for candidate in candidates:
        cand_norm = _normalize_text(candidate)
        for idx, header in enumerate(headers):
            header_norm = _normalize_text(header)
            if cand_norm and (cand_norm in header_norm or header_norm in cand_norm):
                return idx
    return None


@register_tool
class TableLookupTool(BaseTool):
    name = "table_lookup"
    description_en = "Queries structured table data from specifications. Inputs: table_name (str), query_conditions (str/dict), file_name (str, optional), target_column (str, optional)"
    description_zh = "查询规范表格数据。根据表格名称（或描述）和行查询条件，返回对应的数值。输入参数：table_name (str), query_conditions (str/dict), file_name (str, optional), target_column (str, optional)"

    def run(self, table_name: str, query_conditions: Any, file_name: str = "《海港水文规范》.md", target_column: str = None, config_name: str = None, mode: str = "instruct", **kwargs) -> Any:
        """从结构化表格中查询并在必要时进行线性插值。"""
        # Robust filename handling
        file_name = file_name.replace("《", "").replace("》", "")

        use_color = sys.stdout is not None and sys.stdout.isatty() and not os.getenv("NO_COLOR")
        color = "\033[33m" if use_color else ""
        reset = "\033[0m" if use_color else ""
        print(f"{color}  [表格查询] 正在查找表格 '{table_name}'，查询条件: {query_conditions}，来源: {file_name}{reset}")
        trace = []
        knowledge_file = os.path.join(KNOWLEDGE_DIR, file_name)
        if not os.path.exists(knowledge_file):
            return {"error": f"未找到知识库文件: {file_name}"}
            
        try:
            with open(knowledge_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            return {"error": f"无法读取文件: {str(e)}"}

        trace.append(f"加载知识库文件: {file_name}")
        soup = BeautifulSoup(content, 'html.parser')
        html_tables = soup.find_all("table")
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
                    match = re.search(r"(图\s*\d+(?:\.\d+)*(?:-\d+)?[^\n]*)", context_text)
                    if not match:
                        match = re.search(r"(表\s*\d+(?:\.\d+)*(?:-\d+)?[^\n]*)", context_text)
                    if match:
                        context_text = match.group(1).strip()
                        if " / " in context_text:
                            context_text = context_text.split(" / ")[0].strip()
                        context_text = re.sub(r"[)\]）】〉》>]+$", "", context_text).strip()
            if context_text and len(context_text) > 200:
                context_text = context_text[-200:]
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
        
        # 优先选择 Context 中包含查询条件值的表格
        condition_values = []
        if conditions:
            for v in conditions.values():
                if isinstance(v, str) and len(v) > 1:
                     condition_values.append(str(v))

        def score_candidate(cand):
            score = 0
            ctx = cand.get("context", "")
            for val in condition_values:
                if val in ctx:
                    score += 10
            # Also prefer if table name is in context
            if table_name in ctx:
                score += 5
            return score

        # Sort candidates by score descending
        candidates.sort(key=score_candidate, reverse=True)

        target_table = None
        name_norm = _normalize_text(table_name)
        name_words = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", table_name)
        kind_token = "图" if "图" in table_name else ("表" if "表" in table_name else None)
        markdown_candidates = [c for c in candidates if c.get("type") == "markdown"]
        html_candidates = [c for c in candidates if c.get("type") == "html"]
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
            return {"error": f"未找到匹配表格: {table_name}"}

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
            return {"error": "查询条件为空", "_table_name": table_name, "_table_context": target_table["context"], "_table_headers": headers}

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
                    col_idx = _find_column_index(headers, k, [k])
                    if col_idx is not None and col_idx < len(row):
                        cell_text = _normalize_text(row[col_idx])
                        cond_text = _normalize_text(v)
                        if cond_text not in cell_text: # 模糊匹配
                            match = False
                            break
                    # 如果找不到列，暂时忽略该文本条件？或者视为不匹配？
                    # 这是一个策略选择。为了鲁棒性，如果列名不匹配，我们尝试在全行中搜索文本
                    elif col_idx is None:
                        row_str = " ".join(row)
                        if _normalize_text(v) not in _normalize_text(row_str):
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
                 return {"error": "数值条件无法匹配任何行", "_table_name": table_name}
        else:
            # 如果没有列条件（只有文本条件或Header Lookup），默认取第一行（如果有文本筛选）
            # 或者如果 Header Lookup 存在，我们可能不需要特定行（如果表只有一行数据？）
            if rows_to_scan:
                best_row = rows_to_scan[0]

        if not best_row:
             return {"error": "无法确定目标行", "_table_name": table_name}

        # 5. 确定目标列 (Target Column)
        final_target_col_idx = None
        
        # 5.1 如果显式指定了 target_column
        if target_column:
            final_target_col_idx = _find_column_index(headers, target_column, [target_column])
        
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

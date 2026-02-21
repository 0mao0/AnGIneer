import os
import re
import json
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from src.tools.BaseTool import BaseTool, register_tool
from src.config import KNOWLEDGE_DIR


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
    match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", t)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    match = re.search(r"(?:≤|<=)\s*(\d+(?:\.\d+)?)", t)
    if match:
        return (float("-inf"), float(match.group(1)))
    match = re.search(r"(?:≥|>=)\s*(\d+(?:\.\d+)?)", t)
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
        print(f"  [表格查询] 正在查找表格 '{table_name}'，查询条件: {query_conditions}，来源: {file_name}")
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
            candidates.append({
                "html": table_html,
                "context": context_text,
                "index": idx,
                "table": tbl
            })

        target_table = None
        name_norm = _normalize_text(table_name)
        name_words = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", table_name)
        for cand in candidates:
            ctx_norm = _normalize_text(cand["context"])
            if name_norm and name_norm in ctx_norm:
                target_table = cand
                trace.append("表格选择策略: 规范化上下文全匹配")
                break
        
        if not target_table:
            for cand in candidates:
                ctx = cand["context"] or ""
                if any(w and w in ctx for w in name_words):
                    target_table = cand
                    trace.append("表格选择策略: 上下文关键词部分匹配")
                    break
        
        if not target_table:
            for cand in candidates:
                if table_name in cand["html"]:
                    target_table = cand
                    trace.append("表格选择策略: HTML 内容包含表名")
                    break

        if not target_table:
            return {"error": f"未找到匹配表格: {table_name}"}

        headers = _parse_table_headers(target_table["table"])
        rows = _parse_table_rows(target_table["table"])
        trace.append(f"匹配表名: {table_name}")
        trace.append(f"匹配表格上下文: {target_table['context']}")
        trace.append(f"解析表头: {headers}")

        conditions = _parse_query_conditions(query_conditions)
        if not conditions:
            return {"error": "查询条件为空或无法解析"}
        key, raw_value = next(iter(conditions.items()))
        target_value = _extract_first_number(str(raw_value))
        if target_value is None:
            return {"error": f"无法解析查询值: {raw_value}"}
        trace.append(f"查询条件解析: {key}={target_value}")

        key_index = _find_column_index(headers, key, ["DWT", "吨级", "船舶吨级"])
        if key_index is None:
            return {"error": f"未找到查询列: {key}"}
        target_index = None
        if target_column:
            target_index = _find_column_index(headers, target_column, [target_column])
        if target_column and target_index is None:
            return {"error": f"未找到目标列: {target_column}"}

        data = []
        range_items = []
        for row in rows:
            if key_index >= len(row):
                continue
            key_text = row[key_index]
            range_value = _parse_range(key_text)
            x_value = _extract_first_number(key_text)
            if x_value is None and range_value is None:
                continue
            if target_index is None:
                if x_value is None:
                    continue
                data.append((x_value, row))
                continue
            if target_index >= len(row):
                continue
            y_value = _extract_first_number(row[target_index])
            if y_value is None:
                continue
            if x_value is not None:
                data.append((x_value, y_value, row))
            if range_value is not None:
                range_items.append((range_value[0], range_value[1], y_value, row, x_value))

        if not data and not range_items:
            return {"error": "表格数据为空或无法解析"}

        if target_index is None:
            data_sorted = sorted(data, key=lambda x: x[0])
            nearest = min(data_sorted, key=lambda x: abs(x[0] - target_value))
            row_data = nearest[1]
            result_map = {headers[i]: row_data[i] if i < len(row_data) else "" for i in range(len(headers))}
            trace.append(f"匹配最近档位: {nearest[0]}")
            result = {"result": result_map, "method": "nearest"}
        else:
            data_sorted = sorted(data, key=lambda x: x[0])
            range_candidates = [item for item in range_items if item[0] <= target_value <= item[1]]
            hit = None
            if range_candidates:
                hit = range_candidates[0]
            if hit:
                trace.append(f"命中区间行: {hit[0]}-{hit[1]}")
                result = {"result": hit[2], "method": "direct_range_lookup"}
            else:
                exact = next((item for item in data_sorted if abs(item[0] - target_value) < 1e-6), None)
                if exact:
                    trace.append(f"命中档位: {exact[0]}")
                    result = {"result": exact[1], "method": "direct_lookup"}
                else:
                    lower = max((item for item in data_sorted if item[0] < target_value), default=None, key=lambda x: x[0])
                    upper = min((item for item in data_sorted if item[0] > target_value), default=None, key=lambda x: x[0])
                    if not lower or not upper:
                        return {"error": "查询值超出表格范围，无法插值"}
                    y_value = lower[1] + (target_value - lower[0]) * (upper[1] - lower[1]) / (upper[0] - lower[0])
                    y_value = round(y_value, 1)
                    trace.append(f"上下区间: {lower[0]}->{upper[0]}")
                    trace.append(f"区间值: {lower[1]}->{upper[1]}")
                    trace.append(f"线性插值结果: {y_value}")
                    result = {"result": y_value, "method": "interpolation"}

        result["_source_html"] = target_table["html"]
        result["_table_name"] = table_name
        result["_table_headers"] = headers
        result["_table_context"] = target_table["context"]
        result["_trace"] = trace
        return result

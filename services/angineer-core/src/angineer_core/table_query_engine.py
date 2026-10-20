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


def _domain_column_aliases() -> Dict[str, List[str]]:
    """领域包里的表头别名（吨级→载重吨DWT(t) 等）；未启用领域包时为空。"""
    try:
        from angineer_core.sop_domain import load_domain_pack_from_env

        return load_domain_pack_from_env().table_column_aliases or {}
    except Exception:  # noqa: BLE001 领域包只做提示，不能挡住查表
        return {}


def _condition_synonyms(
    key: str, aliases: Optional[Dict[str, List[str]]] = None
) -> List[str]:
    """领域别名 + 条件键本身；别名优先。

    别名优先的原因：单字母键（T）若先匹配会把「载重吨DWT(t)」里的 t 当成吃水列；
    「满载吃水」这类领域别名先命中真正的列。
    """
    mapping = aliases if aliases is not None else _domain_column_aliases()
    out: List[str] = []
    for alias in mapping.get(key, []) or []:
        alias = str(alias)
        if alias and alias not in out:
            out.append(alias)
    if key and key not in out:
        out.append(key)
    return out


def _expand_duplicate_headers(
    headers: List[str], rows: List[List[Any]]
) -> tuple:
    """重复表头 + 首行是子表头时，把子表头并进列名并移除该行。

    canonical 解析会把「船舶主要尺度(m)」的 4 个子列压成 4 个同名列，子表头
    （总长L/型宽B/型深H/满载吃水T）落进 body 首行。不展开就分不清哪列是 T。
    仅当表头有重复且首行全为非数值文本时启用，避免误吃正常文本数据行。
    """
    if not headers or not rows or len(set(headers)) == len(headers):
        return headers, rows
    first = rows[0]
    if not isinstance(first, (list, tuple)) or len(first) < len(headers):
        return headers, rows
    if any(_extract_first_number(cell) is not None for cell in first):
        return headers, rows
    effective: List[str] = []
    changed = False
    for i, header in enumerate(headers):
        sub = str(first[i]) if i < len(first) else ""
        if headers.count(header) > 1 and sub and sub != header:
            effective.append(f"{header} {sub}")
            changed = True
        else:
            effective.append(header)
    if not changed:
        return headers, rows
    return effective, list(rows[1:])


def _normalize_text(text: str) -> str:
    """标准化文本用于匹配。"""
    return re.sub(r"\s+", "", (text or "")).lower()


_LATEX_GREEK_MAP = {
    "gamma": "γ", "lambda": "λ", "phi": "φ", "varphi": "φ", "mu": "μ",
    "alpha": "α", "beta": "β", "theta": "θ", "sigma": "σ", "delta": "δ",
    "epsilon": "ε", "varepsilon": "ε", "omega": "ω", "rho": "ρ", "eta": "η",
    "tau": "τ", "pi": "π", "nu": "ν", "kappa": "κ", "psi": "ψ", "zeta": "ζ",
    "chi": "χ", "xi": "ξ", "Delta": "Δ", "Psi": "Ψ", "Phi": "Φ",
    "Sigma": "Σ", "Omega": "Ω", "Theta": "Θ",
}


def _strip_latex_symbols(text: str) -> str:
    """剥离 LaTeX 记号（\\gamma→γ、$_{}$ 等），供表头/目标列名做符号不敏感比对。

    2026-10-18 实踩：目标列「水平波浪力分项系数γP」与表头「水平波浪力分项系数
    $\\gamma_{P}$」归一化后不相等（γp vs $\\gamma_{p}$）→ 目标列解析失败 → 引擎
    回落「成对列」兜底，取到相邻的稳定情况列（返回「抗滑」字符串）。
    """
    t = str(text or "")
    t = re.sub(r"\\(?:mathrm|text|mathbf|mathit|mathbf|operatorname)\s*\{([^{}]*)\}", r"\1", t)
    t = re.sub(r"\\([A-Za-z]+)", lambda m: _LATEX_GREEK_MAP.get(m.group(1), m.group(1)), t)
    for ch in "$_{}^\\":
        t = t.replace(ch, "")
    t = re.sub(r"\s+", "", t)
    return t.lower()


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


def _is_numeric_condition_value(value: Any) -> bool:
    """判断条件值是否为数值型；含中文的一律按文本处理。

    2026-10-18 实踩：'抛填2层'（文本值含数字）被 _extract_first_number 归为数值条件，
    过滤时以 2.0 参与列匹配 → 行条件静默失效（表4.3.7 护面块体造型过滤全灭）。
    """
    s = str(value).strip()
    if not s:
        return False
    if re.search(r"[\u4e00-\u9fff]", s):
        return False
    return _extract_first_number(s) is not None


_LEADING_RANGE_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)?\s*(?:[~～—–]|至|-|≤|<=|≥|>=|<|>)|[≤<≥>=])"
)


def _cell_condition_distance(cell_text: Any, target_val: float) -> Optional[float]:
    """单元格与数值条件的距离；无法解析返回 None。

    区间语义仅当区间符号紧跟开头数字时启用：
    - '3.1~3.5' → 区间 (3.1, 3.5)，命中返回 0，否则按边界距离 ×10；
    - '5000(4501~7500)' 这类「首数+括号区间」必须仍按首数 5000 处理（旧口径），
      否则会把括号里的子区间当成本格数值（2026-10-18 表4.3.24 配对选行实踩：
      旧逻辑先取首数，区间命中恒不可达 → 横向成对表恒选错行）。
    """
    if cell_text is None:
        return None
    t = str(cell_text).strip()
    if not t:
        return None
    if _LEADING_RANGE_RE.match(t):
        rng = _parse_range(t)
        if rng:
            if rng[0] <= target_val <= rng[1]:
                return 0.0
            return min(abs(target_val - rng[0]), abs(target_val - rng[1])) * 10
    num = _extract_first_number(t)
    if num is None:
        return None
    return abs(num - target_val)


_DIMENSION_PATTERNS = ['航速', '水深', '波长', '周期']


def _match_header_variant(header: str, candidate: str) -> bool:
    """表头与候选列名的变体匹配（含 LaTeX 符号剥离变体）；维度标注列直接跳过。"""
    header_norm = _normalize_text(header)
    if any(dim in header_norm for dim in _DIMENSION_PATTERNS) and not re.search(r'\d', header):
        return False
    cand_variants = _expand_match_variants(candidate)
    for extra in _expand_match_variants(_strip_latex_symbols(candidate)):
        if extra and extra not in cand_variants:
            cand_variants.append(extra)
    header_variants = [header_norm]
    stripped_header = _strip_latex_symbols(header)
    if stripped_header and stripped_header != header_norm:
        header_variants.append(stripped_header)
    for cand_norm in cand_variants:
        if not cand_norm:
            continue
        for header_variant in header_variants:
            if cand_norm in header_variant or header_variant in cand_norm:
                return True
    return False


def _find_column_index(headers: List[str], key: str, synonyms: Optional[List[str]] = None) -> Optional[int]:
    """在表头中匹配列索引。跳过维度标注列（如"船舶航速（kn）"）。"""
    if not headers or not key:
        return None

    candidates = list(synonyms or [])
    if key and key not in candidates:
        candidates.append(key)
    for candidate in candidates:
        for idx, header in enumerate(headers):
            if _match_header_variant(header, candidate):
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


def _find_column_indices_strict(headers: List[str], key: str, synonyms: Optional[List[str]] = None) -> List[int]:
    """变体匹配的重复列组（不含 key_parts 单字母兜底，避免误含大量无关列）。

    用途：成对列校正的目标列候选（2026-10-18 实踩：'型宽B(m)' 若走 key_parts 兜底
    会命中所有含 m 的列 → 校正误把目标挪去 总长L(m)）。
    """
    if not headers or not key:
        return []
    candidates = list(synonyms or [])
    if key and key not in candidates:
        candidates.append(key)
    return [
        idx for idx, header in enumerate(headers)
        if any(_match_header_variant(header, candidate) for candidate in candidates)
    ]


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
        if not _is_numeric_condition_value(value):
            continue
        parsed = _extract_first_number(str(value))
        if parsed is not None:
            numeric_targets.append(parsed)
    if not numeric_targets:
        return 0
    headers = cand.get("headers") or []
    rows = cand.get("rows") or []
    tonnage_col = _find_column_index(headers, "吨级", _condition_synonyms("吨级"))
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


def _probe_range_candidates(
    candidates: List[Dict[str, Any]],
    table_name: str,
    conditions: Dict[str, Any],
    aliases: Optional[Dict[str, List[str]]] = None,
) -> List[Dict[str, Any]]:
    """范围表名（X~Y）：按序探测哪张候选表能真正匹配到行，返回可行表（保序）。

    背景（2026-10-14 评测实踩）：范围表名会把多张子表评分并列（ref 280），旧逻辑只取
    分最高一张——选中渡船表后文本条件全灭（无「散货船」行）→「未找到符合文本条件的行」
    → 参数取不到 → SOP 整链缺参拒答。这里用与主流程同语义的文本/数值可行性预探测重排。
    """
    text_conditions: Dict[str, Any] = {}
    numeric_conditions: Dict[str, Any] = {}
    for k, v in (conditions or {}).items():
        if _is_numeric_condition_value(v):
            numeric_conditions[k] = v
        else:
            text_conditions[k] = str(v)
    feasible: List[Dict[str, Any]] = []
    for cand in candidates:
        if _range_candidate_has_rows(
            cand.get("headers") or [],
            cand.get("rows") or [],
            cand.get("context") or "",
            table_name,
            text_conditions,
            numeric_conditions,
            aliases,
        ):
            feasible.append(cand)
    return feasible


def _range_candidate_has_rows(
    headers: List[str],
    rows: List[List[Any]],
    context: str,
    table_name: str,
    text_conditions: Dict[str, Any],
    numeric_conditions: Dict[str, Any],
    aliases: Optional[Dict[str, List[str]]] = None,
) -> bool:
    """可行性探测：与主流程同语义的文本过滤 + 数值列可解析性检查（只看有没有，不算距离）。"""
    filtered = rows
    if text_conditions:
        filtered = []
        for row in rows:
            ok = True
            for k, v in text_conditions.items():
                col_indices = _find_column_indices(headers, k, _condition_synonyms(k, aliases))
                if col_indices:
                    if not any(idx < len(row) and _text_condition_matches(row[idx], v) for idx in col_indices):
                        ok = False
                        break
                else:
                    if _detect_table_range(table_name):
                        continue
                    if _text_condition_matches(context, v):
                        continue
                    if not _text_condition_matches(" ".join(str(c) for c in row), v):
                        ok = False
                        break
            if ok:
                filtered.append(row)
    if not filtered:
        return False
    for k in numeric_conditions:
        idxs = _find_column_indices(headers, k, _condition_synonyms(k, aliases))
        if not idxs:
            continue
        if not any(
            any(idx < len(row) and (_extract_first_number(row[idx]) is not None or _parse_range(row[idx])) for idx in idxs)
            for row in filtered
        ):
            return False
    return True


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


_TABLE_NUMBER_REF_PATTERN = re.compile(r"^表\s*[A-Za-z]?(?:[.\-]?\d+)+$")


def _is_table_number_ref(table_name: str) -> bool:
    """表号形态（表5.4.8 / 表 A.0.1 / 表5.4.8-1）：选择必须靠编号精确对应，禁用宽松兜底。

    2026-10-12 实踩：错文档无此表号时，拆词兜底（["表","5","4","8"] 中「表」字命中一切
    表格 context）会静默抓回无关表，把「找不到表」伪装成「行条件不匹配」。
    """
    return bool(_TABLE_NUMBER_REF_PATTERN.match(str(table_name or "").strip()))


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
        headers, body_rows = _expand_duplicate_headers(
            list(headers or []), list(cand.get("rows") or [])
        )
        normalized_candidates.append({
            "headers": headers,
            "rows": body_rows,
            "context": cand.get("context") or "",
            "index": idx,
            "doc_id": cand.get("doc_id"),
            "page_idx": cand.get("page_idx"),
        })

    conditions = _parse_query_conditions(query_conditions)
    aliases = _domain_column_aliases()

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
        # 范围表名（X~Y）并列 280 分时不能只取分最高一张：按「能否真正匹配到行」探测重排
        # （2026-10-14 实踩：表A.0.2-1~14 选中渡船表 → 文本条件全灭 → SOP 整链缺参拒答）。
        if len(explicit_candidates) > 1 and _detect_table_range(table_name):
            feasible = _probe_range_candidates(explicit_candidates, table_name, conditions, aliases)
            if feasible and feasible[0] is not target_table:
                target_table = feasible[0]
                trace.append("表格选择策略: 范围表名按行匹配可行性重选")
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
    if not target_table and _is_table_number_ref(table_name):
        return {
            "error": f"scope 内 {len(normalized_candidates)} 个表格块均无编号『{table_name}』",
            "_table_name": table_name,
            "_diagnostic_info": {
                "total_candidates": len(normalized_candidates),
                "candidate_contexts": [
                    str(cand.get("context") or "")[:60] for cand in normalized_candidates[:8]
                ],
                "suggestions": [
                    "确认目标文档与表号属于同一版本（分册号/年份），以及 file_name/scope 指向正确文档",
                    "确认该文档已解析入库且表格标题被正确捕获",
                ],
            },
        }
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

    # 分离文本和数值条件（含中文的值一律按文本处理，见 _is_numeric_condition_value）
    numeric_conditions = {}
    text_conditions = {}
    for k, v in conditions.items():
        if _is_numeric_condition_value(v):
            numeric_conditions[k] = _extract_first_number(str(v))
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
                col_indices = _find_column_indices(headers, k, _condition_synonyms(k, aliases))
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

    # 数值条件处理（多条件最佳匹配；同一条件键可命中多个成对列，按该行最近的一列取距离）
    col_cond_groups: Dict[str, Dict[str, Any]] = {}  # key -> {"cols": [...], "value": num}
    col_conditions: Dict[int, float] = {}  # col_idx -> target_value（供目标列推断排除用）
    header_lookup_conditions = {}  # key -> target_value（没找到列名的）

    for k, v in numeric_conditions.items():
        cols = _find_column_indices(headers, k, _condition_synonyms(k, aliases))
        if cols:
            col_cond_groups[k] = {"cols": cols, "value": v}
            for c in cols:
                col_conditions[c] = v
            trace.append(f"条件列匹配: {k} -> Col {','.join(str(c) for c in cols)}, Val {v}")
        else:
            header_lookup_conditions[k] = v
            trace.append(f"条件列未匹配(可能是表头查找): {k}={v}")

    best_row = None
    numeric_match_cols: Dict[str, int] = {}  # key -> 命中行上实际用于判距的列

    if col_cond_groups:
        scored_rows = []
        for row in rows_to_scan:
            dist = 0.0
            valid = True
            row_choice: Dict[str, int] = {}
            for k, info in col_cond_groups.items():
                best_cell_dist = None
                best_cell_col = None
                for c in info["cols"]:
                    if c >= len(row):
                        continue
                    d = _cell_condition_distance(row[c], info["value"])
                    if d is None:
                        continue
                    if best_cell_dist is None or d < best_cell_dist:
                        best_cell_dist = d
                        best_cell_col = c
                if best_cell_col is None:
                    valid = False
                    break
                row_choice[k] = best_cell_col
                dist += best_cell_dist
            if valid:
                scored_rows.append((dist, row, row_choice))

        if scored_rows:
            scored_rows.sort(key=lambda x: x[0])
            best_dist, best_row, numeric_match_cols = scored_rows[0]
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
        final_target_col_idx = _find_column_index(headers, target_column, _condition_synonyms(target_column, aliases))

        # 成对列校正：目标列名在表头出现多次（重复列组）时，必须取「条件命中列」的
        # 配对列（j+1），否则会取到另一组同名列（2026-10-18 表4.3.24 实踩：
        # 右半区 Vmax 命中第 2 组，目标「护底块石稳定重量W」却解析到第 1 组列）。
        target_col_candidates = _find_column_indices_strict(headers, target_column, _condition_synonyms(target_column, aliases))
        if len(target_col_candidates) > 1:
            matched_cols: List[int] = []
            for key, value in text_conditions.items():
                for idx in _find_column_indices(headers, key, _condition_synonyms(key, aliases)):
                    if idx < len(best_row) and _text_condition_matches(best_row[idx], value):
                        matched_cols.append(idx)
            matched_cols.extend(numeric_match_cols.values())
            for m in matched_cols:
                if m + 1 in target_col_candidates:
                    final_target_col_idx = m + 1
                    trace.append(f"成对列目标列校正: {m} -> {m + 1}（{headers[m + 1]}）")
                    break

    # 对 "条件列-结果列" 成对出现的横向表，优先返回命中的相邻数值列
    if final_target_col_idx is None and text_conditions:
        for key, value in text_conditions.items():
            candidate_indices = _find_column_indices(headers, key, _condition_synonyms(key, aliases))
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
            idx = _find_column_index(headers, k, _condition_synonyms(k, aliases))
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

    if target_column and final_target_col_idx is None:
        return {
            "error": f"目标列未匹配: {target_column}",
            "_table_name": table_name,
            "_table_headers": headers,
            "_trace": trace,
        }

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

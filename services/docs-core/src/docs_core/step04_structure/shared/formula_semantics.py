"""公式结构化提取工具（step04 enrich：04 生产落 jsonl，05 对 popo 块透传、对 solo 块规则兜底）。

语义层契约：输入 ``CanonicalBlock``（block_type=="formula"）及其下文解释段
（section_path + reading_order 邻近定位），输出 ``FormulaSemanticsContract``。
契约挂 ``CanonicalBlock.formula_semantics`` 旁路字段（构建期）；
graph node meta / derived_rows 的最终挂载点由后续统一投影确定。
"""
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING, TypedDict

from docs_core.models.types import CanonicalBlock

if TYPE_CHECKING:
    from ai_inference.llm_client import LLMClient


FORMULA_NUMBER_RE = re.compile(
    r"[（(](\d+(?:\.\d+)*(?:-\d+)?)[）)]|\\tag\{(\d+(?:\.\d+)*(?:-\d+)?)\}"
)
FORMULA_PARAM_SYMBOL_RE = r"[A-Za-zΑ-Ωα-ω\\][A-Za-z0-9_{}^()\\/.\-']{0,20}"
FORMULA_PARAM_RE = re.compile(
    rf"^\s*({FORMULA_PARAM_SYMBOL_RE})\s*(?:[—–\-一]{{1,3}}|:=|=|：|:)\s*(.+?)\s*$"
)
FORMULA_PARAM_SOFT_RE = re.compile(rf"^\s*({FORMULA_PARAM_SYMBOL_RE})\s+(.+?)\s*$")
REFERENCE_HINT_RE = re.compile(r"(采用[^；。]*|按[^；。]*|取[^；。]*|见[^；。]*|按表[^；。]*)")
UNIT_RE = re.compile(r"[（(]([^()（）]{1,20})[）)]")
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_SUBSCRIPT_RE = re.compile(r"_\s*(\{[^{}]*\}|[A-Za-z0-9]+)")
_SYMBOL_ARG_COMMANDS = {
    "mathrm",
    "text",
    "mathit",
    "mathbf",
    "pmb",
    "boldsymbol",
    "bm",
    "mbox",
    "operatorname",
}


class FormulaParamContract(TypedDict):
    """公式参数语义契约。"""

    symbol: str
    description: str
    unit: Optional[str]
    reference_hint: Optional[str]
    confidence: float
    extracted_by: str


class FormulaSemanticsContract(TypedDict):
    """公式语义图契约。"""

    formula_text: str
    formula_number: Optional[str]
    formula_params: List[FormulaParamContract]
    formula_param_count: int
    formula_summary: str
    llm_status: str
    explanation_lines: List[str]


# 清洗公式相关文本，避免空白和尾部标点干扰规则识别。
def clean_formula_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    return normalized.strip("；;")


# 从公式正文或说明文本中提取公式编号。
def extract_formula_number(formula_text: str, explanation_lines: List[str]) -> Optional[str]:
    search_candidates = [clean_formula_text(formula_text), *[clean_formula_text(line) for line in explanation_lines]]
    for candidate in search_candidates:
        if not candidate:
            continue
        match = FORMULA_NUMBER_RE.search(candidate)
        if match:
            return match.group(1) or match.group(2)
    return None


# 将说明段拆成便于逐条解析的候选行。
def split_formula_explanation_lines(explanation_lines: List[str]) -> List[str]:
    lines: List[str] = []
    for raw_line in explanation_lines:
        cleaned = clean_formula_text(raw_line)
        if not cleaned:
            continue
        parts = re.split(r"[\r\n]+", cleaned)
        for part in parts:
            text = clean_formula_text(part)
            if not text:
                continue
            sub_parts = re.split(r"[；;]\s*(?=(?:式中|其中|注[:：]?)?\s*[A-Za-zΑ-Ωα-ω\\])", text)
            for sub_part in sub_parts:
                final_text = clean_formula_text(sub_part)
                if final_text:
                    lines.append(final_text)
    return list(dict.fromkeys(lines))


# 识别说明行中的单位信息。
def extract_formula_unit(description: str) -> Optional[str]:
    for match in UNIT_RE.finditer(description):
        unit = clean_formula_text(match.group(1))
        if not unit:
            continue
        if re.search(r"[A-Za-z%°/]|m\d?|kg|kN|MPa|N", unit, re.IGNORECASE) or any(ch in unit for ch in ("m", "kg", "度", "%", "°")):
            return unit
    return None


# 从说明行中提取引用来源或取值提示。
def extract_formula_reference_hint(description: str) -> Optional[str]:
    match = REFERENCE_HINT_RE.search(description)
    if not match:
        return None
    return clean_formula_text(match.group(1))


# 用规则解析单条公式参数说明。
def parse_formula_param_rule(line: str) -> Optional[Dict[str, Any]]:
    candidate = clean_formula_text(line)
    if not candidate:
        return None
    candidate = re.sub(r"^[•·]\s*", "", candidate)
    candidate = re.sub(r"^(?:式中|其中|注)[:：]?\s*", "", candidate)
    match = FORMULA_PARAM_RE.match(candidate)
    if not match:
        soft_match = FORMULA_PARAM_SOFT_RE.match(candidate)
        if soft_match:
            symbol_candidate = clean_formula_text(soft_match.group(1))
            description_candidate = clean_formula_text(soft_match.group(2))
            if (
                symbol_candidate
                and description_candidate
                and re.search(r"[\u4e00-\u9fff(（]", description_candidate)
                and not description_candidate.startswith(("+", "-", "*", "/", "="))
                and not description_candidate.startswith(("_", "{", "\\", "^", "~"))
                and not symbol_candidate.startswith("\\")
            ):
                match = soft_match
    if not match:
        return None

    symbol = clean_formula_text(match.group(1))
    description = clean_formula_text(match.group(2))
    if not symbol or not description:
        return None

    return {
        "symbol": symbol,
        "description": description,
        "unit": extract_formula_unit(description),
        "reference_hint": extract_formula_reference_hint(description),
        "confidence": 0.92,
        "extracted_by": "rule",
    }


# 将模型输出尽量恢复为 JSON 对象。
def parse_formula_llm_json(payload_text: str) -> Optional[Dict[str, Any]]:
    raw = str(payload_text or "").strip()
    if not raw:
        return None
    block_match = JSON_BLOCK_RE.search(raw)
    if block_match:
        raw = block_match.group(1).strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


# 使用 LLM 兜底解析复杂公式说明。
def llm_extract_formula_params(
    formula_text: str,
    explanation_lines: List[str],
    llm_client: Optional["LLMClient"] = None,
    llm_model: Optional[str] = None,
) -> tuple[List[Dict[str, Any]], str]:
    if not llm_client:
        return [], "not_configured"
    if not explanation_lines:
        return [], "empty_context"

    system_prompt = (
        "你是工程规范中的公式说明结构化提取器。"
        "请从公式及其“式中/其中”说明中提取参数项，仅返回 JSON 对象。"
        '输出格式: {"params":[{"symbol":"γ","description":"风、流压缩角","unit":"^circ","reference_hint":"采用表6.4.2-2中的数值","confidence":0.85}]}\n'
        "如果某字段缺失可返回 null；不要输出额外解释。"
    )
    user_prompt = json.dumps(
        {
            "formula_text": clean_formula_text(formula_text),
            "explanation_lines": split_formula_explanation_lines(explanation_lines),
        },
        ensure_ascii=False,
    )

    try:
        result_text = llm_client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            model=llm_model,
        )
        parsed = parse_formula_llm_json(result_text)
        if not parsed:
            return [], "invalid_json"
        raw_params = parsed.get("params")
        if not isinstance(raw_params, list):
            return [], "empty_result"

        params: List[Dict[str, Any]] = []
        for item in raw_params:
            if not isinstance(item, dict):
                continue
            symbol = clean_formula_text(str(item.get("symbol") or ""))
            description = clean_formula_text(str(item.get("description") or ""))
            if not symbol or not description:
                continue
            confidence_raw = item.get("confidence", 0.8)
            confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.8
            params.append(
                {
                    "symbol": symbol,
                    "description": description,
                    "unit": clean_formula_text(str(item.get("unit") or "")) or extract_formula_unit(description),
                    "reference_hint": clean_formula_text(str(item.get("reference_hint") or "")) or extract_formula_reference_hint(description),
                    "confidence": max(0.0, min(1.0, confidence)),
                    "extracted_by": "llm",
                }
            )
        return params, "ok" if params else "empty_result"
    except Exception as error:
        return [], f"error:{str(error)[:60]}"


# 合并规则结果与 LLM 结果，优先保留规则字段。
def merge_formula_params(
    rule_params: List[Dict[str, Any]],
    llm_params: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for item in llm_params + rule_params:
        symbol = clean_formula_text(str(item.get("symbol") or ""))
        if not symbol:
            continue
        existing = merged.get(symbol, {})
        merged[symbol] = {
            "symbol": symbol,
            "description": existing.get("description") or item.get("description"),
            "unit": existing.get("unit") or item.get("unit"),
            "reference_hint": existing.get("reference_hint") or item.get("reference_hint"),
            "confidence": max(float(existing.get("confidence") or 0.0), float(item.get("confidence") or 0.0)),
            "extracted_by": existing.get("extracted_by") or item.get("extracted_by"),
        }
        if existing.get("extracted_by") == "llm" and item.get("extracted_by") == "rule":
            merged[symbol]["extracted_by"] = "rule"
    return list(merged.values())


# 规范化 LaTeX 符号：去掉命令名与花括号/空白，得到可比较的规范形。
def _normalize_symbol_tex(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"\\[A-Za-z]+\s*(\{[^{}]*\})", r"\1", value)
    value = re.sub(r"\\[A-Za-z]+", "", value)
    return re.sub(r"[\s{}_]", "", value)


def _is_symbol_letter(ch: str) -> bool:
    return (
        (ch.isascii() and ch.isalpha())
        or "\u0391" <= ch <= "\u03a9"
        or "\u03b1" <= ch <= "\u03c9"
    )


def _iter_formula_symbol_tokens(formula_text: str):
    """从公式原文提取符号 token（原文片段, 基础符号, 规范形）。

    跳过 LaTeX 命令名与普通命令的花括号参数；\\mathrm/pmb 等“符号承载”命令的
    花括号参数保留参与扫描，避免漏掉加粗/正体的真实符号。
    """
    text = str(formula_text or "")
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 1
            name_start = i
            while i < n and text[i].isalpha():
                i += 1
            cmd = text[name_start:i]
            j = i
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j] == "{" and cmd not in _SYMBOL_ARG_COMMANDS:
                depth = 0
                i = j
                while i < n:
                    if text[i] == "{":
                        depth += 1
                    elif text[i] == "}":
                        depth -= 1
                        if depth == 0:
                            i += 1
                            break
                    i += 1
                continue
            i = j
            continue
        if _is_symbol_letter(ch):
            start = i
            base = ch
            i += 1
            j = i
            while j < n and text[j].isspace():
                j += 1
            sub_raw = ""
            if j < n and text[j] == "_":
                j += 1
                while j < n and text[j].isspace():
                    j += 1
                if j < n and text[j] == "{":
                    depth = 1
                    sub_start = j
                    j += 1
                    while j < n and depth > 0:
                        if text[j] == "{":
                            depth += 1
                        elif text[j] == "}":
                            depth -= 1
                        j += 1
                    sub_raw = text[sub_start:j]
                else:
                    sub_match = re.match(r"[A-Za-z0-9]+", text[j:])
                    if sub_match:
                        j += len(sub_match.group(0))
                        sub_raw = sub_match.group(0)
                i = j
            else:
                i = j
            raw = text[start:i].strip()
            canonical = base + _normalize_symbol_tex(sub_raw)
            yield raw, base, canonical
            continue
        i += 1


def _extract_subscript_tex(symbol: str) -> Optional[str]:
    match = _SUBSCRIPT_RE.search(str(symbol or ""))
    return match.group(1) if match else None


def _rebuild_token_from_param(token_raw: str, param_symbol: str) -> str:
    """用参数符号重建公式 token：基础符号 + 参数下标（原始下标以参数为准）。"""
    param_sub = _extract_subscript_tex(param_symbol)
    base = str(token_raw or "").strip()[:1]
    if param_sub is None:
        return base
    return f"{base}_{param_sub}"


def _build_symbol_corrections(
    formula_text: str,
    params: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """检测公式内符号与参数符号不一致，产出 corrected 修正项。

    参数符号在公式中出现（基础符号一致）但完整规范形不一致时，视为 OCR/排版
    差异（如下标误识），生成 ``math_content_corrected`` 修正项。仅当某个基础
    符号只有一个参数时允许修正（可消歧）；同基础符号多个参数（如 D 与 D_0）
    时跳过，避免把正确符号误改。
    """
    tokens = list(_iter_formula_symbol_tokens(formula_text))
    if not tokens:
        return []
    token_bases = {base for _raw, base, _canonical in tokens}
    canonicals_by_base: Dict[str, set] = {}
    raw_by_base: Dict[str, str] = {}
    for raw, base, canonical in tokens:
        canonicals_by_base.setdefault(base, set()).add(canonical)
        raw_by_base.setdefault(base, raw)
    params_by_base: Dict[str, List[Dict[str, Any]]] = {}
    for param in params or []:
        symbol = clean_formula_text(str(param.get("symbol") or ""))
        if not symbol:
            continue
        normalized = _normalize_symbol_tex(symbol)
        base_match = re.search(r"[A-Za-zΑ-Ωα-ω]", normalized)
        if not base_match:
            continue
        base = base_match.group(0)
        if base not in token_bases:
            continue
        params_by_base.setdefault(base, []).append(
            {"symbol": symbol, "normalized": normalized}
        )
    corrections: List[Dict[str, Any]] = []
    for base, base_params in params_by_base.items():
        if len(base_params) != 1:
            continue
        item = base_params[0]
        if item["normalized"] in canonicals_by_base.get(base, set()):
            continue
        raw_token = raw_by_base.get(base) or ""
        corrections.append(
            {
                "field": "math_content_corrected",
                "symbol": base,
                "original": raw_token,
                "corrected": _rebuild_token_from_param(raw_token, item["symbol"]),
                "reason": f"公式符号 {raw_token} 与参数符号 {item['symbol']} 不一致",
            }
        )
    return corrections


def _should_write_llm_correction(node: Dict[str, Any]) -> bool:
    """用户已修正（corrected_by == "user"）时，semantic 不再覆盖。"""
    return str(node.get("corrected_by") or "").strip().lower() != "user"


def _apply_symbol_replacements(
    text: str,
    corrections: List[Dict[str, Any]],
) -> str:
    result = str(text or "")
    for corr in corrections:
        original = corr.get("original")
        corrected = corr.get("corrected")
        if original and corrected and original in result:
            result = result.replace(original, corrected, 1)
    return result


# 生成公式结构化表示，供结构化索引层消费。
def build_formula_representations(
    formula_text: str,
    explanation_lines: List[str],
    llm_client: Optional["LLMClient"] = None,
    llm_model: Optional[str] = None,
    use_llm: bool = True,
) -> FormulaSemanticsContract:
    cleaned_formula = clean_formula_text(formula_text)
    normalized_lines = split_formula_explanation_lines(explanation_lines)
    formula_number = extract_formula_number(cleaned_formula, normalized_lines)

    rule_params: List[Dict[str, Any]] = []
    unmatched_lines: List[str] = []
    for line in normalized_lines:
        parsed = parse_formula_param_rule(line)
        if parsed:
            rule_params.append(parsed)
        else:
            unmatched_lines.append(line)

    llm_params: List[Dict[str, Any]] = []
    llm_status = "disabled"
    if use_llm:
        if not normalized_lines:
            llm_status = "not_needed"
        else:
            llm_params, llm_status = llm_extract_formula_params(
                formula_text=cleaned_formula,
                explanation_lines=normalized_lines,
                llm_client=llm_client,
                llm_model=llm_model,
            )

    formula_params = merge_formula_params(rule_params, llm_params)
    summary = cleaned_formula or "未命名公式"
    if formula_number:
        summary = f"公式({formula_number}) {summary}"
    if formula_params:
        symbols = ", ".join(item["symbol"] for item in formula_params[:8])
        summary = f"{summary}；包含 {len(formula_params)} 个参数：{symbols}"

    return {
        "formula_text": cleaned_formula,
        "formula_number": formula_number,
        "formula_params": formula_params,
        "formula_param_count": len(formula_params),
        "formula_summary": summary,
        "llm_status": llm_status,
        "explanation_lines": normalized_lines,
    }


# 从公式块下文定位解释段（section_path + reading_order 邻近）。公式后紧跟的
# 同节段落优先，可跨一页取邻近段。
def _iter_canonical_explanation_blocks(
    block: "CanonicalBlock",
    following_blocks: Optional[List["CanonicalBlock"]] = None,
    max_lines: int = 8,
):
    """?????????? (block, text) ??????? uid ?????"""
    if block is None:
        return
    count = 0
    for nb in following_blocks or []:
        if count >= max_lines:
            break
        if nb.block_type == "formula":
            continue
        if nb.block_type not in {"paragraph", "list_item"}:
            continue
        same_section = (nb.section_path == block.section_path) or not nb.section_path
        nearby = abs(int(nb.page_idx or 0) - int(block.page_idx or 0)) <= 1
        if not (same_section and nearby):
            continue
        text = clean_formula_text(nb.text or nb.text_clean or "")
        if not text:
            continue
        count += 1
        yield nb, text


def collect_canonical_explanation_lines(
    block: "CanonicalBlock",
    following_blocks: Optional[List["CanonicalBlock"]] = None,
    max_lines: int = 8,
) -> List[str]:
    if block is None:
        return []
    return [text for _nb, text in _iter_canonical_explanation_blocks(block, following_blocks, max_lines)]


def _collect_explanation_block_uids(
    block: "CanonicalBlock",
    following_blocks: Optional[List["CanonicalBlock"]] = None,
    max_lines: int = 8,
) -> List[str]:
    """??????????? uid????? explanation_uids ? explanation_lines ???"""
    return [nb.block_id for nb, _text in _iter_canonical_explanation_blocks(block, following_blocks, max_lines)]



# 语义层后端无关入口：输入公式块（type=="formula"）及其下文解释段，产出
# FormulaSemanticsContract，不依赖任何后端内部格式。
def enrich_formula_block(
    block: "CanonicalBlock",
    blocks: Optional[List["CanonicalBlock"]] = None,
    *,
    llm_client: Optional["LLMClient"] = None,
    llm_model: Optional[str] = None,
    use_llm: bool = False,
) -> FormulaSemanticsContract:
    if block is None or block.block_type != "formula":
        return {
            "formula_text": "",
            "formula_number": None,
            "formula_params": [],
            "formula_param_count": 0,
            "formula_summary": "",
            "llm_status": "skipped",
            "explanation_lines": [],
        }
    following: List["CanonicalBlock"] = []
    if blocks:
        ordered = sorted(blocks, key=lambda item: (item.page_idx, item.reading_order))
        start = next(
            (i for i, item in enumerate(ordered) if item.block_id == block.block_id),
            None,
        )
        if start is not None:
            following = ordered[start + 1:]
    explanation_lines = collect_canonical_explanation_lines(block, following)
    return build_formula_representations(
        formula_text=block.text or block.text_clean or "",
        explanation_lines=explanation_lines,
        llm_client=llm_client,
        llm_model=llm_model,
        use_llm=use_llm,
    )


def enrich_blocks_formula_semantics(
    blocks: List["CanonicalBlock"],
    *,
    use_llm: bool = False,
    llm_client: Optional["LLMClient"] = None,
    llm_model: Optional[str] = None,
) -> List["CanonicalBlock"]:
    """blocks 级公式语义增强：按 (page_idx, reading_order) 排序，仅 formula 块计算契约。"""
    ordered = sorted(blocks, key=lambda item: (item.page_idx, item.reading_order))
    contracts: dict[str, dict] = {}
    for block in ordered:
        if block.block_type == "formula":
            contracts[block.block_id] = enrich_formula_block(
                block,
                ordered,
                llm_client=llm_client,
                llm_model=llm_model,
                use_llm=use_llm,
            )
    return [
        block.model_copy(update={"formula_semantics": contracts[block.block_id]})
        if block.block_id in contracts
        else block
        for block in blocks
    ]


_NODE_TYPE_ALIASES = {
    "equation": "formula",
    "equation_interline": "formula",
    "inline_formula": "formula",
    "index": "toc",
    "list": "list_item",
}
_CANONICAL_BLOCK_TYPES = {
    "title", "paragraph", "list_item", "table", "table_caption", "figure",
    "figure_caption", "header_footer", "footnote", "formula", "toc", "unknown",
}


def _node_to_canonical_block(node: Dict[str, Any]) -> CanonicalBlock:
    block_type = _NODE_TYPE_ALIASES.get(
        str(node.get("block_type") or ""), str(node.get("block_type") or "unknown")
    )
    if block_type not in _CANONICAL_BLOCK_TYPES:
        block_type = "unknown"
    return CanonicalBlock(
        block_id=str(node.get("block_uid") or node.get("id") or ""),
        doc_id="",
        page_idx=int(node.get("page_idx") or 0),
        block_type=block_type,
        text=str(node.get("math_content") or node.get("plain_text") or ""),
        text_clean=str(node.get("plain_text") or ""),
        reading_order=int(node.get("block_seq") or 0),
        section_path=str(node.get("title_path") or ""),
    )


def _resolve_explanation_lines(
    node: Dict[str, Any],
    block: CanonicalBlock,
    ordered: List[CanonicalBlock],
    nodes_by_uid: Dict[str, Dict[str, Any]],
) -> List[str]:
    linked = node.get("explanation_uids")
    idx = ordered.index(block)
    rederived = collect_canonical_explanation_lines(block, ordered[idx + 1:])
    if not isinstance(linked, list) or not linked:
        return rederived
    linked_lines: List[str] = []
    for uid in linked:
        text = str(nodes_by_uid.get(str(uid), {}).get("plain_text") or "").strip()
        if text:
            linked_lines.append(text)
    # 并集：04 现场关联优先，重定位补充（避免关联不完整反而减少上下文）
    seen = set(linked_lines)
    merged = list(linked_lines)
    for line in rederived:
        if line not in seen:
            merged.append(line)
            seen.add(line)
    return merged


def enrich_graph_nodes_formula_semantics(
    nodes: List[Dict[str, Any]],
    *,
    use_llm: bool = False,
    llm_client: Optional["LLMClient"] = None,
    llm_model: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """04 建块后、落 jsonl 前调用：给公式节点计算并写入 formula_semantics。

    解释段优先读节点 ``explanation_uids``（solo_engine 公式组关联产出），
    缺失时回退到 section_path+邻近重定位。
    """
    stats: Dict[str, Any] = {
        "total_formulas": 0,
        "enriched": 0,
        "llm_status": "disabled",
        "symbol_corrections": 0,
    }
    if not nodes:
        return nodes, stats

    nodes_by_uid = {str(n.get("block_uid") or n.get("id") or ""): n for n in nodes}
    blocks = [_node_to_canonical_block(n) for n in nodes]
    ordered = sorted(blocks, key=lambda b: (b.page_idx, b.reading_order))
    formula_blocks = [b for b in ordered if b.block_type == "formula"]
    stats["total_formulas"] = len(formula_blocks)
    if not formula_blocks:
        return nodes, stats

    updated = [dict(n) for n in nodes]
    updated_by_uid = {str(n.get("block_uid") or n.get("id") or ""): n for n in updated}
    block_by_uid = {b.block_id: b for b in ordered}
    statuses: List[str] = []

    for block in formula_blocks:
        node = nodes_by_uid.get(block.block_id) or {}
        explanation_lines = _resolve_explanation_lines(node, block, ordered, nodes_by_uid)
        contract = build_formula_representations(
            formula_text=block.text,
            explanation_lines=explanation_lines,
            llm_client=llm_client,
            llm_model=llm_model,
            use_llm=use_llm,
        )
        corrections = _build_symbol_corrections(
            block.text,
            contract.get("formula_params") or [],
        )
        if corrections and _should_write_llm_correction(node):
            corrected_math = _apply_symbol_replacements(block.text, corrections)
            updated_by_uid[block.block_id]["math_content_corrected"] = corrected_math
            raw_plain = str(node.get("plain_text") or "")
            if raw_plain.strip():
                corrected_plain = _apply_symbol_replacements(raw_plain, corrections)
                if corrected_plain != raw_plain:
                    updated_by_uid[block.block_id]["plain_text_corrected"] = corrected_plain
            updated_by_uid[block.block_id]["symbol_mismatch"] = True
            updated_by_uid[block.block_id]["corrected_by"] = "llm"
            updated_by_uid[block.block_id]["corrected_at"] = datetime.now().isoformat()
            stats["symbol_corrections"] += 1
        updated_by_uid[block.block_id]["formula_semantics"] = contract
        # 回写 explanation_uids：04 现场关联 + 重定位并集，保证前端联动与语义内容一致
        idx = ordered.index(block)
        linked_uids = [str(u) for u in (node.get("explanation_uids") or []) if str(u)]
        rederived_uids = _collect_explanation_block_uids(block, ordered[idx + 1:])
        merged_uids: List[str] = []
        for uid in linked_uids + rederived_uids:
            if uid not in merged_uids:
                merged_uids.append(uid)
        updated_by_uid[block.block_id]["explanation_uids"] = merged_uids or None
        statuses.append(str(contract.get("llm_status") or "disabled"))
        stats["enriched"] += 1

    if statuses:
        if any(s == "ok" for s in statuses):
            stats["llm_status"] = "ok"
        elif all(s == "not_needed" for s in statuses):
            stats["llm_status"] = "not_needed"
    return updated, stats


__all__ = [
    "FormulaParamContract",
    "FormulaSemanticsContract",
    "build_formula_representations",
    "clean_formula_text",
    "collect_canonical_explanation_lines",
    "enrich_blocks_formula_semantics",
    "enrich_formula_block",
    "enrich_graph_nodes_formula_semantics",
    "extract_formula_number",
    "extract_formula_reference_hint",
    "extract_formula_unit",
    "llm_extract_formula_params",
    "merge_formula_params",
    "parse_formula_llm_json",
    "parse_formula_param_rule",
    "split_formula_explanation_lines",
]

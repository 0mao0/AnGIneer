"""公式结构化提取工具。"""
import json
import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from angineer_core.infra.llm_client import LLMClient


FORMULA_NUMBER_RE = re.compile(r"[（(](\d+(?:\.\d+)*(?:-\d+)?)[）)]")
FORMULA_PARAM_SYMBOL_RE = r"[A-Za-zΑ-Ωα-ω\\][A-Za-z0-9_{}^()\\/.\-']{0,20}"
FORMULA_PARAM_RE = re.compile(
    rf"^\s*({FORMULA_PARAM_SYMBOL_RE})\s*(?:[—–\-一]{{1,3}}|:=|=|：|:)\s*(.+?)\s*$"
)
FORMULA_PARAM_SOFT_RE = re.compile(rf"^\s*({FORMULA_PARAM_SYMBOL_RE})\s+(.+?)\s*$")
REFERENCE_HINT_RE = re.compile(r"(采用[^；。]*|按[^；。]*|取[^；。]*|见[^；。]*|按表[^；。]*)")
UNIT_RE = re.compile(r"[（(]([^()（）]{1,20})[）)]")
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


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
            return match.group(1)
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
    candidate = re.sub(r"^(式中|其中|注[:：]?)\s*", "", candidate)
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


# 生成公式结构化表示，供结构化索引层消费。
def build_formula_representations(
    formula_text: str,
    explanation_lines: List[str],
    llm_client: Optional["LLMClient"] = None,
    llm_model: Optional[str] = None,
    use_llm: bool = True,
) -> Dict[str, Any]:
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
        if normalized_lines and (unmatched_lines or not rule_params):
            llm_params, llm_status = llm_extract_formula_params(
                formula_text=cleaned_formula,
                explanation_lines=normalized_lines,
                llm_client=llm_client,
                llm_model=llm_model,
            )
        else:
            llm_status = "not_needed"

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
        "formula_summary": summary,
        "llm_status": llm_status,
        "explanation_lines": normalized_lines,
    }


__all__ = [
    "build_formula_representations",
    "clean_formula_text",
    "extract_formula_number",
    "extract_formula_reference_hint",
    "extract_formula_unit",
    "llm_extract_formula_params",
    "merge_formula_params",
    "parse_formula_llm_json",
    "parse_formula_param_rule",
    "split_formula_explanation_lines",
]

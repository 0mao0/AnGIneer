"""查询归一化与简单文本特征提取。"""
import re
from typing import List

_GREEK_ALIAS_MAP = {
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "ε": "varepsilon",
    "η": "eta",
    "θ": "theta",
    "κ": "kappa",
    "λ": "lambda",
    "μ": "mu",
    "ν": "nu",
    "ξ": "xi",
    "π": "pi",
    "ρ": "rho",
    "σ": "sigma",
    "τ": "tau",
    "φ": "phi",
    "ψ": "psi",
    "ω": "omega",
}

_FORMULA_SYMBOL_ROOTS = tuple(sorted(set(_GREEK_ALIAS_MAP.values()) | {
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "eta", "theta",
    "kappa", "lambda", "mu", "nu", "xi", "pi", "rho", "sigma", "tau", "phi",
    "psi", "omega",
}))

# 工程规范正文中的高频通用 n-gram：仅命中它们不构成主题相关信号，打分时大幅降权。
# 例如"斜坡堤稳定计算方法和要求"里的"计算方法/计算/方法/要求"在几乎所有规范条文里都出现，
# 与"斜坡堤稳定"这类主题词权重相同会让无关文档靠通用词刷分（详见 docs/retrieval-chain.md）。
GENERIC_NGRAM_STOPLIST = frozenset({
    # 2 字高频功能词 / 通用表述
    "计算", "方法", "要求", "规定", "公式", "按式", "下列", "确定", "根据",
    "采用", "符合", "标准", "设计", "进行", "按下", "应按", "可取", "应取",
    "如何", "怎么", "做法", "步骤", "流程", "说明", "介绍", "相关", "有关",
    "主要", "内容", "包括", "分为", "属于", "满足", "选用", "选取", "依据",
    "按照", "表示", "布置", "措施", "原则", "条文", "规范", "情况", "条件",
    "一般", "相应", "具体", "换算", "校核", "算方", "法要", "和要", "定计",
    # 3 字通用短语
    "计算方", "算方法", "按下列", "应符合", "应满足", "按规定", "按规范",
    "本规范", "公式计算", "可按下", "按下式", "按公式", "确定方", "规定应",
    "有关规", "相应规", "主要内", "设计计", "验算方", "方法要", "计算要",
    # 4 字及以上通用表述
    "计算方法", "按式计算", "可按下式", "下列规定", "有关规定", "相应规定",
    "符合规定", "采用下列", "按下列规", "计算方法和", "方法和要求", "计算要求",
    "公式计算方", "按下式计算", "可按下式计", "按式确定", "确定方法",
    "计算方法和要求", "规定的要求", "要求计算",
})


def token_scoring_weight(token: str) -> float:
    """给检索打分用的 n-gram 权重：按长度与通用词表加权。

    - 2 字 0.4 / 3 字 0.7 / 4 字 1.0 / 5 字及以上 1.2；
    - 命中 GENERIC_NGRAM_STOPLIST 的通用词乘 0.1；
    - 公式标识符（ε_t,r → eps_t,r 等 ASCII 标识符）1.5，精确信号优先。
    """
    if not token:
        return 0.0
    if re.fullmatch(r"[a-z0-9_]+", token):
        return 1.5
    length = len(token)
    if length <= 2:
        base = 0.4
    elif length == 3:
        base = 0.7
    elif length == 4:
        base = 1.0
    else:
        base = 1.2
    if token in GENERIC_NGRAM_STOPLIST:
        return round(base * 0.1, 3)
    return base


def replace_greek_formula_aliases(text: str) -> str:
    """把 Unicode 希腊字母替换为稳定的 ASCII 别名，便于与 LaTeX 形式对齐。"""
    normalized = text or ""
    for source, target in _GREEK_ALIAS_MAP.items():
        normalized = normalized.replace(source, target)
    return normalized


def strip_latex_text_wrappers(text: str) -> str:
    """移除 `\\mathrm{}` 这类仅影响展示、不影响公式语义的 LaTeX 包装。"""
    normalized = text or ""
    while True:
        next_text = re.sub(r"\\mathrm\s*\{([^{}]+)\}", r"\1", normalized)
        if next_text == normalized:
            return normalized
        normalized = next_text


# 归一化文本以提升中文检索匹配稳定性。
def normalize_match_text(text: str) -> str:
    compact = re.sub(
        r"\s+",
        "",
        strip_latex_text_wrappers(replace_greek_formula_aliases(text or "")),
    )
    compact = re.sub(
        r"[\uff0c\u3002\uff1b\uff1a\u3001\u201c\u201d\u2018\u2019"
        r"\uff08\uff09()\[\]\u3010\u3011\u300a\u300b"
        r"{}<>.,;:!\?\uff01\uff1f\u00b7\u2014\-~$\\]",
        "",
        compact,
    )
    return compact.lower().strip()


# 从连续中文片段中生成 n-gram，提升问句到证据的匹配能力。
def build_cjk_ngrams(text: str, min_n: int = 2, max_n: int = 6) -> List[str]:
    normalized = normalize_match_text(text)
    if len(normalized) < min_n:
        return [normalized] if normalized else []
    grams: List[str] = []
    upper_n = min(max_n, len(normalized))
    for n in range(upper_n, min_n - 1, -1):
        for index in range(0, len(normalized) - n + 1):
            grams.append(normalized[index:index + n])
    return grams


# 切分用户问题为简单关键词，兼容中英文和数字。
def tokenize_query(query: str) -> List[str]:
    raw_query = replace_greek_formula_aliases(query or "")
    raw_tokens = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_]+", raw_query)
    tokens: List[str] = []
    for token in raw_tokens:
        normalized = normalize_match_text(token)
        if not normalized:
            continue
        tokens.append(normalized)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(normalized) >= 4:
            tokens.extend(build_cjk_ngrams(normalized))
    tokens.extend(extract_formula_identifiers(raw_query))
    deduped: List[str] = []
    seen = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def extract_formula_identifiers(text: str) -> List[str]:
    """抽取 `ε_t,r`、`\\varepsilon_{t,r}` 这类公式符号的稳定标识。"""
    normalized_text = strip_latex_text_wrappers(replace_greek_formula_aliases(text or ""))
    matches = re.findall(
        r"(?:\\?[A-Za-z]+(?:_\s*\{?\s*[A-Za-z0-9,\-\s]+\}?)?)",
        normalized_text,
    )
    identifiers: List[str] = []
    seen = set()
    for match in matches:
        candidate = normalize_match_text(match)
        if not candidate or len(candidate) < 2:
            continue
        has_subscript = "_" in match
        if not has_subscript and not any(candidate.startswith(root) for root in _FORMULA_SYMBOL_ROOTS):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        identifiers.append(candidate)
    return identifiers


# 归一化条款号中的空格/连字符/中文数字为点分格式。
# 注：本函数只处理数字编号的归一化，不处理汉字序数如"第六十二条"。
_CN_NUM_MAP = {
    "一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
    "六": "6", "七": "7", "八": "8", "九": "9",
}

def normalize_clause_ref_text(raw: str) -> str:
    """将条款号归一化为点分格式（如 6.2.7）。"""
    text = str(raw or "").strip()
    if not text:
        return ""
    cn_match = re.fullmatch(
        r"([一二三四五六七八九十]+)(?:点([一二三四五六七八九十]+))?(?:点([一二三四五六七八九十]+))?(?:点([一二三四五六七八九十]+))?",
        text,
    )
    if cn_match and cn_match.group(1):
        parts = [g for g in cn_match.groups() if g]
        converted = [_CN_NUM_MAP.get(g, g) for g in parts]
        return ".".join(converted)
    result = re.sub(r"\s+", ".", text)
    result = re.sub(r"-+", ".", result)
    result = re.sub(r"\.{2,}", ".", result)
    return result.strip(".")


# 提取问题中的条款编号，便于优先命中精确条文。
# 支持多形态：6.2.7 / 6 2 7 / 6-2-7 / 六点二点七
def extract_clause_refs(query: str) -> List[str]:
    raw = str(query or "")
    candidates = []
    candidates.extend(re.findall(r"\d+(?:\.\d+){1,4}", raw))
    candidates.extend(re.findall(r"\d+(?:\s+\d+){1,4}", raw))
    candidates.extend(re.findall(r"\d+(?:-\d+){1,4}", raw))
    candidates.extend(
        re.findall(r"[一二三四五六七八九十]+(?:点[一二三四五六七八九十]+){1,4}", raw)
    )
    deduped: List[str] = []
    seen = set()
    for ref in candidates:
        normalized = normalize_clause_ref_text(ref)
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


# 抽取规范文档检索所需的结构化 query 信号。
def extract_query_signals(query: str) -> dict:
    raw_tokens = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_.]+", query or "")
    figure_refs = re.findall(r"(?:图|figure)\s*([0-9]+)", query or "", flags=re.IGNORECASE)
    table_refs = re.findall(r"(?:表|table)\s*([0-9]+)", query or "", flags=re.IGNORECASE)
    formula_refs = re.findall(
        r"(\\[A-Za-z]+\s*_\s*\{[A-Za-z0-9,\-\s]+\}|[α-ωΑ-Ω]\s*_\s*\{?[A-Za-z0-9,\-\s]+\}?)",
        query or "",
        flags=re.IGNORECASE,
    )
    if not formula_refs:
        formula_refs = re.findall(r"(?:公式)\s*([0-9]+)", query or "", flags=re.IGNORECASE)
    clause_refs = extract_clause_refs(query)
    formula_identifiers = extract_formula_identifiers(query)

    question_type = "definition_qa"
    if figure_refs:
        question_type = "locate_figure"
    elif table_refs:
        question_type = "locate_table"
    elif formula_refs or "公式" in query or (formula_identifiers and any(token in query for token in ("式", "式子"))):
        question_type = "locate_formula"
    elif clause_refs:
        question_type = "locate_clause"
    elif any(token in query for token in ("不得", "不应", "应", "允许")):
        question_type = "cross_section_constraint"

    return {
        "question_type": question_type,
        "clause_refs": clause_refs,
        "figure_refs": figure_refs,
        "table_refs": table_refs,
        "formula_refs": formula_refs,
        "raw_tokens": raw_tokens,
        "keywords": tokenize_query(query),
    }


# 判断文本中是否精确包含某个条款编号，避免 6.2.1 误命中 6.6.2.1。
def contains_clause_ref(text: str, clause_ref: str) -> bool:
    if not text or not clause_ref:
        return False
    pattern = rf"(?<![\d.]){re.escape(clause_ref)}(?![\d.])"
    return bool(re.search(pattern, text))


# 为拒答和重排生成较长查询短语，减少短 token 误匹配。
def build_query_phrases(query: str, min_n: int = 4, max_n: int = 8) -> List[str]:
    normalized = normalize_match_text(query)
    if not normalized:
        return []
    if re.fullmatch(r"[a-z0-9_]+", normalized):
        return [normalized] if len(normalized) >= min_n else []
    phrases = build_cjk_ngrams(normalized, min_n=min_n, max_n=min(max_n, len(normalized)))
    deduped: List[str] = []
    seen = set()
    for phrase in phrases:
        if phrase in seen:
            continue
        seen.add(phrase)
        deduped.append(phrase)
    return deduped

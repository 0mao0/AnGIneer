"""
意图分类核心模块，负责根据用户问题选择合适的 SOP 并提取参数。
"""
import json
import math
import re
from collections import Counter
from typing import List, Optional, Tuple, Dict, Any

from angineer_core.base_contracts import SOP, AgentResponse, IntentResult, IntentLevel, ServiceMode, RouteResult
from ai_inference.llm_client import get_llm_client
from ai_inference.llm_response_parser import (
    extract_json_from_text,
)
from angineer_core.base_contracts import IntentResponse
from angineer_core.base_logger import get_logger

logger = get_logger(__name__)

L0_PURE_CHAT_KEYWORDS = ["你好", "您好", "嗨", "hi", "hello", "早上好", "下午好", "晚上好", "早安", "晚安",
                          "谢谢", "感谢", "辛苦了", "再见", "拜拜",
                          "心情", "开心", "难过", "无聊", "累", "烦", "高兴", "生气", "焦虑",
                          "今天天气", "吃了吗", "在吗", "聊聊天", "闲聊"]
L0_AMBIGUOUS_KEYWORDS = ["你是谁", "你叫什么", "能做什么", "有什么功能", "帮我", "怎么用"]
L1_KEYWORDS = ["什么是", "是什么", "哪些", "定义", "概念", "组成", "包括", "分为", "划分", "分类", "类型", "位于", "设置", "位置", "在哪里", "宜设置", "应设置", "如何确定", "怎么确定", "怎样确定", "如何定义", "怎么定义", "如何划分", "怎么划分", "简述", "说明", "列举", "阐述", "解释", "原理", "作用", "功能", "特点", "特征", "区别", "异同", "对比", "比较", "差异", "选用", "选型", "适用条件", "适用范围", "影响因素", "注意事项"]
L2_KEYWORDS = ["取值", "范围", "规定", "条款", "要求", "标准值", "限值", "允许值", "应符合", "不应超过", "查表", "依据", "按照", "遵照", "应满足", "取值表", "参数表", "数据表", "条文"]
L3_KEYWORDS = ["计算", "求", "验算", "核算", "校核", "公式", "等于多少", "结果是多少", "求解", "算出", "推定", "是多少", "求值", "推算"]
# L4 关键词：仅当题目明确要求多步骤综合/方案设计/多方案比较时才触发
# 注意：单独的"分析""评价"等词在工程考试中常是L1/L3，不能单独作为L4依据
L4_KEYWORDS = ["综合评价", "综合评估", "系统分析", "方案设计", "设计方案", "多方案比较", 
                "优化设计", "比选", "技术经济比较", "可行性研究", "初步设计", "施工图设计"]
# L4 辅助信号：需要多个强信号同时出现才判定为L4
L4_COMPOUND_SIGNALS = ["并", "且", "同时", "再", "然后", "最后", "分步", "步骤", 
                        "第一", "第二", "第三", "首先", "其次", "接着"]

CLAUSE_ID_PATTERN = re.compile(r"(?:第\s*([A-Za-z]?\d+(?:\.\d+){1,4})\s*(?:条|款|节|章|式)?)|(?:(?:[A-Za-z]?\d+(?:\.\d+){1,4})\s*(?:条|款|节|章|式))")

PARAM_PATTERN = re.compile(r"([a-zA-Zα-ωΑ-Ω][a-zA-Zα-ωΑ-Ω_]*)\s*[=＝]\s*([\d.]+)")
NUM_VALUE_PATTERN = re.compile(r"[\d]+(?:\.\d+)?(?:\s*(?:m|t|吨|级|kn|°|%%|s|mm|cm|km|m/s|kg/m|万|亿))")

STANDARD_CODE_PATTERN = re.compile(
    r"(?:GB|GB/T|JGJ|JGJ/T|JTS|JTJ|JTG|JTG/T|JTSC|CJJ|CJJ/T|DL|DL/T|SL|SL/T|NB|NB/T|SY|SY/T|HJ|HJ/T|YB|YB/T|TB|TB/T|SH|SH/T|HG|HG/T|CECS|DB)\s*[/\-]?\s*\d+(?:\s*[-—–]\s*\d+)?",
    re.IGNORECASE,
)

ROUTE_CONFIDENCE_THRESHOLD = 0.45
ROUTE_RECALL_TOP_K = 5
ROUTE_RECALL_MIN_SCORE = 0.02

# 各意图层级的默认升级链：当前路径失败后逐级回退
DEFAULT_EXECUTION_PLANS: Dict[str, List[str]] = {
    "L0": ["casual_chat"],
    "L1": ["semantic_retrieval"],
    "L2": ["sql_first", "semantic_retrieval"],
    "L3": ["standard_sop", "semantic_retrieval"],
    "L4": ["dynamic_orchestration"],
}

# 简短参数名 → 中文含义映射，帮助 LLM 理解 SOP 参数并正确提取
PARAM_DESCRIPTIONS: Dict[str, str] = {
    "H": "波高（m），常以H4%或H1%形式出现在题面",
    "L": "波长（m）",
    "d": "水深（m），可由设计水位与底高程推算",
    "h": "码头上部结构高度（m）",
    "h0": "波峰面高出上部结构底面的高度（m），波峰低于底面时取0",
    "b": "船宽/B值（m），常通过吨级+船型查附录表A.0.2获取",
    "夹角": "水流方向与航道轴线的夹角（°），由流向+航道方位推算",
    "掩护情况": "码头掩护条件：掩护良好/部分掩护/开敞水域，可从'受顺浪''横浪'等描述推断",
    "K1": "波浪系数：顺浪取0.3，横浪取0.5",
    "k2": "波浪富裕深度折减系数（0~1.0）",
    "折减系数": "波浪富裕深度折减系数（0~1.0）",
    "流速": "水流流速（m/s）",
    "横风风力": "横风风力等级（≤7级为横风，≥7级为大风）",
    "船舶航速": "船舶设计航速（kn）",
    "船舶类型": "航道类型：单线航道或双线航道",
}
GENERIC_TEXT_STOP_MARKERS = [
    "，备淤",
    ",备淤",
    "备淤富裕深度",
    "，计算",
    ",计算",
    "，求",
    ",求",
    "，采用",
    ",采用",
    "，码头结构",
    ",码头结构",
    "，波浪",
    ",波浪",
    "，允许",
    ",允许",
    "，平均周期",
    ",平均周期",
    "，取小数点后",
    ",取小数点后",
    "（",
    "(",
]
SHIP_TYPE_INFERENCE_RULES: List[Tuple[List[str], str, str]] = [
    (["矿石", "煤", "散粮", "散货", "干散货"], "散货船", "干散货船"),
    (["原油", "成品油", "油品", "液货", "液体散货"], "油船", "液体散货船"),
    (["集装箱"], "集装箱船", "集装箱船"),
    (["滚装", "ro-ro", "roro"], "滚装船", "滚装船"),
    (["化学品"], "化学品船", "化学品船"),
    (["水泥"], "散装水泥船", "散装水泥船"),
]


def _build_intent_result(
    *,
    intent_level: IntentLevel,
    intent_type: str,
    required_capabilities: List[str],
    service_mode: ServiceMode,
    parameters: Optional[Dict[str, Any]] = None,
    execution_plan: Optional[List[ServiceMode]] = None,
    reason: Optional[str] = None,
) -> IntentResult:
    """统一构造意图识别结果，并为分层尝试链补齐兼容字段。"""
    if execution_plan:
        plan = list(execution_plan)
    else:
        plan = list(DEFAULT_EXECUTION_PLANS.get(intent_level, [service_mode]))
    final_path = plan[-1] if len(plan) == 1 else None
    return IntentResult(
        intent_level=intent_level,
        primary_level=intent_level,
        intent_type=intent_type,
        parameters=parameters or {},
        required_capabilities=required_capabilities,
        service_mode=service_mode,
        execution_plan=plan,
        final_path=final_path,
        reason=reason,
    )


def _looks_like_clause_then_calculation(
    query: str,
    *,
    is_multiple_choice: bool,
    has_l3_keyword: bool,
    has_l2_keyword: bool,
    clause_match: Optional[re.Match[str]],
    standard_code_match: Optional[re.Match[str]],
    num_values: List[str],
) -> bool:
    """判断题目是否更适合先走 L2 定位依据，再视情况进入 L3 计算。"""
    if not has_l3_keyword:
        return False
    has_clause_signal = bool(standard_code_match or clause_match or has_l2_keyword)
    has_rich_numeric_context = len(num_values) >= 2
    return has_clause_signal and has_rich_numeric_context and is_multiple_choice


def _extract_value_by_patterns(query: str, patterns: List[str]) -> Optional[str]:
    """按候选正则顺序提取参数值。"""
    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            value = next((group for group in match.groups() if group), "")
            value = str(value or "").strip(" ，。；;:：")
            if value:
                return value
    return None


def _extract_value_after_markers(query: str, markers: List[str]) -> Optional[str]:
    """按“字段名 + 为/取/=”的自然语言表达提取后续片段。"""
    text = str(query or "")
    separators = ("为", "取", ":", "：", "=")
    stop_chars = "，。；;,\n"
    for marker in markers:
        idx = text.find(marker)
        if idx < 0:
            continue
        tail = text[idx + len(marker):].lstrip()
        if not tail:
            continue
        if tail[0] in separators:
            tail = tail[1:].lstrip()
        collected = []
        for char in tail:
            if char in stop_chars:
                break
            collected.append(char)
        value = "".join(collected).strip(" ，。；;:：")
        if value:
            return value
    return None


def _trim_generic_tail(value: str) -> str:
    """裁剪抽取片段尾部的通用描述噪声，保留核心参数短语。"""
    cleaned = str(value or "").strip(" ，。；;:：")
    for marker in GENERIC_TEXT_STOP_MARKERS:
        idx = cleaned.find(marker)
        if idx > 0:
            cleaned = cleaned[:idx].strip(" ，。；;:：")
    return cleaned


def _infer_ship_types_from_query(query: str) -> Dict[str, str]:
    """根据题面中的船型/货种语义推断可复用的船型字段。"""
    text = str(query or "")
    for keywords, ship_type, design_ship_type in SHIP_TYPE_INFERENCE_RULES:
        if any(keyword.lower() in text.lower() for keyword in keywords):
            return {
                "船型": ship_type,
                "设计船型": design_ship_type,
            }
    return {}


def _derive_extra_args_from_query(query: str) -> Dict[str, Any]:
    """从题面直接派生 SOP 可复用的补充参数，减少后续步骤盲算。"""
    args: Dict[str, Any] = {}
    silt_depth = _extract_value_by_patterns(
        query,
        [
            r"备淤(?:富裕)?深度(?:取|为|按)?\s*([\d.]+(?:m)?)",
            r"Z4(?:取|为|=|＝)?\s*([\d.]+(?:m)?)",
        ],
    )
    if silt_depth:
        args["Z4"] = silt_depth
        try:
            numeric = float(re.search(r"[-+]?\d+(?:\.\d+)?", silt_depth).group(0))
            args["回淤条件"] = "有回淤" if numeric > 0 else "不淤"
        except Exception:
            pass

    # 波浪系数 K1: 顺浪0.3, 横浪0.5
    if "顺浪" in query:
        args["K1"] = "0.3"
    elif "横浪" in query:
        args["K1"] = "0.5"

    # 掩护情况: 从波浪方向+掩护描述推断
    if "开敞" in query:
        args["掩护情况"] = "开敞水域"
    elif re.search(r"受[顺横]浪", query):
        args["掩护情况"] = "部分掩护"

    # 船舶类型: 从航道描述推断
    if "单线航道" in query:
        args["船舶类型"] = "单线航道"
    elif "双线航道" in query:
        args["船舶类型"] = "双线航道"

    # 夹角: 从流向+航道方位推算
    flow_match = re.search(r"流向\s*([NSEW])\s*(\d+)\s*[°°]", query)
    channel_match = re.search(r"航道(?:轴线)?方位(?:为|是)?\s*(\d+)\s*[°°]\s*[~～]\s*(\d+)\s*[°°]", query)
    if flow_match and channel_match:
        try:
            flow_dir = flow_match.group(1)
            flow_deg = float(flow_match.group(2))
            ch_start = float(channel_match.group(1))
            ch_end = float(channel_match.group(2))
            ch_mid = (ch_start + ch_end) / 2.0
            # 夹角 = |航道中线方位 - 流向角度|, 流向角度根据N/S/E/W换算
            if flow_dir == "N":
                flow_bearing = flow_deg
            elif flow_dir == "S":
                flow_bearing = 180.0 + flow_deg
            elif flow_dir == "E":
                flow_bearing = 90.0
            elif flow_dir == "W":
                flow_bearing = 270.0
            else:
                flow_bearing = flow_deg
            angle = abs(ch_mid - flow_bearing)
            if angle > 180:
                angle = 360 - angle
            if angle > 90:
                angle = 180 - angle
            args["夹角"] = str(round(angle, 1))
        except Exception:
            pass

    # h0: 上水标准下波峰低于上部结构底面时取0
    if "h0" not in args:
        args["h0"] = "0"

    # d (水深): 可由设计水位和底高程推算
    water_level = _extract_value_by_patterns(
        query,
        [r"设计(?:高|低)水位(?:为|取)?\s*([\-\d.]+(?:m)?)"],
    )
    bottom_elev = _extract_value_by_patterns(
        query,
        [r"(?:码头前沿)?(?:水域)?底高程(?:为|取)?\s*([\-\d.]+(?:m)?)"],
    )
    if water_level and bottom_elev:
        try:
            wl = float(re.search(r"[-+]?\d+(?:\.\d+)?", water_level).group(0))
            be = float(re.search(r"[-+]?\d+(?:\.\d+)?", bottom_elev).group(0))
            args["d"] = str(round(wl - be, 2))
        except Exception:
            pass

    return args


def _clean_extracted_arg(param_name: str, value: Any, query: str) -> Any:
    """清洗抽取结果，统一为更适合进入 SOP blackboard 的参数形态。"""
    if value in (None, ""):
        return value
    cleaned = _trim_generic_tail(str(value))
    if param_name == "吨级":
        match = re.search(r"\d+(?:\.\d+)?", cleaned)
        return match.group(0) if match else cleaned
    if param_name == "底质条件":
        cleaned = cleaned.replace("海底", "").replace("底质条件", "").replace("底质", "").strip(" 为取")
        return _trim_generic_tail(cleaned)
    if param_name in {"船型", "设计船型"}:
        if "码头" in cleaned and "船" not in cleaned:
            cleaned = cleaned.split("码头", 1)[0]
        cleaned = re.sub(r"^\d+(?:\.\d+)?\s*吨级", "", cleaned).strip()
        cleaned = cleaned.strip(" 的")
        inferred_ship_types = _infer_ship_types_from_query(query)
        if not cleaned or cleaned in {"码头", "泊位"}:
            return inferred_ship_types.get(param_name, cleaned)
        if "船" not in cleaned and inferred_ship_types.get(param_name):
            return inferred_ship_types[param_name]
        return cleaned
    # Generic: if value starts with a number, extract just the leading numeric
    # portion, discarding any trailing unit suffix (e.g. "1.5m" → "1.5").
    num_match = re.match(r'^([-+]?\d+(?:\.\d+)?)', cleaned)
    if num_match:
        return num_match.group(1)
    return cleaned


def _supplement_sop_args_from_query(
    query: str,
    required_params: List[str],
    base_args: Dict[str, Any],
) -> Dict[str, Any]:
    """根据题面中的显式参数，为 SOP 路由结果补充可直接识别的字段。"""
    args = dict(base_args or {})
    normalized_required = {str(item) for item in (required_params or [])}
    extractors: Dict[str, List[str]] = {
        "H4%": [
            r"H4%\s*[=＝为:]?\s*([\d.]+(?:m)?)",
            r"波高\s*H4%\s*[=＝为:]?\s*([\d.]+(?:m)?)",
        ],
        "H": [
            r"(?:波高|H1%|H4%|H5%|H13%)\s*[=＝为:]?\s*([\d.]+(?:m)?)",
            r"(?:重现期|一遇)波高\s*(?:H1%|H4%)?\s*[=＝为:]?\s*([\d.]+(?:m)?)",
        ],
        "L": [
            r"波长\s*(?:L)?\s*[=＝为:]?\s*([\d.]+(?:m)?)",
        ],
        "d": [
            r"水深\s*(?:d)?\s*[=＝为:]?\s*([\d.]+(?:m)?)",
        ],
        "h": [
            r"(?:上部结构高度|结构高度)\s*(?:h)?\s*[=＝为:]?\s*([\d.]+(?:m)?)",
        ],
        "h0": [
            r"波峰面高出上部结构底面的高度\s*(?:h0)?\s*[=＝为:]?\s*([\d.]+(?:m)?)",
            r"h0\s*[=＝为:]?\s*([\d.]+(?:m)?)",
        ],
        "掩护情况": [
            r"掩护(?:水域|情况|条件)?[为取]?([^，。；;]{1,10})",
            r"(部分掩护|掩护良好|开敞水域|开敞式|无掩护)",
        ],
        "b": [
            r"(?:船宽|B\s*[=＝为:])\s*([\d.]+(?:m)?)",
        ],
        "夹角": [
            r"(?:夹角|交角)\s*[=＝为:]?\s*([\d.]+(?:°|度)?)",
        ],
        "吨级": [
            r"(\d+(?:\.\d+)?)\s*吨级",
            r"(\d+(?:\.\d+)?)\s*(?:GT|gt|DWT|dwt)",
        ],
        "起算水位": [
            r"起算水位(?:为|取)?\s*([\-\d.]+(?:m)?)",
            r"设计低水位(?:为|取)?\s*([\-\d.]+(?:m)?)",
        ],
        "底质条件": [
            r"(?:海底)?底质(?:条件)?(?:为|取)?([^，。；;]+)",
        ],
        "回淤条件": [
            r"回淤条件(?:为|取)?([^，。；;]+)",
            r"(有回淤|不淤港口|不淤)",
        ],
        "设计船型": [
            r"设计船型(?:为|取)?\s*([^，。；;]{1,15}船)",
            r"拟建\s*(\d+(?:\.\d+)?吨级[^，。；;]{1,15}船)",
        ],
        "船型": [
            r"船型(?:为|取)?\s*([^，。；;]{1,15}船)",
            r"通航船舶为\s*(\S+船)",
            r"船舶为\s*(\S+船)",
        ],
        "流速": [
            r"(?:水流)?流速\s*[=＝为:]?\s*([\d.]+(?:\s*(?:m/s)?)?)",
        ],
        "横风风力": [
            r"(?:横风|风力)\s*(?:≤|≤|小于等于|小于|为)?\s*(\d+)\s*(?:级)?",
        ],
        "船舶航速": [
            r"航速\s*[=＝为:]?\s*([\d.]+(?:\s*(?:kn|节)?)?)",
        ],
        "船舶类型": [
            r"(单线航道|双线航道|单向航道|双向航道)",
        ],
        "K1": [
            r"K1\s*[=＝为:]?\s*([\d.]+)",
        ],
        "k2": [
            r"k2\s*[=＝为:]?\s*([\d.]+)",
        ],
        "折减系数": [
            r"折减系数\s*[=＝为取:]?\s*([\d.]+)",
            r"(?:波浪富裕深度)?折减系数\s*[=＝为取:]?\s*([\d.]+)",
        ],
    }
    marker_extractors: Dict[str, List[str]] = {
        "起算水位": ["起算水位", "设计低水位"],
        "底质条件": ["海底底质为", "海底底质", "底质条件为", "底质为"],
        "回淤条件": ["回淤条件为", "回淤条件"],
        "设计船型": ["设计船型为", "设计船型"],
        "船型": ["船型为", "船型"],
        "掩护情况": ["掩护条件为", "掩护情况为", "掩护条件", "掩护情况"],
        "夹角": ["夹角为", "夹角", "交角为", "交角"],
        "流速": ["流速为", "流速", "水流流速为", "水流流速"],
        "横风风力": ["横风为", "横风", "风力为", "风力"],
        "船舶航速": ["航速为", "航速", "船速为", "船速"],
        "船舶类型": ["航道为", "航道类型为"],
        "K1": ["K1=", "K1为", "K1=", "K1:"],
        "k2": ["k2=", "k2为", "k2=", "k2:"],
        "折减系数": ["折减系数为", "折减系数取", "折减系数"],
        "H": ["波高为", "波高", "H4%=", "H1%=", "H4%为", "H1%为"],
        "L": ["波长为", "波长", "L=", "L为"],
        "d": ["水深为", "水深"],
        "b": ["船宽为", "船宽", "B="],
    }
    for param_name in normalized_required:
        if args.get(param_name) not in (None, ""):
            continue
        patterns = extractors.get(param_name)
        if not patterns:
            extracted = None
        else:
            extracted = _extract_value_by_patterns(query, patterns)
        if not extracted and param_name in marker_extractors:
            extracted = _extract_value_after_markers(query, marker_extractors[param_name])
        if extracted:
            args[param_name] = _clean_extracted_arg(param_name, extracted, query)
    for key, value in list(args.items()):
        args[key] = _clean_extracted_arg(key, value, query)
    inferred_ship_types = _infer_ship_types_from_query(query)
    for key, value in inferred_ship_types.items():
        if key in normalized_required and not args.get(key):
            args[key] = value
    if "设计船型" in normalized_required and not args.get("船型") and args.get("设计船型"):
        args["船型"] = args["设计船型"]
    if "船型" in normalized_required and not args.get("设计船型") and args.get("船型"):
        args["设计船型"] = args["船型"]
    args.update({k: v for k, v in _derive_extra_args_from_query(query).items() if v not in (None, "") and not args.get(k)})
    return args


# 字符级 bigram 分词，避免外部分词依赖
def _char_bigrams(text: str) -> List[str]:
    """对文本做字符级 bigram 切分，用于中文文本的相似度计算。"""
    cleaned = re.sub(r"\s+", "", text)
    if len(cleaned) < 2:
        return [cleaned] if cleaned else []
    return [cleaned[i:i + 2] for i in range(len(cleaned) - 1)]


# 构建 SOP 文档语料
def _build_sop_corpus(sops: List[SOP]) -> Tuple[List[str], List[str]]:
    """构建 SOP 文档语料，每个 SOP 的文档 = id + name_zh + description + blackboard.required。"""
    doc_ids = []
    documents = []
    for sop in sops:
        doc_ids.append(sop.id)
        parts = [sop.id]
        if sop.name_zh:
            parts.append(sop.name_zh)
        if sop.name_en:
            parts.append(sop.name_en)
        if sop.description:
            parts.append(sop.description)
        if sop.description_zh:
            parts.append(sop.description_zh)
        bb = sop.blackboard or {}
        required = bb.get("required") or []
        if required:
            parts.extend(str(r) for r in required)
        outputs = bb.get("outputs") or []
        if outputs:
            parts.extend(str(o) for o in outputs)
        documents.append(" ".join(parts))

    logger.debug(f"[DEBUG-SOP-ROUTE] 语料库构建完成: 总数={len(doc_ids)}, SOP IDs={doc_ids}")
    return doc_ids, documents


# TF-IDF 关键词召回
def _keyword_recall(
    query: str,
    doc_ids: List[str],
    documents: List[str],
    top_k: int = ROUTE_RECALL_TOP_K,
    min_score: float = ROUTE_RECALL_MIN_SCORE,
) -> List[Tuple[str, float]]:
    """基于字符级 bigram + TF-IDF 的关键词召回，返回 [(sop_id, score), ...]。"""
    if not documents:
        logger.warning("[DEBUG-SOP-ROUTE] TF-IDF 召回: 文档列表为空")
        return []

    all_docs = documents + [query]
    tokenized = [_char_bigrams(d) for d in all_docs]

    query_tokens = tokenized[-1]
    logger.debug(f"[DEBUG-SOP-ROUTE] 查询分词结果 (bigram): {query_tokens[:20]}{'...' if len(query_tokens) > 20 else ''}")

    doc_freq = Counter()
    for tokens in tokenized:
        for t in set(tokens):
            doc_freq[t] += 1
    n_docs = len(tokenized)

    def _tfidf(tokens: List[str]) -> Dict[str, float]:
        tf = Counter(tokens)
        total = len(tokens) if tokens else 1
        return {
            t: (count / total) * math.log(n_docs / (doc_freq.get(t, 1)))
            for t, count in tf.items()
            if doc_freq.get(t, 0) > 0
        }

    query_vec = _tfidf(tokenized[-1])

    all_scores = []
    for i, doc_tokens in enumerate(tokenized[:-1]):
        doc_vec = _tfidf(doc_tokens)
        dot = sum(query_vec.get(t, 0) * doc_vec.get(t, 0) for t in query_vec)
        q_norm = math.sqrt(sum(v ** 2 for v in query_vec.values())) if query_vec else 0
        d_norm = math.sqrt(sum(v ** 2 for v in doc_vec.values())) if doc_vec else 0
        score = dot / (q_norm * d_norm) if q_norm > 0 and d_norm > 0 else 0.0
        all_scores.append((doc_ids[i], score))

    logger.debug(f"[DEBUG-SOP-ROUTE] TF-IDF 全量分数 (阈值={min_score}):")
    for sop_id, score in sorted(all_scores, key=lambda x: x[1], reverse=True):
        status = "✓" if score >= min_score else "✗"
        logger.debug(f"  {status} {sop_id}: {score:.4f}")

    results = [(sop_id, score) for sop_id, score in all_scores if score >= min_score]
    results.sort(key=lambda x: x[1], reverse=True)

    logger.info(f"[DEBUG-SOP-ROUTE] TF-IDF 召回结果: top_k={top_k}, 命中={len(results)}个, 结果={[(r[0], f'{r[1]:.4f}') for r in results[:top_k]]}")
    return results[:top_k]


# 检测查询是否包含实质性工程内容
def _has_substantive_content(query: str) -> bool:
    """判断查询是否包含实质性工程内容（规范编号、条款、参数、数值、专业关键词等）。"""
    if STANDARD_CODE_PATTERN.search(query):
        return True
    if CLAUSE_ID_PATTERN.search(query):
        return True
    if PARAM_PATTERN.findall(query):
        return True
    if len(NUM_VALUE_PATTERN.findall(query)) >= 2:
        return True
    if any(kw in query for kw in L1_KEYWORDS):
        return True
    if any(kw in query for kw in L2_KEYWORDS):
        return True
    if any(kw in query for kw in L3_KEYWORDS):
        return True
    if any(kw in query for kw in L4_KEYWORDS):
        return True
    if len(query) > 15:
        return True
    return False


# L0 闲聊快速检测（独立函数，供 classify_intent 优先调用）
def _check_l0_intent(query: str) -> Optional[IntentResult]:
    """仅检测明确的闲聊/问候意图，不做 L1-L4 判定。"""
    if not query:
        return None
    has_pure_chat = any(kw in query for kw in L0_PURE_CHAT_KEYWORDS)
    has_ambiguous = any(kw in query for kw in L0_AMBIGUOUS_KEYWORDS)
    if has_pure_chat and not has_ambiguous and not _has_substantive_content(query):
        return _build_intent_result(
            intent_level="L0",
            intent_type="casual_chat",
            required_capabilities=[],
            service_mode="casual_chat",
            reason="检测到纯闲聊关键词",
        )
    if has_ambiguous and not _has_substantive_content(query):
        return _build_intent_result(
            intent_level="L0",
            intent_type="casual_chat",
            required_capabilities=[],
            service_mode="casual_chat",
            reason="检测到歧义闲聊关键词且无实质性内容",
        )
    return None


# 基于规则快速判定意图层级（LLM 分类失败时的兜底）
def _rule_based_classify(query: str) -> Optional[IntentResult]:
    """基于规则判定意图层级。仅用作 LLM 分类失败后的兜底。"""
    if not query:
        return None

    # L0 闲聊已由 _check_l0_intent 在前置处理，此处跳过

    is_multiple_choice = bool(re.search(r"\([A-D]\)", query) or re.search(r"[（][A-D][）]", query))
    has_l3_keyword = any(kw in query for kw in L3_KEYWORDS)
    num_values = NUM_VALUE_PATTERN.findall(query)
    standard_code_match = STANDARD_CODE_PATTERN.search(query)
    clause_match = CLAUSE_ID_PATTERN.search(query)
    param_matches = PARAM_PATTERN.findall(query)
    has_l2_keyword = any(kw in query for kw in L2_KEYWORDS)
    has_l4_keyword = any(kw in query for kw in L4_KEYWORDS)

    if _looks_like_clause_then_calculation(
        query,
        is_multiple_choice=is_multiple_choice,
        has_l3_keyword=has_l3_keyword,
        has_l2_keyword=has_l2_keyword,
        clause_match=clause_match,
        standard_code_match=standard_code_match,
        num_values=num_values,
    ):
        return _build_intent_result(
            intent_level="L2",
            intent_type="clause_then_calculation",
            parameters={"num_values_count": len(num_values)},
            required_capabilities=["retrieval", "sql", "calculation", "sop", "orchestration"],
            service_mode="sql_first",
            execution_plan=["sql_first", "standard_sop", "dynamic_orchestration"],
            reason="检测到条文/规范定位信号与计算特征，先走 L2 定位依据，必要时回退到 L3/L4",
        )

    # 规范编号精确查找（如 JGJ 162、GB 50010、JTS 165-2025 等）
    if standard_code_match:
        return _build_intent_result(
            intent_level="L2",
            intent_type="standard_lookup",
            parameters={"standard_code": standard_code_match.group(0)},
            required_capabilities=["retrieval", "sql"],
            service_mode="sql_first",
            reason=f"检测到规范编号({standard_code_match.group(0)})，走SQL精确检索",
        )

    if is_multiple_choice and has_l3_keyword and len(num_values) >= 1:
        return _build_intent_result(
            intent_level="L3",
            intent_type="standard_calculation",
            parameters={"num_values_count": len(num_values)},
            required_capabilities=["retrieval", "calculation", "sop"],
            service_mode="standard_sop",
            reason=f"检测到多选题计算模式：{len(num_values)}个数值参数(考试题模式)",
        )
    if param_matches and has_l3_keyword:
        return _build_intent_result(
            intent_level="L3",
            intent_type="standard_calculation",
            parameters={name: float(value) for name, value in param_matches},
            required_capabilities=["retrieval", "calculation", "sop"],
            service_mode="standard_sop",
            reason=f"检测到参数提取({len(param_matches)}个)和计算关键词",
        )
    if has_l3_keyword and len(num_values) >= 2:
        return _build_intent_result(
            intent_level="L3",
            intent_type="standard_calculation",
            parameters={"num_values_count": len(num_values)},
            required_capabilities=["retrieval", "calculation", "sop"],
            service_mode="standard_sop",
            reason=f"检测到计算关键词和{len(num_values)}个数值参数(考试题模式)",
        )
    if clause_match and has_l2_keyword:
        clause_id_value = clause_match.group(1) or clause_match.group(2)
        return _build_intent_result(
            intent_level="L2",
            intent_type="clause_application",
            parameters={"clause_id": clause_id_value},
            required_capabilities=["retrieval", "sql"],
            service_mode="sql_first",
            reason=f"检测到条款编号({clause_id_value})和条款关键词",
        )

    # ========== 渐进式意图层级判定（L1 → L2 → L3 → L4） ==========
    # 原则：低层级优先，只有明确不满足低层级特征时才进入更高层级
    
    has_l1_keyword = any(kw in query for kw in L1_KEYWORDS)
    has_l4_compound = any(kw in query for kw in L4_COMPOUND_SIGNALS)
    
    # L1: 概念/定义/位置类查询（只要检测到L1关键词且没有强L3信号）
    if has_l1_keyword and not (has_l3_keyword and len(num_values) >= 1):
        if any(kw in query for kw in ["位于", "设置", "位置", "在哪里", "宜设置", "应设置"]):
            return _build_intent_result(
                intent_level="L1",
                intent_type="locate_navigation",
                required_capabilities=["retrieval"],
                service_mode="semantic_retrieval",
                reason="检测到定位/位置类关键词",
            )
        return _build_intent_result(
            intent_level="L1",
            intent_type="concept_resolution",
            required_capabilities=["retrieval"],
            service_mode="semantic_retrieval",
            reason="检测到概念/定义类关键词",
        )

    # L3: 计算类查询（优先于L4，工程考试题中"计算"是强信号）
    # 只要满足以下任一条件即判定为L3：
    # 1. 有计算关键词 + 参数匹配
    # 2. 有计算关键词 + 多个数值
    # 3. 多选题 + 计算关键词
    if has_l3_keyword:
        if param_matches:
            return _build_intent_result(
                intent_level="L3",
                intent_type="standard_calculation",
                parameters={name: float(value) for name, value in param_matches},
                required_capabilities=["retrieval", "calculation", "sop"],
                service_mode="standard_sop",
                reason=f"检测到计算关键词和参数提取({len(param_matches)}个)",
            )
        if len(num_values) >= 1:
            return _build_intent_result(
                intent_level="L3",
                intent_type="standard_calculation",
                parameters={"num_values_count": len(num_values)},
                required_capabilities=["retrieval", "calculation", "sop"],
                service_mode="standard_sop",
                reason=f"检测到计算关键词和{len(num_values)}个数值参数",
            )
        # 纯计算关键词（无参数）也走L3，由SOP内部处理
        return _build_intent_result(
            intent_level="L3",
            intent_type="standard_calculation",
            required_capabilities=["retrieval", "calculation", "sop"],
            service_mode="standard_sop",
            reason="检测到计算关键词",
        )

    # L4: 复杂任务 —— 必须同时满足：
    # 1. 包含L4关键词（多步骤综合类）
    # 2. 包含复合信号词（多步骤指示）或题目长度较长（>30字）
    # 3. 不满足L1/L2/L3的强信号
    if has_l4_keyword and (has_l4_compound or len(query) > 30):
        return _build_intent_result(
            intent_level="L4",
            intent_type="complex_task",
            required_capabilities=["retrieval", "calculation", "sop", "orchestration"],
            service_mode="dynamic_orchestration",
            reason="检测到复杂任务关键词及多步骤/长文本特征",
        )
    
    # L2: 条款应用（兜底，只要检测到L2关键词）
    if has_l2_keyword:
        clause_id_value = (clause_match.group(1) or clause_match.group(2)) if clause_match else None
        return _build_intent_result(
            intent_level="L2",
            intent_type="clause_application",
            parameters={"clause_id": clause_id_value} if clause_id_value else {},
            required_capabilities=["retrieval", "sql"],
            service_mode="sql_first",
            reason="检测到条款应用关键词",
        )

    return None


class IntentClassifier:
    """意图分类器，负责分析用户查询并匹配最合适的 SOP。"""

    def __init__(self, sops: List[SOP], llm_client=None):
        """
        初始化意图分类器。

        Args:
            sops: 可用的 SOP 列表
            llm_client: 可选的 LLM 客户端实例，默认使用全局实例
        """
        self.sops = sops
        self._llm_client = llm_client or get_llm_client()
        logger.info(f"[DEBUG-SOP-ROUTE] 意图分类器初始化完成")
        logger.info(f"[DEBUG-SOP-ROUTE] 加载 SOP 总数: {len(sops)}")
        for i, sop in enumerate(sops):
            bb = sop.blackboard or {}
            required = bb.get("required") or []
            outputs = bb.get("outputs") or []
            has_blackboard = sop.blackboard is not None
            logger.debug(f"[DEBUG-SOP-ROUTE]   [{i+1}] id={sop.id}, name={sop.name_zh}, blackboard={'✓' if has_blackboard else '✗'}, params={required}, outputs={outputs}")

    # L1~L4 元意图分类与 service mode 决策
    def classify_intent(
        self,
        user_query: str,
        config_name: str = None,
        mode: str = "instruct",
    ) -> IntentResult:
        logger.info(f"[DEBUG-SOP-ROUTE] ===== 意图分类开始 =====")
        logger.info(f"[DEBUG-SOP-ROUTE] 用户查询: {user_query[:100]}{'...' if len(user_query) > 100 else ''}")
        logger.info(f"[DEBUG-SOP-ROUTE] 配置: config_name={config_name}, mode={mode}")

        # 步骤 1: 规则优先检查 L0（闲聊/问候，规则足够精准）
        l0_result = _check_l0_intent(user_query)
        if l0_result:
            logger.info(f"[DEBUG-SOP-ROUTE] L0 规则命中: reason={l0_result.reason}")
            return l0_result

        # 步骤 2: LLM 直接分类 L1/L2/L3/L4（主力分类器）
        logger.debug("[DEBUG-SOP-ROUTE] 非L0查询，进入 LLM 主力分类...")
        llm_result = self._llm_classify_intent(user_query, config_name=config_name, mode=mode)
        if llm_result:
            logger.info(f"[DEBUG-SOP-ROUTE] LLM分类结果: level=L{llm_result.intent_level}, type={llm_result.intent_type}, mode={llm_result.service_mode}")
            return llm_result

        # 步骤 3: LLM 分类失败，规则兜底
        logger.debug("[DEBUG-SOP-ROUTE] LLM分类失败，进入规则兜底...")
        rule_result = _rule_based_classify(user_query)
        if rule_result:
            logger.info(f"[DEBUG-SOP-ROUTE] 规则兜底结果: level=L{rule_result.intent_level}, type={rule_result.intent_type}, mode={rule_result.service_mode}, reason={rule_result.reason}")
            return rule_result

        # 步骤 4: 最终默认 L1
        fallback_result = _build_intent_result(
            intent_level="L1",
            intent_type="concept_resolution",
            required_capabilities=["retrieval"],
            service_mode="semantic_retrieval",
            reason="LLM和规则均分类失败，默认降级为L1语义检索",
        )
        logger.warning(f"[DEBUG-SOP-ROUTE] 最终降级: {fallback_result.reason}")
        return fallback_result

    # 调用 LLM 进行意图分类
    def _llm_classify_intent(
        self,
        user_query: str,
        config_name: str = None,
        mode: str = "instruct",
    ) -> Optional[IntentResult]:
        """LLM 主力分类器：直接判定 L1/L2/L3/L4，含置信度阈值过滤。"""
        system_prompt = """你是工程规范领域的意图分类器。根据用户问题判断意图层级和服务模式。

## 意图层级定义

| 层级 | 名称 | 判定特征 | service_mode（必须严格对应） |
|------|------|----------|------------------------------|
| L1 | 概念解析 | 问"什么是XX"、"XX的定义/原理"、"简述XX"、"XX的分类"、"XX的作用"，无计算参数 | semantic_retrieval |
| L2 | 条款应用 | 问条款取值、规范参数、查表取值（如"依据XX规范确定XX"、"查表得XX值"），不涉及多步计算 | sql_first |
| L3 | 标准计算 | 有具体数值参数需要计算（吨级、水位、波高、尺寸等工程参数），且存在预定义SOP可承接 | standard_sop |
| L4 | 复杂任务 | 无预定义SOP可承接的复合任务、多方案比较、系统设计分析 | dynamic_orchestration |

## 关键判断规则

1. 只要题目包含"计算/求/验算/求解/算出"等动词 + 工程参数（吨级、水位、波高、尺寸等数值），优先判为 L3
2. 考试选择题（带选项A/B/C/D）+ 含计算意图 = L3
3. "查表""依据XX规范""取值""应符合XX条" + 无计算 = L2
4. 纯概念问答（"什么是""简述""原理""分类""作用"）+ 无参数 = L1
5. 多方案比较/系统设计/综合评价 = L4

## Few-shot 示例

Q: "什么是港口吞吐量？"
A: {"intent_level": "L1", "intent_type": "概念解析", "confidence": 0.95, "service_mode": "semantic_retrieval", "reason": "纯概念定义查询，无计算参数"}

Q: "依据《海港总体设计规范》确定5万吨级散货船的设计船型尺度"
A: {"intent_level": "L2", "intent_type": "条款查表", "confidence": 0.90, "service_mode": "sql_first", "reason": "规范条款查表取值，不涉及计算"}

Q: "某5万吨级散货船，设计船型总长L=230m，型宽B=32m，满载吃水T=12.8m，试计算码头前沿水深。"
A: {"intent_level": "L3", "intent_type": "标准计算", "confidence": 0.92, "service_mode": "standard_sop", "reason": "含具体参数需要码头水深SOP计算"}

Q: "试对某港区进行总体布置方案设计，包括码头选型、泊位数量确定和陆域堆场布局。"
A: {"intent_level": "L4", "intent_type": "复杂方案设计", "confidence": 0.88, "service_mode": "dynamic_orchestration", "reason": "多步骤综合分析，无单一SOP可承接"}

## 输出格式

输出JSON对象（service_mode 必须从上述四种中选一，confidence 为 0.0-1.0）：
{
  "intent_level": "L3",
  "intent_type": "简短意图标签",
  "confidence": 0.85,
  "parameters": {"提取的参数": "值"},
  "required_capabilities": ["retrieval"],
  "service_mode": "standard_sop",
  "reason": "一句话说明判断依据"
}"""
        try:
            logger.debug("[DEBUG-SOP-ROUTE] 调用 LLM 进行意图分类...")
            response_text = self._llm_client.chat(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"用户问题: {user_query}"},
                ],
                mode=mode,
                config_name=config_name,
            )
            logger.debug(f"[DEBUG-SOP-ROUTE] LLM 意图分类原始响应: {response_text[:200]}{'...' if len(response_text) > 200 else ''}")

            if not response_text:
                logger.warning("[DEBUG-SOP-ROUTE] LLM 意图分类响应为空")
                return None
            parsed = extract_json_from_text(response_text)
            if not parsed:
                logger.warning(f"[DEBUG-SOP-ROUTE] LLM 意图分类解析失败, 原始文本: {response_text[:100]}")
                return None
            # 置信度阈值检查：低置信度时拒绝 LLM 结果，回退到规则
            confidence = float(parsed.get("confidence", 1.0))
            if confidence < 0.5:
                logger.warning(
                    f"[DEBUG-SOP-ROUTE] LLM 分类置信度过低 ({confidence:.2f})，回退规则兜底: "
                    f"level={parsed.get('intent_level')}, reason={parsed.get('reason')}"
                )
                return None
            result = _build_intent_result(
                intent_level=parsed.get("intent_level", "L1"),
                intent_type=parsed.get("intent_type", ""),
                parameters=parsed.get("parameters", {}),
                required_capabilities=parsed.get("required_capabilities", ["retrieval"]),
                service_mode=parsed.get("service_mode", "semantic_retrieval"),
                execution_plan=parsed.get("execution_plan"),
                reason=parsed.get("reason", ""),
            )
            logger.info(f"[DEBUG-SOP-ROUTE] LLM 意图分类成功 (confidence={confidence:.2f}): {json.dumps(parsed, ensure_ascii=False)}")
            return result
        except Exception as e:
            logger.warning(f"[DEBUG-SOP-ROUTE] LLM 意图分类异常: {e}")
            return None

    # 两阶段 SOP 路由：关键词粗筛 → LLM 精排 + 拒绝
    def route(
        self,
        user_query: str,
        config_name: str = None,
        mode: str = "instruct"
    ) -> RouteResult:
        """两阶段 SOP 匹配：关键词粗筛召回候选，LLM 精排并判断置信度，低于阈值则拒绝。"""
        logger.info(f"[DEBUG-SOP-ROUTE] ==================== SOP ROUTE 开始 ====================")
        logger.info(f"[DEBUG-SOP-ROUTE] 用户查询: {user_query[:150]}{'...' if len(user_query) > 150 else ''}")
        logger.info(f"[DEBUG-SOP-ROUTE] 配置参数: config_name={config_name}, mode={mode}")
        logger.info(f"[DEBUG-SOP-ROUTE] 系统参数: TOP_K={ROUTE_RECALL_TOP_K}, MIN_SCORE={ROUTE_RECALL_MIN_SCORE}, CONFIDENCE_THRESHOLD={ROUTE_CONFIDENCE_THRESHOLD}")
        logger.info(f"[DEBUG-SOP-ROUTE] 可用 SOP 总数: {len(self.sops)}, IDs: {[s.id for s in self.sops]}")

        if not self.sops:
            logger.warning("[DEBUG-SOP-ROUTE] 没有可用的 SOP 列表进行匹配")
            return RouteResult(sop=None, args={}, reason="无可用SOP", confidence=0.0, candidates=[])

        # Step 1: 关键词粗筛
        logger.info("[DEBUG-SOP-ROUTE] ---------- Stage 1: TF-IDF 关键词召回 ----------")
        doc_ids, documents = _build_sop_corpus(self.sops)
        recall_results = _keyword_recall(user_query, doc_ids, documents)

        if not recall_results:
            logger.warning(f"[DEBUG-SOP-ROUTE] 关键词粗筛无命中，fallback 到全量 SOP (共{len(self.sops)}个)")
            recall_results = [(sop.id, 0.0) for sop in self.sops]

        logger.info(f"[DEBUG-SOP-ROUTE] Stage 1 完成: 召回 {len(recall_results)} 个候选 SOP")

        # 构建候选 SOP 详情
        id_to_sop = {s.id: s for s in self.sops}
        candidates = []
        for sop_id, score in recall_results:
            sop = id_to_sop.get(sop_id)
            if sop:
                bb = sop.blackboard or {}
                candidate = {
                    "id": sop.id,
                    "name_zh": sop.name_zh or sop.id,
                    "description": sop.description_zh or sop.description or "无描述",
                    "required_params": bb.get("required") or [],
                    "outputs": bb.get("outputs") or [],
                    "recall_score": round(score, 4),
                }
                candidates.append(candidate)
                logger.debug(f"[DEBUG-SOP-ROUTE] 候选 SOP: {candidate['id']} (score={candidate['recall_score']}, params={candidate['required_params']}, outputs={candidate['outputs']})")

        # Step 2: LLM 精排 + 拒绝 + 参数提取（合并为单次调用）
        logger.info("[DEBUG-SOP-ROUTE] ---------- Stage 2: LLM 精排 + 置信度判断 + 参数提取 ----------")
        candidates_detail = "\n".join(
            f"- ID: {c['id']}, 名称: {c['name_zh']}, 描述: {c['description']}, "
            f"所需参数: {c['required_params']}"
            + (
                f", 参数说明: {{{', '.join(f'{p}: {PARAM_DESCRIPTIONS[p]}' for p in c['required_params'] if p in PARAM_DESCRIPTIONS)}}}"
                if any(p in PARAM_DESCRIPTIONS for p in c['required_params']) else ""
            )
            + f", 输出: {c['outputs']}"
            for c in candidates
        )

        param_hints = "\n".join(
            f"  \"{k}\": \"{v}\"" for k, v in PARAM_DESCRIPTIONS.items()
        )

        system_prompt = f"""你是一个工程规范领域的 SOP 匹配器。判断用户问题是否与某个候选 SOP 语义匹配，并提取所需参数。

候选 SOP 列表：
{candidates_detail}

常见参数名含义参考：
{param_hints}

输出 JSON 对象：
{{
  "sop_id": "匹配的 SOP ID，如果没有匹配则返回 null",
  "confidence": 0.0到1.0的置信度,
  "reason": "匹配或不匹配的原因",
  "args": {{"字段名": "从用户问题中提取的值或null", ...}}
}}

重要规则：
- 只有当用户问题的计算目标与 SOP 的输出高度一致时才匹配
- 如果用户问题只是部分相关或需要多个 SOP 协同，返回 null
- confidence 反映语义匹配程度：1.0=完全匹配，0.7=高度相关，0.5=部分相关，0.3=弱相关
- confidence < {ROUTE_CONFIDENCE_THRESHOLD} 视为不匹配
- 如果 sop_id 不为 null，则需要根据候选列表中的"所需参数"字段，从用户问题中提取对应的参数值填入 args
- 注意参考"常见参数名含义参考"理解缩写参数名的含义，例如"H"对应题目中的"波高"，"L"对应"波长"
- 值中不要带单位后缀，例如"3.5m"应提取为"3.5"
- 如果无法确定某个字段值，该字段返回 null"""

        logger.debug(f"[DEBUG-SOP-ROUTE] 发送给 LLM 的候选列表:\n{candidates_detail}")

        try:
            logger.debug("[DEBUG-SOP-ROUTE] 调用 LLM 进行精排...")
            response_text = self._llm_client.chat(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"用户问题: {user_query}"},
                ],
                mode=mode,
                config_name=config_name,
            )
            logger.info(f"[DEBUG-SOP-ROUTE] LLM 精排原始响应: {response_text}")
        except Exception as e:
            logger.error(f"[DEBUG-SOP-ROUTE] LLM 精排调用失败: {e}", exc_info=True)
            return RouteResult(sop=None, args={}, reason=f"LLM精排失败: {e}", confidence=0.0, candidates=candidates)

        if not response_text:
            logger.warning("[DEBUG-SOP-ROUTE] LLM 精排响应为空")
            return RouteResult(sop=None, args={}, reason="LLM精排响应为空", confidence=0.0, candidates=candidates)

        try:
            parsed = extract_json_from_text(response_text)
            if not parsed:
                logger.warning(f"[DEBUG-SOP-ROUTE] LLM 精排响应无法解析: {response_text[:200]}")
                return RouteResult(sop=None, args={}, reason="LLM精排响应解析失败", confidence=0.0, candidates=candidates)

            sop_id = parsed.get("sop_id")
            confidence = float(parsed.get("confidence", 0.0))
            reason = parsed.get("reason", "")
            raw_args = parsed.get("args", {}) or {}
            args = {k: v for k, v in raw_args.items() if v is not None} if isinstance(raw_args, dict) else {}

            logger.info(f"[DEBUG-SOP-ROUTE] LLM 解析结果: sop_id={sop_id}, confidence={confidence:.4f}, reason={reason}, args={args}")

            if not sop_id or str(sop_id).lower() in ["null", "none", "nan", ""]:
                logger.info(f"[DEBUG-SOP-ROUTE] ✗ LLM 精排拒绝匹配: {reason}")
                logger.info(f"[DEBUG-SOP-ROUTE] ==================== SOP ROUTE 结束 (无匹配) ====================\n")
                return RouteResult(sop=None, args={}, reason=reason, confidence=confidence, candidates=candidates)

            if confidence < ROUTE_CONFIDENCE_THRESHOLD:
                logger.info(f"[DEBUG-SOP-ROUTE] ✗ LLM 置信度不足: confidence={confidence:.4f} < threshold={ROUTE_CONFIDENCE_THRESHOLD}, reason={reason}")
                logger.info(f"[DEBUG-SOP-ROUTE] ==================== SOP ROUTE 结束 (置信度不足) ====================\n")
                return RouteResult(sop=None, args={}, reason=f"置信度不足({confidence:.2f}): {reason}", confidence=confidence, candidates=candidates)

            # 查找匹配的 SOP
            sop_id_str = str(sop_id).strip()
            selected_sop = next(
                (s for s in self.sops if s.id.strip().lower() == sop_id_str.lower()),
                None
            )
            if not selected_sop:
                selected_sop = next(
                    (s for s in self.sops if s.name_zh and s.name_zh.strip() == sop_id_str),
                    None
                )

            if not selected_sop:
                available_ids = [s.id for s in self.sops]
                logger.warning(f"[DEBUG-SOP-ROUTE] LLM 返回了未知的 SOP ID: '{sop_id_str}', 可用SOP: {available_ids}")
                logger.info(f"[DEBUG-SOP-ROUTE] ==================== SOP ROUTE 结束 (未知SOP) ====================\n")
                return RouteResult(sop=None, args={}, reason=f"未知SOP ID: {sop_id_str}", confidence=confidence, candidates=candidates)

            required_params = list((selected_sop.blackboard or {}).get("required") or [])
            args = _supplement_sop_args_from_query(user_query, required_params, args)

            logger.info(f"✓ SOP 匹配成功: {selected_sop.id} (confidence={confidence:.4f}, args={args})")
            logger.info(f"[DEBUG-SOP-ROUTE] ==================== SOP ROUTE 结束 (匹配成功) ====================\n")

            logger.info(f"SOP 匹配成功: {selected_sop.id}, confidence={confidence:.2f}, reason={reason}")

            return RouteResult(
                sop=selected_sop,
                args=args,
                reason=reason,
                confidence=confidence,
                candidates=candidates,
            )

        except Exception as e:
            logger.error(f"LLM 精排解析错误: {e}")
            return RouteResult(sop=None, args={}, reason=f"精排解析错误: {e}", confidence=0.0, candidates=candidates)

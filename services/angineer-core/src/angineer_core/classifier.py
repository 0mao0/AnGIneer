"""
意图分类核心模块，负责根据用户问题选择合适的 SOP 并提取参数。
"""
import json
import math
import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import List, Optional, Tuple, Dict, Any

from angineer_core.base_contracts import SOP, AgentResponse, IntentResult, IntentLevel, ServiceMode, RouteResult
from angineer_core.base_config import SOP_ROUTE_CONFIDENCE_THRESHOLD as ROUTE_CONFIDENCE_THRESHOLD
from ai_inference.llm_client import chat_result_guarded, get_llm_client
from ai_inference.llm_response_parser import (
    extract_json_from_text,
)
from angineer_core.base_contracts import IntentResponse
from angineer_core.base_logger import get_logger
from angineer_core.prompts.classifier import (
    CLASSIFY_INTENT_SYSTEM_PROMPT,
    ROUTE_SOP_SYSTEM_PROMPT,
)

logger = get_logger(__name__)

L0_PURE_CHAT_KEYWORDS = ["你好", "您好", "嗨", "hi", "hello", "早上好", "下午好", "晚上好", "早安", "晚安",
                          "谢谢", "感谢", "辛苦了", "再见", "拜拜",
                          "心情", "开心", "难过", "无聊", "累", "烦", "高兴", "生气", "焦虑",
                          "今天天气", "吃了吗", "在吗", "聊聊天", "闲聊", "笑话"]
L0_AMBIGUOUS_KEYWORDS = ["你是谁", "你叫什么", "能做什么", "有什么功能", "帮我", "怎么用"]
L1_KEYWORDS = ["什么是", "是什么", "哪些", "定义", "概念", "组成", "包括", "分为", "划分", "分类", "类型", "位于", "设置", "位置", "在哪里", "宜设置", "应设置", "如何确定", "怎么确定", "怎样确定", "如何定义", "怎么定义", "如何划分", "怎么划分", "简述", "说明", "列举", "阐述", "解释", "原理", "作用", "功能", "特点", "特征", "区别", "异同", "对比", "比较", "差异", "选用", "选型", "适用条件", "适用范围", "影响因素", "注意事项",
               # 废 meta_query 路由（第二步）：统计/计数类问法并入 L1 判据——既补 _has_substantive_content
               # 的 L0 兜底（统计题不再被闲聊分支吞掉），也使规则兜底路径把统计题归 L1 semantic_retrieval；
               # 刻意只收计数词、不收「分布/统计/趋势」（与工程词重叠，见已删 META_QUERY_VERBS 的 2026-09-06 复盘）
               "多少", "几篇", "几份", "几本", "几个", "数量", "总数"]
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

ROUTE_RECALL_TOP_K = 5
ROUTE_RECALL_MIN_SCORE = 0.02


def _route_llm_timeout_s() -> float:
    """精排 LLM 单次调用预算（秒），``ANGINEER_SOP_ROUTE_LLM_TIMEOUT`` 覆盖。

    无内层预算时精排挂起会烧满 sop_execute 的 loop 级 120s 工具超时才报错
    （agent_loop 只按 config.tool_timeout_s 掐，不知内部构成）；加内层闸让
    挂起在 ~30s 走既有「精排失败 → 回 error → 模型转检索」降级路。
    """
    try:
        return max(1.0, float(os.getenv("ANGINEER_SOP_ROUTE_LLM_TIMEOUT", "30")))
    except ValueError:
        return 30.0

# 各意图层级的默认升级链：当前路径失败后逐级回退
DEFAULT_EXECUTION_PLANS: Dict[str, List[str]] = {
    "L0": ["casual_chat"],
    "L1": ["semantic_retrieval"],
    "L2": ["structured_lookup", "semantic_retrieval"],
    "L3": ["standard_sop", "semantic_retrieval"],
    "L4": ["dynamic_orchestration"],
}

# 简短参数名 → 中文含义映射，帮助 LLM 理解 SOP 参数并正确提取。
# 领域内容已外置到领域知识包（angineer_core/domain_packs/*.json），经
# ANGINEER_SOP_DOMAIN_PACK 启用后由构造参数注入；引擎默认不带任何领域词条。
PARAM_DESCRIPTIONS: Dict[str, str] = {}
# 统计/元数据查询规则已随废 meta_query 路由删除（2026-10-02 第二步）：原 META_QUERY_VERBS/
# META_QUERY_TARGETS/_is_meta_query 统计题改由 L1 semantic_retrieval + 工具自选承接
# （knowledge_stats 已下沉 L1 工具箱）；计数问法并入 L1_KEYWORDS 维持 L0 兜底判据。


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


def _derive_extra_args_from_query(query: str, domain: Any = None) -> Dict[str, Any]:
    """从题面派生 SOP 补充参数（领域包规则版；domain=None 时无领域规则=通用空派生）。"""
    from angineer_core.domain_arg_rules import derive_extra

    return derive_extra(query, domain)


def _clean_extracted_arg(param_name: str, value: Any, query: str, domain: Any = None) -> Any:
    """清洗抽取结果（通用尾裁 + 领域包 clean_rules；domain=None 时仅通用清洗）。"""
    from angineer_core.domain_arg_rules import clean_arg

    return clean_arg(param_name, value, query, domain)


def _supplement_sop_args_from_query(
    query: str,
    required_params: List[str],
    base_args: Dict[str, Any],
    domain: Any = None,
) -> Dict[str, Any]:
    """按 SOP required 提参并补派生参数（领域包规则版；domain=None 时仅做通用清洗）。"""
    from angineer_core.domain_arg_rules import supplement_args

    return supplement_args(query, required_params, base_args, domain)


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


# 条款号快路径（需求 §5.3 靶子，2026-09-26）：「应符合/应满足哪条规范」「在哪条规范里」类问句
# 问的是条款出处而非条款内容，现役 LLM 分类器实测会漏成 L1（§8 对照 4 例），规则直达 L2 更准也更快。
# 刻意保持窄口径（动词+哪条 或 哪条+规范名词）防误伤；开关 ANGINEER_CLAUSE_FASTPATH 默认开。
_CLAUSE_NUMBER_PATTERN = re.compile(
    r"(?:应符合|应满足|应符合于|符合|满足|查)哪条"
    r"|在哪条(?:规范|规定|条款|标准|条文)"
    r"|哪条(?:规范|规定|条款|标准|条文)"
)


def _clause_fastpath_enabled() -> bool:
    return (os.getenv("ANGINEER_CLAUSE_FASTPATH", "true") or "").strip().lower() not in ("0", "false", "no", "off")


def _is_clause_number_query(query: str) -> bool:
    if not query:
        return False
    return bool(_CLAUSE_NUMBER_PATTERN.search(query))


# 计算方法问句快路径（2026-10-16，docs/req-calc-method-l2-routing.md）：
# 「XX怎么计算/如何计算/计算公式是什么」类问句（计算动词 + 题面零数值）问的是方法与公式
# （规范条款查证，L2），不是执行计算（L3 需具体数值参数 + SOP 承接）。
# 生产实况：同句 2026-10-04→10-06 被 LLM 从 L1 漂到 L3，L3 链路无 SOP 可执行即缺参/拒答。
# 刻意窄口径（问句尾巴限定）防误伤；开关 ANGINEER_CALC_METHOD_FASTPATH 默认开。
_CALC_METHOD_PATTERN = re.compile(
    r"(?:怎么|如何|怎样)(?:计算|算(?!法)|求解|求|算出|得出|推算)"
    r"|(?:计算|求解|(?<![寻请要需])求)(?:公式|方法|步骤|过程)\s*"
    r"(?:是什么|是啥|是多少|怎么样|是怎样的|为多少|为|有哪些|分别|呢|[?？]|$)"
)

_DIGIT_PATTERN = re.compile(r"[0-9０-９]")


def _calc_method_fastpath_enabled() -> bool:
    return (os.getenv("ANGINEER_CALC_METHOD_FASTPATH", "true") or "").strip().lower() not in ("0", "false", "no", "off")


def _is_calc_method_query(query: str) -> bool:
    if not query:
        return False
    if _DIGIT_PATTERN.search(query):
        return False
    return bool(_CALC_METHOD_PATTERN.search(query))


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
            service_mode="structured_lookup",
            execution_plan=["structured_lookup", "standard_sop", "dynamic_orchestration"],
            reason="检测到条文/规范定位信号与计算特征，先走 L2 定位依据，必要时回退到 L3/L4",
        )

    # 规范编号精确查找（如 JGJ 162、GB 50010、JTS 165-2025 等）
    if standard_code_match:
        return _build_intent_result(
            intent_level="L2",
            intent_type="standard_lookup",
            parameters={"standard_code": standard_code_match.group(0)},
            required_capabilities=["retrieval", "sql"],
            service_mode="structured_lookup",
            reason=f"检测到规范编号({standard_code_match.group(0)})，走条款/表格精确查证",
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
            service_mode="structured_lookup",
            reason=f"检测到条款编号({clause_id_value})和条款关键词",
        )

    # ========== 渐进式意图层级判定（L1 → L2 → L3 → L4） ==========
    # 原则：低层级优先，只有明确不满足低层级特征时才进入更高层级
    
    has_l1_keyword = any(kw in query for kw in L1_KEYWORDS)
    has_l4_compound = any(kw in query for kw in L4_COMPOUND_SIGNALS)

    # 计算方法问句（无数值参数）→ L2 条款/公式查证（与计算快路径同口径；2026-10-16）
    # 必须置于 L1 分支之前：L1_KEYWORDS 含「是什么」，否则「计算公式是什么」会被 L1 先截胡（实测）
    if _calc_method_fastpath_enabled() and _is_calc_method_query(query):
        return _build_intent_result(
            intent_level="L2",
            intent_type="method_lookup",
            required_capabilities=["retrieval", "sql"],
            service_mode="structured_lookup",
            reason="计算方法问句（无数值参数）：规则归 L2 条款/公式查证（计算快路径同口径）",
        )
    
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
            service_mode="structured_lookup",
            reason="检测到条款应用关键词",
        )

    return None


class IntentClassifier:
    """意图分类器，负责分析用户查询并匹配最合适的 SOP。"""

    def __init__(
        self,
        sops: List[SOP],
        llm_client=None,
        param_descriptions: Optional[Dict[str, str]] = None,
        domain_args: Optional[Any] = None,
    ):
        """
        初始化意图分类器。

        Args:
            sops: 可用的 SOP 列表
            llm_client: 可选的 LLM 客户端实例，默认使用全局实例
            param_descriptions: 领域参数释义（来自领域知识包），供 route() 精排提示；
                缺省为空=不注入参数说明，行为保持通用
        """
        self.sops = sops
        self._llm_client = llm_client or get_llm_client()
        self._param_descriptions = dict(param_descriptions) if param_descriptions else {}
        self._domain_args = domain_args  # 领域参数规则包（DomainHints）；None=通用行为
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
        error_sink: Optional[List[str]] = None,
    ) -> IntentResult:
        """公开入口：计时 + 观测落盘（data/ops/classify-*.jsonl，需求 §3.2 口径），转调实现。"""
        import time as _time

        _t0 = _time.perf_counter()
        result = self._classify_intent_impl(user_query, config_name=config_name, mode=mode, error_sink=error_sink)
        try:
            from angineer_core.ops_metrics import record_event

            record_event(
                "classify",
                {
                    "dur_ms": round((_time.perf_counter() - _t0) * 1000, 1),
                    "level": getattr(result, "intent_level", None),
                    "mode": getattr(result, "service_mode", None),
                    "query": user_query,
                    "reason": getattr(result, "reason", None),
                },
            )
        except Exception:  # noqa: BLE001
            pass
        return result

    def _classify_intent_impl(
        self,
        user_query: str,
        config_name: str = None,
        mode: str = "instruct",
        error_sink: Optional[List[str]] = None,
    ) -> IntentResult:
        """error_sink：LLM 分类被吞掉的失败留痕（评测哨兵 b），不影响降级路径本身。"""
        logger.info(f"[DEBUG-SOP-ROUTE] ===== 意图分类开始 =====")
        logger.info(f"[DEBUG-SOP-ROUTE] 用户查询: {user_query[:100]}{'...' if len(user_query) > 100 else ''}")
        logger.info(f"[DEBUG-SOP-ROUTE] 配置: config_name={config_name}, mode={mode}")

        # 步骤 1: 规则优先检查 L0（闲聊/问候，规则足够精准）
        l0_result = _check_l0_intent(user_query)
        if l0_result:
            logger.info(f"[DEBUG-SOP-ROUTE] L0 规则命中: reason={l0_result.reason}")
            return l0_result

        # 步骤 1.5: 强 L1 定位信号优先于 LLM（避免“XX在哪里”被 LLM 判为 L2 后表格问答链路不稳定）
        location_result = _rule_based_classify(user_query)
        if location_result is not None and location_result.intent_level == "L1" and location_result.intent_type == "locate_navigation":
            logger.info(f"[DEBUG-SOP-ROUTE] L1 定位信号规则优先命中: reason={location_result.reason}")
            return location_result

        # 步骤 1.6: 统计/元数据查询规则已删（废 meta_query 路由第二步）——统计题走 LLM 判 L1，
        # knowledge_stats 由 L1 档工具箱按工具描述自选承接

        # 步骤 1.7: 条款号快路径（默认开，ANGINEER_CLAUSE_FASTPATH=false 关闭）
        if _clause_fastpath_enabled() and _is_clause_number_query(user_query):
            clause_result = _build_intent_result(
                intent_level="L2",
                intent_type="clause_lookup",
                required_capabilities=["retrieval", "sql"],
                service_mode="structured_lookup",
                reason="条款号查询快路径：问句在问条款出处（符合/满足/在哪条规范类），规则直达 L2",
            )
            logger.info(f"[DEBUG-SOP-ROUTE] 条款号快路径命中: {user_query[:50]}")
            return clause_result

        # 步骤 1.8: 计算方法问句快路径（2026-10-16，docs/req-calc-method-l2-routing.md）
        # 「堤顶高程怎么计算」类：问方法/公式而非执行计算（题面无数值参数），规则直达 L2。
        if _calc_method_fastpath_enabled() and _is_calc_method_query(user_query):
            calc_method_result = _build_intent_result(
                intent_level="L2",
                intent_type="method_lookup",
                required_capabilities=["retrieval", "sql"],
                service_mode="structured_lookup",
                reason="计算方法问句快路径：似查公式/方法而非执行计算（无数值参数），规则直达 L2",
            )
            logger.info(f"[DEBUG-SOP-ROUTE] 计算方法问句快路径命中: {user_query[:50]}")
            return calc_method_result

        # 步骤 2: LLM 直接分类 L1/L2/L3/L4（主力分类器）
        logger.debug("[DEBUG-SOP-ROUTE] 非L0查询，进入 LLM 主力分类...")
        llm_result = self._llm_classify_intent(user_query, config_name=config_name, mode=mode, error_sink=error_sink)
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
        error_sink: Optional[List[str]] = None,
    ) -> Optional[IntentResult]:
        """LLM 主力分类器：直接判定 L1/L2/L3/L4，含置信度阈值过滤。

        error_sink 只收"LLM 侧故障"（异常/空响应——53 题全灭事故的典型签名），
        不收解析失败与低置信度（那是模型真实输出，属正常降级）。"""
        system_prompt = CLASSIFY_INTENT_SYSTEM_PROMPT
        try:
            logger.debug("[DEBUG-SOP-ROUTE] 调用 LLM 进行意图分类...")
            result = chat_result_guarded(
                self._llm_client,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"用户问题: {user_query}"},
                ],
                mode=mode,
                config_name=config_name,
            )
            response_text = result.text
            logger.debug(f"[DEBUG-SOP-ROUTE] LLM 意图分类原始响应: {response_text[:200]}{'...' if len(response_text) > 200 else ''}")

            if not response_text:
                logger.warning("[DEBUG-SOP-ROUTE] LLM 意图分类响应为空")
                if error_sink is not None:
                    error_sink.append("意图分类 LLM 空响应")
                return None
            parsed = extract_json_from_text(response_text, strict=True)
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
            if error_sink is not None:
                error_sink.append(f"意图分类 LLM 异常: {str(e)[:300]}")
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
        param_desc = self._param_descriptions
        candidates_detail = "\n".join(
            f"- ID: {c['id']}, 名称: {c['name_zh']}, 描述: {c['description']}, "
            f"所需参数: {c['required_params']}"
            + (
                f", 参数说明: {{{', '.join(f'{p}: {param_desc[p]}' for p in c['required_params'] if p in param_desc)}}}"
                if any(p in param_desc for p in c['required_params']) else ""
            )
            + f", 输出: {c['outputs']}"
            for c in candidates
        )

        param_hints = "\n".join(
            f"  \"{k}\": \"{v}\"" for k, v in param_desc.items()
        )

        system_prompt = ROUTE_SOP_SYSTEM_PROMPT.format(
            candidates_detail=candidates_detail,
            param_hints=param_hints,
            threshold=ROUTE_CONFIDENCE_THRESHOLD,
        )

        logger.debug(f"[DEBUG-SOP-ROUTE] 发送给 LLM 的候选列表:\n{candidates_detail}")

        try:
            logger.debug("[DEBUG-SOP-ROUTE] 调用 LLM 进行精排...")
            # 内层超时闸（同 sop_runner llm_generate 模式）：网关挂起时内层先超时，
            # 走下方统一的精排失败降级路，而非烧满 sop_execute 的 120s 工具预算。
            route_timeout = _route_llm_timeout_s()
            executor = ThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(
                    chat_result_guarded,
                    self._llm_client,
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"用户问题: {user_query}"},
                    ],
                    mode=mode,
                    config_name=config_name,
                )
                result = future.result(timeout=route_timeout)
            except FuturesTimeoutError:
                # 超时后立即放弃等待；线程未杀死（泄漏至客户端总超时，与全仓同款限制）
                logger.warning(
                    "[DEBUG-SOP-ROUTE] LLM 精排超时（%ss），按精排失败降级（线程未杀死）",
                    route_timeout,
                )
                return RouteResult(
                    sop=None, args={},
                    reason=f"LLM精排超时（{route_timeout}s），已降级",
                    confidence=0.0, candidates=candidates,
                )
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
            response_text = result.text
            logger.info(f"[DEBUG-SOP-ROUTE] LLM 精排原始响应: {response_text}")
        except Exception as e:
            logger.error(f"[DEBUG-SOP-ROUTE] LLM 精排调用失败: {e}", exc_info=True)
            return RouteResult(sop=None, args={}, reason=f"LLM精排失败: {e}", confidence=0.0, candidates=candidates)

        if not response_text:
            logger.warning("[DEBUG-SOP-ROUTE] LLM 精排响应为空")
            return RouteResult(sop=None, args={}, reason="LLM精排响应为空", confidence=0.0, candidates=candidates)

        try:
            parsed = extract_json_from_text(response_text, strict=True)
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
            args = _supplement_sop_args_from_query(user_query, required_params, args, domain=self._domain_args)

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

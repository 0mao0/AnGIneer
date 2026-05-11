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
    parse_and_validate,
    ParseError,
)
from angineer_core.base_contracts import IntentResponse, ArgsExtractResponse
from angineer_core.base_logger import get_logger

logger = get_logger(__name__)

L0_PURE_CHAT_KEYWORDS = ["你好", "您好", "嗨", "hi", "hello", "早上好", "下午好", "晚上好", "早安", "晚安",
                          "谢谢", "感谢", "辛苦了", "再见", "拜拜",
                          "心情", "开心", "难过", "无聊", "累", "烦", "高兴", "生气", "焦虑",
                          "今天天气", "吃了吗", "在吗", "聊聊天", "闲聊"]
L0_AMBIGUOUS_KEYWORDS = ["你是谁", "你叫什么", "能做什么", "有什么功能", "帮我", "怎么用"]
L1_KEYWORDS = ["什么是", "是什么", "哪些", "定义", "概念", "组成", "包括", "分为", "划分", "分类", "类型", "位于", "设置", "位置", "在哪里", "宜设置", "应设置", "如何确定", "怎么确定", "怎样确定", "如何定义", "怎么定义", "如何划分", "怎么划分"]
L2_KEYWORDS = ["取值", "范围", "规定", "条款", "要求", "标准值", "限值", "允许值", "应符合", "不应超过"]
L3_KEYWORDS = ["计算", "求", "验算", "核算", "校核", "公式", "等于多少", "结果是多少"]
L4_KEYWORDS = ["评价", "评估", "分析", "综合", "方案", "设计", "比较", "选择", "优化"]

CLAUSE_ID_PATTERN = re.compile(r"(?:第\s*)?(\d+(?:\.\d+){1,4})\s*(条|款|节|章)?")

PARAM_PATTERN = re.compile(r"([a-zA-Zα-ωΑ-Ω][a-zA-Zα-ωΑ-Ω_]*)\s*[=＝]\s*([\d.]+)")
NUM_VALUE_PATTERN = re.compile(r"[\d]+(?:\.\d+)?(?:\s*(?:m|t|吨|级|kn|°|%%|s|mm|cm|km|m/s|kg/m|万|亿))")

STANDARD_CODE_PATTERN = re.compile(
    r"(?:GB|GB/T|JGJ|JGJ/T|JTS|JTJ|JTG|JTG/T|JTSC|CJJ|CJJ/T|DL|DL/T|SL|SL/T|NB|NB/T|SY|SY/T|HJ|HJ/T|YB|YB/T|TB|TB/T|SH|SH/T|HG|HG/T|CECS|DB)\s*[/\-]?\s*\d+(?:\s*[-—–]\s*\d+)?",
    re.IGNORECASE,
)

ROUTE_CONFIDENCE_THRESHOLD = 0.6
ROUTE_RECALL_TOP_K = 3
ROUTE_RECALL_MIN_SCORE = 0.05


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
        return []

    all_docs = documents + [query]
    tokenized = [_char_bigrams(d) for d in all_docs]

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

    results = []
    for i, doc_tokens in enumerate(tokenized[:-1]):
        doc_vec = _tfidf(doc_tokens)
        dot = sum(query_vec.get(t, 0) * doc_vec.get(t, 0) for t in query_vec)
        q_norm = math.sqrt(sum(v ** 2 for v in query_vec.values())) if query_vec else 0
        d_norm = math.sqrt(sum(v ** 2 for v in doc_vec.values())) if doc_vec else 0
        score = dot / (q_norm * d_norm) if q_norm > 0 and d_norm > 0 else 0.0
        if score >= min_score:
            results.append((doc_ids[i], score))

    results.sort(key=lambda x: x[1], reverse=True)
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


# 基于规则快速判定意图层级
def _rule_based_classify(query: str) -> Optional[IntentResult]:
    if not query:
        return None

    # L0: 闲聊检测 — 纯闲聊关键词直接判定
    has_pure_chat = any(kw in query for kw in L0_PURE_CHAT_KEYWORDS)
    has_ambiguous = any(kw in query for kw in L0_AMBIGUOUS_KEYWORDS)
    if has_pure_chat and not has_ambiguous and not _has_substantive_content(query):
        return IntentResult(
            intent_level="L0",
            intent_type="casual_chat",
            parameters={},
            required_capabilities=[],
            service_mode="casual_chat",
            reason="检测到纯闲聊关键词",
        )
    if has_ambiguous and not _has_substantive_content(query):
        return IntentResult(
            intent_level="L0",
            intent_type="casual_chat",
            parameters={},
            required_capabilities=[],
            service_mode="casual_chat",
            reason="检测到歧义闲聊关键词且无实质性内容",
        )

    # 规范编号精确查找（如 JGJ 162、GB 50010、JTS 165-2025 等）
    standard_code_match = STANDARD_CODE_PATTERN.search(query)
    if standard_code_match:
        return IntentResult(
            intent_level="L2",
            intent_type="standard_lookup",
            parameters={"standard_code": standard_code_match.group(0)},
            required_capabilities=["retrieval", "sql"],
            service_mode="sql_first",
            reason=f"检测到规范编号({standard_code_match.group(0)})，走SQL精确检索",
        )

    clause_match = CLAUSE_ID_PATTERN.search(query)
    param_matches = PARAM_PATTERN.findall(query)
    has_l2_keyword = any(kw in query for kw in L2_KEYWORDS)
    has_l3_keyword = any(kw in query for kw in L3_KEYWORDS)
    has_l4_keyword = any(kw in query for kw in L4_KEYWORDS)
    if param_matches and has_l3_keyword:
        return IntentResult(
            intent_level="L3",
            intent_type="standard_calculation",
            parameters={name: float(value) for name, value in param_matches},
            required_capabilities=["retrieval", "calculation", "sop"],
            service_mode="standard_sop",
            reason=f"检测到参数提取({len(param_matches)}个)和计算关键词",
        )
    num_values = NUM_VALUE_PATTERN.findall(query)
    is_multiple_choice = bool(re.search(r"\([A-D]\)", query) or re.search(r"[（][A-D][）]", query))
    if has_l3_keyword and len(num_values) >= 2:
        return IntentResult(
            intent_level="L3",
            intent_type="standard_calculation",
            parameters={"num_values_count": len(num_values)},
            required_capabilities=["retrieval", "calculation", "sop"],
            service_mode="standard_sop",
            reason=f"检测到计算关键词和{len(num_values)}个数值参数(考试题模式)",
        )
    if clause_match and has_l2_keyword:
        return IntentResult(
            intent_level="L2",
            intent_type="clause_application",
            parameters={"clause_id": clause_match.group(1)},
            required_capabilities=["retrieval", "sql"],
            service_mode="sql_first",
            reason=f"检测到条款编号({clause_match.group(1)})和条款关键词",
        )

    has_l1_keyword = any(kw in query for kw in L1_KEYWORDS)
    if has_l1_keyword:
        if any(kw in query for kw in ["位于", "设置", "位置", "在哪里", "宜设置", "应设置"]):
            return IntentResult(
                intent_level="L1",
                intent_type="locate_navigation",
                parameters={},
                required_capabilities=["retrieval"],
                service_mode="semantic_retrieval",
                reason="检测到定位/位置类关键词",
            )
        return IntentResult(
            intent_level="L1",
            intent_type="concept_resolution",
            parameters={},
            required_capabilities=["retrieval"],
            service_mode="semantic_retrieval",
            reason="检测到概念/定义类关键词",
        )

    if has_l4_keyword:
        return IntentResult(
            intent_level="L4",
            intent_type="complex_task",
            parameters={},
            required_capabilities=["retrieval", "calculation", "sop", "orchestration"],
            service_mode="dynamic_orchestration",
            reason="检测到复杂任务关键词",
        )
    if has_l3_keyword:
        return IntentResult(
            intent_level="L3",
            intent_type="standard_calculation",
            parameters={name: float(value) for name, value in param_matches} if param_matches else {},
            required_capabilities=["retrieval", "calculation", "sop"],
            service_mode="standard_sop",
            reason="检测到计算关键词",
        )
    if has_l2_keyword:
        return IntentResult(
            intent_level="L2",
            intent_type="clause_application",
            parameters={"clause_id": clause_match.group(1)} if clause_match else {},
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
        logger.info(f"意图分类器初始化完成，加载了 {len(sops)} 个 SOP")

    # L1~L4 元意图分类与 service mode 决策
    def classify_intent(
        self,
        user_query: str,
        config_name: str = None,
        mode: str = "instruct",
    ) -> IntentResult:
        rule_result = _rule_based_classify(user_query)
        if rule_result:
            logger.info(f"规则快速匹配意图: L{rule_result.intent_level}, mode={rule_result.service_mode}")
            return rule_result

        llm_result = self._llm_classify_intent(user_query, config_name=config_name, mode=mode)
        if llm_result:
            return llm_result

        return IntentResult(
            intent_level="L1",
            intent_type="concept_resolution",
            parameters={},
            required_capabilities=["retrieval"],
            service_mode="semantic_retrieval",
            reason="默认降级为L1语义检索",
        )

    # 调用 LLM 进行意图分类
    def _llm_classify_intent(
        self,
        user_query: str,
        config_name: str = None,
        mode: str = "instruct",
    ) -> Optional[IntentResult]:
        system_prompt = """你是工程规范领域的意图分类器。根据用户问题判断意图层级和服务模式。

## 意图层级定义

| 层级 | 名称 | 判定特征 | service_mode（必须严格对应） |
|------|------|----------|------------------------------|
| L0 | 闲聊寒暄 | 问候、情感表达、日常闲聊、自我介绍请求，与工程规范无关 | casual_chat |
| L1 | 概念解析 | 问"什么是XX"、"XX的定义/原理"，无具体参数 | semantic_retrieval |
| L2 | 条款应用 | 问条款取值、规范参数、简单查表，不需要多步计算流程 | sql_first |
| L3 | 标准计算 | 有具体数值参数需要计算，且存在预定义SOP可承接（如码头水深、航道宽度、顶高程等标准工程计算） | standard_sop |
| L4 | 复杂任务 | 无预定义SOP可承接的复合任务、综合分析、方案设计 | dynamic_orchestration |

## 关键判断规则

0. 如果用户只是打招呼、闲聊、表达情绪、问你是谁，与工程规范无关 = L0 / casual_chat
1. 只要题目包含"计算/求/验算"等动词 + 多个工程参数（吨级、水位、波高等），优先判为 L3 / standard_sop
2. 考试选择题（带选项ABCD）+ 计算类 = L3 / standard_sop
3. 只有概念问答 = L1 / semantic_retrieval
4. 只有条款编号或取值查询 = L2 / sql_first
5. 综合性评价/设计/多步骤复合题 = L4 / dynamic_orchestration

输出JSON对象（service_mode 必须从上述五种中选一）：
{
  "intent_level": "L1",
  "intent_type": "简短意图标签",
  "parameters": {"提取的参数": "值"},
  "required_capabilities": ["retrieval"],
  "service_mode": "semantic_retrieval",
  "reason": "一句话说明判断依据"
}"""
        try:
            response_text = self._llm_client.chat(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"用户问题: {user_query}"},
                ],
                mode=mode,
                config_name=config_name,
            )
            if not response_text:
                return None
            parsed = extract_json_from_text(response_text)
            if not parsed:
                return None
            return IntentResult(
                intent_level=parsed.get("intent_level", "L1"),
                intent_type=parsed.get("intent_type", ""),
                parameters=parsed.get("parameters", {}),
                required_capabilities=parsed.get("required_capabilities", ["retrieval"]),
                service_mode=parsed.get("service_mode", "semantic_retrieval"),
                reason=parsed.get("reason", ""),
            )
        except Exception as e:
            logger.warning(f"LLM 意图分类失败: {e}")
            return None

    # 从用户查询中提取参数
    def _extract_args_with_blackboard(
        self,
        user_query: str,
        required_keys: List[str],
        config_name: str = None,
        mode: str = "instruct"
    ) -> Dict[str, Any]:
        if not required_keys:
            return {}

        system_prompt = f"""
你是一个参数抽取器。请根据用户请求填充指定字段。
只输出 JSON 对象，格式为: {{ "args": {{ ... }} }}。不要输出多余文本。
需要填充的字段列表:
{json.dumps(required_keys, ensure_ascii=False)}
如果无法确定某个字段值，请返回 null。
"""
        user_prompt = f"用户请求: {user_query}"

        try:
            response_text = self._llm_client.chat(
                [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                mode=mode,
                config_name=config_name
            )

            parsed = parse_and_validate(response_text, ArgsExtractResponse, strict=False)
            args = parsed.args or {}

            filtered_args = {k: v for k, v in args.items() if v is not None}
            logger.debug(f"参数提取完成: {filtered_args}")
            return filtered_args

        except ParseError as e:
            logger.warning(f"参数提取解析失败: {e}")
            return {}
        except Exception as e:
            logger.error(f"参数提取失败: {e}")
            return {}

    # 两阶段 SOP 路由：关键词粗筛 → LLM 精排 + 拒绝
    def route(
        self,
        user_query: str,
        config_name: str = None,
        mode: str = "instruct"
    ) -> RouteResult:
        """两阶段 SOP 匹配：关键词粗筛召回候选，LLM 精排并判断置信度，低于阈值则拒绝。"""
        if not self.sops:
            logger.warning("没有可用的 SOP 列表进行匹配")
            return RouteResult(sop=None, args={}, reason="无可用SOP", confidence=0.0, candidates=[])

        # Step 1: 关键词粗筛
        doc_ids, documents = _build_sop_corpus(self.sops)
        recall_results = _keyword_recall(user_query, doc_ids, documents)

        if not recall_results:
            logger.info(f"关键词粗筛无命中，fallback 到全量 SOP: query={user_query[:50]}")
            recall_results = [(sop.id, 0.0) for sop in self.sops]

        logger.info(f"关键词粗筛命中 {len(recall_results)} 个候选: {[(r[0], f'{r[1]:.3f}') for r in recall_results]}")

        # 构建候选 SOP 详情
        id_to_sop = {s.id: s for s in self.sops}
        candidates = []
        for sop_id, score in recall_results:
            sop = id_to_sop.get(sop_id)
            if sop:
                bb = sop.blackboard or {}
                candidates.append({
                    "id": sop.id,
                    "name_zh": sop.name_zh or sop.id,
                    "description": sop.description_zh or sop.description or "无描述",
                    "required_params": bb.get("required") or [],
                    "outputs": bb.get("outputs") or [],
                    "recall_score": round(score, 4),
                })

        # Step 2: LLM 精排 + 拒绝
        candidates_detail = "\n".join(
            f"- ID: {c['id']}, 名称: {c['name_zh']}, 描述: {c['description']}, "
            f"所需参数: {c['required_params']}, 输出: {c['outputs']}"
            for c in candidates
        )

        system_prompt = f"""你是一个工程规范领域的 SOP 匹配器。判断用户问题是否与某个候选 SOP 语义匹配。

候选 SOP 列表：
{candidates_detail}

输出 JSON 对象：
{{
  "sop_id": "匹配的 SOP ID，如果没有匹配则返回 null",
  "confidence": 0.0到1.0的置信度,
  "reason": "匹配或不匹配的原因"
}}

重要规则：
- 只有当用户问题的计算目标与 SOP 的输出高度一致时才匹配
- 如果用户问题只是部分相关或需要多个 SOP 协同，返回 null
- confidence 反映语义匹配程度：1.0=完全匹配，0.7=高度相关，0.5=部分相关，0.3=弱相关
- confidence < {ROUTE_CONFIDENCE_THRESHOLD} 视为不匹配"""

        try:
            response_text = self._llm_client.chat(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"用户问题: {user_query}"},
                ],
                mode=mode,
                config_name=config_name,
            )
        except Exception as e:
            logger.error(f"LLM 精排调用失败: {e}")
            return RouteResult(sop=None, args={}, reason=f"LLM精排失败: {e}", confidence=0.0, candidates=candidates)

        if not response_text:
            logger.warning("LLM 精排响应为空")
            return RouteResult(sop=None, args={}, reason="LLM精排响应为空", confidence=0.0, candidates=candidates)

        try:
            parsed = extract_json_from_text(response_text)
            if not parsed:
                logger.warning(f"LLM 精排响应无法解析: {response_text[:200]}")
                return RouteResult(sop=None, args={}, reason="LLM精排响应解析失败", confidence=0.0, candidates=candidates)

            sop_id = parsed.get("sop_id")
            confidence = float(parsed.get("confidence", 0.0))
            reason = parsed.get("reason", "")

            if not sop_id or str(sop_id).lower() in ["null", "none", "nan", ""]:
                logger.info(f"LLM 精排拒绝匹配: {reason}")
                return RouteResult(sop=None, args={}, reason=reason, confidence=confidence, candidates=candidates)

            if confidence < ROUTE_CONFIDENCE_THRESHOLD:
                logger.info(f"LLM 精排置信度不足: sop_id={sop_id}, confidence={confidence:.2f}, reason={reason}")
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
                logger.warning(f"LLM 返回了未知的 SOP ID: {sop_id_str}，可用 SOP: {[s.id for s in self.sops]}")
                return RouteResult(sop=None, args={}, reason=f"未知SOP ID: {sop_id_str}", confidence=confidence, candidates=candidates)

            logger.info(f"SOP 匹配成功: {selected_sop.id}, confidence={confidence:.2f}, reason={reason}")

            # Step 3: 参数提取
            args = {}
            blackboard = selected_sop.blackboard or {}
            required_keys = blackboard.get("required") or []
            if required_keys:
                args = self._extract_args_with_blackboard(
                    user_query, required_keys, config_name=config_name, mode=mode
                )

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

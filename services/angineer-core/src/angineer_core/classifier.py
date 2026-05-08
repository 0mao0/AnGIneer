"""
意图分类核心模块，负责根据用户问题选择合适的 SOP 并提取参数。
"""
import json
import re
from typing import List, Optional, Tuple, Dict, Any

from angineer_core.base_contracts import SOP, AgentResponse, IntentResult, IntentLevel, ServiceMode
from ai_inference.llm_client import llm_client, get_llm_client
from ai_inference.llm_response_parser import (
    extract_json_from_text,
    parse_and_validate,
    ParseError,
)
from angineer_core.base_contracts import IntentResponse, ArgsExtractResponse
from angineer_core.base_logger import get_logger

logger = get_logger(__name__)

L1_KEYWORDS = ["什么是", "是什么", "哪些", "定义", "概念", "组成", "包括", "分为", "划分", "分类", "类型", "位于", "设置", "位置", "在哪里", "宜设置", "应设置", "如何确定", "怎么确定", "怎样确定", "如何定义", "怎么定义", "如何划分", "怎么划分"]
L2_KEYWORDS = ["取值", "范围", "规定", "条款", "要求", "标准值", "限值", "允许值", "应符合", "不应超过"]
L3_KEYWORDS = ["计算", "求", "验算", "核算", "校核", "公式", "等于多少", "结果是多少"]
L4_KEYWORDS = ["评价", "评估", "分析", "综合", "方案", "设计", "比较", "选择", "优化"]

CLAUSE_ID_PATTERN = re.compile(r"(?:第\s*)?(\d+(?:\.\d+){1,4})\s*(?:条|款|节|章)?")

PARAM_PATTERN = re.compile(r"([a-zA-Zα-ωΑ-Ω][a-zA-Zα-ωΑ-Ω_]*)\s*[=＝]\s*([\d.]+)")


# 基于规则快速判定意图层级
def _rule_based_classify(query: str) -> Optional[IntentResult]:
    if not query:
        return None
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
        system_prompt = """你是一个工程规范领域的意图分类器。请根据用户问题判断意图层级和服务模式。

L1 概念解析：用户询问概念定义、原理理解类问题，只需语义检索+LLM总结。
L2 条款应用：用户询问条款取值、规范参数、章节内容，需要SQL精确检索+语义托底。
L3 标准计算：用户有具体参数需要计算，存在预定义工程SOP可承接。
L4 复杂计算：用户提出复合任务或无预定义SOP的复杂问题，需要动态编排多种能力。

输出JSON对象：
{
  "intent_level": "L1" | "L2" | "L3" | "L4",
  "intent_type": "简短意图标签",
  "parameters": {"提取的参数": "值"},
  "required_capabilities": ["retrieval", "sql", "calculation", "sop"],
  "service_mode": "semantic_retrieval" | "sql_first" | "standard_sop" | "dynamic_orchestration",
  "reason": "分类原因"
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

    # 分析用户查询，返回匹配的 SOP 和提取的参数
    def route(
        self,
        user_query: str,
        config_name: str = None,
        mode: str = "instruct"
    ) -> Tuple[Optional[SOP], Dict[str, Any], Optional[str]]:
        if not self.sops:
            logger.warning("没有可用的 SOP 列表进行匹配")
            return None, {}, None

        sop_descriptions = []
        for sop in self.sops:
            desc = f"- ID: {sop.id}, 名称: {sop.name_zh or sop.id}, 描述: {sop.description_zh or sop.description or '无描述'}"
            sop_descriptions.append(desc)

        sop_descriptions_str = "\n".join(sop_descriptions)

        system_prompt = f"""
你是一个意图分类器。你的目标是根据用户的请求选择最合适的标准作业程序 (SOP)。
可选的 SOP 列表：
{sop_descriptions_str}

输出一个 JSON 对象，包含：
- "sop_id": 选中的 SOP ID（必须是列表中存在的 ID）。如果没有匹配的，返回 null。
- "reason": 简短的解释。

示例输入: "计算 25 * 4"
示例输出: {{ "sop_id": "math_sop", "reason": "用户想要进行数学计算" }}
"""

        user_prompt = f"用户请求: {user_query}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            response_text = self._llm_client.chat(messages, mode=mode, config_name=config_name)
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return None, {}, None

        if not response_text:
            logger.warning("LLM 响应为空")
            return None, {}, None

        try:
            parsed = parse_and_validate(response_text, IntentResponse, strict=False)
            sop_id = parsed.sop_id
            reason = parsed.reason

            if not sop_id or str(sop_id).lower() in ["null", "none", "nan", ""]:
                logger.info(f"未匹配到 SOP: {reason}")
                return None, {}, reason

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
                logger.warning(
                    f"LLM 返回了未知的 SOP ID: {sop_id_str}，"
                    f"可用 SOP: {[s.id for s in self.sops]}"
                )
                return None, {}, reason

            logger.info(f"匹配到 SOP: {selected_sop.id}，原因: {reason}")

            args = {}
            blackboard = selected_sop.blackboard or {}
            required_keys = blackboard.get("required") or []

            if required_keys:
                args = self._extract_args_with_blackboard(
                    user_query, required_keys, config_name=config_name, mode=mode
                )

            return selected_sop, args, reason

        except ParseError as e:
            logger.error(f"意图分类解析错误: {e}")
            return None, {}, None
        except Exception as e:
            logger.error(f"意图分类未知错误: {e}")
            return None, {}, None

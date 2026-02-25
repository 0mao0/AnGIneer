"""
意图分类核心模块，负责根据用户问题选择合适的 SOP 并提取参数。
"""
import json
from typing import List, Optional, Tuple, Dict, Any

from angineer_core.standard.context_models import SOP, AgentResponse
from angineer_core.infra.llm_client import llm_client, get_llm_client
from angineer_core.infra.response_parser import (
    extract_json_from_text,
    parse_and_validate,
    IntentResponse,
    ArgsExtractResponse,
    ParseError,
)
from angineer_core.infra.logger import get_logger

logger = get_logger(__name__)


class IntentClassifier:
    """
    意图分类器，负责分析用户查询并匹配最合适的 SOP。
    """
    
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
    
    def _extract_args_with_blackboard(
        self,
        user_query: str,
        required_keys: List[str],
        config_name: str = None,
        mode: str = "instruct"
    ) -> Dict[str, Any]:
        """
        从用户查询中提取参数。
        
        Args:
            user_query: 用户查询
            required_keys: 需要提取的参数键列表
            config_name: LLM 配置名称
            mode: 运行模式
        
        Returns:
            提取的参数字典
        """
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
    
    def route(
        self,
        user_query: str,
        config_name: str = None,
        mode: str = "instruct"
    ) -> Tuple[Optional[SOP], Dict[str, Any], Optional[str]]:
        """
        分析用户查询，返回匹配的 SOP 和提取的参数。
        
        Args:
            user_query: 用户输入的查询
            config_name: 指定的 LLM 配置名称
            mode: 运行模式 ("instruct" or "thinking")
        
        Returns:
            Tuple[Optional[SOP], Dict[str, Any], Optional[str]]:
                - 匹配的 SOP 对象，未匹配则为 None
                - 提取的参数字典
                - 匹配原因
        """
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

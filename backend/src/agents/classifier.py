import json
from typing import List, Optional, Tuple, Dict, Any
from src.core.contextStruct import SOP, AgentResponse
from src.core.llm import llm_client

class IntentClassifier:
    """
    意图分类器，负责分析用户查询并匹配最合适的 SOP。
    """
    def __init__(self, sops: List[SOP]):
        self.sops = sops
        
    def route(self, user_query: str) -> Tuple[Optional[SOP], Dict[str, Any]]:
        """
        分析用户查询，返回匹配的 SOP 和提取的参数。
        """
        sop_descriptions = []
        for sop in self.sops:
            desc = f"- ID: {sop.id}, 名称: {sop.name_zh}/{sop.name_en}, 描述: {sop.description_zh or sop.description}/{sop.description_en}"
            sop_descriptions.append(desc)
        
        sop_descriptions_str = "\n".join(sop_descriptions)
        
        system_prompt = f"""
你是一个意图分类器。你的目标是根据用户的请求选择最合适的标准作业程序 (SOP)。
可选的 SOP 列表：
{sop_descriptions_str}

输出一个 JSON 对象，包含：
- "sop_id": 选中的 SOP ID。如果没有匹配的，返回 null。
- "reason": 简短的解释。
- "args": 从查询中提取的 SOP 可能需要的参数字典。

示例输入: "计算 25 * 4"
示例输出: {{ "sop_id": "math_sop", "reason": "用户想要进行数学计算", "args": {{ "expression": "25 * 4" }} }}
"""
        
        user_prompt = f"用户请求: {user_query}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response_text = llm_client.chat(messages)
        
        try:
            # 清理可能的 Markdown 代码块
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]
                
            data = json.loads(response_text.strip())
            sop_id = data.get("sop_id")
            args = data.get("args", {})
            
            if not sop_id:
                return None, {}
                
            selected_sop = next((s for s in self.sops if s.id == sop_id), None)
            return selected_sop, args
            
        except Exception as e:
            print(f"分类器错误: {e}, 响应内容: {response_text}")
            return None, {}

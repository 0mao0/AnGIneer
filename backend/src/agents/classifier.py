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
        
    def route(self, user_query: str, config_name: str = None, mode: str = "instruct") -> Tuple[Optional[SOP], Dict[str, Any], Optional[str]]:
        """
        分析用户查询，返回匹配的 SOP 和提取的参数。
        
        Args:
            user_query: 用户输入的查询
            config_name: 指定的 LLM 配置名称 (e.g., "DeepSeek Official")
            mode: 运行模式 ("instruct" or "thinking")
        """
        if not self.sops:
            print("警告: 没有可用的 SOP 列表进行匹配。")
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
- "args": 从查询中提取的 SOP 可能需要的参数字典。

示例输入: "计算 25 * 4"
示例输出: {{ "sop_id": "math_sop", "reason": "用户想要进行数学计算", "args": {{ "expression": "25 * 4" }} }}
"""
        
        user_prompt = f"用户请求: {user_query}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # Pass config_name and mode to llm_client.chat
        response_text = llm_client.chat(messages, mode=mode, config_name=config_name)
        if not response_text:
            print("分类器错误: LLM 响应为空")
            return None, {}, None
        
        try:
            # 更加鲁棒的 JSON 提取逻辑
            content = response_text.strip()
            
            # 1. 尝试寻找 Markdown 代码块
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                # 寻找第一个 ``` 和最后一个 ``` 之间的内容
                parts = content.split("```")
                if len(parts) >= 3:
                    content = parts[1]
            
            # 2. 如果还是包含非 JSON 字符，尝试寻找第一个 { 和最后一个 }
            if "{" in content and "}" in content:
                start = content.find("{")
                end = content.rfind("}") + 1
                content = content[start:end]
                
            data = json.loads(content.strip())
            sop_id = data.get("sop_id")
            args = data.get("args", {})
            reason = data.get("reason")
            
            # 处理 null/None/空字符串
            if not sop_id or str(sop_id).lower() in ["null", "none", "nan", ""]:
                return None, {}, reason
                
            # 3. 匹配 SOP (支持大小写不敏感和前后空格)
            sop_id_str = str(sop_id).strip()
            selected_sop = next((s for s in self.sops if s.id.strip().lower() == sop_id_str.lower()), None)
            
            # 4. 如果 ID 没匹配上，尝试通过名称匹配 (可选，但为了鲁棒性增加)
            if not selected_sop:
                selected_sop = next((s for s in self.sops if s.name_zh and s.name_zh.strip() == sop_id_str), None)

            if not selected_sop:
                print(f"警告: LLM 返回了未知的 SOP ID: {sop_id_str}")
                print(f"当前可用的 SOP ID 列表: {[s.id for s in self.sops]}")
                
            return selected_sop, args, reason
            
        except Exception as e:
            error_msg = f"分类器解析错误: {e}"
            print(error_msg)
            print(f"原始响应内容: {response_text}")
            # 这里的输出供前端识别
            print(f"  [AI 运行出错]: {error_msg}")
            return None, {}, None

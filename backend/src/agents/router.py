import json
from typing import List, Optional, Tuple, Dict, Any
from src.core.models import SOP
from src.core.llm import llm_client

class IntentRouter:
    def __init__(self, sops: List[SOP]):
        self.sops = sops
        
    def route(self, user_query: str) -> Tuple[Optional[SOP], Dict[str, Any]]:
        """
        Analyze user query and return the matching SOP and extracted arguments.
        """
        sop_descriptions = []
        for sop in self.sops:
            desc = f"- ID: {sop.id}, Name: {sop.name_zh}/{sop.name_en}, Desc: {sop.description_zh or sop.description}/{sop.description_en}"
            sop_descriptions.append(desc)
        
        sop_descriptions_str = "\n".join(sop_descriptions)
        
        system_prompt = f"""
You are an Intent Router. Your goal is to select the best Standard Operating Procedure (SOP) for the user's request.
Available SOPs:
{sop_descriptions_str}

Output a JSON object with:
- "sop_id": The ID of the chosen SOP. If none match, return null.
- "reason": A brief explanation.
- "args": A dictionary of arguments extracted from the query that might be needed by the SOP.

Example Input: "Calculate 25 * 4"
Example Output: {{ "sop_id": "calculator_sop", "reason": "User wants to do math", "args": {{ "expression": "25 * 4" }} }}
"""
        
        user_prompt = f"User Request: {user_query}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response_text = llm_client.chat(messages)
        
        try:
            # Clean up potential markdown code blocks
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
            print(f"Router Error: {e}, Response: {response_text}")
            return None, {}

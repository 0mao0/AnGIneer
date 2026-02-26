import json
import re
import os
from typing import List, Dict, Any, Tuple
from angineer_core.standard.context_models import SOP, Step

# ---------- 极简内联工具 ----------
def _extract_json_from_text(text: str) -> Dict[str, Any]:
    """粗暴提取 ```json 包裹或裸 JSON。"""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.endswith("```"):
        text = text[:-3]
    raw = text.strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    start = raw.find("{")
    if start == -1:
        raise
    depth = 0
    in_str = False
    escape = False
    last_ok = -1
    for idx, ch in enumerate(raw[start:], start):
        if in_str:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == "\"":
                in_str = False
            continue
        if ch == "\"":
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_ok = idx
                break
    if last_ok != -1:
        return json.loads(raw[start:last_ok + 1])
    raise

def _normalize_step_io(tool: str, inputs: Any, outputs: Any, file_name: str) -> Tuple[Dict, Dict]:
    """仅保证字段结构，模板全部交给 LLM。"""
    ins = inputs if isinstance(inputs, dict) else {}
    outs = outputs if isinstance(outputs, dict) else {}
    # 列表兜底转 dict
    if isinstance(outputs, list):
        outs = {}
        for item in outputs:
            if isinstance(item, dict):
                k = item.get("name") or item.get("variable")
                if k:
                    outs[k] = item.get("target") or "result"
            elif isinstance(item, str):
                outs[item] = "result"
    # table_lookup 必备字段兜底
    if tool == "table_lookup":
        ins.setdefault("table_name", "")
        ins.setdefault("query_conditions", {})
        ins.setdefault("file_name", os.path.basename(file_name))
    return ins, outs

def _compact_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """移除字典中值为 None 的字段。"""
    return {k: v for k, v in data.items() if v is not None}

class SopParser:
    """
    SOP 解析器，负责将 Markdown 内容转换为结构化 Step 对象。
    包含 LLM 解析、规则提取等核心逻辑。
    """

    @staticmethod
    def extract_blackboard_from_markdown(content: str) -> Dict[str, Any]:
        refs = set(re.findall(r"\$\{([^}]+)\}", content or ""))
        outputs = set()
        in_outputs = False
        for line in (content or "").splitlines():
            line_str = line.strip()
            if "**Outputs**" in line_str:
                in_outputs = True
                continue
            if "**Inputs**" in line_str or "**Tool**" in line_str or line_str.startswith("###"):
                in_outputs = False
            if in_outputs:
                for name in re.findall(r"`([^`]+)`", line_str):
                    if name:
                        outputs.add(name)
        required = {r for r in refs if r and r not in outputs and r != "user_query"}
        return {
            "required": sorted(required),
            "outputs": sorted(outputs),
            "all": sorted(required | outputs)
        }

    @staticmethod
    def build_blackboard_from_step_dicts(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        required = set()
        produced = set()

        def collect_refs(value: Any):
            if isinstance(value, str):
                for name in re.findall(r"\$\{([^}]+)\}", value):
                    if name:
                        yield name
            elif isinstance(value, dict):
                for v in value.values():
                    yield from collect_refs(v)
            elif isinstance(value, list):
                for v in value:
                    yield from collect_refs(v)

        for step in steps or []:
            inputs = step.get("inputs") or {}
            for name in collect_refs(inputs):
                if name not in produced:
                    required.add(name)
            outputs = step.get("outputs") or {}
            produced.update(list(outputs.keys()))

        required.discard("user_query")
        return {
            "required": sorted(required),
            "outputs": sorted(produced),
            "all": sorted(required | produced)
        }

    @staticmethod
    def build_blackboard_from_steps(steps: List[Step]) -> Dict[str, Any]:
        required = set()
        produced = set()

        def collect_refs(value: Any):
            if isinstance(value, str):
                for name in re.findall(r"\$\{([^}]+)\}", value):
                    if name:
                        yield name
            elif isinstance(value, dict):
                for v in value.values():
                    yield from collect_refs(v)
            elif isinstance(value, list):
                for v in value:
                    yield from collect_refs(v)

        for step in steps or []:
            inputs = step.inputs or {}
            for name in collect_refs(inputs):
                if name not in produced:
                    required.add(name)
            outputs = step.outputs or {}
            produced.update(list(outputs.keys()))

        required.discard("user_query")
        return {
            "required": sorted(required),
            "outputs": sorted(produced),
            "all": sorted(required | produced)
        }

    @staticmethod
    def save_sop_json(sop: SOP, file_mtime: float, json_path: str, steps: List[Step]) -> None:
        """保存解析后的 SOP 到 sop_json。"""
        sop_json_dir = os.path.dirname(json_path)
        if not os.path.exists(sop_json_dir):
            os.makedirs(sop_json_dir)
        serialized_steps = []
        for step in steps:
            if hasattr(step, "model_dump"):
                serialized_steps.append(step.model_dump(exclude_none=True))
            else:
                serialized_steps.append({k: v for k, v in step.dict().items() if v is not None})
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                _compact_dict({
                    "id": sop.id,
                    "description": sop.description,
                    "mtime": file_mtime,
                    "steps": serialized_steps,
                    "blackboard": sop.blackboard
                }),
                f,
                indent=2,
                ensure_ascii=False
            )

    def parse(self, sop: SOP, content: str, filename: str, config_name: str = "Qwen3-4B (Public)", mode: str = "instruct", save_to_json: bool = False, file_mtime: float = 0, json_path: str = None) -> SOP:
        """
        利用 LLM 解析 SOP 内容。
        """
        # 一次性让 LLM 出完整 JSON
        system = """
You are an expert System Analyst. Your goal is to convert a Markdown Standard Operating Procedure (SOP) into a structured JSON execution plan.
Input: A Markdown SOP document containing Steps.
Output: A JSON object with a "steps" list. Output ONLY a valid JSON object, no markdown or extra text. Do not include line breaks inside any JSON string value.
- "id": A short, unique identifier (e.g., "step_1", "calc_width").
- "name": The step title.
- "description": A summary of what to do.
- "tool": The best tool for this step. Options: "calculator" (for math), "knowledge_search" (for looking up specs), "table_lookup" (for structured table queries), "user_input" (ask user), or "auto" (let dispatcher decide).
  - PRIORITY: Use "table_lookup" if the step mentions "Table", "Chart", "表", or "图".
  - STRICTLY FORBIDDEN: Do NOT use "knowledge_search" if a table name is mentioned (e.g. "Table A.0.1", "图 6.4.6-1"). Use "table_lookup" instead.
- "inputs": A dictionary of required input parameters for this step. keys are parameter names, values are descriptions or context references.
  - For table_lookup, inputs must include "table_name", "query_conditions" (dict), "file_name" (relative to knowledge_base folder, e.g. "markdown/海港总体设计规范_JTS_165-2025.md"), and optionally "target_column" (the column name to read).
  - For knowledge_search, inputs must include "query" (the search question or keyword) and "file_name" (relative to knowledge_base folder, optional).
  - Guidelines for conditional (conditional branching):
  - Use when step requires different actions based on condition variable value (e.g. ship type, material type).
  - Input structure:
    ```json
    {
      "tool": "conditional",
      "inputs": {
        "condition_var": "${ship_type}",
        "branches": [
          {"match": ["杂货船", "集装箱船", "其他船型"], "value": 0},
          {"match": ["干散货船", "液体散货船"], "value": 0.15},
          {"match": "滚装船", "table_lookup": {"table_name": "表5.4.12-2", "query_conditions": {"船型": "${ship_type}"}, "file_name": "markdown/xxx.md"}}
        ],
        "default": 0
      }
    }
    ```
  - "match": can be a single value or list of values
  - "value": fixed return value
  - "table_lookup": execute table lookup if matched
  - "calculator": execute calculation if matched
  - "default": default value if no branch matches
- For calculator, inputs must include "expression" (a mathematical expression using ${variable} references).
- "outputs": A dictionary mapping context keys to tool output paths.
  - Format: {"Variable_Name": "result"}. Example: {"T": "result"}, {"Z0": "result"}.
  - DO NOT use {"result": "Variable_Name"}.
- "notes": CRITICAL. Extract any "Note", "Warning", "Attention", or conditional logic (e.g., "If soft soil, use lower value"). If none, leave empty.
Guidelines for table_lookup:
- Derive table_name from the mentioned 表/图编号.
- Build query_conditions as a dict using condition keywords in the step text.
- Use ${} to reference context variables, e.g. "吨级": "${dwt}", "船型": "${船型}", "航速": "${nav_speed_kn}", "水深": "${water_depth}", "土质": "${bottom_material}", "水域条件": "${navigation_area}".
- Infer target_column from the step objective (e.g. "获取设计船型满载吃水 T" -> target_column="满载吃水 T" or "T").
Guidelines for calculator:
- Extract the formula from the description.
- Convert variable names to ${} references (e.g., "D0 = T + Z0" -> "${T} + ${Z0}").
- For outputs mapping:
- For table_lookup and calculator: map target variables to "result", e.g. {"T": "result"}.
- For user_input: map to "input" (NOT "input_value"), e.g. {"H_nav": "input"} or {"Z3": "0.15"} for fixed values.
"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"SOP Content:\n{content}"}
        ]
        try:
            from angineer_core.infra.llm_client import llm_client
            resp = llm_client.chat(messages, mode=mode, config_name=config_name)
            data = _extract_json_from_text(resp)
            llm_steps = []
            for s in data.get("steps", []):
                ins, outs = _normalize_step_io(s.get("tool", "auto"), s.get("inputs", {}), s.get("outputs", {}), filename)
                llm_steps.append(Step(
                    id=s.get("id"),
                    name=s.get("name"),
                    description=s.get("description"),
                    tool=s.get("tool", "auto"),
                    inputs=ins,
                    outputs=outs,
                    notes=s.get("notes", ""),
                    analysis_status="analyzed",
                ))
            if llm_steps:
                sop.blackboard = self.build_blackboard_from_steps(llm_steps)
                sop.steps = llm_steps
                if save_to_json and json_path:
                    self.save_sop_json(sop, file_mtime, json_path, llm_steps)
                return sop
        except Exception as e:
            print(f"[LLM 一次性解析失败，改用兜底]: {e}")
            pass

        if not sop.blackboard:
            sop.blackboard = self.extract_blackboard_from_markdown(content)

        return sop

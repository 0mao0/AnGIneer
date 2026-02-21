
import os
import glob
import json
import re
from typing import List, Dict, Any
import sys

# Ensure src can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.core.contextStruct import SOP, Step

class SopLoader:
    """
    负责管理 Markdown SOP 的索引和加载。
    引入索引文件 (index.json) 机制，避免每次启动都扫描所有 MD 文件，
    并且确保 Router 仅获取轻量级的元数据（ID, Name, Description），
    防止大量文件内容导致 Context Window 爆炸。
    """
    
    def __init__(self, sop_dir: str):
        self.sop_dir = sop_dir
        self.index_file = os.path.join(sop_dir, "index.json")
        self.sops: List[SOP] = [] # Cache

    def load_all(self) -> List[SOP]:
        """
        从索引文件加载 SOP 列表。
        如果索引不存在，则自动生成。
        """
        if not os.path.exists(self.index_file):
            print(f"SOP Index not found at {self.index_file}, generating...")
            self.refresh_index()
            
        self.sops = self._load_from_index()
        return self.sops

    def refresh_index(self):
        """
        扫描目录下所有 .md 文件，提取元数据并生成/更新 index.json。
        仅读取文件头部以提取描述。
        """
        if not os.path.exists(self.sop_dir):
            return

        index_data = []
        md_files = glob.glob(os.path.join(self.sop_dir, "*.md"))
        
        for fpath in md_files:
            try:
                filename = os.path.basename(fpath)
                sop_id = os.path.splitext(filename)[0]
                
                # 提取描述：读取前 500 字符，找第一个非空行或标题
                description = f"SOP for {sop_id}"
                with open(fpath, 'r', encoding='utf-8') as f:
                    # 只读头部，避免加载全文
                    head_content = f.read(1000)
                    lines = head_content.split('\n')
                    for line in lines:
                        line = line.strip()
                        if line and not line.startswith('#'):
                             # 假设第一个非标题行是描述
                            description = line
                            break
                        elif line.startswith('# '):
                             # 或者使用一级标题作为描述的一部分
                             description = line.lstrip('#').strip()
                
                # 截断过长的描述
                if len(description) > 200:
                    description = description[:197] + "..."

                index_data.append({
                    "id": sop_id,
                    "filename": filename,
                    "name": sop_id, # 默认用文件名，可手动在 index.json 修改
                    "description": description
                })
                
            except Exception as e:
                print(f"Error indexing {fpath}: {e}")
        
        # 写入 index.json
        with open(self.index_file, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=2, ensure_ascii=False)
        print(f"SOP Index generated with {len(index_data)} entries.")

    def _load_from_index(self) -> List[SOP]:
        """
        读取 index.json 并转换为 SOP 对象列表。
        """
        sops = []
        if not os.path.exists(self.index_file):
            return sops

        try:
            with open(self.index_file, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
                
            for entry in index_data:
                # 构造 SOP 对象
                # 在混合架构中，我们依然创建一个基础 SOP 对象
                # 但真正的结构化解析（_analyze_sop_with_llm）会推迟到 Dispatcher 需要时，或者在 load 时按需进行
                # 目前为了保持兼容，先创建一个 wrapper step，但我们允许通过 analyze() 方法扩展它
                step = Step(
                    id="execute_md",
                    tool="sop_run",
                    description=f"Run SOP: {entry['filename']}",
                    inputs={
                        "question": "${user_query}",
                        "filename": entry['filename']
                    },
                    outputs={
                        "result": "result"
                    }
                )
                
                sop = SOP(
                    id=entry['id'],
                    name_zh=entry.get('name', entry['id']),
                    name_en=entry.get('name_en', entry['id']),
                    description=entry.get('description', ''),
                    steps=[step]
                )
                sops.append(sop)
                
        except Exception as e:
            print(f"Error loading SOP index: {e}")
            
        return sops

    def _normalize_subscripts(self, text: str) -> str:
        """
        将常见下标字符转换为普通数字，便于变量名解析。
        """
        mapping = {
            "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
            "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9"
        }
        for k, v in mapping.items():
            text = text.replace(k, v)
        return text

    def _extract_formulas(self, text: str) -> List[str]:
        """
        从段落文本中提取包含等号的公式字符串。
        """
        formulas = []
        inline = re.findall(r"`([^`]+)`", text)
        latex = re.findall(r"\$([^$]+)\$", text)
        for item in inline + latex:
            if "=" in item:
                formulas.append(item)
        if not formulas:
            for line in text.splitlines():
                if "公式" in line or "=" in line:
                    formulas.append(line.strip())
        cleaned = []
        for f in formulas:
            sanitized = self._sanitize_formula(f)
            if sanitized and "=" in sanitized:
                cleaned.append(sanitized)
        return cleaned

    def _sanitize_formula(self, text: str) -> str:
        """
        清理公式文本中的 Markdown 与 LaTeX 噪声并做基础表达式规整。
        """
        text = text.replace("＝", "=")
        text = text.replace("：", ":")
        text = re.sub(r"\*+|\`+", "", text)
        if "公式" in text and ":" in text:
            text = text.split(":", 1)[1]
        if "$" in text:
            text = text.replace("$", "")
        text = text.replace("\\", "")
        text = self._normalize_subscripts(text)
        text = text.strip()
        text = text.replace("^", "**")
        for func in ["sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh", "log", "ln", "sqrt", "exp"]:
            text = re.sub(rf"\b{func}\s+([a-zA-Z_]\w*|\d+(?:\.\d+)?)", rf"{func}(\1)", text)
        text = re.sub(r"(\d)([a-zA-Z_])", r"\1*\2", text)
        text = re.sub(r"([a-zA-Z_0-9])\s+\(", r"\1*(", text)
        text = re.sub(r"([a-zA-Z_0-9])\s+(?=[a-zA-Z_])", r"\1*", text)
        text = re.sub(r"\)\s*(?=[a-zA-Z_0-9])", r")*", text)
        return text.strip()

    def _is_trivial_formula(self, left_key: str, expression: str) -> bool:
        """
        判断公式是否为占位赋值或单变量映射。
        """
        if not expression:
            return True
        normalized = self._normalize_subscripts(expression).strip().replace(" ", "")
        if normalized == left_key:
            return True
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized):
            return True
        return False

    def _should_table_lookup(self, section_text: str) -> bool:
        """判断当前步骤是否应该使用表格查询工具。"""
        return any(k in section_text for k in ["查表", "查图", "表", "图"])

    def _extract_table_name(self, section_text: str) -> str:
        """从步骤描述中提取表格或图表名称。"""
        match = re.search(r"(表|图)\s*([A-Za-z0-9\.\-]+)", section_text)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        return "规范表"

    def _extract_variables(self, section_text: str) -> List[str]:
        """
        提取并清理步骤中的变量引用。
        """
        raw_vars = re.findall(r"`([^`]+)`", section_text)
        variables = []
        for item in raw_vars:
            if "=" in item:
                continue
            normalized = self._normalize_subscripts(item).strip()
            if normalized:
                variables.append(normalized)
        return variables

    def _infer_output_key(self, title: str, section_text: str) -> str:
        """从标题或正文推断输出变量名。"""
        variables = self._extract_variables(section_text)
        if variables:
            return variables[0]
        candidates = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", title or "")
        if not candidates:
            return ""
        return candidates[-1]

    def _parse_steps_from_markdown(self, content: str) -> List[Step]:
        """
        解析 Markdown 的 Step 段落并生成结构化步骤。
        """
        lines = content.splitlines()
        step_headers = []
        header_pattern = re.compile(r"^###\s*(?:Step|步骤)\s*\d*\.?\s*(.*)$", re.IGNORECASE)
        for idx, line in enumerate(lines):
            m = header_pattern.match(line.strip())
            if m:
                step_headers.append((idx, m.group(1) or line.strip()))
        if not step_headers:
            return []

        steps = []
        for i, (start_idx, title) in enumerate(step_headers):
            end_idx = step_headers[i + 1][0] if i + 1 < len(step_headers) else len(lines)
            section_lines = lines[start_idx + 1:end_idx]
            section_text = "\n".join(section_lines).strip()
            formulas = self._extract_formulas(section_text)

            file_match = re.search(r"《[^》]+》\.md", section_text)
            file_name = file_match.group(0) if file_match else "《海港水文规范》.md"

            calc_formulas = []
            if formulas:
                for f_idx, formula in enumerate(formulas, start=1):
                    if "=" in formula:
                        left, right = formula.split("=", 1)
                        left_key = self._normalize_subscripts(left).strip().replace(" ", "")
                        expression = right.strip()
                    else:
                        left_key = f"step_{i+1}_result_{f_idx}"
                        expression = formula.strip()
                    if self._is_trivial_formula(left_key, expression):
                        continue
                    calc_formulas.append((f_idx, formula, left_key, expression))

            if calc_formulas:
                for f_idx, formula, left_key, expression in calc_formulas:
                    steps.append(Step(
                        id=f"step_{i+1}_calc_{f_idx}",
                        name=title or f"step_{i+1}",
                        description=formula.strip(),
                        tool="calculator",
                        inputs={"expression": expression, "variables": "${variables}"},
                        outputs={left_key: "result"},
                        notes=section_text,
                        analysis_status="analyzed"
                    ))
                continue
            if formulas:
                variables = self._extract_variables(section_text)
                if self._should_table_lookup(section_text):
                    outputs = {variables[0]: "result"} if len(variables) == 1 else {}
                    steps.append(Step(
                        id=f"step_{i+1}",
                        name=title or f"step_{i+1}",
                        description=section_text,
                        tool="table_lookup",
                        inputs={
                            "table_name": self._extract_table_name(section_text),
                            "query_conditions": "${variables}",
                            "file_name": file_name
                        },
                        outputs=outputs,
                        notes=section_text,
                        analysis_status="analyzed"
                    ))
                    continue
                steps.append(Step(
                    id=f"step_{i+1}",
                    name=title or f"step_{i+1}",
                    description=section_text,
                    tool="auto",
                    inputs={"variables": variables},
                    outputs={},
                    notes=section_text,
                    analysis_status="analyzed"
                ))
                continue

            lowered = section_text.lower()
            if self._should_table_lookup(section_text):
                output_key = self._infer_output_key(title, section_text)
                outputs = {output_key: "result"} if output_key else {}
                steps.append(Step(
                    id=f"step_{i+1}",
                    name=title or f"step_{i+1}",
                    description=section_text,
                    tool="table_lookup",
                    inputs={
                        "table_name": self._extract_table_name(section_text),
                        "query_conditions": "${variables}",
                        "file_name": file_name
                    },
                    outputs=outputs,
                    notes=section_text,
                    analysis_status="analyzed"
                ))
                continue
            if any(k in section_text for k in ["规范", "查阅", "参考"]) or "spec" in lowered:
                steps.append(Step(
                    id=f"step_{i+1}",
                    name=title or f"step_{i+1}",
                    description=section_text,
                    tool="knowledge_search",
                    inputs={"query": title or section_text, "file_name": file_name},
                    outputs={"knowledge": "result"},
                    notes=section_text,
                    analysis_status="analyzed"
                ))
                continue

            if any(k in section_text for k in ["输出", "结果"]):
                steps.append(Step(
                    id=f"step_{i+1}",
                    name=title or f"step_{i+1}",
                    description=section_text,
                    tool="report_generator",
                    inputs={"title": title or "SOP 结果", "data": "${context}"},
                    outputs={"report": "result"},
                    notes=section_text,
                    analysis_status="analyzed"
                ))
                continue

            variables = self._extract_variables(section_text)
            steps.append(Step(
                id=f"step_{i+1}",
                name=title or f"step_{i+1}",
                description=section_text,
                tool="auto",
                inputs={"variables": variables},
                outputs={},
                notes=section_text,
                analysis_status="analyzed"
            ))

        return steps

    def _compact_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """移除字典中值为 None 的字段。"""
        return {k: v for k, v in data.items() if v is not None}

    def _save_sop_json(self, sop: SOP, file_mtime: float, json_path: str, steps: List[Step]) -> None:
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
                self._compact_dict({
                    "id": sop.id,
                    "name_zh": sop.name_zh,
                    "name_en": sop.name_en,
                    "description": sop.description,
                    "mtime": file_mtime,
                    "steps": serialized_steps
                }),
                f,
                indent=2,
                ensure_ascii=False
            )

    def analyze_sop(self, sop_id: str, config_name: str = None, mode: str = "instruct", save_to_json: bool = False, prefer_llm: bool = True) -> SOP:
        """
        【混合架构核心】
        利用 LLM 读取指定的 SOP Markdown 文件，并将其解析为细粒度的 Steps 列表。
        这对应了"整体分析一遍 SOP"的策略。
        """
        from src.core.llm import llm_client
        
        # 1. 找到对应的 Markdown 文件
        if self.sops:
            sop = next((s for s in self.sops if s.id == sop_id), None)
        else:
            sop = next((s for s in self.load_all() if s.id == sop_id), None)
        if not sop:
            raise ValueError(f"SOP {sop_id} not found")
            
        # 假设 step[0] 是我们之前创建的 wrapper step，从中获取 filename
        filename = sop.steps[0].inputs.get("filename")
        if not filename:
             raise ValueError(f"SOP {sop_id} has no filename associated")
             
        filepath = os.path.join(self.sop_dir, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"SOP file {filepath} not found")

        file_mtime = os.path.getmtime(filepath)
        sop_json_dir = os.path.abspath(os.path.join(self.sop_dir, "..", "sop_json"))
        json_path = os.path.join(sop_json_dir, f"{sop_id}.json")
            
        # 2. 读取全文并进行轻量裁剪
        with open(filepath, 'r', encoding='utf-8') as f:
            raw_content = f.read()
        lines = raw_content.splitlines()
        start_idx = 0
        keywords = ["## 实施步骤", "## 步骤", "## Steps", "## Implementation", "# Steps"]
        for i, ln in enumerate(lines):
            if any(ln.strip().startswith(k) for k in keywords):
                start_idx = i
                break
        content = "\n".join(lines[start_idx:]) if start_idx > 0 else raw_content
        if len(content) > 8000:
            content = content[:8000] + "\n...(内容已截断)"

        def _try_llm_parse() -> List[Step]:
            system_prompt = """
You are an expert System Analyst. Your goal is to convert a Markdown Standard Operating Procedure (SOP) into a structured JSON execution plan.

Input: A Markdown SOP document containing Steps.
Output: A JSON object with a "steps" list. Each step must have:
- "id": A short, unique identifier (e.g., "step_1", "calc_width").
- "name": The step title.
- "description": A summary of what to do.
- "tool": The best tool for this step. Options: "calculator" (for math), "knowledge_search" (for looking up specs), "table_lookup" (for structured table queries), "user_input" (ask user), or "auto" (let dispatcher decide).
- "inputs": A dictionary of required input parameters for this step. keys are parameter names, values are descriptions or context references. For table_lookup, inputs must include table_name, query_conditions (dict), and file_name.
- "outputs": A dictionary mapping context keys to tool output paths.
- "notes": CRITICAL. Extract any "Note", "Warning", "Attention", or conditional logic (e.g., "If soft soil, use lower value"). If none, leave empty.

Guidelines for table_lookup:
- Derive table_name from the mentioned 表/图编号.
- Build query_conditions as a dict using condition keywords in the step text.
- Use ${} to reference context variables, e.g. "吨级": "${dwt}", "船型": "${船型}", "航速": "${nav_speed_kn}", "水深": "${water_depth}", "土质": "${bottom_material}", "水域条件": "${navigation_area}".
For outputs mapping:
- table_lookup and calculator should map target variables to "result".
"""
            user_prompt = f"SOP Content:\n{content}"
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            print(f"  [SopLoader] Analyzing {filename} with LLM...")
            try:
                preferred = config_name or os.getenv("PREFERRED_LLM_CONFIG")
                response = llm_client.chat(messages, mode=mode, config_name=preferred)
                if "```json" in response:
                    response = response.split("```json")[1].split("```")[0]
                elif "```" in response:
                    response = response.split("```")[1].split("```")[0]
                data = json.loads(response.strip())
                new_steps = []
                for s_data in data.get("steps", []):
                    tool_name = s_data.get("tool", "auto")
                    if isinstance(tool_name, str):
                        tool_name = tool_name.replace('`', '').strip()
                    new_step = Step(
                        id=s_data.get("id"),
                        name=s_data.get("name"),
                        description=s_data.get("description"),
                        tool=tool_name,
                        inputs=s_data.get("inputs", {}),
                        outputs=s_data.get("outputs", {}),
                        notes=s_data.get("notes"),
                        analysis_status="analyzed"
                    )
                    new_steps.append(new_step)
                print(f"  [SopLoader] Successfully analyzed {len(new_steps)} steps for {sop_id}.")
                return new_steps
            except Exception as e:
                print(f"  [SopLoader] Analysis failed: {e}")
                return []

        if prefer_llm:
            llm_steps = _try_llm_parse()
            if llm_steps:
                sop.steps = llm_steps
                if save_to_json:
                    self._save_sop_json(sop, file_mtime, json_path, llm_steps)
                return sop

        if not save_to_json and os.path.exists(json_path) and os.path.getmtime(json_path) >= file_mtime:
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                steps = [Step(**s) for s in data.get("steps", [])]
                sop = SOP(
                    id=data.get("id", sop_id),
                    name_zh=data.get("name_zh", sop.name_zh),
                    name_en=data.get("name_en", sop.name_en),
                    description=data.get("description", sop.description),
                    steps=steps
                )
                return sop
            except Exception:
                pass

        parsed_steps = self._parse_steps_from_markdown(content)
        if parsed_steps:
            sop.steps = parsed_steps
            if save_to_json:
                self._save_sop_json(sop, file_mtime, json_path, parsed_steps)
            return sop

        if not prefer_llm:
            llm_steps = _try_llm_parse()
            if llm_steps:
                sop.steps = llm_steps
                if save_to_json:
                    self._save_sop_json(sop, file_mtime, json_path, llm_steps)
                return sop

        return sop

    def preparse_all(self, config_name: str = None, mode: str = "instruct") -> Dict[str, object]:
        """批量预解析所有 SOP 并输出到 sop_json。"""
        sops = self.load_all()
        results = {"total": len(sops), "success": 0, "failed": 0, "items": []}
        for sop in sops:
            try:
                analyzed = self.analyze_sop(sop.id, config_name=config_name, mode=mode, save_to_json=True, prefer_llm=True)
                results["success"] += 1
                results["items"].append({"id": sop.id, "steps": len(analyzed.steps)})
            except Exception as e:
                results["failed"] += 1
                results["items"].append({"id": sop.id, "error": str(e)})
        return results

def _run_preparse_from_cli():
    """从命令行触发 SOP 预解析。"""
    sop_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "sops"))
    config_name = sys.argv[2] if len(sys.argv) > 2 else None
    mode = sys.argv[3] if len(sys.argv) > 3 else "instruct"
    loader = SopLoader(sop_dir)
    result = loader.preparse_all(config_name=config_name, mode=mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    _run_preparse_from_cli()

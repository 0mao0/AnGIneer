
import os
import glob
import json
import re
from typing import List, Dict, Any, Tuple
import sys

# Ensure src can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.core.contextStruct import SOP, Step

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

    def _extract_blackboard_from_markdown(self, content: str) -> Dict[str, Any]:
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

    def _build_blackboard_from_step_dicts(self, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
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

    def _build_blackboard_from_steps(self, steps: List[Step]) -> Dict[str, Any]:
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

    def load_all(self) -> List[SOP]:
        """
        从索引文件加载 SOP 列表。
        如果索引不存在，则自动生成。
        """
        if not os.path.exists(self.index_file):
            print(f"SOP Index not found at {self.index_file}, generating...")
            self.refresh_index()
            
        self.sops = self._load_from_index()
        if any(s.blackboard is None for s in self.sops):
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
                    full_content = f.read()
                    head_content = full_content[:1000]
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

                blackboard = self._extract_blackboard_from_markdown(full_content)
                
                # 截断过长的描述
                if len(description) > 200:
                    description = description[:197] + "..."

                index_data.append({
                    "id": sop_id,
                    "filename": filename,
                    "name": sop_id, # 默认用文件名，可手动在 index.json 修改
                    "description": description,
                    "blackboard": blackboard
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
                
            sop_json_dir = os.path.abspath(os.path.join(self.sop_dir, "..", "sop_json"))
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
                    steps=[step],
                    blackboard=entry.get("blackboard")
                )
                json_path = os.path.join(sop_json_dir, f"{entry['id']}.json")
                if os.path.exists(json_path):
                    try:
                        with open(json_path, "r", encoding="utf-8") as jf:
                            cached = json.load(jf)
                        if cached.get("blackboard"):
                            sop.blackboard = cached.get("blackboard")
                        elif cached.get("steps"):
                            sop.blackboard = self._build_blackboard_from_step_dicts(cached.get("steps"))
                    except Exception:
                        pass
                sops.append(sop)
                
        except Exception as e:
            print(f"Error loading SOP index: {e}")
            
        return sops
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
                    "description": sop.description,
                    "mtime": file_mtime,
                    "steps": serialized_steps,
                    "blackboard": sop.blackboard
                }),
                f,
                indent=2,
                ensure_ascii=False
            )

    def analyze_sop(self, sop_id: str, config_name: str = "Qwen3-4B (Public)", mode: str = "instruct", save_to_json: bool = False, prefer_llm: bool = True) -> SOP:
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



        if prefer_llm:
            # 一次性让 LLM 出完整 JSON，不再分段兜底
            system = """
You are an expert System Analyst. Your goal is to convert a Markdown Standard Operating Procedure (SOP) into a structured JSON execution plan.
Input: A Markdown SOP document containing Steps.
Output: A JSON object with a "steps" list. Output ONLY a valid JSON object, no markdown or extra text. Do not include line breaks inside any JSON string value.
- "id": A short, unique identifier (e.g., "step_1", "calc_width").
- "name": The step title.
- "description": A summary of what to do.
- "tool": The best tool for this step. Options: "calculator" (for math), "knowledge_search" (for looking up specs), "table_lookup" (for structured table queries), "user_input" (ask user), or "auto" (let dispatcher decide).
- "inputs": A dictionary of required input parameters for this step. keys are parameter names, values are descriptions or context references. For table_lookup, inputs must include table_name, query_conditions (dict), and file_name (base filename only, e.g. "《海港水文规范》.md").
- "outputs": A dictionary mapping context keys to tool output paths.
- "notes": CRITICAL. Extract any "Note", "Warning", "Attention", or conditional logic (e.g., "If soft soil, use lower value"). If none, leave empty.
Guidelines for table_lookup:
- Derive table_name from the mentioned 表/图编号.
- Build query_conditions as a dict using condition keywords in the step text.
- Use ${} to reference context variables, e.g. "吨级": "${dwt}", "船型": "${船型}", "航速": "${nav_speed_kn}", "水深": "${water_depth}", "土质": "${bottom_material}", "水域条件": "${navigation_area}".
For outputs mapping:
- table_lookup and calculator should map target variables to "result".
"""
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": f"SOP Content:\n{content}"}
            ]
            try:
                from .llm import llm_client
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
                    sop.blackboard = self._build_blackboard_from_steps(llm_steps)
                    sop.steps = llm_steps
                    if save_to_json:
                        self._save_sop_json(sop, file_mtime, json_path, llm_steps)
                    return sop
            except Exception as e:
                print(f"[LLM 一次性解析失败，改用兜底]: {e}")
                pass

        if not sop.blackboard:
            sop.blackboard = self._extract_blackboard_from_markdown(content)

        # 不再使用硬编码兜底解析，直接返回空 SOP
        return sop

    def preparse_all(self, config_name: str = "Qwen3-4B (Public)", mode: str = "instruct") -> Dict[str, object]:
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
    sop_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "sops"))
    config_name = "Qwen3-4B (Public)"
    mode = "instruct"
    sop_id = None
    args = sys.argv[1:]
    if args:
        sop_dir = args[0]
        args = args[1:]
    i = 0
    while i < len(args):
        key = args[i]
        val = args[i + 1] if i + 1 < len(args) else None
        if key in ("--sop", "--sop_id"):
            sop_id = val
            i += 2
            continue
        if key in ("--config", "--config_name"):
            config_name = val
            i += 2
            continue
        if key == "--mode":
            mode = val or mode
            i += 2
            continue
        i += 1
    loader = SopLoader(sop_dir)
    if sop_id:
        analyzed = loader.analyze_sop(sop_id, config_name=config_name, mode=mode, save_to_json=True, prefer_llm=True)
        result = {
            "total": 1, 
            "success": 1, 
            "failed": 0, 
            "items": [{"id": sop_id, "steps": len(analyzed.steps)}],
            "blackboard": analyzed.blackboard
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if "--all" in sys.argv:
        result = loader.preparse_all(config_name=config_name, mode=mode)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print("Please specify --sop <sop_id> to preparse a single SOP, or add --all to preparse all.")

if __name__ == "__main__":
    _run_preparse_from_cli()

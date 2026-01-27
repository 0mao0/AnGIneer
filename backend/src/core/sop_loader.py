
import os
import glob
import json
from typing import List, Dict
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

    def analyze_sop(self, sop_id: str, config_name: str = None, mode: str = "instruct") -> SOP:
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
        if os.path.exists(json_path) and os.path.getmtime(json_path) >= file_mtime:
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
            
        # 3. LLM 结构化解析
        system_prompt = """
You are an expert System Analyst. Your goal is to convert a Markdown Standard Operating Procedure (SOP) into a structured JSON execution plan.

Input: A Markdown SOP document containing Steps.
Output: A JSON object with a "steps" list. Each step must have:
- "id": A short, unique identifier (e.g., "step_1", "calc_width").
- "name": The step title.
- "description": A summary of what to do.
- "tool": The best tool for this step. Options: "calculator" (for math), "knowledge_search" (for looking up specs), "user_input" (ask user), or "auto" (let dispatcher decide).
- "inputs": A dictionary of required input parameters for this step. keys are parameter names, values are descriptions.
- "notes": CRITICAL. Extract any "Note", "Warning", "Attention", or conditional logic (e.g., "If soft soil, use lower value"). If none, leave empty.
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
            # Clean json
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]
                
            data = json.loads(response.strip())
            
            # 4. 重构 SOP 对象
            new_steps = []
            for s_data in data.get("steps", []):
                # Clean tool name
                tool_name = s_data.get("tool", "auto")
                if isinstance(tool_name, str):
                    tool_name = tool_name.replace('`', '').strip()

                new_step = Step(
                    id=s_data.get("id"),
                    name=s_data.get("name"),
                    description=s_data.get("description"),
                    tool=tool_name,
                    inputs=s_data.get("inputs", {}),
                    notes=s_data.get("notes"), # 核心：注入 LLM 提取的注意事项
                    analysis_status="analyzed"
                )
                new_steps.append(new_step)
                
            sop.steps = new_steps
            print(f"  [SopLoader] Successfully analyzed {len(new_steps)} steps for {sop_id}.")
            # 用户需求：自动解析的结果不要保存到磁盘，保持 json 文件的官方唯一性
            # if not os.path.exists(sop_json_dir):
            #     os.makedirs(sop_json_dir)
            # with open(json_path, "w", encoding="utf-8") as f:
            #     json.dump(
            #         {
            #             "id": sop.id,
            #             "name_zh": sop.name_zh,
            #             "name_en": sop.name_en,
            #             "description": sop.description,
            #             "mtime": file_mtime,
            #             "steps": [s.dict() for s in new_steps]
            #         },
            #         f,
            #         indent=2,
            #         ensure_ascii=False
            #     )
            return sop
            
        except Exception as e:
            print(f"  [SopLoader] Analysis failed: {e}")
            # Fallback to original wrapper step
            return sop

    def preparse_all(self, config_name: str = None, mode: str = "instruct") -> Dict[str, object]:
        """批量预解析所有 SOP 并输出到 sop_json。"""
        sops = self.load_all()
        results = {"total": len(sops), "success": 0, "failed": 0, "items": []}
        for sop in sops:
            try:
                analyzed = self.analyze_sop(sop.id, config_name=config_name, mode=mode)
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

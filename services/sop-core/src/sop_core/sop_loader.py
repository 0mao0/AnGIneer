import os
import glob
import json
import sys
from typing import List, Dict, Any

# Ensure src can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from angineer_core.standard.context_models import SOP, Step
from sop_core.sop_parser import SopParser

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
        self.parser = SopParser()

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
                
                # 提取描述：读取前 1000 字符，找第一个非空行或标题
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

                blackboard = self.parser.extract_blackboard_from_markdown(full_content)
                
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
                
            base_dir = os.path.abspath(os.path.join(self.sop_dir, ".."))
            json_dir_candidates = [os.path.join(base_dir, "json"), os.path.join(base_dir, "sop_json")]
            sop_json_dir = next((p for p in json_dir_candidates if os.path.exists(p)), json_dir_candidates[0])
            for entry in index_data:
                # 构造 SOP 对象
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
                            sop.blackboard = self.parser.build_blackboard_from_step_dicts(cached.get("steps"))
                    except Exception:
                        pass
                sops.append(sop)
                
        except Exception as e:
            print(f"Error loading SOP index: {e}")
            
        return sops

    def analyze_sop(self, sop_id: str, config_name: str = "Qwen3-4B (Public)", mode: str = "instruct", save_to_json: bool = False, prefer_llm: bool = True, force_refresh: bool = False) -> SOP:
        """
        【混合架构核心】
        获取 SOP 的详细执行步骤。
        策略：
        1. 优先尝试加载 sop_json 缓存（如果存在且比 Markdown 新）。
        2. 如果缓存失效或 force_refresh=True，则读取 Markdown 并调用 Parser (LLM) 进行解析。
        """
        
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
        base_dir = os.path.abspath(os.path.join(self.sop_dir, ".."))
        json_dir_candidates = [os.path.join(base_dir, "json"), os.path.join(base_dir, "sop_json")]
        sop_json_dir = next((p for p in json_dir_candidates if os.path.exists(p)), json_dir_candidates[0])
        json_path = os.path.join(sop_json_dir, f"{sop_id}.json")
        
        # 2. 尝试从 JSON 缓存加载 (Cache Hit)
        if not force_refresh and os.path.exists(json_path):
            json_mtime = os.path.getmtime(json_path)
            if json_mtime >= file_mtime:
                try:
                    with open(json_path, "r", encoding="utf-8") as jf:
                        cached_data = json.load(jf)
                    
                    # 恢复 Steps
                    steps_data = cached_data.get("steps", [])
                    if steps_data:
                        loaded_steps = []
                        for s_dict in steps_data:
                            # 恢复 Step 对象
                            loaded_steps.append(Step(**s_dict))
                        
                        sop.steps = loaded_steps
                        sop.blackboard = cached_data.get("blackboard") or self.parser.build_blackboard_from_steps(loaded_steps)
                        # print(f"[SOP Loader] Loaded {sop_id} from cache.")
                        return sop
                except Exception as e:
                    print(f"[SOP Loader] Cache load failed for {sop_id}: {e}, falling back to parser.")

        # 3. 读取全文并进行解析 (Cache Miss)
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
            return self.parser.parse(
                sop=sop,
                content=content,
                filename=filename,
                config_name=config_name,
                mode=mode,
                save_to_json=save_to_json,
                file_mtime=file_mtime,
                json_path=json_path
            )

        if not sop.blackboard:
            sop.blackboard = self.parser.extract_blackboard_from_markdown(content)

        return sop

    def preparse_all(self, config_name: str = "Qwen3-4B (Public)", mode: str = "instruct", force: bool = False) -> Dict[str, object]:
        """批量预解析所有 SOP 并输出到 sop_json。"""
        sops = self.load_all()
        results = {"total": len(sops), "success": 0, "failed": 0, "items": []}
        for sop in sops:
            try:
                # 强制刷新以确保最新
                analyzed = self.analyze_sop(
                    sop.id, 
                    config_name=config_name, 
                    mode=mode, 
                    save_to_json=True, 
                    prefer_llm=True,
                    force_refresh=force
                )
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
    force = False
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
        if key == "--force":
            force = True
            i += 1
            continue
        i += 1
    loader = SopLoader(sop_dir)
    if sop_id:
        analyzed = loader.analyze_sop(
            sop_id, 
            config_name=config_name, 
            mode=mode, 
            save_to_json=True, 
            prefer_llm=True,
            force_refresh=force
        )
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
        result = loader.preparse_all(config_name=config_name, mode=mode, force=force)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print("Please specify --sop <sop_id> to preparse a single SOP, or add --all to preparse all.")

if __name__ == "__main__":
    _run_preparse_from_cli()

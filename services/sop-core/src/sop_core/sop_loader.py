import os
import glob
import json
import sys
from typing import List, Dict, Any, Optional

# Ensure src can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from angineer_core.base_contracts import SOP, Step
from sop_core.sop_parser import SopParser

def _normalize_inline_description(value: Any) -> Dict[str, Any]:
    """将步骤描述规范化为 {content, citations[]} 结构。"""
    if isinstance(value, dict):
        return {
            "content": str(value.get("content") or ""),
            "citations": value.get("citations") if isinstance(value.get("citations"), list) else [],
        }
    if value is None:
        return {"content": "", "citations": []}
    if isinstance(value, str):
        return {"content": value, "citations": []}
    return {"content": str(value), "citations": []}


def _normalize_step_dict(step_dict: Dict[str, Any]) -> Dict[str, Any]:
    """对 Step 字典做最小归一化，确保能通过 Step 契约校验。"""
    normalized = dict(step_dict or {})
    normalized["description"] = _normalize_inline_description(normalized.get("description"))
    return normalized


class SopLoader:
    """
    SOP 加载器，管理结构化 SOP 的索引与加载。

    新架构：以 json/ 目录为唯一真相源，index.json 位于根目录。
    raw/ 目录保留用于 Markdown 源文件的向后兼容。

    目录结构：
        sop_base_dir/
        ├── json/           ← 结构化 SOP（主要数据源）
        │   └── *.json      ← 包含完整 id, name_zh, description, steps, blackboard
        ├── index.json      ← 索引文件（从 json/ 自动生成）
        └── raw/ (可选)     ← Markdown 源文件（历史兼容）
            └── *.md
    """

    def __init__(self, sop_base_dir: str):
        """初始化 SOP 加载器。

        Args:
            sop_base_dir: SOP 根目录路径，包含 json/、raw/ 和 index.json
        """
        self.sop_base_dir = sop_base_dir
        self.json_dir = os.path.join(sop_base_dir, "json")
        self.raw_dir = os.path.join(sop_base_dir, "raw")
        self.index_file = os.path.join(sop_base_dir, "index.json")
        self.sops: List[SOP] = []
        self.parser = SopParser()

    def load_all(self) -> List[SOP]:
        """从索引文件加载 SOP 列表。如果索引不存在则自动生成。"""
        if not os.path.exists(self.index_file):
            print(f"SOP Index not found at {self.index_file}, generating...")
            self.refresh_index()

        self.sops = self._load_from_index()
        if any(s.blackboard is None for s in self.sops):
            self.refresh_index()
            self.sops = self._load_from_index()
        return self.sops

    def refresh_index(self):
        """生成或更新 index.json，优先扫描 json/ 目录，兼容 raw/ 目录。"""
        if not os.path.exists(self.sop_base_dir):
            return

        index_data = []

        # 主要数据源：json/ 目录下的所有 .json 文件
        if os.path.exists(self.json_dir):
            json_files = glob.glob(os.path.join(self.json_dir, "*.json"))
            for fpath in sorted(json_files):
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        sop_data = json.load(f)

                    sop_id = sop_data.get("id", "")
                    if not sop_id:
                        sop_id = os.path.splitext(os.path.basename(fpath))[0]

                    description = sop_data.get("description", f"SOP for {sop_id}")
                    if len(description) > 200:
                        description = description[:197] + "..."

                    index_data.append({
                        "id": sop_id,
                        "name_zh": sop_data.get("name_zh", sop_id),
                        "name_en": sop_data.get("name_en", ""),
                        "description": description,
                        "blackboard": sop_data.get("blackboard"),
                        "_source": "json"
                    })
                except Exception as e:
                    print(f"Error indexing JSON {fpath}: {e}")

        # 兼容数据源：raw/ 目录下的 .md 文件（仅当 json/ 中未注册时）
        if os.path.exists(self.raw_dir):
            existing_ids = {entry["id"] for entry in index_data}
            md_files = glob.glob(os.path.join(self.raw_dir, "*.md"))

            for fpath in sorted(md_files):
                try:
                    filename = os.path.basename(fpath)
                    sop_id = os.path.splitext(filename)[0]

                    if sop_id in existing_ids:
                        continue

                    description = f"SOP for {sop_id}"
                    with open(fpath, 'r', encoding='utf-8') as f:
                        full_content = f.read()
                        head_content = full_content[:1000]
                        lines = head_content.split('\n')
                        for line in lines:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                description = line
                                break
                            elif line.startswith('# '):
                                description = line.lstrip('#').strip()

                    blackboard = self.parser.extract_blackboard_from_markdown(full_content)

                    if len(description) > 200:
                        description = description[:197] + "..."

                    index_data.append({
                        "id": sop_id,
                        "filename": filename,
                        "name": sop_id,
                        "description": description,
                        "blackboard": blackboard,
                        "_source": "raw"
                    })
                except Exception as e:
                    print(f"Error indexing MD {fpath}: {e}")

        # 写入到根目录的 index.json
        with open(self.index_file, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=2, ensure_ascii=False)
        print(f"SOP Index generated with {len(index_data)} entries (json={sum(1 for e in index_data if e.get('_source')=='json')}, raw={sum(1 for e in index_data if e.get('_source')=='raw')}).")

    def _load_from_index(self) -> List[SOP]:
        """读取 index.json 并转换为 SOP 对象列表，根据来源类型选择加载策略。"""
        sops = []
        if not os.path.exists(self.index_file):
            return sops

        try:
            with open(self.index_file, 'r', encoding='utf-8') as f:
                index_data = json.load(f)

            for entry in index_data:
                source = entry.get("_source", "raw")
                sop_id = entry["id"]

                if source == "json":
                    sop = self._load_json_sop(sop_id)
                    if sop:
                        sops.append(sop)
                    continue

                # raw/ 来源的 SOP（原有逻辑）
                sop = self._load_raw_sop(entry)
                if sop:
                    sops.append(sop)

        except Exception as e:
            print(f"Error loading SOP index: {e}")

        return sops

    def _load_json_sop(self, sop_id: str) -> Optional[SOP]:
        """从 json/ 目录加载完整的 SOP 对象（包含 steps 和 blackboard）。"""
        json_path = os.path.join(self.json_dir, f"{sop_id}.json")
        if not os.path.exists(json_path):
            return None

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                sop_data = json.load(f)

            steps_data = sop_data.get("steps", [])
            loaded_steps = []
            if steps_data:
                for s_dict in steps_data:
                    loaded_steps.append(Step(**_normalize_step_dict(s_dict)))

            sop = SOP(
                id=sop_data.get("id", sop_id),
                name_zh=sop_data.get("name_zh", sop_id),
                name_en=sop_data.get("name_en", ""),
                description=sop_data.get("description", ""),
                steps=loaded_steps or [Step(id="execute_md", tool="auto")],
                blackboard=sop_data.get("blackboard")
            )
            return sop
        except Exception as e:
            print(f"Error loading JSON SOP {sop_id}: {e}")
            return None

    def _load_raw_sop(self, entry: Dict[str, Any]) -> Optional[SOP]:
        """从 raw/ 索引条目加载 SOP，并尝试用 json/ 中的缓存补充详情。"""
        sop_id = entry["id"]

        step = Step(
            id="execute_md",
            tool="sop_run",
            description={"content": f"Run SOP: {entry.get('filename', sop_id)}", "citations": []},
            inputs={
                "question": "${user_query}",
                "filename": entry.get('filename', f"{sop_id}.md")
            },
            outputs={"result": "result"}
        )

        sop = SOP(
            id=sop_id,
            name_zh=entry.get("name_zh", entry.get("name", sop_id)),
            name_en=entry.get("name_en", sop_id),
            description=entry.get("description", ""),
            steps=[step],
            blackboard=entry.get("blackboard")
        )

        # 尝试从 json/ 缓存加载详细步骤
        json_path = os.path.join(self.json_dir, f"{sop_id}.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as jf:
                    cached = json.load(jf)
                if cached.get("steps"):
                    loaded_steps = [Step(**_normalize_step_dict(s)) for s in cached.get("steps")]
                    sop.steps = loaded_steps
                    sop.blackboard = cached.get("blackboard") or self.parser.build_blackboard_from_steps(loaded_steps)
                elif cached.get("blackboard"):
                    sop.blackboard = cached.get("blackboard")
            except Exception:
                pass

        return sop

    def analyze_sop(self, sop_id: str, config_name: str = "Qwen3-4B (Public)", mode: str = "instruct", save_to_json: bool = False, prefer_llm: bool = True, force_refresh: bool = False) -> SOP:
        """获取 SOP 的详细执行步骤。

        策略：
        1. 如果 SOP 来自 json/ 且已有完整 steps，直接返回（无需解析）。
        2. 如果 SOP 来自 raw/ 或需要刷新，走原有的 MD→LLM 解析流程。
        """
        # 查找已加载的 SOP
        if self.sops:
            sop = next((s for s in self.sops if s.id == sop_id), None)
        else:
            sop = next((s for s in self.load_all() if s.id == sop_id), None)
        if not sop:
            raise ValueError(f"SOP {sop_id} not found")

        # 判断 SOP 来源
        is_json_source = False
        json_path = os.path.join(self.json_dir, f"{sop_id}.json")

        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                if cached.get("steps") and len(cached.get("steps")) > 1:
                    is_json_source = True
            except Exception:
                pass

        # JSON 来源且已有完整步骤：直接返回
        if is_json_source and not force_refresh:
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                steps_data = cached_data.get("steps", [])
                if steps_data:
                    loaded_steps = [Step(**s) for s in steps_data]
                    sop.steps = loaded_steps
                    sop.blackboard = cached_data.get("blackboard") or self.parser.build_blackboard_from_steps(loaded_steps)
                    return sop
            except Exception as e:
                print(f"[SOP Loader] Failed to load JSON SOP {sop_id}: {e}")

        # Raw 来源或强制刷新：走原有解析流程
        filename = sop.steps[0].inputs.get("filename") if sop.steps else ""
        if not filename:
            if is_json_source:
                return sop
            raise ValueError(f"SOP {sop_id} has no filename associated")

        filepath = os.path.join(self.raw_dir, filename)
        if not os.path.exists(filepath):
            if is_json_source:
                return sop
            raise FileNotFoundError(f"SOP file {filepath} not found")

        file_mtime = os.path.getmtime(filepath)

        # 尝试从 JSON 缓存加载
        if not force_refresh and os.path.exists(json_path):
            json_mtime = os.path.getmtime(json_path)
            if json_mtime >= file_mtime:
                try:
                    with open(json_path, "r", encoding="utf-8") as jf:
                        cached_data = json.load(jf)
                    steps_data = cached_data.get("steps", [])
                    if steps_data:
                        loaded_steps = [Step(**s) for s in steps_data]
                        sop.steps = loaded_steps
                        sop.blackboard = cached_data.get("blackboard") or self.parser.build_blackboard_from_steps(loaded_steps)
                        return sop
                except Exception as e:
                    print(f"[SOP Loader] Cache load failed for {sop_id}: {e}, falling back to parser.")

        # LLM 解析流程
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
        """批量预解析所有 SOP 并输出到 json/。"""
        sops = self.load_all()
        results = {"total": len(sops), "success": 0, "failed": 0, "items": []}
        for sop in sops:
            try:
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
    sop_base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "sops"))
    config_name = "Qwen3-4B (Public)"
    mode = "instruct"
    sop_id = None
    force = False
    args = sys.argv[1:]
    if args:
        sop_base_dir = args[0]
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
    loader = SopLoader(sop_base_dir)
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

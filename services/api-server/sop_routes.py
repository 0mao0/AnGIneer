"""SOP 经验库 API 路由。"""
import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, HTTPException, UploadFile, File as FastAPIFile, Form
from pydantic import BaseModel, Field

from angineer_core.base_contracts import SOP as SopModel, Step as StepModel
from sop_core.sop_parser import SopParser
from sop_core.sop_loader import SopLoader

sop_router = APIRouter()

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
SOP_BASE_DIR = os.environ.get("SOP_DATA_DIR", os.path.join(ROOT_DIR, "data", "sops"))
SOP_JSON_DIR = os.path.join(SOP_BASE_DIR, "json")
SOP_RAW_DIR = os.path.join(SOP_BASE_DIR, "raw")
SOP_FOLDERS_FILE = os.path.join(SOP_BASE_DIR, "folders.json")

_sop_loader = SopLoader(SOP_BASE_DIR)
_sop_parser = SopParser()


class SopCreateRequest(BaseModel):
    """创建 SOP 请求体。"""
    id: Optional[str] = None
    name_zh: str
    name_en: Optional[str] = None
    description: Optional[str] = None
    folder_id: Optional[str] = None
    sort_order: Optional[int] = None
    steps: Optional[List[Dict[str, Any]]] = None
    blackboard: Optional[Dict[str, Any]] = None


class SopUpdateRequest(BaseModel):
    """更新 SOP 请求体。"""
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    folder_id: Optional[str] = None
    sort_order: Optional[int] = None
    steps: Optional[List[Dict[str, Any]]] = None
    blackboard: Optional[Dict[str, Any]] = None


class FolderCreateRequest(BaseModel):
    """创建文件夹请求体。"""
    folder_id: Optional[str] = None
    title: str
    parent_folder_id: Optional[str] = None
    sort_order: Optional[int] = None


class FolderUpdateRequest(BaseModel):
    """更新文件夹请求体。"""
    title: Optional[str] = None
    parent_folder_id: Optional[str] = None
    sort_order: Optional[int] = None


class SopStepParseRequest(BaseModel):
    """步骤描述解析请求体。"""
    description: str = Field(..., min_length=1)


def _ensure_json_dir() -> None:
    """确保 SOP JSON 目录存在。"""
    os.makedirs(SOP_JSON_DIR, exist_ok=True)


def _read_folders() -> List[Dict[str, Any]]:
    """读取文件夹结构。"""
    if not os.path.exists(SOP_FOLDERS_FILE):
        return []
    try:
        with open(SOP_FOLDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _write_folders(folders: List[Dict[str, Any]]) -> None:
    """写入文件夹结构。"""
    os.makedirs(os.path.dirname(SOP_FOLDERS_FILE), exist_ok=True)
    with open(SOP_FOLDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(folders, f, indent=2, ensure_ascii=False)


def _sort_items(items: List[Dict[str, Any]], title_key: str) -> List[Dict[str, Any]]:
    """按排序号和标题稳定排序。"""
    return sorted(
        items,
        key=lambda item: (
            item.get("sort_order", 10**9),
            str(item.get(title_key) or ""),
        ),
    )


def _get_next_sop_sort_order(folder_id: Optional[str]) -> int:
    """计算指定文件夹下下一个 SOP 排序号。"""
    sops = _scan_json_sops()
    sibling_orders = [
        int(item.get("sort_order", 0))
        for item in sops
        if (item.get("folder_id") or None) == (folder_id or None)
    ]
    return (max(sibling_orders) + 1) if sibling_orders else 0


def _get_next_folder_sort_order(parent_folder_id: Optional[str]) -> int:
    """计算指定父文件夹下下一个文件夹排序号。"""
    folders = _read_folders()
    sibling_orders = [
        int(item.get("sort_order", 0))
        for item in folders
        if (item.get("parent_folder_id") or None) == (parent_folder_id or None)
    ]
    return (max(sibling_orders) + 1) if sibling_orders else 0


def _scan_json_sops() -> List[Dict[str, Any]]:
    """扫描 JSON 目录下的 SOP 文件，返回元数据列表。"""
    _ensure_json_dir()
    results = []
    for fname in os.listdir(SOP_JSON_DIR):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(SOP_JSON_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            results.append({
                "id": data.get("id", os.path.splitext(fname)[0]),
                "name_zh": data.get("name_zh", ""),
                "name_en": data.get("name_en", ""),
                "description": data.get("description", ""),
                "folder_id": data.get("folder_id"),
                "sort_order": data.get("sort_order"),
                "step_count": len(data.get("steps", [])),
            })
        except Exception:
            continue
    return _sort_items(results, "name_zh")


def _read_sop_json(sop_id: str) -> Optional[Dict[str, Any]]:
    """读取单个 SOP 的 JSON 文件内容。"""
    json_path = os.path.join(SOP_JSON_DIR, f"{sop_id}.json")
    if not os.path.exists(json_path):
        return None
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_sop_json(sop_id: str, data: Dict[str, Any]) -> None:
    """写入单个 SOP 的 JSON 文件。"""
    _ensure_json_dir()
    json_path = os.path.join(SOP_JSON_DIR, f"{sop_id}.json")
    data["id"] = sop_id
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _normalize_inline_step_description(value: Any, allow_string: bool) -> Dict[str, Any]:
    """将步骤 description 规范化为结构化 {content, citations[]}。"""
    if isinstance(value, dict):
        return {
            "content": str(value.get("content") or ""),
            "citations": value.get("citations") if isinstance(value.get("citations"), list) else [],
        }
    if value is None:
        return {"content": "", "citations": []}
    if isinstance(value, str):
        if not allow_string:
            raise HTTPException(status_code=422, detail="Step.description 必须为 {content,citations[]} 结构，不再支持字符串。")
        return {"content": value, "citations": []}
    if not allow_string:
        raise HTTPException(status_code=422, detail="Step.description 必须为 {content,citations[]} 结构。")
    return {"content": str(value), "citations": []}


def _normalize_steps_payload(steps: Any, allow_string: bool) -> List[Dict[str, Any]]:
    """规范化 steps 列表并校验 step.description 类型。"""
    if steps is None:
        return []
    if not isinstance(steps, list):
        raise HTTPException(status_code=422, detail="steps 必须为数组。")
    normalized: List[Dict[str, Any]] = []
    for item in steps:
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="steps 中的每一项必须为对象。")
        step = dict(item)
        step["description"] = _normalize_inline_step_description(step.get("description"), allow_string=allow_string)
        normalized.append(step)
    return normalized


def _migrate_sop_steps_inplace(sop_id: str, data: Dict[str, Any]) -> bool:
    """将存量 SOP JSON 中的旧 steps.description（字符串）迁移为结构化对象。"""
    steps = data.get("steps")
    if not isinstance(steps, list):
        return False
    migrated = False
    normalized_steps: List[Dict[str, Any]] = []
    for item in steps:
        if not isinstance(item, dict):
            normalized_steps.append(item)
            continue
        desc = item.get("description")
        if isinstance(desc, str):
            migrated = True
        normalized_item = dict(item)
        normalized_item["description"] = _normalize_inline_step_description(desc, allow_string=True)
        normalized_steps.append(normalized_item)
    if migrated:
        data["steps"] = normalized_steps
        _write_sop_json(sop_id, data)
    return migrated


def _extract_json_from_text(text: str) -> Dict[str, Any]:
    """从 LLM 响应中提取 JSON 对象。"""
    raw = (text or "").strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        pass

    start = raw.find("{")
    if start < 0:
        raise ValueError("未找到 JSON 对象")

    depth = 0
    in_str = False
    escape = False
    for index, char in enumerate(raw[start:], start):
        if in_str:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == "\"":
                in_str = False
            continue
        if char == "\"":
            in_str = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(raw[start:index + 1])

    raise ValueError("JSON 解析失败")


def _collect_descendant_folder_ids(folder_id: str, folders: List[Dict[str, Any]]) -> Set[str]:
    """收集指定文件夹及其所有子文件夹 ID。"""
    collected: Set[str] = set()
    pending = [folder_id]
    while pending:
        current = pending.pop()
        if current in collected:
            continue
        collected.add(current)
        for folder in folders:
            if folder.get("parent_folder_id") == current:
                pending.append(str(folder.get("folder_id")))
    return collected


def _build_folder_delete_preview(folder_id: str) -> Dict[str, Any]:
    """构建文件夹删除影响预览。"""
    folders = _read_folders()
    target = next((folder for folder in folders if folder.get("folder_id") == folder_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Folder not found")

    folder_ids = _collect_descendant_folder_ids(folder_id, folders)
    related_sops = [item for item in _scan_json_sops() if (item.get("folder_id") or None) in folder_ids]
    folder_titles = [
        folder.get("title", "")
        for folder in folders
        if folder.get("folder_id") in folder_ids and folder.get("title")
    ]
    sop_titles = [item.get("name_zh") or item.get("id") for item in related_sops]
    sample_titles = [title for title in [*folder_titles, *sop_titles] if title][:3]
    folder_count = len(folder_ids)
    document_count = len(related_sops)
    return {
        "target_id": folder_id,
        "target_title": target.get("title", folder_id),
        "target_type": "folder",
        "folder_count": folder_count,
        "document_count": document_count,
        "total_nodes": folder_count + document_count,
        "sample_titles": sample_titles,
    }


def _guess_tool(description: str) -> str:
    """在 LLM 不可用时根据描述进行最小工具类型猜测。"""
    text = description.lower()
    if any(keyword in description for keyword in ["表", "图", "查表", "查询表", "查图"]) or "table" in text:
        return "table_lookup"
    if any(keyword in description for keyword in ["计算", "公式", "求和", "乘", "除", "加", "减"]) or any(symbol in description for symbol in ["=", "+", "-", "*", "/"]):
        return "calculator"
    if any(keyword in description for keyword in ["调用", "总结", "生成", "分析", "提取"]) or "llm" in text:
        return "llm_call"
    return "manual"


def _extract_named_items(description: str, labels: List[str]) -> Dict[str, str]:
    """从“输入/输出”段落里提取逗号分隔的键名。"""
    for label in labels:
        match = re.search(rf"{label}\s*[:：]\s*([^\n]+)", description, re.IGNORECASE)
        if not match:
            continue
        segment = match.group(1)
        items = [part.strip(" `") for part in re.split(r"[，,、；;]", segment) if part.strip(" `")]
        return {item: "" for item in items}
    return {}


def _fallback_parse_step_description(description: str) -> Dict[str, Any]:
    """在无法调用 LLM 时兜底解析步骤描述。"""
    variable_refs = re.findall(r"\$\{([^}]+)\}", description or "")
    input_map = {name: f"${{{name}}}" for name in variable_refs}
    input_map.update(_extract_named_items(description, ["输入参数", "输入", "Inputs"]))
    output_map = _extract_named_items(description, ["输出参数", "输出", "Outputs"])
    return {
        "tool": _guess_tool(description),
        "inputs": input_map,
        "outputs": output_map,
    }


def _parse_step_description(description: str) -> Dict[str, Any]:
    """优先调用 LLM 解析步骤描述，失败时回退到规则解析。"""
    normalized = (description or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="描述不能为空")

    system_prompt = (
        "你是一个 SOP 步骤结构化助手。"
        "请根据用户提供的步骤描述，输出一个 JSON 对象，且只能输出 JSON。"
        "格式为: {\"tool\":\"manual|calculator|table_lookup|auto|sop_run|llm_call\","
        "\"inputs\":{\"参数名\":\"参数说明或引用\"},\"outputs\":{\"输出名\":\"输出说明或结果键\"}}。"
        "如果无法判断，就尽量保守，tool 返回 manual，inputs/outputs 返回空对象。"
    )
    user_prompt = f"步骤描述：\n{normalized}"
    try:
        from ai_inference.llm_client import llm_client

        result = llm_client.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            mode="instruct",
        )
        parsed = _extract_json_from_text(result)
        tool = str(parsed.get("tool") or "manual").strip() or "manual"
        inputs = parsed.get("inputs") if isinstance(parsed.get("inputs"), dict) else {}
        outputs = parsed.get("outputs") if isinstance(parsed.get("outputs"), dict) else {}
        return {
            "tool": tool,
            "inputs": inputs,
            "outputs": outputs,
        }
    except Exception:
        return _fallback_parse_step_description(normalized)


@sop_router.get("")
def list_sops():
    """列出所有 SOP。"""
    return {"sops": _scan_json_sops()}


@sop_router.get("/{sop_id}/delete-preview")
def get_sop_delete_preview(sop_id: str):
    """获取 SOP 删除影响预览。"""
    sop_data = _read_sop_json(sop_id)
    if sop_data is None:
        raise HTTPException(status_code=404, detail=f"SOP {sop_id} not found")
    title = sop_data.get("name_zh") or sop_data.get("name_en") or sop_id
    return {
        "target_id": sop_id,
        "target_title": title,
        "target_type": "sop",
        "folder_count": 0,
        "document_count": 1,
        "total_nodes": 1,
        "sample_titles": [title],
    }


@sop_router.get("/folders/{folder_id}/delete-preview")
def get_folder_delete_preview(folder_id: str):
    """获取文件夹删除影响预览。"""
    return _build_folder_delete_preview(folder_id)


@sop_router.post("/import")
async def import_sop(file: UploadFile = FastAPIFile(...), folder_id: Optional[str] = Form(default=None)):
    """导入 Markdown SOP 文件，自动解析为结构化 JSON。"""
    if not file.filename or not file.filename.lower().endswith(".md"):
        raise HTTPException(status_code=400, detail="仅支持 .md 文件")

    content = await file.read()
    try:
        md_text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件编码错误，请使用 UTF-8 编码")

    sop_id = os.path.splitext(file.filename)[0]
    existing_json = os.path.join(SOP_JSON_DIR, f"{sop_id}.json")

    # 同名冲突自动加 1：文件.json → 文件(1).json → 文件(2).json
    counter = 1
    original_id = sop_id
    while os.path.exists(existing_json):
        sop_id = f"{original_id}({counter})"
        existing_json = os.path.join(SOP_JSON_DIR, f"{sop_id}.json")
        counter += 1

    os.makedirs(SOP_RAW_DIR, exist_ok=True)
    new_filename = f"{sop_id}.md"
    raw_path = os.path.join(SOP_RAW_DIR, new_filename)
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(md_text)

    name_zh = sop_id
    description = ""
    for line in md_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# "):
            name_zh = stripped.lstrip("#").strip()
            continue
        if stripped and not stripped.startswith("#"):
            description = stripped
            break
    if len(description) > 200:
        description = description[:197] + "..."

    parse_content = md_text
    lines = md_text.splitlines()
    start_idx = 0
    step_keywords = ["## 实施步骤", "## 步骤", "## Steps", "## Implementation", "# Steps"]
    for i, ln in enumerate(lines):
        if any(ln.strip().startswith(k) for k in step_keywords):
            start_idx = i
            break
    if start_idx > 0:
        parse_content = "\n".join(lines[start_idx:])
    if len(parse_content) > 8000:
        parse_content = parse_content[:8000] + "\n...(内容已截断)"

    initial_step = StepModel(
        id="execute_md",
        tool="auto",
        description={"content": f"Run SOP: {file.filename}", "citations": []},
        inputs={"question": "${user_query}", "filename": file.filename},
        outputs={"result": "result"},
    )
    sop = SopModel(
        id=sop_id,
        name_zh=name_zh,
        name_en=name_zh,
        description=description,
        steps=[initial_step],
        blackboard=None,
    )

    try:
        sop = _sop_parser.parse(
            sop=sop,
            content=parse_content,
            filename=file.filename,
            save_to_json=False,
        )
    except Exception:
        sop.blackboard = _sop_parser.extract_blackboard_from_markdown(md_text)

    serialized_steps = []
    for step in sop.steps:
        if hasattr(step, "model_dump"):
            serialized_steps.append(step.model_dump(exclude_none=True))
        else:
            serialized_steps.append({k: v for k, v in step.dict().items() if v is not None})

    target_folder_id = folder_id if folder_id else None
    data = {
        "id": sop_id,
        "name_zh": sop.name_zh or name_zh,
        "name_en": sop.name_en or name_zh,
        "description": sop.description or description,
        "folder_id": target_folder_id,
        "sort_order": _get_next_sop_sort_order(target_folder_id),
        "steps": _normalize_steps_payload(serialized_steps, allow_string=True),
        "blackboard": sop.blackboard,
    }
    _write_sop_json(sop_id, data)
    _sop_loader.refresh_index()

    return {"status": "success", "id": sop_id}




@sop_router.post("/steps/parse")
def parse_step_description(request: SopStepParseRequest):
    """解析步骤描述中的工具、输入与输出建议。"""
    return _parse_step_description(request.description)


@sop_router.get("/{sop_id}")
def get_sop(sop_id: str):
    """获取单个 SOP 完整内容。"""
    data = _read_sop_json(sop_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"SOP {sop_id} not found")
    _migrate_sop_steps_inplace(sop_id, data)
    return data


@sop_router.put("/{sop_id}")
def update_sop(sop_id: str, request: SopUpdateRequest):
    """更新 SOP 内容。"""
    existing = _read_sop_json(sop_id) or {"id": sop_id}
    _migrate_sop_steps_inplace(sop_id, existing)
    field_set = getattr(request, "model_fields_set", getattr(request, "__fields_set__", set()))
    if "name_zh" in field_set:
        existing["name_zh"] = request.name_zh
    if "name_en" in field_set:
        existing["name_en"] = request.name_en
    if "description" in field_set:
        existing["description"] = request.description
    if "folder_id" in field_set:
        existing["folder_id"] = request.folder_id
    if "sort_order" in field_set:
        existing["sort_order"] = request.sort_order
    if "steps" in field_set:
        existing["steps"] = _normalize_steps_payload(request.steps, allow_string=False)
    if "blackboard" in field_set:
        existing["blackboard"] = request.blackboard
    _write_sop_json(sop_id, existing)
    _sop_loader.refresh_index()
    return {"status": "success", "id": sop_id}


@sop_router.post("")
def create_sop(request: SopCreateRequest):
    """创建新 SOP。"""
    _ensure_json_dir()
    sop_id = request.id or f"sop-{uuid.uuid4().hex[:8]}"
    json_path = os.path.join(SOP_JSON_DIR, f"{sop_id}.json")
    if os.path.exists(json_path):
        raise HTTPException(status_code=409, detail=f"SOP {sop_id} already exists")
    data = {
        "id": sop_id,
        "name_zh": request.name_zh,
        "name_en": request.name_en or request.name_zh,
        "description": request.description or "",
        "folder_id": request.folder_id,
        "sort_order": request.sort_order if request.sort_order is not None else _get_next_sop_sort_order(request.folder_id),
        "steps": _normalize_steps_payload(request.steps or [], allow_string=False),
        "blackboard": request.blackboard,
    }
    _write_sop_json(sop_id, data)
    _sop_loader.refresh_index()
    return {"status": "success", "id": sop_id}


@sop_router.delete("/{sop_id}")
def delete_sop(sop_id: str):
    """删除 SOP。"""
    json_path = os.path.join(SOP_JSON_DIR, f"{sop_id}.json")
    if os.path.exists(json_path):
        os.remove(json_path)
        _sop_loader.refresh_index()
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="SOP not found")


@sop_router.get("/folders/list")
def list_folders():
    """获取文件夹结构。"""
    folders = _sort_items(_read_folders(), "title")
    return {"folders": folders}


@sop_router.post("/folders")
def create_folder(request: FolderCreateRequest):
    """创建文件夹。"""
    folders = _read_folders()
    folder_id = request.folder_id or f"folder-{uuid.uuid4().hex[:8]}"
    if any(f.get("folder_id") == folder_id for f in folders):
        raise HTTPException(status_code=409, detail=f"Folder {folder_id} already exists")
    folders.append({
        "folder_id": folder_id,
        "title": request.title,
        "parent_folder_id": request.parent_folder_id,
        "sort_order": request.sort_order if request.sort_order is not None else _get_next_folder_sort_order(request.parent_folder_id),
    })
    _write_folders(folders)
    return {"status": "success", "folder_id": folder_id}


@sop_router.patch("/folders/{folder_id}")
def update_folder(folder_id: str, request: FolderUpdateRequest):
    """更新文件夹。"""
    folders = _read_folders()
    target = next((f for f in folders if f.get("folder_id") == folder_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Folder not found")
    field_set = getattr(request, "model_fields_set", getattr(request, "__fields_set__", set()))
    if "title" in field_set:
        target["title"] = request.title
    if "parent_folder_id" in field_set:
        target["parent_folder_id"] = request.parent_folder_id
    if "sort_order" in field_set:
        target["sort_order"] = request.sort_order
    _write_folders(folders)
    return {"status": "success"}


@sop_router.delete("/folders/{folder_id}")
def delete_folder(folder_id: str):
    """删除文件夹。"""
    folders = _read_folders()
    target = next((folder for folder in folders if folder.get("folder_id") == folder_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Folder not found")

    folder_ids = _collect_descendant_folder_ids(folder_id, folders)
    new_folders = [folder for folder in folders if folder.get("folder_id") not in folder_ids]
    for sop in _scan_json_sops():
        if (sop.get("folder_id") or None) not in folder_ids:
            continue
        json_path = os.path.join(SOP_JSON_DIR, f"{sop['id']}.json")
        if os.path.exists(json_path):
            os.remove(json_path)
    _write_folders(new_folders)
    return {"status": "success"}

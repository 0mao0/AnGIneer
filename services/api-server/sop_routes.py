"""SOP 经验库 API 路由。"""
import json
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

sop_router = APIRouter()

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
SOP_JSON_DIR = os.path.join(ROOT_DIR, "data", "sops", "json")
SOP_FOLDERS_FILE = os.path.join(ROOT_DIR, "data", "sops", "folders.json")


class SopCreateRequest(BaseModel):
    """创建 SOP 请求体。"""
    id: Optional[str] = None
    name_zh: str
    name_en: Optional[str] = None
    description: Optional[str] = None
    folder_id: Optional[str] = None
    steps: Optional[List[Dict[str, Any]]] = None


class SopUpdateRequest(BaseModel):
    """更新 SOP 请求体。"""
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    folder_id: Optional[str] = None
    steps: Optional[List[Dict[str, Any]]] = None
    blackboard: Optional[Dict[str, Any]] = None


class FolderCreateRequest(BaseModel):
    """创建文件夹请求体。"""
    folder_id: Optional[str] = None
    title: str
    parent_folder_id: Optional[str] = None


class FolderUpdateRequest(BaseModel):
    """更新文件夹请求体。"""
    title: Optional[str] = None
    parent_folder_id: Optional[str] = None


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
                "step_count": len(data.get("steps", [])),
            })
        except Exception:
            continue
    return results


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


@sop_router.get("")
def list_sops():
    """列出所有 SOP。"""
    return {"sops": _scan_json_sops()}


@sop_router.get("/{sop_id}")
def get_sop(sop_id: str):
    """获取单个 SOP 完整内容。"""
    data = _read_sop_json(sop_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"SOP {sop_id} not found")
    return data


@sop_router.put("/{sop_id}")
def update_sop(sop_id: str, request: SopUpdateRequest):
    """更新 SOP 内容。"""
    existing = _read_sop_json(sop_id) or {"id": sop_id}
    if request.name_zh is not None:
        existing["name_zh"] = request.name_zh
    if request.name_en is not None:
        existing["name_en"] = request.name_en
    if request.description is not None:
        existing["description"] = request.description
    if request.folder_id is not None:
        existing["folder_id"] = request.folder_id
    if request.steps is not None:
        existing["steps"] = request.steps
    if request.blackboard is not None:
        existing["blackboard"] = request.blackboard
    _write_sop_json(sop_id, existing)
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
        "steps": request.steps or [],
        "blackboard": None,
    }
    _write_sop_json(sop_id, data)
    return {"status": "success", "id": sop_id}


@sop_router.delete("/{sop_id}")
def delete_sop(sop_id: str):
    """删除 SOP。"""
    json_path = os.path.join(SOP_JSON_DIR, f"{sop_id}.json")
    if os.path.exists(json_path):
        os.remove(json_path)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="SOP not found")


@sop_router.get("/folders/list")
def list_folders():
    """获取文件夹结构。"""
    folders = _read_folders()
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
    if request.title is not None:
        target["title"] = request.title
    if request.parent_folder_id is not None:
        target["parent_folder_id"] = request.parent_folder_id
    _write_folders(folders)
    return {"status": "success"}


@sop_router.delete("/folders/{folder_id}")
def delete_folder(folder_id: str):
    """删除文件夹。"""
    folders = _read_folders()
    new_folders = [f for f in folders if f.get("folder_id") != folder_id]
    if len(new_folders) == len(folders):
        raise HTTPException(status_code=404, detail="Folder not found")
    _write_folders(new_folders)
    return {"status": "success"}

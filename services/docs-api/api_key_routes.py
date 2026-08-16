"""内部 API Key 管理端点。"""
import sqlite3
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from models.api_key import generate_key, list_keys, deactivate_key, reactivate_key, delete_key, rename_key
from models.parse_record import get_statistics
from models.v1_responses import CreateKeyRequest

router = APIRouter(prefix="/api")


class KeyItem(BaseModel):
    id: int
    key_prefix: str
    user_name: str
    is_active: bool
    created_at: str
    last_used_at: str | None = None
    scope: str = "both"
    library_id: str = ""
    doc_count: int = 0


class CreateKeyResponse(BaseModel):
    api_key: str = Field(..., description="完整 key，仅此时可见")
    key_prefix: str
    user_name: str
    scope: str
    created_at: str
    message: str = "请妥善保管此 Key，离开此页面后将无法再次查看完整 Key。"


@router.get("/api-keys", response_model=list[KeyItem], tags=["Admin"])
async def list_api_keys():
    keys = list_keys()
    try:
        from pathlib import Path
        pr_db = str(
            Path(__file__).resolve().parent.parent.parent.parent
            / "data" / "parse_records.sqlite"
        )
        if Path(pr_db).exists():
            conn = sqlite3.connect(pr_db)
            rows = conn.execute(
                "SELECT api_key_id, COUNT(*) as cnt FROM parse_records WHERE api_key_id IS NOT NULL AND status != 'deleted' GROUP BY api_key_id"
            ).fetchall()
            conn.close()
            count_map = {r[0]: r[1] for r in rows}
            for k in keys:
                k["doc_count"] = count_map.get(k["id"], 0)
    except Exception:
        pass
    return keys


@router.post("/api-keys", response_model=CreateKeyResponse, tags=["Admin"])
async def create_api_key(req: CreateKeyRequest):
    raw_key, api_key = generate_key(req.user_name, scope=req.scope, library_id=req.library_id)
    return CreateKeyResponse(
        api_key=raw_key,
        key_prefix=api_key.key_prefix,
        user_name=api_key.user_name,
        scope=api_key.scope,
        created_at=api_key.created_at,
    )


@router.post("/api-keys/{key_id}/deactivate", tags=["Admin"])
async def deactivate_api_key(key_id: int):
    ok = deactivate_key(key_id)
    if not ok:
        raise HTTPException(404, "Key not found")
    return {"status": "deactivated"}


@router.post("/api-keys/{key_id}/reactivate", tags=["Admin"])
async def reactivate_api_key(key_id: int):
    ok = reactivate_key(key_id)
    if not ok:
        raise HTTPException(404, "Key not found")
    return {"status": "reactivated"}


@router.put("/api-keys/{key_id}/rename", tags=["Admin"])
async def rename_api_key(key_id: int, body: dict):
    new_name = (body.get("name") or "").strip()
    if not new_name:
        raise HTTPException(400, "名称不能为空")
    ok = rename_key(key_id, new_name)
    if not ok:
        raise HTTPException(404, "Key not found")
    return {"status": "success", "message": "名称已更新"}


@router.delete("/api-keys/{key_id}", tags=["Admin"])
async def delete_api_key(key_id: int):
    """永久删除 API Key。"""
    ok = delete_key(key_id)
    if not ok:
        raise HTTPException(404, "Key not found")
    return {"status": "success", "message": "Key 已删除"}


@router.get("/api-keys/statistics", tags=["Admin"])
async def get_parse_statistics(
    start_date: str,
    end_date: str,
    group_by: str = "day",
):
    """获取解析统计数据。start_date/end_date 格式: YYYY-MM-DD"""
    data = get_statistics(start_date, end_date, group_by)
    return {"status": "success", "data": data}

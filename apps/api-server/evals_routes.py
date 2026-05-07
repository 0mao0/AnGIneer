"""Evals API 路由。"""
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File as FastAPIFile

from evals_core.contracts import (
    AddQuestionRequest,
    CompareResult,
    CreateDatasetRequest,
    CreateFolderRequest,
    EvalRunProgress,
    MoveDatasetRequest,
    StartEvalRunRequest,
    UpdateFolderRequest,
    UpdateQuestionRequest,
)
from evals_core.dataset import manager
from evals_core.runner import suite_runner
from evals_core.storage import result_store

evals_router = APIRouter()


@evals_router.on_event("startup")
async def _startup():
    """应用启动时初始化数据库。"""
    result_store.init_db()


# --- 题集管理 ---


@evals_router.get("/datasets")
async def get_datasets():
    """列出所有测试集。"""
    datasets = manager.list_datasets()
    return {"datasets": datasets}


@evals_router.post("/datasets")
async def create_dataset(req: CreateDatasetRequest):
    """创建空测试集。"""
    dataset = manager.create_dataset(req.model_dump())
    return dataset


@evals_router.post("/datasets/import")
async def import_dataset(file: UploadFile = FastAPIFile(...)):
    """导入 JSON 题集文件。"""
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="仅支持 .json 文件")
    content = await file.read()
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {exc}")
    try:
        dataset = manager.import_bundle(payload, source_file=file.filename)
        return dataset
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"题集格式错误: {exc}")


@evals_router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str):
    """获取测试集详情。"""
    dataset = manager.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="测试集不存在")
    return dataset


@evals_router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str):
    """删除测试集。"""
    success = manager.delete_dataset(dataset_id)
    if not success:
        raise HTTPException(status_code=404, detail="测试集不存在")
    return {"status": "deleted"}


@evals_router.patch("/datasets/{dataset_id}")
async def update_dataset(dataset_id: str, body: Dict[str, Any] = None):
    """更新测试集元信息（如标题）。"""
    if not body:
        raise HTTPException(status_code=400, detail="无更新内容")
    dataset = manager.update_dataset(dataset_id, body)
    if not dataset:
        raise HTTPException(status_code=404, detail="测试集不存在")
    return dataset


@evals_router.get("/datasets/{dataset_id}/questions")
async def get_questions(dataset_id: str):
    """获取测试集题目列表。"""
    questions = manager.list_questions(dataset_id)
    return {"questions": questions}


@evals_router.post("/datasets/{dataset_id}/questions")
async def add_question(dataset_id: str, req: AddQuestionRequest):
    """向测试集添加单题。"""
    question = manager.add_question(dataset_id, req.model_dump())
    return question


@evals_router.put("/datasets/{dataset_id}/questions/{question_id}")
async def update_question(dataset_id: str, question_id: str, req: UpdateQuestionRequest):
    """编辑题目。"""
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="无更新内容")
    question = manager.update_question(dataset_id, question_id, updates)
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")
    return question


@evals_router.delete("/datasets/{dataset_id}/questions/{question_id}")
async def delete_question(dataset_id: str, question_id: str):
    """删除题目。"""
    success = manager.delete_question(dataset_id, question_id)
    if not success:
        raise HTTPException(status_code=404, detail="题目不存在")
    return {"status": "deleted"}


@evals_router.get("/datasets/{dataset_id}/export")
async def export_dataset(dataset_id: str):
    """导出测试集为规范 JSON。"""
    data = manager.export_dataset(dataset_id)
    if not data:
        raise HTTPException(status_code=404, detail="测试集不存在")
    return data


# --- 文件夹管理 ---


@evals_router.get("/folders")
async def get_folders():
    """列出所有文件夹。"""
    folders = manager.list_folders()
    return {"folders": folders}


@evals_router.post("/folders")
async def create_folder(req: CreateFolderRequest):
    """创建文件夹。"""
    folder = manager.create_folder(req.model_dump())
    return folder


@evals_router.patch("/folders/{folder_id}")
async def update_folder(folder_id: str, req: UpdateFolderRequest):
    """更新文件夹信息。"""
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="无更新内容")
    folder = manager.update_folder(folder_id, updates)
    if not folder:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return folder


@evals_router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str):
    """删除文件夹。"""
    success = manager.delete_folder(folder_id)
    if not success:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return {"status": "deleted"}


@evals_router.patch("/datasets/{dataset_id}/move")
async def move_dataset(dataset_id: str, req: MoveDatasetRequest):
    """移动数据集到指定文件夹。"""
    dataset = manager.move_dataset(dataset_id, req.folder_id, req.sort_order)
    if not dataset:
        raise HTTPException(status_code=404, detail="测试集不存在")
    return dataset


# --- 评测运行 ---


@evals_router.post("/runs")
async def start_run(req: StartEvalRunRequest):
    """启动评测运行（异步）。"""
    try:
        run_data = suite_runner.start_eval_run(req.dataset_id)
        return run_data
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@evals_router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """查询运行进度/结果。"""
    run = suite_runner.get_eval_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return run


@evals_router.get("/runs")
async def list_runs(dataset_id: Optional[str] = None):
    """列出历史运行记录。"""
    runs = suite_runner.list_eval_runs(dataset_id)
    return {"runs": runs}


@evals_router.get("/compare")
async def compare_runs(run_id_a: str, run_id_b: str):
    """对比两次运行结果。"""
    result = suite_runner.compare_runs(run_id_a, run_id_b)
    if not result:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return result

"""SOP 生成与导出 API 路由。

职责：
- 从实体路径生成单条 SOP
- 从文档图谱批量生成 SOP 列表

依赖：sop-core（SOP 生成器）+ knowledge-graph（只读 GraphStore）
"""

import logging
import os
import sys
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

sop_router = APIRouter()

# 注入 sop-core 与 knowledge-graph 源码路径
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SOP_SRC = os.path.join(ROOT_DIR, "services", "sop-core", "src")
KG_SRC = os.path.join(ROOT_DIR, "services", "knowledge-graph", "src")
for _p in (SOP_SRC, KG_SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# 获取知识图谱存储实例
def _get_store():
    from knowledge_graph.graph_store import GraphStore
    db_path = os.environ.get(
        "KG_DB_PATH",
        os.path.join(ROOT_DIR, "data", "knowledge_graph.sqlite"),
    )
    return GraphStore(db_path)


# 从实体路径生成单条 SOP 的请求
class SopExportRequest(BaseModel):
    path: List[str]
    title: str
    clause: str = ""
    include_extractions: bool = True
    library_id: str = ""
    doc_id: str = ""


# 从文档批量生成 SOP 的请求
class SopGenerateFromDocRequest(BaseModel):
    library_id: str
    doc_id: str


# 从实体路径生成单条 SOP
@sop_router.post("/generate")
async def generate_sop_from_path(req: SopExportRequest):
    from sop_core.sop_path_generator import SopPathGenerator

    store = _get_store()
    generator = SopPathGenerator(store=store if req.include_extractions else None)
    entities_map = {}
    for name in req.path:
        entity = store.get_entity_by_name(name)
        entities_map[name] = entity.layer if entity else "concept"
    sop = generator.generate_sop_skeleton(
        sop_id=req.title,
        title=req.title,
        path_entities=req.path,
        entities=entities_map,
        source_clause=req.clause,
        library_id=req.library_id,
        doc_id=req.doc_id,
    )
    return sop


# 从文档图谱批量生成 SOP（彻底解耦：只读图谱，不触发 KG 内部方法）
@sop_router.post("/generate-from-doc")
async def generate_sops_from_doc(req: SopGenerateFromDocRequest):
    from knowledge_graph.config import EntityLayer
    from sop_core.sop_path_generator import SopPathGenerator

    store = _get_store()

    # 检查 1：该文档是否有图谱数据
    doc_entities = store.list_entities_by_doc(req.library_id, req.doc_id)
    if not doc_entities:
        raise HTTPException(
            status_code=412,
            detail={
                "error": "graph_not_built",
                "message": "该文档尚未提取知识图谱，请先在知识图谱模块点击「提取图谱」",
                "hint": "前往知识图谱模块对该文档执行「提取图谱」",
            },
        )

    # 检查 2：是否有 framework 或 ACTION 层实体（SOP 路径来源）
    frameworks = store.get_frameworks_by_doc(req.library_id, req.doc_id)
    action_entities = [e for e in doc_entities if e.layer == EntityLayer.ACTION]
    if not frameworks and not action_entities:
        raise HTTPException(
            status_code=412,
            detail={
                "error": "extractors_not_run",
                "message": "该文档图谱未跑 AI 深度提取，SOP 生成可能为空骨架",
                "hint": "请在知识图谱模块对文档执行「AI 深度提取」后再生成 SOP",
            },
        )

    # 图谱已就绪，生成 SOP
    generator = SopPathGenerator(store=store)
    try:
        result = generator.generate_sops_from_doc(req.library_id, req.doc_id, store)
        logger.info("generate-sops-from-doc result: %s", result)
        return result
    except Exception as e:
        logger.error("generate-sops-from-doc failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

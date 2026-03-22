import os
import json
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks, Body
from pydantic import BaseModel

from docs_core import mineru_parser, file_storage, knowledge_service

router = APIRouter()

# 全局状态跟踪
parse_worker_threads: Dict[str, threading.Thread] = {}

class KnowledgeParseRequest(BaseModel):
    library_id: str
    doc_id: str
    file_path: Optional[str] = None

class KnowledgeStructuredIndexRequest(BaseModel):
    library_id: str
    doc_id: str
    strategy: Optional[str] = 'A_structured'

def _update_parse_task_progress(
    task_id: str,
    doc_id: str,
    status: str,
    progress: int,
    stage: str,
    error: Optional[str] = None
) -> None:
    """同步更新解析任务表和知识节点表的进度、状态及错误信息"""
    knowledge_service.update_parse_task(
        task_id,
        status=status,
        progress=max(0, min(100, progress)),
        stage=stage,
        error=error
    )
    knowledge_service.update_node(
        doc_id,
        status='failed' if status == 'failed' else 'processing' if status in {'queued', 'processing'} else 'completed',
        parse_progress=max(0, min(100, progress)),
        parse_stage=stage,
        parse_error=error
    )

def _build_structured_index_for_doc(library_id: str, doc_id: str, strategy: str = 'A_structured') -> Dict[str, Any]:
    """根据指定的策略（如结构化、RAG、页索引）为文档构建语义索引数据"""
    if strategy == 'A_structured':
        from docs_core.storage.structured_strategy import build_structured_index_for_doc
        return build_structured_index_for_doc(library_id, doc_id, strategy)
    if strategy == 'B_mineru_rag':
        from docs_core.storage.mineru_rag_strategy import build_mineru_rag_index_for_doc
        return build_mineru_rag_index_for_doc(library_id, doc_id, strategy)
    if strategy == 'C_pageindex':
        from docs_core.storage.pageindex_strategy import build_pageindex_for_doc
        return build_pageindex_for_doc(library_id, doc_id, strategy)
    raise ValueError(f'Unsupported strategy: {strategy}')

def _run_parse_task(task_id: str, library_id: str, doc_id: str, target_file_path: str) -> None:
    """执行后台解析任务的全生命周期管理，包括 MinerU 解析、产物整理和索引构建"""
    try:
        _update_parse_task_progress(task_id, doc_id, 'processing', 10, 'initializing')
        output_dir = tempfile.mkdtemp(prefix=f'parse-{doc_id}-')
        
        # 1. 调用 MinerUParser 解析文档
        _update_parse_task_progress(task_id, doc_id, 'processing', 35, 'mineru_processing')
        result = mineru_parser.parse_document(target_file_path, output_dir)
        
        if not result.get('success'):
            error_msg = result.get('error') or 'MinerU 解析失败'
            _update_parse_task_progress(task_id, doc_id, 'failed', 100, 'failed', error_msg)
            return
            
        _update_parse_task_progress(task_id, doc_id, 'processing', 70, 'reading_markdown')
        md_path = result.get('md_file')
        if not md_path or not os.path.exists(md_path):
            _update_parse_task_progress(task_id, doc_id, 'failed', 100, 'failed', '解析结果未生成 Markdown 文件')
            return
            
        with open(md_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
            
        # 2. 保存 Markdown 和产物
        _update_parse_task_progress(task_id, doc_id, 'processing', 85, 'saving_data')
        file_storage.save_markdown(library_id, doc_id, markdown_content)
        file_storage.save_parse_artifacts(library_id, doc_id, output_dir)
        
        # 3. 更新节点元数据并构建索引
        knowledge_service.update_node(
            doc_id,
            file_path=target_file_path,
            parse_task_id=task_id,
            parse_error=None
        )
        
        strategy = (knowledge_service.get_node(doc_id).strategy if knowledge_service.get_node(doc_id) else 'A_structured') or 'A_structured'
        _update_parse_task_progress(task_id, doc_id, 'processing', 92, 'building_structured_index')
        _build_structured_index_for_doc(library_id, doc_id, strategy)
        
        # 4. 完成任务
        _update_parse_task_progress(task_id, doc_id, 'completed', 100, 'completed')
        knowledge_service.update_node(doc_id, status='completed', parse_progress=100, parse_stage='completed')
        knowledge_service.update_parse_task(task_id, status='completed', progress=100, stage='completed', error=None)
        print(f'[ParseTask] completed: task_id={task_id}, doc_id={doc_id}')

    except Exception as error:
        import traceback
        traceback.print_exc()
        _update_parse_task_progress(task_id, doc_id, 'failed', 100, 'failed', str(error))
    finally:
        parse_worker_threads.pop(task_id, None)
        try:
            shutil.rmtree(output_dir)
        except:
            pass

@router.post("/parse")
async def create_parse_task(request: KnowledgeParseRequest, background_tasks: BackgroundTasks):
    """创建文档解析任务"""
    # 1. 获取文档信息
    doc = knowledge_service.get_node(request.doc_id)
    if not doc:
        # 如果数据库没有，尝试注册
        if not request.file_path or not os.path.exists(request.file_path):
            raise HTTPException(status_code=404, detail="Document not found and no file path provided")
        
        doc = knowledge_service.register_document(
            library_id=request.library_id,
            file_path=request.file_path
        )
    
    # 2. 准备文件
    target_file_path = request.file_path
    if not target_file_path:
        # 尝试从 storage 获取
        target_file_path = file_storage.ensure_doc_source_file(request.library_id, request.doc_id)
        
    if not target_file_path or not os.path.exists(target_file_path):
        raise HTTPException(status_code=400, detail=f"Source file not found for doc {request.doc_id}")

    # 3. 创建任务记录
    task_id = f"parse-{request.doc_id}-{int(time.time())}"
    knowledge_service.create_parse_task(task_id, request.library_id, request.doc_id)
    
    # 4. 启动后台线程
    thread = threading.Thread(
        target=_run_parse_task,
        args=(task_id, request.library_id, request.doc_id, target_file_path)
    )
    thread.daemon = True
    thread.start()
    parse_worker_threads[task_id] = thread
    
    return {"task_id": task_id, "status": "queued"}

@router.get("/parse/{task_id}")
async def get_parse_status(task_id: str):
    """获取解析任务状态"""
    task = knowledge_service.get_parse_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.post("/parse/structured-index")
async def build_structured_index(request: KnowledgeStructuredIndexRequest):
    """重建结构化索引"""
    try:
        result = _build_structured_index_for_doc(request.library_id, request.doc_id, request.strategy)
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class DocBlocksGraphRequest(BaseModel):
    library_id: str
    doc_id: str


@router.post("/parse/doc-blocks-graph")
async def get_doc_blocks_graph(request: DocBlocksGraphRequest):
    """获取文档块图谱数据（用于前端树形/图形视图）"""
    from docs_core.storage.structured_strategy import get_doc_blocks_graph as _get_doc_blocks_graph
    try:
        graph = _get_doc_blocks_graph(request.library_id, request.doc_id)
        if not graph:
            raise HTTPException(status_code=404, detail="Graph data not found. Please run structured-index first.")
        return {"status": "success", "data": graph}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

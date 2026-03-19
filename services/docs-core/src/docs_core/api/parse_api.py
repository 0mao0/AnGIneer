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
    """更新解析任务和节点状态"""
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
    """后台执行解析任务"""
    try:
        _update_parse_task_progress(task_id, doc_id, 'processing', 10, 'initializing')
        output_dir = tempfile.mkdtemp(prefix=f'parse-{doc_id}-')
        _update_parse_task_progress(task_id, doc_id, 'processing', 35, 'mineru_processing')
        
        # 1. 调用 MinerUParser 下载并解压原始数据
        # mineru_parser 负责：上传文件 -> 轮询状态 -> 下载 ZIP -> 解压到 output_dir (扁平化) -> 清理多余 md -> 生成 content.md
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
            
        # 读取 Markdown 内容
        with open(md_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
            
        _update_parse_task_progress(task_id, doc_id, 'processing', 85, 'saving_data')
        
        # 保存 Markdown
        file_storage.save_markdown(library_id, doc_id, markdown_content)
        
        # 保存原始文件 (model.json, layout.json, content_list.json 等) 到 parsed 目录
        # 这一步是为了解决 doc-1fe10aca 缺失文件的问题，确保 zip 解压出的所有内容都被保留
        parsed_dir = file_storage.get_parsed_dir(library_id, doc_id)
        out_path_obj = Path(output_dir)
        
        print(f"[ParseTask] Copying artifacts from {output_dir} to {parsed_dir}")
        # 递归复制所有文件到 parsed 目录
        try:
            if not parsed_dir.exists():
                parsed_dir.mkdir(parents=True, exist_ok=True)
            # 使用 dirs_exist_ok=True 允许覆盖 (Python 3.8+)
            shutil.copytree(output_dir, parsed_dir, dirs_exist_ok=True)
        except Exception as e:
            print(f"[ParseTask] Copy tree failed: {e}")
            # Fallback: manual copy
            for item in out_path_obj.rglob('*'):
                if item.is_file():
                    rel_path = item.relative_to(out_path_obj)
                    dest = parsed_dir / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest)

        # 确保关键 JSON 文件在 mineru_raw 目录
        mineru_raw_dir = parsed_dir / 'mineru_raw'
        mineru_raw_dir.mkdir(parents=True, exist_ok=True)
        
        final_json_files = []
        parsed_path_obj = Path(parsed_dir)

        # 1. 清理 PDF 文件 (如 origin.pdf)
        for pdf_file in list(parsed_path_obj.rglob('*.pdf')):
            try:
                print(f"[ParseTask] Removing PDF file: {pdf_file}")
                pdf_file.unlink()
            except Exception as e:
                print(f"[ParseTask] Failed to remove PDF {pdf_file}: {e}")

        # 2. 移动和重命名 JSON 文件到 mineru_raw
        # 移动 ZIP 文件 (origin.zip)
        zip_file = parsed_dir / 'origin.zip'
        if zip_file.exists():
            target_zip = mineru_raw_dir / 'origin.zip'
            try:
                if target_zip.exists():
                    target_zip.unlink()
                shutil.move(str(zip_file), str(target_zip))
                print(f"[ParseTask] Moved origin.zip to {target_zip}")
            except Exception as e:
                print(f"[ParseTask] Failed to move origin.zip: {e}")

        # 查找 model.json (支持前缀，如 docid_model.json)
        model_json_found = False
        for f in list(parsed_path_obj.rglob('*model.json')):
            target = mineru_raw_dir / 'model.json'
            try:
                if f.resolve() != target.resolve():
                     if target.exists():
                         target.unlink()
                     shutil.move(str(f), str(target))
                if target not in final_json_files:
                    final_json_files.append(target)
                model_json_found = True
            except Exception as e:
                 print(f"[ParseTask] Failed to move model.json: {e}")
        
        if not model_json_found:
             print(f"[ParseTask] WARNING: model.json not found in {parsed_dir}")

        # 查找 layout.json
        for f in list(parsed_path_obj.rglob('layout.json')):
            target = mineru_raw_dir / 'layout.json'
            try:
                if f.resolve() != target.resolve():
                    shutil.move(str(f), str(target))
                if target not in final_json_files:
                    final_json_files.append(target)
            except Exception as e:
                print(f"[ParseTask] Failed to move layout.json: {e}")

        # 查找 content_list_v2.json (支持前缀)
        v2_found = False
        for f in list(parsed_path_obj.rglob('*content_list_v2.json')):
            target = mineru_raw_dir / 'content_list_v2.json'
            try:
                if f.resolve() != target.resolve():
                     if target.exists():
                         target.unlink()
                     shutil.move(str(f), str(target))
                if target not in final_json_files:
                    final_json_files.append(target)
                v2_found = True
            except Exception as e:
                 print(f"[ParseTask] Failed to move content_list_v2.json: {e}")

        if not v2_found:
             print(f"[ParseTask] WARNING: content_list_v2.json not found in {parsed_dir}")

        # 查找 *_content_list.json (重命名为 content_list.json)
        for f in list(parsed_path_obj.rglob('*_content_list.json')):
            if f.name == 'content_list_v2.json':
                continue
            target = mineru_raw_dir / 'content_list.json'
            try:
                if f.resolve() != target.resolve():
                    # 如果目标已存在 (可能是之前的运行残留)，先删除
                    if target.exists():
                        target.unlink()
                    shutil.move(str(f), str(target))
                if target not in final_json_files:
                    final_json_files.append(target)
            except Exception as e:
                print(f"[ParseTask] Failed to move/rename content_list: {e}")

        # 注意：不再生成 mineru_blocks.json
        # doc_blocks_graph.json 直接由 structured_strategy 从 content_list_v2.json 构建

        # 清理旧数据
        middle_json_path = file_storage.get_doc_manifest(library_id, doc_id).get('middle_json')
        if isinstance(middle_json_path, str) and middle_json_path and os.path.isfile(middle_json_path):
            try:
                os.remove(middle_json_path)
            except Exception:
                pass
                
        # 3. 清理可能存在的冗余 assets 目录 (如果 images 存在)
        # 用户要求: "assets和images是重复的两个文件夹，zip文件解压出来的叫什么就是什么"
        # 因此，如果不使用 save_assets (它会强制创建 assets)，则保留 ZIP 原样。
        # 如果 ZIP 里只有 images，copytree 已经复制了 images。
        # 我们这里额外清理一下之前可能错误生成的 assets 目录 (如果它与 images 重复)
        assets_path = parsed_dir / 'assets'
        images_path = parsed_dir / 'images'
        if assets_path.exists() and images_path.exists():
             try:
                 print(f"[ParseTask] Removing redundant assets directory: {assets_path}")
                 shutil.rmtree(assets_path)
             except Exception as e:
                 print(f"[ParseTask] Failed to remove assets dir: {e}")
            
        knowledge_service.update_node(
            doc_id,
            file_path=target_file_path,
            parse_task_id=task_id,
            parse_error=None
        )
        strategy = (knowledge_service.get_node(doc_id).strategy if knowledge_service.get_node(doc_id) else 'A_structured') or 'A_structured'
        _update_parse_task_progress(task_id, doc_id, 'processing', 92, 'building_structured_index')
        _build_structured_index_for_doc(library_id, doc_id, strategy)
        _update_parse_task_progress(task_id, doc_id, 'completed', 100, 'completed')
        knowledge_service.update_node(doc_id, status='completed', parse_progress=100, parse_stage='completed')
        knowledge_service.update_parse_task(task_id, status='completed', progress=100, stage='completed', error=None)
        print(f'[ParseTask] completed: task_id={task_id}, doc_id={doc_id}, parsed_dir={parsed_dir}')
    except Exception as error:
        import traceback
        traceback.print_exc()
        _update_parse_task_progress(task_id, doc_id, 'failed', 100, 'failed', str(error))
    finally:
        parse_worker_threads.pop(task_id, None)
        # 清理临时目录
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

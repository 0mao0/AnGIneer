"""MinerU 文档解析服务 (公司自部署 API)"""
import json
import logging
import os
import tempfile
import threading
from typing import Optional, Dict, Any, List, Callable
from pathlib import Path
from dotenv import load_dotenv
import requests
import io
import zipfile
import shutil
import uuid

import docs_core.paths as paths

load_dotenv()

logger = logging.getLogger(__name__)


def _emit_on_step(
    on_step: Optional[Callable[[str, str, str], None]],
    step: str,
    status: str = "done",
    detail: str = "",
) -> None:
    if on_step is not None:
        try:
            on_step(step, status, detail)
        except Exception:
            logger.warning("MinerU 步骤回调失败 step=%s", step, exc_info=True)


def save_markdown(
    library_id: str,
    doc_id: str,
    content: str,
    base_dir: Optional[str] = None,
) -> str:
    """保存 Markdown 文件（parsed + edited 孪生配对）。"""
    parsed_md_path = paths.get_parsed_markdown_path(library_id, doc_id, base_dir)
    parsed_md_path.parent.mkdir(parents=True, exist_ok=True)
    with open(parsed_md_path, "w", encoding="utf-8") as f:
        f.write(content)
    edited_md_path = paths.get_edited_markdown_path(library_id, doc_id, base_dir)
    edited_md_path.parent.mkdir(parents=True, exist_ok=True)
    if not edited_md_path.exists():
        with open(edited_md_path, "w", encoding="utf-8") as f:
            f.write(content)
    return str(parsed_md_path)


def save_parse_artifacts(
    library_id: str,
    doc_id: str,
    output_dir: str,
    base_dir: Optional[str] = None,
    on_step: Optional[Callable[[str, str, str], None]] = None,
) -> Dict[str, Any]:
    """保存解析产物到文档目录（staging + mineru_raw 归一化 + 原子替换）。"""
    parsed_dir = paths.get_parsed_dir(library_id, doc_id, base_dir)
    parsed_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = parsed_dir.parent / f"{parsed_dir.name}.staging-{uuid.uuid4().hex[:8]}"
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    shutil.copytree(output_dir, staging_dir)

    mineru_raw_dir = staging_dir / "mineru_raw"
    mineru_raw_dir.mkdir(parents=True, exist_ok=True)

    # 源文件目录已保留原始 PDF（上传或转换产物），解压产物中的渲染 PDF（可能上百 MB）不再保留
    for pdf_file in list(staging_dir.rglob("*.pdf")):
        try:
            pdf_file.unlink()
        except Exception:
            pass

    artifact_map = {
        "origin.zip": "origin.zip",
        "*model.json": "model.json",
        "layout.json": "layout.json",
        "*content_list_v2.json": "content_list_v2.json",
        "content_list.json": "content_list.json",
        "*_content_list.json": "content_list.json",
        "middle.json": "middle.json",
    }

    final_files = {}
    for pattern, target_name in artifact_map.items():
        found_files = list(staging_dir.rglob(pattern))
        for artifact_file in found_files:
            if target_name == "content_list.json" and artifact_file.name == "content_list_v2.json":
                continue
            target = mineru_raw_dir / target_name
            try:
                if artifact_file.resolve() != target.resolve():
                    if target.exists():
                        target.unlink()
                    shutil.move(str(artifact_file), str(target))
                final_files[target_name] = str(target)
            except Exception:
                pass

    assets_path = staging_dir / "assets"
    images_path = staging_dir / "images"
    if assets_path.exists() and images_path.exists():
        try:
            shutil.rmtree(assets_path)
        except Exception:
            pass

    backup_dir = parsed_dir.parent / f"{parsed_dir.name}.backup-{uuid.uuid4().hex[:8]}"
    if parsed_dir.exists():
        parsed_dir.replace(backup_dir)
    staging_dir.replace(parsed_dir)
    if backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)

    _emit_on_step(
        on_step,
        "content_list.json 落盘",
        "done" if "content_list.json" in final_files
        else ("skipped" if "content_list_v2.json" in final_files else "failed"),
        str(final_files.get("content_list.json") or final_files.get("content_list_v2.json") or ""),
    )
    _emit_on_step(
        on_step,
        "middle.json / model.json 落盘",
        "done" if ("middle.json" in final_files or "model.json" in final_files) else "failed",
        str(final_files.get("middle.json") or final_files.get("model.json") or ""),
    )
    return final_files


class MinerUParser:
    """MinerU 文档解析器 (公司自部署 API)"""

    def __init__(self):
        self.api_url = (
            os.getenv('MINERU_API_URL', '')
            or os.getenv('MINERU_BASE_URL', '')
            or os.getenv('MINERU_ENDPOINT', '')
        ).strip().rstrip('/')
        self.api_key = (
            os.getenv('MINERU_API_KEY', '')
            or os.getenv('MINERU_API_TOKEN', '')
            or os.getenv('MINERU_TOKEN', '')
        )
        self.cloud_poll_max_attempts = max(1, int(os.getenv('MINERU_CLOUD_POLL_MAX_ATTEMPTS', '90')))
        self.proxy_fallback_enabled = os.getenv('MINERU_PROXY_FALLBACK_ENABLED', '1') != '0'
        self.ocr_enabled = os.getenv('MINERU_OCR_ENABLED', 'false').lower() == 'true'
        self.backend = os.getenv('MINERU_BACKEND', 'hybrid-engine').strip().lower()
        self.max_download_bytes = max(1, int(os.getenv('MINERU_DOWNLOAD_MAX_BYTES', str(1 << 30))))
        self.max_uncompressed_bytes = max(1, int(os.getenv('MINERU_UNCOMPRESSED_MAX_BYTES', str(4 << 30))))
        self.company_api_timeout = max(30, int(os.getenv('MINERU_COMPANY_API_TIMEOUT', '600')))
        self._abort_event = threading.Event()

    def cancel(self):
        """中断所有正在进行的请求。"""
        self._abort_event.set()

    def _request_with_proxy_fallback(self, method: str, url: str, **kwargs):
        """执行请求，代理失败时自动回退直连。"""
        if self._abort_event.is_set():
            raise RuntimeError("MinerU 请求已取消")
        try:
            return requests.request(method=method, url=url, **kwargs)
        except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as error:
            if self._abort_event.is_set():
                raise RuntimeError("MinerU 请求已取消")
            if not self.proxy_fallback_enabled:
                raise
            if isinstance(error, requests.exceptions.ConnectionError) and 'proxy' not in str(error).lower():
                raise
            retry_kwargs = dict(kwargs)
            retry_kwargs['proxies'] = {'http': None, 'https': None}
            return requests.request(method=method, url=url, **retry_kwargs)
        except requests.exceptions.Timeout:
            if self._abort_event.is_set():
                raise RuntimeError("MinerU 请求已取消")
            raise

    def _download_bytes(self, url: str, timeout: int, headers: Optional[Dict[str, str]] = None) -> Optional[bytes]:
        """流式下载并限制大小；取消/超限时抛异常，HTTP 失败时返回 None。"""
        resp = self._request_with_proxy_fallback(
            'GET', url, headers=headers, timeout=timeout, verify=False, stream=True,
        )
        if resp.status_code != 200:
            return None
        chunks: List[bytes] = []
        total = 0
        for chunk in resp.iter_content(chunk_size=1 << 20):
            if self._abort_event.is_set():
                raise RuntimeError("MinerU 请求已取消")
            total += len(chunk)
            if total > self.max_download_bytes:
                raise RuntimeError(f"MinerU 下载超过大小限制 {self.max_download_bytes} bytes: {url}")
            chunks.append(chunk)
        return b"".join(chunks)

    def _build_parse_result(
        self,
        success: bool,
        md_file: Optional[str] = None,
        error: Optional[str] = None,
        mineru_blocks: Optional[List[Dict[str, Any]]] = None,
        raw_artifacts: Optional[Dict[str, Any]] = None,
        output_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        return {
            'success': success,
            'md_file': md_file,
            'error': error,
            'mineru_blocks': mineru_blocks or [],
            'raw_artifacts': raw_artifacts or {},
            'output_dir': output_dir
        }

    def _write_markdown_file(
        self,
        output_dir: str,
        markdown: str,
        raw_artifacts: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """将 Markdown 写入 content.md 并返回成功结果。"""
        md_file_path = os.path.join(output_dir, 'content.md')
        with open(md_file_path, 'w', encoding='utf-8') as output_file:
            output_file.write(markdown)
        return self._build_parse_result(
            True,
            md_file=md_file_path,
            error=None,
            mineru_blocks=None,
            raw_artifacts=raw_artifacts,
            output_dir=output_dir
        )

    def _extract_zip_archive(self, zip_bytes: bytes, target_dir: Path) -> None:
        """将云端 ZIP 解压到目标目录，智能扁平化结构；失败或超限时抛出 RuntimeError。"""
        target_dir.mkdir(parents=True, exist_ok=True)
        target_root = target_dir.resolve()
        total_uncompressed = 0
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
                namelist = archive.namelist()
                logger.info("Extracting ZIP. Content (%d files): %s...", len(namelist), namelist[:10])

                # 分析目录结构，看是否所有文件都在同一个顶级目录下
                top_dirs = set()
                for name in namelist:
                    parts = Path(name).parts
                    if len(parts) > 1:
                        top_dirs.add(parts[0])
                    elif not name.endswith('/'):  # 根目录下的文件
                        top_dirs.add('')  # 标记有文件在根目录

                # 如果只有一个顶级目录且根目录下没有文件，说明是嵌套结构
                has_single_top_dir = len(top_dirs) == 1 and '' not in top_dirs
                logger.info("Zip structure: top_dirs=%s, flatten=%s", top_dirs, has_single_top_dir)

                for info in archive.infolist():
                    if info.is_dir():
                        continue

                    # zip bomb 防护：解压总大小限制
                    total_uncompressed += info.file_size
                    if total_uncompressed > self.max_uncompressed_bytes:
                        raise RuntimeError(f"解压总大小超过限制 {self.max_uncompressed_bytes} bytes")

                    member = Path(info.filename.replace("\\", "/"))
                    # Zip Slip 防护：拒绝绝对路径与含 .. 的条目
                    if member.is_absolute() or any(part == ".." for part in member.parts):
                        logger.warning("Skip unsafe zip entry: %s", info.filename)
                        continue

                    if has_single_top_dir:
                        # 去掉第一层目录
                        parts = member.parts
                        if len(parts) > 1:
                            destination = target_dir.joinpath(*parts[1:])
                        else:
                            destination = target_dir / member.name
                    else:
                        destination = target_dir / member

                    # 兜底校验：解析后的路径必须仍在目标目录内
                    try:
                        destination.resolve().relative_to(target_root)
                    except ValueError:
                        logger.warning("Skip zip entry escaping target dir: %s", info.filename)
                        continue

                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, open(destination, 'wb') as target:
                        shutil.copyfileobj(source, target)

        except Exception as e:
            raise RuntimeError(f"Zip extract failed: {e}") from e

    def _read_json_file(self, file_path: Path) -> Optional[Any]:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def _get_pdf_page_count(self, input_path: str) -> int:
        """获取 PDF 页数，非 PDF 或读取失败返回 0。"""
        try:
            import fitz
            doc = fitz.open(input_path)
            count = doc.page_count
            doc.close()
            return count
        except ImportError:
            logger.warning("PyMuPDF not installed, cannot check page count")
        except Exception as exc:
            logger.warning("Page count check failed: %s", exc)
        return 0

    def _split_pdf(self, input_path: str, chunk_size: int = 200) -> List[str]:
        """将 PDF 按页数拆分为多个临时文件，返回文件路径列表。"""
        import fitz

        doc = fitz.open(input_path)
        total_pages = doc.page_count
        chunk_paths: List[str] = []

        for start in range(0, total_pages, chunk_size):
            end = min(start + chunk_size, total_pages)
            chunk_doc = fitz.open()
            chunk_doc.insert_pdf(doc, from_page=start, to_page=end - 1)
            fd, chunk_path = tempfile.mkstemp(suffix=f"_pages_{start+1}-{end}.pdf")
            os.close(fd)
            chunk_doc.save(chunk_path)
            chunk_doc.close()
            chunk_paths.append(chunk_path)
            logger.info("Split chunk: pages %d-%d -> %s", start + 1, end, chunk_path)

        doc.close()
        return chunk_paths

    def _merge_chunk_results(self, output_dir: str, chunk_output_dirs: List[str], chunk_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """合并多个分段的解析结果为一份完整文档。"""
        merged_markdown_parts: List[str] = []

        for idx, result in enumerate(chunk_results):
            if not result.get("success"):
                return result

            md_file = result.get("md_file")
            if md_file and os.path.isfile(md_file):
                with open(md_file, "r", encoding="utf-8") as f:
                    merged_markdown_parts.append(f.read())

        merged_markdown = "\n\n".join(merged_markdown_parts)

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        for idx, chunk_dir in enumerate(chunk_output_dirs):
            if not os.path.isdir(chunk_dir):
                continue
            self._merge_dir_contents(Path(chunk_dir), Path(output_dir), chunk_idx=idx)

        # ---- 合并分块 JSON 产物（page_idx 偏移） ----
        self._merge_chunk_json_artifacts(Path(output_dir), chunk_output_dirs)

        return self._write_markdown_file(output_dir, merged_markdown)

    def _merge_chunk_json_artifacts(self, output_dir: Path, chunk_output_dirs: List[str]) -> None:
        """将各 chunk 的 JSON 产物合并到基准文件，对 page_idx 做偏移。"""
        import json as _json

        if len(chunk_output_dirs) <= 1:
            return

        # 计算每段页数
        page_offsets = [0]
        for chunk_dir_str in chunk_output_dirs[:-1]:
            chunk_dir = Path(chunk_dir_str)
            offset = page_offsets[-1]
            for cl_name in ("content_list_v2.json", "content_list.json"):
                cl_data = self._read_json_file(chunk_dir / cl_name)
                if isinstance(cl_data, list):
                    offset += len(cl_data)
                    break
            page_offsets.append(offset)

        for idx in range(1, len(chunk_output_dirs)):
            chunk_dir = Path(chunk_output_dirs[idx])
            offset = page_offsets[idx]
            self._merge_single_chunk_json(chunk_dir, output_dir, idx, offset, _json)

        # 清理带 _chunkN 后缀的残留文件
        residue_paths = list(output_dir.rglob("*_chunk*"))
        auto_dir = output_dir / "auto"
        if auto_dir.exists():
            residue_paths.extend(auto_dir.rglob("*_chunk*"))
        for artifact_path in residue_paths:
            try:
                artifact_path.unlink()
                logger.info("Cleaned residue: %s", artifact_path)
            except OSError:
                pass

    def _merge_single_chunk_json(self, chunk_dir: Path, output_dir: Path, chunk_idx: int, page_offset: int, _json: Any) -> None:
        """合并单个 chunk 的 JSON 产物到基准文件中。"""
        suffix_tag = f"_chunk{chunk_idx + 1}"

        # content_list_v2.json / content_list.json：list[list[dict]]，页面级数组直接拼接
        for cl_name in ("content_list_v2.json", "content_list.json"):
            # 分块文件路径（由 _merge_dir_contents 重命名而来）
            stem = cl_name.rsplit(".", 1)[0]
            ext = cl_name.rsplit(".", 1)[1]
            src_path = output_dir / f"{stem}{suffix_tag}.{ext}"
            if not src_path.exists():
                continue
            src_data = self._read_json_file(src_path)
            if not isinstance(src_data, list):
                continue
            base_path = output_dir / cl_name
            if not base_path.exists():
                continue
            base_data = self._read_json_file(base_path)
            if not isinstance(base_data, list):
                continue
            merged = base_data + src_data
            base_path.write_text(_json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Merged %s: %d+%d=%d pages", cl_name, len(base_data), len(src_data), len(merged))

        # model.json / middle.json：list/dict，对 page_idx 做偏移后合并
        for dj_name in ("model.json", "middle.json"):
            stem = dj_name.rsplit(".", 1)[0]
            ext = dj_name.rsplit(".", 1)[1]
            src_path = output_dir / f"{stem}{suffix_tag}.{ext}"
            if not src_path.exists():
                continue
            src_data = self._read_json_file(src_path)
            if not isinstance(src_data, (dict, list)):
                continue
            base_path = output_dir / dj_name
            if not base_path.exists():
                continue
            base_data = self._read_json_file(base_path)
            if isinstance(src_data, list) and isinstance(base_data, list):
                for item in src_data:
                    if isinstance(item, dict) and "page_idx" in item and isinstance(item["page_idx"], (int, float)):
                        item["page_idx"] = int(item["page_idx"]) + page_offset
                merged = base_data + src_data
                base_path.write_text(_json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info("Merged %s: %d+%d=%d items (page_offset=%d)", dj_name, len(base_data), len(src_data), len(merged), page_offset)
            elif isinstance(src_data, dict) and isinstance(base_data, dict):
                # hybrid 后端产出的 middle.json 为 dict，页面尺寸在 pdf_info 数组里；
                # 与 list 分支一致，对 pdf_info 逐条做 page_idx 偏移后拼接，否则
                # 第 2+ 块 chunk 的页面尺寸会丢失（page_width/page_height 归 0，bbox 全空）。
                src_pages = src_data.get("pdf_info")
                base_pages = base_data.get("pdf_info")
                if not isinstance(src_pages, list) or not isinstance(base_pages, list) or not src_pages:
                    logger.warning(
                        "Skip merging %s chunk %d: pdf_info 缺失或类型不符",
                        dj_name, chunk_idx + 1,
                    )
                    continue
                for item in src_pages:
                    if isinstance(item, dict) and "page_idx" in item and isinstance(item["page_idx"], (int, float)):
                        item["page_idx"] = int(item["page_idx"]) + page_offset
                merged = dict(base_data)
                merged["pdf_info"] = base_pages + src_pages
                base_path.write_text(_json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info(
                    "Merged %s.pdf_info: %d+%d=%d items (page_offset=%d)",
                    dj_name, len(base_pages), len(src_pages), len(merged["pdf_info"]), page_offset,
                )

    def _merge_dir_contents(self, src_dir: Path, dest_dir: Path, chunk_idx: int) -> None:
        """将源目录内容合并到目标目录，处理文件名冲突。"""
        for item in src_dir.rglob("*"):
            if item.is_dir():
                continue
            rel = item.relative_to(src_dir)
            dest = dest_dir / rel
            if dest.exists():
                base_name = dest.stem
                suffix = dest.suffix
                dest = dest.with_name(f"{base_name}_chunk{chunk_idx+1}{suffix}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(item), str(dest))

    def _parse_document(self, input_path: str, output_dir: str) -> Optional[Dict[str, Any]]:
        """文档解析流程：超页数/超大文件自动拆分合并，单文件走公司自部署 API。"""
        page_count = self._get_pdf_page_count(input_path)
        max_pages = 200
        max_sync_bytes = max(1, int(os.getenv('MINERU_SYNC_MAX_BYTES', str(30 << 20))))
        try:
            file_size = os.path.getsize(input_path)
        except OSError:
            file_size = 0

        if page_count > max_pages:
            logger.info("PDF has %d pages (limit %d), auto-splitting...", page_count, max_pages)
            result = self._parse_large_pdf_in_chunks(input_path, output_dir, page_count, max_pages)
        elif file_size > max_sync_bytes:
            # 大体积文件按页分块，避免公司网关同步请求超时（504）
            chunk_pages = max(1, int(os.getenv('MINERU_CHUNK_PAGES', '60')))
            logger.info(
                "PDF size %.1fMB > %dMB, splitting into %d-page chunks...",
                file_size / (1 << 20), max_sync_bytes >> 20, chunk_pages,
            )
            result = self._parse_large_pdf_in_chunks(input_path, output_dir, page_count, chunk_pages)
        else:
            result = self._parse_single_file(input_path, output_dir)
        result["page_count"] = page_count
        return result

    def _parse_large_pdf_in_chunks(
        self, input_path: str, output_dir: str, page_count: int, chunk_size: int
    ) -> Dict[str, Any]:
        """拆分大 PDF 为多段，逐段解析后合并结果。"""
        chunk_paths = self._split_pdf(input_path, chunk_size)
        total_chunks = len(chunk_paths)
        chunk_results: List[Dict[str, Any]] = []
        chunk_output_dirs: List[str] = []

        for idx, chunk_path in enumerate(chunk_paths):
            chunk_output_dir = tempfile.mkdtemp(prefix=f"parse-chunk-{idx}-")
            chunk_output_dirs.append(chunk_output_dir)
            logger.info("Parsing chunk %d/%d: %s", idx + 1, total_chunks, chunk_path)
            try:
                result = self._parse_single_file(chunk_path, chunk_output_dir)
                chunk_results.append(result)
                if not result.get("success"):
                    logger.error("Chunk %d/%d failed: %s", idx + 1, total_chunks, result.get('error'))
                    for remaining in chunk_paths[idx+1:]:
                        try:
                            os.unlink(remaining)
                        except OSError:
                            pass
                    break
            finally:
                try:
                    os.unlink(chunk_path)
                except OSError:
                    pass

        if all(r.get("success") for r in chunk_results):
            merged = self._merge_chunk_results(output_dir, chunk_output_dirs, chunk_results)
            logger.info("All %d chunks merged successfully", total_chunks)
            for d in chunk_output_dirs:
                shutil.rmtree(d, ignore_errors=True)
            return merged

        for d in chunk_output_dirs:
            shutil.rmtree(d, ignore_errors=True)
        failed = next((r for r in chunk_results if not r.get("success")), None)
        return failed or self._build_parse_result(False, error="Chunk parse failed")

    def _parse_single_file(self, input_path: str, output_dir: str, _retry_count: int = 0, _force_ocr: Optional[bool] = None) -> Dict[str, Any]:
        """公司自部署 API 的单文件同步解析。

        POST 文件到 /file_parse 端点，返回 ZIP 包含所有产物。
        _force_ocr: None=使用全局 OCR 配置, True/False=强制开关
        """
        import time as _time

        api_endpoint = self.api_url.strip().rstrip('/')
        headers = {'Authorization': f'Bearer {self.api_key}'}
        file_name = Path(input_path).name
        use_ocr = _force_ocr if _force_ocr is not None else self.ocr_enabled

        logger.info("Company API: POST %s file=%s ocr=%s", api_endpoint, file_name, use_ocr)
        try:
            with open(input_path, 'rb') as f:
                resp = self._request_with_proxy_fallback(
                    'POST', api_endpoint,
                    headers=headers,
                    files={'files': (file_name, f, 'application/pdf')},
                    data={
                        'return_md': 'true',
                        'return_content_list': 'true',
                        'return_middle_json': 'true',
                        'return_model_output': 'true',
                        'response_format_zip': 'true',
                        'backend': self.backend,
                        'formula_enable': 'true',
                        'table_enable': 'true',
                        'return_images': 'true',
                        **({'is_ocr': 'true'} if use_ocr else {}),
                        'is_async': 'false',
                    },
                    timeout=self.company_api_timeout,
                    verify=False,
                )

            # 请求返回后立即检查取消（请求期间 requests 阻塞无法中断，返回后立即中止处理）
            if self._abort_event.is_set():
                raise RuntimeError("MinerU 请求已取消")

            # 200 → ZIP 直接返回
            if resp.status_code == 200:
                return self._extract_zip_bytes(resp.content, output_dir)

            # 202 → async 模式，需要轮询
            if resp.status_code == 202:
                try:
                    task_info = resp.json()
                    task_id = task_info.get("task_id", "")
                except Exception:
                    task_info = {}
                    task_id = ""
                if task_id:
                    logger.info("Async task %s, polling...", task_id)
                    return self._poll_async_task(task_id, api_endpoint, headers, output_dir)
                return self._build_parse_result(False, error='Company API returned 202 without task_id')

            # 409 → 冲突（并发限制或任务失败）
            if resp.status_code == 409:
                try:
                    body = resp.json()
                except Exception:
                    return self._build_parse_result(
                        False,
                        error=f'Company API returned 409 (conflict): {resp.text[:300]}'
                    )
                task_id = body.get("task_id", "")
                status = body.get("status", "")
                if status == "failed":
                    error_detail = body.get("error", "")
                    # 未开 OCR 的扫描件会自动开 OCR 重试一次
                    if not use_ocr:
                        logger.info("Task %s failed, retrying with OCR enabled...", task_id)
                        _time.sleep(3)
                        result = self._parse_single_file(input_path, output_dir, _retry_count + 1, _force_ocr=True)
                        result["ocr_retried"] = True
                        return result
                    if _retry_count < 2:
                        logger.info("Task %s failed, retry %d/2...", task_id, _retry_count + 1)
                        _time.sleep(3)
                        return self._parse_single_file(input_path, output_dir, _retry_count + 1, _force_ocr=use_ocr)
                    return self._build_parse_result(
                        False,
                        error=f'MinerU pipeline failed for "{file_name}": '
                              f'task_id={task_id}. MinerU error: {error_detail}'
                    )
                if status in ("pending", "processing") and task_id:
                    logger.info("Task %s in progress, polling...", task_id)
                    return self._poll_async_task(task_id, api_endpoint, headers, output_dir)
                return self._build_parse_result(
                    False,
                    error=f'Company API returned 409 (conflict): {resp.text[:300]}'
                )

            # 502/503/504 → 网关瞬时抖动/同步超时：退避重试（大文件另有分块兜底）
            if resp.status_code in (502, 503, 504) and _retry_count < 2:
                logger.warning(
                    "Company API returned %d (transient), retry %d/2 in %.1fs...",
                    resp.status_code, _retry_count + 1, 3.0 * (_retry_count + 1),
                )
                _time.sleep(3.0 * (_retry_count + 1))
                return self._parse_single_file(input_path, output_dir, _retry_count + 1, _force_ocr=use_ocr)

            return self._build_parse_result(
                False,
                error=f'Company API returned {resp.status_code}: {resp.text[:200]}'
            )

        except Exception as error:
            if self._abort_event.is_set():
                raise RuntimeError("MinerU 请求已取消") from error
            logger.exception("Company API exception: %s", error)
            return self._build_parse_result(False, error=f'Company API exception: {error}')

    def _poll_async_task(self, task_id: str, api_endpoint: str, headers: dict, output_dir: str) -> Dict[str, Any]:
        """轮询异步任务直到完成，返回解析结果。"""
        import time as _time
        poll_url = f"{api_endpoint}/status/{task_id}"
        max_attempts = max(1, self.cloud_poll_max_attempts)
        for attempt in range(max_attempts):
            if self._abort_event.is_set():
                raise RuntimeError("MinerU 请求已取消")
            if attempt > 0:
                _time.sleep(3 if attempt < 10 else 5)
            try:
                resp = self._request_with_proxy_fallback(
                    'GET', poll_url, headers=headers, timeout=30, verify=False,
                )
            except Exception as e:
                logger.warning("Poll attempt %d failed: %s", attempt + 1, e)
                if self._abort_event.is_set():
                    raise RuntimeError("MinerU 请求已取消") from e
                continue
            if resp.status_code != 200:
                continue
            try:
                info = resp.json()
            except Exception:
                continue
            status = str(info.get("status", "")).lower()
            if status == "done":
                download_url = info.get("download_url") or info.get("result_url") or ""
                if download_url:
                    data = self._download_bytes(download_url, 60, headers=headers)
                    if data is not None:
                        return self._extract_zip_bytes(data, output_dir)
                return self._build_parse_result(False, error=f'Async task {task_id} done but download failed')
            if status == "failed":
                return self._build_parse_result(False, error=f'Async task {task_id} failed')
            if status in ("pending", "processing"):
                continue
        return self._build_parse_result(False, error=f'Async task {task_id} timed out after {max_attempts} polls')

    def _extract_zip_bytes(self, zip_bytes: bytes, output_dir: str) -> Dict[str, Any]:
        """从原始 ZIP 字节中提取产物并写入 output_dir。"""
        if len(zip_bytes) > self.max_download_bytes:
            return self._build_parse_result(
                False,
                error=f'ZIP 产物超过大小限制 {self.max_download_bytes} bytes',
            )

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # 保存 origin.zip
        try:
            zip_path = Path(output_dir) / 'origin.zip'
            with open(zip_path, 'wb') as f:
                f.write(zip_bytes)
        except Exception as e:
            logger.warning("Failed to save origin.zip: %s", e)

        # 解压 ZIP 到 output_dir
        self._extract_zip_archive(zip_bytes, Path(output_dir))

        # 合并所有 images 子目录到 output_dir/images（content.md 引用 images/xxx.jpg 相对路径）
        images_root = Path(output_dir) / 'images'
        images_root.mkdir(parents=True, exist_ok=True)
        for img_dir in list(Path(output_dir).rglob('images')):
            if img_dir.resolve() == images_root.resolve():
                continue
            try:
                for img_file in img_dir.iterdir():
                    if img_file.is_file():
                        dest = images_root / img_file.name
                        if not dest.exists():
                            shutil.copy2(str(img_file), str(dest))
            except Exception as e:
                logger.warning("合并图片目录失败 %s: %s", img_dir, e)

        # 寻找 markdown
        md_content = None
        for md_file in Path(output_dir).rglob('*.md'):
            try:
                text = md_file.read_text(encoding='utf-8').strip()
                if text:
                    md_content = text
                    dest = Path(output_dir) / 'content.md'
                    if md_file.resolve() != dest.resolve():
                        shutil.copy2(str(md_file), str(dest))
                    break
            except Exception:
                continue

        # 整理 JSON 产物到 output_dir 根目录
        json_patterns = {
            'content_list.json': ['*content_list.json', '*content_list_v2.json'],
            'content_list_v2.json': ['*content_list_v2.json'],
            'model.json': ['*model.json'],
            'middle.json': ['*middle.json'],
        }
        for target_name, patterns in json_patterns.items():
            for pattern in patterns:
                matches = list(Path(output_dir).rglob(pattern))
                if matches:
                    dest = Path(output_dir) / target_name
                    try:
                        shutil.copy2(str(matches[0]), str(dest))
                    except Exception:
                        pass
                    break

        # 铺平：删除所有中间子目录（auto/、hybrid_auto/、vlm/ 等），只保留 images/ 与根文件
        for sub in list(Path(output_dir).iterdir()):
            if sub.is_dir() and sub.name != 'images':
                try:
                    shutil.rmtree(sub)
                except Exception as e:
                    logger.warning("清理中间目录失败 %s: %s", sub, e)

        if not md_content:
            return self._build_parse_result(False, error='Company API: no markdown found in ZIP response')

        return self._write_markdown_file(output_dir, md_content)

    def parse_document(self, input_path: str, output_dir: str, **kwargs) -> Dict[str, Any]:
        """解析文档入口"""
        return self._parse_document(input_path, output_dir) or self._build_parse_result(False, error="Unknown error")

    def parse_to_raw_artifacts(
        self,
        input_path: str,
        output_dir: Optional[str] = None,
        *,
        library_id: Optional[str] = None,
        doc_id: Optional[str] = None,
        on_step: Optional[Callable[[str, str, str], None]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """MinerU 原始产物解析；提供 library_id/doc_id 时解析完成后自动落盘到文档目录。

        返回 dict 含 'persisted'：{parsed_dir, output_summary, has_images}（落盘后产物清单）。
        output_dir 缺省时内部自建临时目录并在结束后清理。
        """
        own_temp = output_dir is None
        if own_temp:
            output_dir = tempfile.mkdtemp(prefix="mineru-parse-")
        try:
            result = self.parse_document(input_path=input_path, output_dir=output_dir, **kwargs)
            if result.get("success") and library_id and doc_id:
                _emit_on_step(on_step, "MinerU 引擎解析", "done", "")
                result["persisted"] = self._persist_to_doc(
                    library_id, doc_id, output_dir, on_step=on_step
                )
                result["persisted"]["page_count"] = int(result.get("page_count") or 0)
                result["persisted"]["ocr_retried"] = bool(result.get("ocr_retried"))
            else:
                result.setdefault("persisted", {})
            return result
        finally:
            if own_temp:
                shutil.rmtree(output_dir, ignore_errors=True)

    def _persist_to_doc(
        self,
        library_id: str,
        doc_id: str,
        output_dir: str,
        on_step: Optional[Callable[[str, str, str], None]] = None,
    ) -> Dict[str, Any]:
        """解析产物落盘到文档目录：content.md + mineru_raw/images 等归位，返回产物清单。"""

        markdown_path = os.path.join(output_dir, "content.md")
        if os.path.isfile(markdown_path):
            with open(markdown_path, "r", encoding="utf-8") as handle:
                save_markdown(library_id, doc_id, handle.read())
        _emit_on_step(
            on_step,
            "content.md 落盘",
            "done" if os.path.isfile(markdown_path) else "failed",
            str(paths.get_parsed_markdown_path(library_id, doc_id)),
        )
        save_parse_artifacts(library_id, doc_id, output_dir, on_step=on_step)

        parsed_dir = paths.get_parsed_dir(library_id, doc_id)
        output_parts = []
        try:
            for item in sorted(parsed_dir.iterdir(), key=lambda p: p.name):
                if item.name in ("popo",) or item.name.startswith("doc_blocks_graph"):
                    continue
                output_parts.append(str(item))
                if item.is_dir() and item.name == "mineru_raw":
                    for sub in sorted(item.iterdir(), key=lambda p: p.name):
                        output_parts.append(str(sub))
        except OSError:
            pass
        images_dir = parsed_dir / "images"
        has_images = images_dir.exists() and any(images_dir.iterdir())
        _emit_on_step(
            on_step,
            "图片资源提取",
            "done" if has_images else "skipped",
            "has_images" if has_images else "无图片资源",
        )
        return {
            "parsed_dir": str(parsed_dir),
            "output_summary": " + ".join(output_parts) if output_parts else str(parsed_dir),
            "has_images": has_images,
        }


mineru_parser = MinerUParser()

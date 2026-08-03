"""MinerU 文档解析服务 (Simplified)"""
import json
import os
import tempfile
import threading
from typing import Optional, Dict, Any, List
from pathlib import Path
from dotenv import load_dotenv
import requests
import time
import re
import io
import zipfile
import shutil
from datetime import datetime

load_dotenv()


class MinerUParser:
    """MinerU 文档解析器 (仅支持 Cloud Batch 模式)"""

    def __init__(self):
        self.api_url = (
            os.getenv('MINERU_API_URL', '')
            or os.getenv('MINERU_BASE_URL', '')
            or os.getenv('MINERU_ENDPOINT', '')
            or 'https://mineru.net/api/v4'
        ).strip().rstrip('/')
        self.api_key = (
            os.getenv('MINERU_API_KEY', '')
            or os.getenv('MINERU_API_TOKEN', '')
            or os.getenv('MINERU_TOKEN', '')
        )
        self.cloud_poll_max_attempts = max(1, int(os.getenv('MINERU_CLOUD_POLL_MAX_ATTEMPTS', '90')))
        self.cloud_poll_interval_seconds = max(1, int(os.getenv('MINERU_CLOUD_POLL_INTERVAL_SECONDS', '4')))
        self.proxy_fallback_enabled = os.getenv('MINERU_PROXY_FALLBACK_ENABLED', '1') != '0'
        self.ocr_enabled = os.getenv('MINERU_OCR_ENABLED', 'false').lower() == 'true'
        self.backend = os.getenv('MINERU_BACKEND', 'hybrid-engine').strip().lower()
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

    def _normalize_api_url(self, api_url: str) -> str:
        """规范化 MinerU API 地址"""
        normalized = (api_url or '').strip().rstrip('/')
        if not normalized:
            return 'https://mineru.net/api/v4'
        if '/api/v4' in normalized:
            return f"{normalized.split('/api/v4')[0]}/api/v4"
        if normalized.endswith('/api'):
            return f"{normalized}/v4"
        return f"{normalized}/api/v4"

    def _is_valid_markdown_text(self, text: Optional[str]) -> bool:
        if not text:
            return False
        return len(text.strip()) >= 10  # 简化校验逻辑

    def _extract_nested_value(self, data: Dict[str, Any], keys: List[str]) -> str:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ''

    def _build_cloud_headers(self) -> Dict[str, str]:
        headers = {'Content-Type': 'application/json', 'Accept': '*/*'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        return headers

    def _write_json_output(self, file_path: Path, payload: Any) -> None:
        with open(file_path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

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

    def _extract_blocks_from_zip(self, zip_bytes: bytes) -> List[Dict[str, Any]]:
        """从云端 ZIP 包中的 JSON/JSONL 文件提取块级结构。"""
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
                # 简化：只提取 content_list 或 layout，这里为了兼容性暂保留 structure_builder 调用
                # 实际上如果用户只需要 content.md，这个步骤可能不是必须的，但为了 SmartTree 可能需要
                return [] # 暂时返回空，如果需要再恢复复杂逻辑，或者保持 minimal
        except Exception:
            return []

    def _extract_mineru_blocks_from_output_dir(self, output_dir: str) -> List[Dict[str, Any]]:
        return [] # 简化

    def _write_markdown_file(
        self,
        output_dir: str,
        markdown: str,
        raw_artifacts: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """将 Markdown 写入 content.md 并返回成功结果。"""
        # 修正文件名：parsed.md -> content.md
        md_file_path = os.path.join(output_dir, 'content.md')
        
        # 简单处理图片路径：假设图片都在 images/ 目录下
        # 这里可以根据需要做更复杂的路径修正，但如果解压后结构正确，通常不需要
        
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

    def _fetch_markdown_from_cloud_urls(self, markdown_url: str, zip_url: str) -> Dict[str, Any]:
        markdown: Optional[str] = None
        source = ''
        zip_bytes: Optional[bytes] = None
        
        if markdown_url:
            print(f"[MinerU] Downloading Markdown: {markdown_url}")
            md_resp = self._request_with_proxy_fallback('GET', markdown_url, timeout=120, verify=False)
            if md_resp.status_code == 200 and self._is_valid_markdown_text(md_resp.text):
                markdown = md_resp.text
                source = 'markdown_url'
        
        if not markdown and zip_url:
            print(f"[MinerU] Downloading ZIP (fallback): {zip_url}")
            zip_resp = self._request_with_proxy_fallback('GET', zip_url, timeout=120, verify=False)
            if zip_resp.status_code == 200:
                markdown = self._download_markdown_from_zip(zip_resp.content)
                if markdown:
                    source = 'zip_url'
                zip_bytes = zip_resp.content
        elif markdown and zip_url:
            print(f"[MinerU] Downloading ZIP (archive): {zip_url}")
            zip_resp = self._request_with_proxy_fallback('GET', zip_url, timeout=120, verify=False)
            if zip_resp.status_code == 200:
                zip_bytes = zip_resp.content
                
        return {'markdown': markdown, 'source': source, 'zip_bytes': zip_bytes}

    def _download_markdown_from_zip(self, zip_bytes: bytes) -> Optional[str]:
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
                file_list = archive.namelist()
                markdown_candidates = [name for name in file_list if name.lower().endswith('.md')]
                for name in markdown_candidates:
                    with archive.open(name) as file_obj:
                        content = file_obj.read().decode('utf-8', errors='ignore').strip()
                        if content:
                            return content
        except Exception as e:
            print(f"[MinerU] Error extracting markdown from ZIP: {e}")
        return None

    def _extract_zip_archive(self, zip_bytes: bytes, target_dir: Path) -> None:
        """将云端 ZIP 解压到目标目录，智能扁平化结构"""
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
                namelist = archive.namelist()
                print(f"[MinerU] Extracting ZIP. Content ({len(namelist)} files): {namelist[:10]}...")
                
                # 分析目录结构，看是否所有文件都在同一个顶级目录下
                top_dirs = set()
                for name in namelist:
                    parts = Path(name).parts
                    if len(parts) > 1:
                        top_dirs.add(parts[0])
                    elif not name.endswith('/'): # 根目录下的文件
                        top_dirs.add('') # 标记有文件在根目录
                
                # 如果只有一个顶级目录且根目录下没有文件，说明是嵌套结构
                has_single_top_dir = len(top_dirs) == 1 and '' not in top_dirs
                print(f"[MinerU] Zip structure: top_dirs={top_dirs}, flatten={has_single_top_dir}")
                
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    
                    member = Path(info.filename)
                    if has_single_top_dir:
                        # 去掉第一层目录
                        parts = member.parts
                        if len(parts) > 1:
                            destination = target_dir.joinpath(*parts[1:])
                        else:
                            destination = target_dir / member.name
                    else:
                        destination = target_dir / member

                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, open(destination, 'wb') as target:
                        shutil.copyfileobj(source, target)
                        
        except Exception as e:
            print(f"[MinerU] Zip extract failed: {e}")
            import traceback
            traceback.print_exc()

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
            print("[MinerU] PyMuPDF not installed, cannot check page count")
        except Exception as exc:
            print(f"[MinerU] Page count check failed: {exc}")
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
            chunk_path = tempfile.mktemp(suffix=f"_pages_{start+1}-{end}.pdf")
            chunk_doc.save(chunk_path)
            chunk_doc.close()
            chunk_paths.append(chunk_path)
            print(f"[MinerU] Split chunk: pages {start+1}-{end} -> {chunk_path}")

        doc.close()
        return chunk_paths

    def _merge_chunk_results(self, output_dir: str, chunk_output_dirs: List[str], chunk_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """合并多个分段的解析结果为一份完整文档。"""
        import json as _json

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
                print(f"[MinerU] Cleaned residue: {artifact_path}")
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
            print(f"[MinerU] Merged {cl_name}: {len(base_data)}+{len(src_data)}={len(merged)} pages")

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
                print(f"[MinerU] Merged {dj_name}: {len(base_data)}+{len(src_data)}={len(merged)} items (page_offset={page_offset})")

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

    def _parse_document_cloud_batch(self, input_path: str, output_dir: str) -> Optional[Dict[str, Any]]:
        """云端批量解析流程，超页数自动拆分合并。"""
        page_count = self._get_pdf_page_count(input_path)
        max_pages = 200

        if page_count > max_pages:
            print(f"[MinerU] PDF has {page_count} pages (limit {max_pages}), auto-splitting...")
            return self._parse_large_pdf_in_chunks(input_path, output_dir, page_count, max_pages)

        return self._parse_single_file_cloud(input_path, output_dir)

    def _parse_large_pdf_in_chunks(
        self, input_path: str, output_dir: str, page_count: int, chunk_size: int
    ) -> Dict[str, Any]:
        """拆分大 PDF 为多段，逐段云端解析后合并结果。"""
        chunk_paths = self._split_pdf(input_path, chunk_size)
        total_chunks = len(chunk_paths)
        chunk_results: List[Dict[str, Any]] = []
        chunk_output_dirs: List[str] = []

        for idx, chunk_path in enumerate(chunk_paths):
            chunk_output_dir = tempfile.mkdtemp(prefix=f"parse-chunk-{idx}-")
            chunk_output_dirs.append(chunk_output_dir)
            print(f"[MinerU] Parsing chunk {idx+1}/{total_chunks}: {chunk_path}")
            try:
                result = self._parse_single_file_cloud(chunk_path, chunk_output_dir)
                chunk_results.append(result)
                if not result.get("success"):
                    print(f"[MinerU] Chunk {idx+1}/{total_chunks} failed: {result.get('error')}")
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
            print(f"[MinerU] All {total_chunks} chunks merged successfully")
            for d in chunk_output_dirs:
                shutil.rmtree(d, ignore_errors=True)
            return merged

        failed = next((r for r in chunk_results if not r.get("success")), None)
        return failed or self._build_parse_result(False, error="Chunk parse failed")

    def _is_company_api(self) -> bool:
        """检测是否使用公司自部署的 MinerU API（区别于公共 API）。"""
        url = self.api_url.lower()
        return ':50170' in url or '/file_parse' in url

    def _parse_single_file_company_api(self, input_path: str, output_dir: str, _retry_count: int = 0, _force_ocr: Optional[bool] = None) -> Dict[str, Any]:
        """公司自部署 API 的单文件同步解析。
        
        POST 文件到 /file_parse 端点，返回 ZIP 包含所有产物。
        _force_ocr: None=使用全局 OCR 配置, True/False=强制开关
        """
        import io as _io
        import zipfile as _zipfile
        import time as _time
        
        api_endpoint = self.api_url.strip().rstrip('/')
        headers = {'Authorization': f'Bearer {self.api_key}'}
        file_name = Path(input_path).name
        use_ocr = _force_ocr if _force_ocr is not None else self.ocr_enabled
        
        print(f"[MinerU] Company API: POST {api_endpoint} file={file_name} ocr={use_ocr}")
        try:
            with open(input_path, 'rb') as f:
                file_bytes = f.read()
            
            resp = self._request_with_proxy_fallback(
                'POST', api_endpoint,
                headers=headers,
                files={'files': (file_name, file_bytes, 'application/pdf')},
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
                timeout=600,
                verify=False,
            )

            # 请求返回后立即检查取消（请求期间 requests 阻塞无法中断，返回后立即中止处理）
            if self._abort_event.is_set():
                raise RuntimeError("MinerU 请求已取消")

            # 200 → ZIP 直接返回
            if resp.status_code == 200:
                return self._extract_zip_response(resp, output_dir)

            # 202 → async 模式，需要轮询
            if resp.status_code == 202:
                try:
                    task_info = resp.json()
                    task_id = task_info.get("task_id", "")
                except Exception:
                    task_info = {}
                    task_id = ""
                if task_id:
                    print(f"[MinerU] Async task {task_id}, polling...")
                    return self._poll_async_task(task_id, api_endpoint, headers, output_dir)
                return self._build_parse_result(False, error=f'Company API returned 202 without task_id')

            # 409 → 冲突（并发限制或任务失败）
            if resp.status_code == 409:
                try:
                    body = resp.json()
                    task_id = body.get("task_id", "")
                    status = body.get("status", "")
                    if status == "failed":
                        error_detail = body.get("error", "")
                        # 未开 OCR 的扫描件会自动开 OCR 重试一次
                        if not use_ocr:
                            print(f"[MinerU] Task {task_id} failed, retrying with OCR enabled...")
                            _time.sleep(3)
                            return self._parse_single_file_company_api(input_path, output_dir, _retry_count + 1, _force_ocr=True)
                        if _retry_count < 2:
                            print(f"[MinerU] Task {task_id} failed, retry {_retry_count + 1}/2...")
                            _time.sleep(3)
                            return self._parse_single_file_company_api(input_path, output_dir, _retry_count + 1, _force_ocr=use_ocr)
                        return self._build_parse_result(
                            False,
                            error=f'MinerU pipeline failed for "{file_name}": '
                                  f'task_id={task_id}. MinerU error: {error_detail}'
                        )
                    if status in ("pending", "processing"):
                        print(f"[MinerU] Retrying after conflict (task {task_id} in progress)...")
                        _time.sleep(5)
                        return self._parse_single_file_company_api(input_path, output_dir)
                except Exception:
                    pass
                return self._build_parse_result(
                    False,
                    error=f'Company API returned 409 (conflict): {resp.text[:300]}'
                )

            return self._build_parse_result(
                False,
                error=f'Company API returned {resp.status_code}: {resp.text[:200]}'
            )
            
        except Exception as error:
            import traceback
            traceback.print_exc()
            return self._build_parse_result(False, error=f'Company API exception: {error}')

    def _poll_async_task(self, task_id: str, api_endpoint: str, headers: dict, output_dir: str) -> Dict[str, Any]:
        """轮询异步任务直到完成，返回解析结果。"""
        import time as _time
        poll_url = f"{api_endpoint}/status/{task_id}"
        max_attempts = 120
        for attempt in range(max_attempts):
            if self._abort_event.is_set():
                raise RuntimeError("MinerU 请求已取消")
            _time.sleep(3 if attempt < 10 else 5)
            try:
                resp = self._request_with_proxy_fallback(
                    'GET', poll_url, headers=headers, timeout=30, verify=False,
                )
            except Exception as e:
                print(f"[MinerU] Poll attempt {attempt + 1} failed: {e}")
                if self._abort_event.is_set():
                    raise RuntimeError("MinerU 请求已取消")
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
                    dl_resp = self._request_with_proxy_fallback(
                        'GET', download_url, headers=headers, timeout=60, verify=False,
                    )
                    if dl_resp.status_code == 200:
                        return self._extract_zip_response(dl_resp, output_dir)
                return self._build_parse_result(False, error=f'Async task {task_id} done but no download URL')
            if status == "failed":
                return self._build_parse_result(False, error=f'Async task {task_id} failed')
            if status in ("pending", "processing"):
                continue
        return self._build_parse_result(False, error=f'Async task {task_id} timed out after {max_attempts} polls')

    def _extract_zip_response(self, resp: 'requests.Response', output_dir: str) -> Dict[str, Any]:
        """从原始 ZIP 响应中提取产物并写入 output_dir。"""
        import shutil as _shutil
        zip_bytes = resp.content

        # 保存 origin.zip
        try:
            zip_path = Path(output_dir) / 'origin.zip'
            with open(zip_path, 'wb') as f:
                f.write(zip_bytes)
        except Exception as e:
            print(f"[MinerU] Failed to save origin.zip: {e}")

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
                            _shutil.copy2(str(img_file), str(dest))
            except Exception as e:
                print(f"[MinerU] 合并图片目录失败 {img_dir}: {e}")

        # 寻找 markdown
        md_content = None
        for md_file in Path(output_dir).rglob('*.md'):
            try:
                text = md_file.read_text(encoding='utf-8').strip()
                if text:
                    md_content = text
                    dest = Path(output_dir) / 'content.md'
                    if md_file.resolve() != dest.resolve():
                        _shutil.copy2(str(md_file), str(dest))
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
                        _shutil.copy2(str(matches[0]), str(dest))
                    except Exception:
                        pass
                    break

        # 铺平：删除所有中间子目录（auto/、hybrid_auto/、vlm/ 等），只保留 images/ 与根文件
        for sub in list(Path(output_dir).iterdir()):
            if sub.is_dir() and sub.name != 'images':
                try:
                    _shutil.rmtree(sub)
                except Exception as e:
                    print(f"[MinerU] 清理中间目录失败 {sub}: {e}")

        if not md_content:
            return self._build_parse_result(False, error='Company API: no markdown found in ZIP response')

        return self._write_markdown_file(output_dir, md_content)

    def _parse_single_file_cloud(self, input_path: str, output_dir: str) -> Dict[str, Any]:
        """单文件云端解析流程（不含页数预检）。"""
        # 检测是否使用公司自部署 API
        if self._is_company_api():
            return self._parse_single_file_company_api(input_path, output_dir)

        base_url = self._normalize_api_url(self.api_url)
        headers = self._build_cloud_headers()
        
        try:
            # 1. 获取上传链接 (Create Batch)
            # 接口文档: POST /file-urls/batch
            create_resp = self._request_with_proxy_fallback(
                'POST', f'{base_url}/file-urls/batch',
                headers=headers, 
                json={
                    'files': [{'name': Path(input_path).name}],
                    'model_version': 'vlm',
                    'is_ocr': True
                },
                timeout=30, verify=False
            )
            try:
                create_json = create_resp.json()
            except (json.JSONDecodeError, requests.exceptions.JSONDecodeError) as e:
                print(f"[MinerU] Create batch JSON error: {e}. Content: {create_resp.text[:200]}")
                return self._build_parse_result(False, error=f'Create response invalid JSON: {create_resp.text[:100]}')
            
            if create_resp.status_code != 200 or create_json.get('code') != 0:
                return self._build_parse_result(False, error=f'Create failed: {create_resp.text}')

            batch_data = create_json.get('data', {})
            batch_id = batch_data.get('batch_id')
            upload_url = batch_data.get('file_urls', [])[0]
            
            # 2. 上传文件
            print(f"[MinerU] Uploading to: {upload_url[:60]}...")
            with open(input_path, 'rb') as file_obj:
                upload_resp = self._request_with_proxy_fallback(
                    'PUT', upload_url, data=file_obj, timeout=300, verify=False
                )
            if upload_resp.status_code not in (200, 201):
                return self._build_parse_result(False, error=f'Upload failed: {upload_resp.status_code}')

            # 3. 轮询状态
            for _ in range(self.cloud_poll_max_attempts):
                time.sleep(self.cloud_poll_interval_seconds)
                poll_url = f'{base_url}/extract-results/batch/{batch_id}'
                query_resp = self._request_with_proxy_fallback('GET', poll_url, headers=headers, timeout=60, verify=False)
                
                try:
                    payload = query_resp.json()
                except (json.JSONDecodeError, requests.exceptions.JSONDecodeError) as e:
                    print(f"[MinerU] Poll JSON error: {e}. Content: {query_resp.text[:200]}")
                    continue # Retry polling if JSON fails temporarily
                
                if query_resp.status_code != 200:
                    continue

                result_list = payload.get('data', {}).get('extract_result') or []
                if not result_list:
                    print(f"[MinerU] Poll returned empty extract_result. Payload: {json.dumps(payload, ensure_ascii=False)[:300]}")
                    continue
                    
                first = result_list[0]
                state = self._extract_nested_value(first, ['state', 'extract_state']).lower()
                print(f"[MinerU] Poll state: {state}")
                
                if state in ('failed', 'error', 'timeout'):
                    error_msg = (
                        self._extract_nested_value(first, ['err_msg', 'error_msg', 'error_message', 'fail_reason', 'message'])
                        or self._extract_nested_value(first, ['msg', 'reason', 'detail'])
                    )
                    print(f"[MinerU] Cloud parse failed. State={state}. Full item: {json.dumps(first, ensure_ascii=False)}")
                    detail = f": {error_msg}" if error_msg else ""
                    return self._build_parse_result(False, error=f'Cloud parse failed: {state}{detail}')
                
                if state == 'done':
                    print(f"[MinerU] Full result payload: {json.dumps(first, ensure_ascii=False)}")
                    markdown_url = self._extract_nested_value(first, ['full_md_url', 'markdown_url'])
                    zip_url = self._extract_nested_value(first, ['full_zip_url', 'zip_url'])
                    
                    print(f"[MinerU] Done. MD: {markdown_url}, ZIP: {zip_url}")
                    markdown_bundle = self._fetch_markdown_from_cloud_urls(markdown_url, zip_url)
                    markdown = markdown_bundle.get('markdown')
                    
                    if not markdown:
                        print("[MinerU] Markdown not ready, retrying...")
                        continue

                    # 解压 ZIP 到 output_dir (扁平化，去除 raw/ 目录)
                    zip_bytes = markdown_bundle.get('zip_bytes')
                    if zip_bytes:
                        # Save original ZIP file
                        try:
                            zip_path = Path(output_dir) / 'origin.zip'
                            with open(zip_path, 'wb') as f:
                                f.write(zip_bytes)
                            print(f"[MinerU] Saved origin.zip to {zip_path}")
                        except Exception as e:
                            print(f"[MinerU] Failed to save origin.zip: {e}")

                        self._extract_zip_archive(zip_bytes, Path(output_dir))
                        
                        # 清理：删除解压出来的多余 markdown 文件，避免混淆，只保留 content.md
                        for md_file in Path(output_dir).glob('*.md'):
                            if md_file.name != 'content.md':
                                try:
                                    md_file.unlink()
                                except:
                                    pass
                    
                    # 写入 content.md
                    return self._write_markdown_file(output_dir, markdown)

            return self._build_parse_result(False, error='Polling timed out')

        except Exception as error:
            import traceback
            traceback.print_exc()
            return self._build_parse_result(False, error=f'Exception: {error}')

    def parse_document(self, input_path: str, output_dir: str, **kwargs) -> Dict[str, Any]:
        """解析文档入口"""
        return self._parse_document_cloud_batch(input_path, output_dir) or self._build_parse_result(False, error="Unknown error")

    def parse_to_raw_artifacts(
        self,
        input_path: str,
        output_dir: Optional[str] = None,
        *,
        library_id: Optional[str] = None,
        doc_id: Optional[str] = None,
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
                result["persisted"] = self._persist_to_doc(library_id, doc_id, output_dir)
            else:
                result.setdefault("persisted", {})
            return result
        finally:
            if own_temp:
                shutil.rmtree(output_dir, ignore_errors=True)

    def _persist_to_doc(self, library_id: str, doc_id: str, output_dir: str) -> Dict[str, Any]:
        """解析产物落盘到文档目录：content.md + mineru_raw/images 等归位，返回产物清单。"""
        import docs_core.paths as paths
        from docs_core.write.store.assets_file_store import file_storage

        markdown_path = os.path.join(output_dir, "content.md")
        if os.path.isfile(markdown_path):
            with open(markdown_path, "r", encoding="utf-8") as handle:
                file_storage.save_markdown(library_id, doc_id, handle.read())
        file_storage.save_parse_artifacts(library_id, doc_id, output_dir)

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
        return {
            "parsed_dir": str(parsed_dir),
            "output_summary": " + ".join(output_parts) if output_parts else str(parsed_dir),
            "has_images": has_images,
        }

mineru_parser = MinerUParser()

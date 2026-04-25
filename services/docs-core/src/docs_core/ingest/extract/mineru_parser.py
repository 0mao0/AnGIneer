"""MinerU 文档解析服务 (Simplified)"""
import json
import os
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
        self.cloud_poll_max_attempts = max(1, int(os.getenv('MINERU_CLOUD_POLL_MAX_ATTEMPTS', '45')))
        self.cloud_poll_interval_seconds = max(1, int(os.getenv('MINERU_CLOUD_POLL_INTERVAL_SECONDS', '4')))
        self.proxy_fallback_enabled = os.getenv('MINERU_PROXY_FALLBACK_ENABLED', '1') != '0'

    def _request_with_proxy_fallback(self, method: str, url: str, **kwargs):
        """执行请求，代理失败时自动回退直连。"""
        try:
            return requests.request(method=method, url=url, **kwargs)
        except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as error:
            if not self.proxy_fallback_enabled:
                raise
            if isinstance(error, requests.exceptions.ConnectionError) and 'proxy' not in str(error).lower():
                raise
            retry_kwargs = dict(kwargs)
            retry_kwargs['proxies'] = {'http': None, 'https': None}
            return requests.request(method=method, url=url, **retry_kwargs)

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

    def _parse_document_cloud_batch(self, input_path: str, output_dir: str) -> Optional[Dict[str, Any]]:
        """云端批量解析流程 (Simplified)"""
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
                    continue
                    
                first = result_list[0]
                state = self._extract_nested_value(first, ['state', 'extract_state']).lower()
                
                if state in ('failed', 'error', 'timeout'):
                    return self._build_parse_result(False, error=f'Cloud parse failed: {state}')
                
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
                    # MinerUParser 不再负责生成 mineru_blocks.json，只负责下载和解压原始数据
                    # 原始 JSON 文件 (model.json, layout.json, content_list.json) 将保留在 output_dir 中
                    # 由调用方 (Orchestrator) 负责后续处理
                    
                    return self._write_markdown_file(output_dir, markdown)

            return self._build_parse_result(False, error='Polling timed out')

        except Exception as error:
            import traceback
            traceback.print_exc()
            return self._build_parse_result(False, error=f'Exception: {error}')

    def parse_document(self, input_path: str, output_dir: str, **kwargs) -> Dict[str, Any]:
        """解析文档入口"""
        return self._parse_document_cloud_batch(input_path, output_dir) or self._build_parse_result(False, error="Unknown error")

mineru_parser = MinerUParser()

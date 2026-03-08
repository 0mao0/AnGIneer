"""MinerU 文档解析服务"""
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
from datetime import datetime

load_dotenv()


class MinerUParser:
    """MinerU 文档解析器"""

    def __init__(self):
        self.api_url = (
            os.getenv('MINERU_API_URL', '')
            or os.getenv('MINERU_BASE_URL', '')
            or os.getenv('MINERU_ENDPOINT', '')
            or 'https://mineru.net/api/v4'
        ).strip().rstrip('/')
        self.client_base_url = self._normalize_api_url(self.api_url)
        self.api_key = (
            os.getenv('MINERU_API_KEY', '')
            or os.getenv('MINERU_API_TOKEN', '')
            or os.getenv('MINERU_TOKEN', '')
        )
        self._client = None
        self._direct_base_url_checked = False
        self._direct_base_url: Optional[str] = None
        self.max_parse_retries = max(1, int(os.getenv('MINERU_PARSE_MAX_RETRIES', '4')))
        self.retry_delay_seconds = max(1, int(os.getenv('MINERU_PARSE_RETRY_DELAY_SECONDS', '2')))
        self.light_end_page = max(0, int(os.getenv('MINERU_LIGHT_END_PAGE', '10')))
        self.oom_retry_wait_seconds = max(1, int(os.getenv('MINERU_OOM_RETRY_WAIT_SECONDS', '8')))
        self.min_free_memory_mib = max(1, int(os.getenv('MINERU_MIN_FREE_MEMORY_MIB', '256')))
        self.cloud_poll_max_attempts = max(1, int(os.getenv('MINERU_CLOUD_POLL_MAX_ATTEMPTS', '45')))
        self.cloud_poll_interval_seconds = max(1, int(os.getenv('MINERU_CLOUD_POLL_INTERVAL_SECONDS', '4')))

    def _normalize_api_url(self, api_url: str) -> str:
        """规范化 MinerU API 地址"""
        normalized = (api_url or '').strip().rstrip('/')
        if not normalized:
            return 'https://mineru.net/api/v4'
        if normalized.endswith('/api/v4'):
            return normalized
        if normalized.endswith('/api'):
            return f'{normalized}/v4'
        return f'{normalized}/api/v4'

    def _get_direct_base_candidates(self) -> List[str]:
        """获取 file_parse 直连地址候选列表"""
        candidates: List[str] = []
        raw = (self.api_url or '').strip().rstrip('/')
        if raw:
            candidates.append(raw)
            if raw.endswith('/file_parse'):
                candidates.append(raw[:-11].rstrip('/'))
            if raw.endswith('/api/v4'):
                candidates.append(raw[:-7].rstrip('/'))
            if raw.endswith('/api'):
                candidates.append(raw[:-4].rstrip('/'))
        normalized_client_base = (self.client_base_url or '').strip().rstrip('/')
        if normalized_client_base.endswith('/api/v4'):
            candidates.append(normalized_client_base[:-7].rstrip('/'))
        unique_candidates: List[str] = []
        for item in candidates:
            if item and item not in unique_candidates:
                unique_candidates.append(item)
        return unique_candidates

    def _detect_direct_base_url(self) -> Optional[str]:
        """检测是否支持 /file_parse 直连接口"""
        if self._direct_base_url_checked:
            return self._direct_base_url
        self._direct_base_url_checked = True
        for base_url in self._get_direct_base_candidates():
            try:
                response = requests.get(
                    f'{base_url}/openapi.json',
                    timeout=8,
                    verify=False
                )
                if response.status_code != 200:
                    continue
                payload = response.json()
                paths = payload.get('paths', {})
                if '/file_parse' in paths:
                    self._direct_base_url = base_url
                    return self._direct_base_url
            except Exception:
                continue
        return None

    def _extract_markdown_from_payload(self, payload: Any) -> Optional[str]:
        """从响应体中提取 Markdown 文本"""
        def score_markdown_candidate(text: str) -> int:
            candidate = (text or '').strip()
            if not candidate:
                return -100
            lowered = candidate.lower()
            score = 0
            if '\n' in candidate:
                score += 3
            if len(candidate) >= 80:
                score += 2
            elif len(candidate) >= 24:
                score += 1
            if re.search(r'(^|\n)\s{0,3}(#{1,6}\s+|[-*+]\s+|\d+\.\s+)', candidate):
                score += 3
            if re.search(r'\|.+\|', candidate):
                score += 2
            if re.search(r'!\[[^\]]*\]\([^)]+\)', candidate):
                score += 2
            if re.search(r'`[^`]+`', candidate):
                score += 1
            if lowered in {'pipeline', 'success', 'ok', 'done', 'true', 'false'}:
                score -= 8
            if len(candidate) <= 12 and '\n' not in candidate:
                score -= 4
            return score

        def pick_best(candidates: List[str]) -> Optional[str]:
            best_text: Optional[str] = None
            best_score = -1000
            for item in candidates:
                item_text = (item or '').strip()
                if not item_text:
                    continue
                current_score = score_markdown_candidate(item_text)
                if current_score > best_score:
                    best_text = item_text
                    best_score = current_score
                elif current_score == best_score and best_text and len(item_text) > len(best_text):
                    best_text = item_text
            if best_text and best_score >= 2:
                return best_text
            return None

        if isinstance(payload, str):
            text = payload.strip()
            return text if score_markdown_candidate(text) >= 2 else None
        if isinstance(payload, list):
            candidates: List[str] = []
            for item in payload:
                markdown = self._extract_markdown_from_payload(item)
                if markdown:
                    candidates.append(markdown)
            return pick_best(candidates)
        if isinstance(payload, dict):
            candidates: List[str] = []
            for key in ('markdown', 'md', 'md_content', 'content', 'text'):
                value = payload.get(key)
                if isinstance(value, str):
                    item = value.strip()
                    if item:
                        candidates.append(item)
                    continue
                markdown = self._extract_markdown_from_payload(value)
                if markdown:
                    candidates.append(markdown)
            for value in payload.values():
                markdown = self._extract_markdown_from_payload(value)
                if markdown:
                    candidates.append(markdown)
            return pick_best(candidates)
        return None

    def _is_valid_markdown_text(self, text: Optional[str]) -> bool:
        if not text:
            return False
        markdown = self._extract_markdown_from_payload(text)
        return bool(markdown and len(markdown.strip()) >= 24)

    def _extract_nested_value(self, data: Dict[str, Any], keys: List[str]) -> str:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ''

    def _build_cloud_headers(self) -> Dict[str, str]:
        """构建云端解析请求头。"""
        headers = {
            'Content-Type': 'application/json',
            'Accept': '*/*'
        }
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        return headers

    def _ensure_raw_output_dir(self, output_dir: str) -> Path:
        """确保原始返回落盘目录存在。"""
        raw_dir = Path(output_dir) / 'raw'
        raw_dir.mkdir(parents=True, exist_ok=True)
        return raw_dir

    def _write_json_output(self, file_path: Path, payload: Any) -> None:
        """将 JSON 数据写入指定文件。"""
        with open(file_path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def _build_parse_result(
        self,
        success: bool,
        md_file: Optional[str] = None,
        error: Optional[str] = None,
        mineru_blocks: Optional[List[Dict[str, Any]]] = None,
        raw_artifacts: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """构建统一解析结果结构。"""
        return {
            'success': success,
            'md_file': md_file,
            'error': error,
            'mineru_blocks': mineru_blocks or [],
            'raw_artifacts': raw_artifacts or {}
        }

    def _build_final_result(
        self,
        result: Optional[Dict[str, Any]],
        input_path: str,
        output_dir: str,
        fallback_error: Optional[str] = None
    ) -> Dict[str, Any]:
        """补齐上层 parse_document 返回字段。"""
        parsed = result or {}
        mineru_blocks = parsed.get('mineru_blocks')
        if not isinstance(mineru_blocks, list) or not mineru_blocks:
            mineru_blocks = self._extract_mineru_blocks_from_output_dir(output_dir)
        return {
            'success': parsed.get('success', False),
            'md_file': parsed.get('md_file'),
            'error': parsed.get('error') or fallback_error,
            'input_path': input_path,
            'output_dir': output_dir,
            'mineru_blocks': mineru_blocks,
            'raw_artifacts': parsed.get('raw_artifacts') or {}
        }

    def _is_block_candidate(self, payload: Dict[str, Any]) -> bool:
        position_keys = ('bbox', 'rect', 'box', 'pdf_bbox', 'pdf_rect', 'position')
        page_keys = ('page', 'page_no', 'pageNo', 'page_index')
        line_keys = ('line', 'line_start', 'line_end', 'lineStart', 'lineEnd', 'start_line', 'end_line')
        has_position = any(key in payload for key in position_keys)
        has_page = any(key in payload for key in page_keys)
        has_line = any(key in payload for key in line_keys)
        return has_position or (has_page and has_line)

    def _normalize_block(self, payload: Dict[str, Any], index: int, source: str) -> Dict[str, Any]:
        block = dict(payload)
        position = block.get('position')
        if isinstance(position, dict):
            if 'bbox' not in block and isinstance(position.get('bbox'), list):
                block['bbox'] = position.get('bbox')
            if 'rect' not in block and isinstance(position.get('rect'), list):
                block['rect'] = position.get('rect')
            if 'page' not in block and isinstance(position.get('page'), (int, float)):
                block['page'] = position.get('page')
        if not block.get('id'):
            block['id'] = f'mineru-block-{index}'
        block['source_file'] = source
        return block

    def _extract_blocks_from_payload(self, payload: Any, source: str) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                if self._is_block_candidate(value):
                    result.append(value)
                for child in value.values():
                    walk(child)
                return
            if isinstance(value, list):
                for child in value:
                    walk(child)

        walk(payload)
        normalized: List[Dict[str, Any]] = []
        for index, block in enumerate(result):
            normalized.append(self._normalize_block(block, index, source))
        return normalized

    def _extract_mineru_blocks_from_output_dir(self, output_dir: str) -> List[Dict[str, Any]]:
        root = Path(output_dir)
        if not root.exists():
            return []
        blocks: List[Dict[str, Any]] = []
        seen = set()
        json_files = sorted(root.rglob('*.json'))
        for json_file in json_files:
            try:
                if json_file.stat().st_size > 8 * 1024 * 1024:
                    continue
                with open(json_file, 'r', encoding='utf-8') as handle:
                    payload = json.load(handle)
            except Exception:
                continue
            extracted = self._extract_blocks_from_payload(payload, str(json_file))
            for item in extracted:
                fingerprint = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                blocks.append(item)
                if len(blocks) >= 2000:
                    return blocks
        return blocks

    def _write_markdown_file(
        self,
        output_dir: str,
        markdown: str,
        mineru_blocks: Optional[List[Dict[str, Any]]] = None,
        raw_artifacts: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """将 Markdown 写入标准输出文件并返回成功结果。"""
        md_file_path = os.path.join(output_dir, 'parsed.md')
        with open(md_file_path, 'w', encoding='utf-8') as output_file:
            output_file.write(markdown)
        return self._build_parse_result(
            True,
            md_file=md_file_path,
            error=None,
            mineru_blocks=mineru_blocks,
            raw_artifacts=raw_artifacts
        )

    def _fetch_markdown_from_cloud_urls(self, markdown_url: str, zip_url: str) -> Dict[str, Any]:
        """按优先级从云端 URL 获取 Markdown，并返回来源与 ZIP 字节。"""
        markdown: Optional[str] = None
        source = ''
        zip_bytes: Optional[bytes] = None
        if markdown_url:
            md_resp = requests.get(markdown_url, timeout=120, verify=False)
            if md_resp.status_code == 200 and self._is_valid_markdown_text(md_resp.text):
                markdown = md_resp.text
                source = 'markdown_url'
        if not markdown and zip_url:
            zip_resp = requests.get(zip_url, timeout=120, verify=False)
            if zip_resp.status_code == 200:
                markdown = self._download_markdown_from_zip(zip_resp.content)
                if markdown:
                    source = 'zip_url'
                    zip_bytes = zip_resp.content
        return {'markdown': markdown, 'source': source, 'zip_bytes': zip_bytes}

    def _download_markdown_from_zip(self, zip_bytes: bytes) -> Optional[str]:
        """从 ZIP 响应中提取 Markdown 文本。"""
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
                markdown_candidates = [
                    name for name in archive.namelist()
                    if name.lower().endswith('.md')
                ]
                for name in markdown_candidates:
                    with archive.open(name) as file_obj:
                        content = file_obj.read().decode('utf-8', errors='ignore').strip()
                        if self._is_valid_markdown_text(content):
                            return content
        except Exception:
            return None
        return None

    def _parse_document_cloud_batch(self, input_path: str, output_dir: str) -> Optional[Dict[str, Any]]:
        """使用云端 batch 接口解析文档。"""
        if not self.api_key:
            return None
        base_url = self.client_base_url
        headers = self._build_cloud_headers()
        raw_dir = self._ensure_raw_output_dir(output_dir)
        data_id = f'parse-{int(time.time())}-{Path(input_path).stem[:24]}'
        create_payload = {
            'files': [{'name': Path(input_path).name, 'data_id': data_id}],
            'model_version': 'vlm'
        }
        try:
            create_resp = requests.post(
                f'{base_url}/file-urls/batch',
                headers=headers,
                json=create_payload,
                timeout=60,
                verify=False
            )
            create_json = create_resp.json()
            self._write_json_output(raw_dir / 'cloud_create_response.json', create_json)
            if create_resp.status_code != 200 or create_json.get('code') != 0:
                return self._build_parse_result(
                    False,
                    error=f'云端上传地址创建失败: status={create_resp.status_code}, response={create_json}'
                )

            batch_data = create_json.get('data', {}) if isinstance(create_json, dict) else {}
            batch_id = batch_data.get('batch_id') or batch_data.get('id') or ''
            file_urls = batch_data.get('file_urls') or []
            if not batch_id or not file_urls:
                return self._build_parse_result(False, error='云端上传地址创建成功但缺少 batch_id 或 file_urls')

            upload_url = str(file_urls[0])
            with open(input_path, 'rb') as file_obj:
                upload_resp = requests.put(upload_url, data=file_obj, timeout=300, verify=False)
            if upload_resp.status_code not in (200, 201):
                detail = (upload_resp.text or '').strip()[:320]
                return self._build_parse_result(
                    False,
                    error=f'云端上传失败: status={upload_resp.status_code}, detail={detail}'
                )

            last_state = ''
            last_query_payload: Dict[str, Any] = {}
            for _ in range(self.cloud_poll_max_attempts):
                time.sleep(self.cloud_poll_interval_seconds)
                query_resp = requests.get(
                    f'{base_url}/extract-results/batch/{batch_id}',
                    headers=headers,
                    timeout=60,
                    verify=False
                )
                payload = query_resp.json()
                if isinstance(payload, dict):
                    last_query_payload = payload
                if query_resp.status_code != 200 or payload.get('code') != 0:
                    continue

                result_list = payload.get('data', {}).get('extract_result') or payload.get('data', {}).get('files') or []
                if not result_list or not isinstance(result_list, list):
                    continue
                first = result_list[0] if isinstance(result_list[0], dict) else {}
                state = self._extract_nested_value(first, ['state', 'status', 'extract_state', 'parse_state']).lower()
                last_state = state
                markdown_url = self._extract_nested_value(first, ['full_md_url', 'md_url', 'markdown_url'])
                zip_url = self._extract_nested_value(first, ['full_zip_url', 'zip_url', 'result_zip_url'])
                if any(flag in state for flag in ('failed', 'error', 'timeout')):
                    if last_query_payload:
                        self._write_json_output(raw_dir / 'cloud_query_response.json', last_query_payload)
                    return self._build_parse_result(False, error=f'云端解析失败: state={state or "unknown"}')
                markdown_bundle = self._fetch_markdown_from_cloud_urls(markdown_url, zip_url)
                markdown = markdown_bundle.get('markdown')
                if markdown:
                    if last_query_payload:
                        self._write_json_output(raw_dir / 'cloud_query_response.json', last_query_payload)
                    zip_bytes = markdown_bundle.get('zip_bytes')
                    if isinstance(zip_bytes, (bytes, bytearray)) and zip_bytes:
                        with open(raw_dir / 'cloud_result.zip', 'wb') as handle:
                            handle.write(bytes(zip_bytes))
                    manifest_payload = {
                        'batch_id': batch_id,
                        'data_id': data_id,
                        'state': state,
                        'markdown_url': markdown_url,
                        'zip_url': zip_url,
                        'markdown_source': markdown_bundle.get('source') or '',
                        'saved_at': datetime.now().isoformat()
                    }
                    self._write_json_output(raw_dir / 'cloud_result_manifest.json', manifest_payload)
                    cloud_blocks = self._extract_blocks_from_payload(first, 'cloud_result')
                    return self._write_markdown_file(
                        output_dir,
                        markdown,
                        cloud_blocks,
                        raw_artifacts={
                            'raw_dir': str(raw_dir),
                            'manifest_file': str(raw_dir / 'cloud_result_manifest.json')
                        }
                    )
            if last_query_payload:
                self._write_json_output(raw_dir / 'cloud_query_response.json', last_query_payload)
            return self._build_parse_result(False, error=f'云端解析轮询超时: state={last_state or "unknown"}')
        except Exception as error:
            return self._build_parse_result(False, error=f'云端解析流程异常: {error}')

    def _is_oom_message(self, text: str) -> bool:
        """判断是否为显存不足错误"""
        normalized = (text or '').lower()
        return 'cuda out of memory' in normalized or 'out of memory' in normalized or '显存' in normalized

    def _build_direct_retry_profiles(self) -> List[Dict[str, str]]:
        """构建直连接口重试配置"""
        return [
            {
                'return_md': 'true',
                'response_format_zip': 'false',
                'formula_enable': 'false',
                'table_enable': 'false',
                'parse_method': 'txt',
                'start_page_id': '0',
                'end_page_id': '0'
            },
            {
                'return_md': 'true',
                'response_format_zip': 'false',
                'formula_enable': 'false',
                'table_enable': 'false',
                'parse_method': 'txt',
                'start_page_id': '0',
                'end_page_id': str(self.light_end_page)
            },
            {
                'return_md': 'true',
                'response_format_zip': 'false',
                'formula_enable': 'false',
                'table_enable': 'false',
                'parse_method': 'auto',
                'start_page_id': '0',
                'end_page_id': str(self.light_end_page)
            },
            {
                'return_md': 'true',
                'response_format_zip': 'false',
                'formula_enable': 'true',
                'table_enable': 'true',
                'parse_method': 'auto'
            }
        ]

    def _extract_free_memory_mib(self, error_text: str) -> Optional[float]:
        """从错误文本中提取可用显存 MiB"""
        match = re.search(r'of which\s+([0-9.]+)\s+MiB\s+is free', error_text or '', flags=re.IGNORECASE)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    def _should_fast_fail_on_oom(self, error_text: str) -> bool:
        """根据可用显存判断是否应快速失败"""
        free_mib = self._extract_free_memory_mib(error_text)
        if free_mib is None:
            return False
        return free_mib < float(self.min_free_memory_mib)

    def _build_oom_hint(self, error_text: str) -> str:
        """构建显存不足提示信息"""
        match = re.search(r'of which\s+([0-9.]+\s+MiB)\s+is free', error_text or '', flags=re.IGNORECASE)
        free_text = match.group(1) if match else '当前可用显存不足'
        threshold_text = f'{self.min_free_memory_mib} MiB'
        return f'请先释放 GPU 任务后重试（检测到可用显存：{free_text}，建议至少保留：{threshold_text}）'

    def _resolve_direct_error(
        self,
        error_text: str,
        index: int,
        retry_profiles: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """处理直连接口错误并决定是否继续重试。"""
        if self._is_oom_message(error_text):
            if self._should_fast_fail_on_oom(error_text):
                fast_error = f'GPU 繁忙，检测到可用显存过低，已跳过重复重试：{error_text}；{self._build_oom_hint(error_text)}'
                return {'retry': False, 'result': self._build_parse_result(False, error=fast_error)}
            if index < len(retry_profiles) - 1:
                return {'retry': True, 'result': None}
            oom_error = f'显存不足，已执行{len(retry_profiles)}次降级重试后仍失败：{error_text}；{self._build_oom_hint(error_text)}'
            return {'retry': False, 'result': self._build_parse_result(False, error=oom_error)}
        return {'retry': False, 'result': self._build_parse_result(False, error=error_text)}

    def _parse_document_direct(self, input_path: str, output_dir: str) -> Optional[Dict[str, Any]]:
        """使用 /file_parse 接口直接解析文档"""
        base_url = self._detect_direct_base_url()
        if not base_url:
            return None
        try:
            raw_dir = self._ensure_raw_output_dir(output_dir)
            retry_profiles = self._build_direct_retry_profiles()[:self.max_parse_retries]
            last_error = ''
            for index, data in enumerate(retry_profiles):
                with open(input_path, 'rb') as file_obj:
                    response = requests.post(
                        f'{base_url}/file_parse',
                        headers={'Authorization': f'Bearer {self.api_key}'} if self.api_key else {},
                        data=data,
                        files=[('files', (Path(input_path).name, file_obj, 'application/pdf'))],
                        timeout=300,
                        verify=False
                    )
                detail = (response.text or '').strip()
                if response.status_code != 200:
                    detail = detail[:280] if detail else ''
                    last_error = f'Request failed with status {response.status_code}: {detail or "Unknown error"}'
                    decision = self._resolve_direct_error(last_error, index, retry_profiles)
                    if decision.get('retry'):
                        time.sleep(self.oom_retry_wait_seconds)
                        continue
                    return decision.get('result')
                try:
                    payload = response.json()
                except json.JSONDecodeError:
                    payload = response.text or ''
                if isinstance(payload, (dict, list)):
                    self._write_json_output(raw_dir / 'direct_parse_response.json', payload)
                if isinstance(payload, dict) and payload.get('error'):
                    last_error = str(payload.get('error'))
                    decision = self._resolve_direct_error(last_error, index, retry_profiles)
                    if decision.get('retry'):
                        time.sleep(self.oom_retry_wait_seconds)
                        continue
                    return decision.get('result')
                markdown = self._extract_markdown_from_payload(payload)
                if not markdown:
                    return self._build_parse_result(False, error='解析成功但未返回 Markdown 内容')
                direct_blocks = self._extract_blocks_from_payload(payload, 'direct_result')
                return self._write_markdown_file(
                    output_dir,
                    markdown,
                    direct_blocks,
                    raw_artifacts={'raw_dir': str(raw_dir)}
                )
            return self._build_parse_result(
                False,
                error=f'显存不足，已执行{len(retry_profiles)}次降级重试后仍失败：{last_error}；{self._build_oom_hint(last_error)}'
            )
        except Exception as error:
            return self._build_parse_result(False, error=f'解析请求失败: {error}')

    def _get_client(self):
        """获取 MinerU 客户端"""
        if self._client is None:
            try:
                from mineru_rag import MinerUClient
                constructor_candidates = [
                    {'api_token': self.api_key},
                    {'api_key': self.api_key},
                    {'token': self.api_key},
                    {}
                ]
                last_error: Optional[Exception] = None
                for kwargs in constructor_candidates:
                    try:
                        self._client = MinerUClient(**kwargs)
                        break
                    except TypeError as error:
                        last_error = error
                if self._client is None:
                    if last_error:
                        raise last_error
                    raise RuntimeError('MinerUClient 初始化失败')
                for field in ('api_url', 'base_url', 'endpoint'):
                    if hasattr(self._client, field):
                        setattr(self._client, field, self.client_base_url)
                        break
            except ImportError:
                raise ImportError("请安装 mineru-rag: pip install mineru-rag[rag]")
        return self._client

    def parse_document(
        self,
        input_path: str,
        output_dir: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        解析文档

        Args:
            input_path: 输入文件路径
            output_dir: 输出目录
            **kwargs: 其他参数

        Returns:
            解析结果字典
        """
        cloud_result = self._parse_document_cloud_batch(input_path, output_dir)
        if cloud_result is not None and cloud_result.get('success'):
            return self._build_final_result(cloud_result, input_path, output_dir)

        direct_result = self._parse_document_direct(input_path, output_dir)
        if direct_result is not None:
            return self._build_final_result(
                direct_result,
                input_path,
                output_dir,
                fallback_error=cloud_result.get('error') if cloud_result else None
            )

        client = self._get_client()

        result = client.process_file(
            input_path=input_path,
            output_path=output_dir,
            **kwargs
        )

        return self._build_final_result(
            result,
            input_path,
            output_dir,
            fallback_error=cloud_result.get('error') if cloud_result else None
        )

    def parse_documents_batch(
        self,
        file_paths: list,
        output_dir: str,
        **kwargs
    ) -> list:
        """
        批量解析文档

        Args:
            file_paths: 文件路径列表
            output_dir: 输出目录
            **kwargs: 其他参数

        Returns:
            解析结果列表
        """
        client = self._get_client()

        results = client.process_files_batch(
            file_paths=file_paths,
            output_dir=output_dir,
            **kwargs
        )

        return results


class MinerURag:
    """MinerU RAG 服务"""

    def __init__(self):
        self._rag = None
        self._llm = None

    def _get_rag(self):
        """获取 RAG 构建器"""
        if self._rag is None:
            try:
                from mineru_rag import RAGBuilder
                self._rag = RAGBuilder()
            except ImportError:
                raise ImportError("请安装 mineru-rag: pip install mineru-rag[rag]")
        return self._rag

    def _get_llm(self):
        """获取 LLM 客户端"""
        if self._llm is None:
            try:
                from mineru_rag import LLMClient
                from dotenv import load_dotenv
                load_dotenv()

                api_key = os.getenv('Public_ALIYUN_API_KEY') or os.getenv('ALIYUN_API_KEY')
                base_url = os.getenv('Public_ALIYUN_API_URL') or os.getenv('ALIYUN_API_URL')
                model = os.getenv('Public_ALIYUN_MODEL2') or os.getenv('ALIYUN_MODEL', 'qwen3.5-397b-a17b')

                self._llm = LLMClient(
                    api_key=api_key,
                    base_url=base_url,
                    model=model
                )
            except ImportError:
                raise ImportError("请安装 mineru-rag: pip install mineru-rag[rag]")
        return self._llm

    def build_knowledge_base(
        self,
        markdown_files: list,
        library_id: str,
        metadata: dict = None
    ) -> Dict[str, Any]:
        """
        构建知识库

        Args:
            markdown_files: Markdown 文件路径列表
            library_id: 知识库 ID
            metadata: 元数据

        Returns:
            构建结果
        """
        rag = self._get_rag()

        rag.build_from_files(
            file_paths=markdown_files,
            library_id=library_id,
            metadata=metadata or {}
        )

        return {
            'success': True,
            'library_id': library_id,
            'file_count': len(markdown_files)
        }

    def load_knowledge_base(self, library_id: str) -> None:
        """加载知识库"""
        rag = self._get_rag()
        rag.load_vector_store(library_id=library_id)

    def query(
        self,
        question: str,
        k: int = 4,
        library_id: str = 'default'
    ) -> Dict[str, Any]:
        """
        查询知识库（仅检索）

        Args:
            question: 问题
            k: 检索数量
            library_id: 知识库 ID

        Returns:
            检索结果
        """
        rag = self._get_rag()
        rag.load_vector_store(library_id=library_id)

        result = rag.query(question=question, k=k)

        return {
            'question': question,
            'num_sources': result.get('num_sources', 0),
            'sources': result.get('sources', [])
        }

    def query_with_llm(
        self,
        question: str,
        k: int = 4,
        library_id: str = 'default'
    ) -> Dict[str, Any]:
        """
        查询知识库并使用 LLM 生成答案

        Args:
            question: 问题
            k: 检索数量
            library_id: 知识库 ID

        Returns:
            问答结果
        """
        rag = self._get_rag()
        llm = self._get_llm()

        rag.load_vector_store(library_id=library_id)

        rag_result = rag.query(question=question, k=k)
        answer = llm.query_with_rag(rag_result)

        return {
            'question': question,
            'answer': answer.get('answer', ''),
            'num_sources': answer.get('num_sources', 0),
            'sources': answer.get('sources', [])
        }


mineru_parser = MinerUParser()
mineru_rag = MinerURag()

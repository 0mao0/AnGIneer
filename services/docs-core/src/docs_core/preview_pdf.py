"""PDF 预览副本（对象流重排）构建器。

背景：页字典散落的老排版 PDF，pdf.js 加载时取末页会逐页跨文件取字典，
每个字典触发一个新分块，13MB 的文件要整份下完才出首屏（JTS 165-2013 实测）。
重排成对象流后页字典聚拢，同一文件首屏只需 1.2MB。

消费方：
- docs-api `/api/files`（probe=1 探测 / web=1 走副本）；
- 解析管线 vectors 阶段收尾预热（prewarm_for_document）。

并发契约：同一 cache_path 只起一个构建线程（_building 去重）；构建失败绝不影响预览。
"""

import hashlib
import logging
import os
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PDF_WEB_MIN_BYTES = 1024 * 1024
_locks_guard = threading.Lock()
_building: set = set()  # 正在后台构建的 cache_path，防同一文件重复起线程


def pdf_web_optimize_enabled() -> bool:
    return os.getenv("PDF_WEB_OPTIMIZE", "1").strip().lower() not in {"0", "false", "no", "off"}


def pdf_web_cache_dir() -> Path:
    from docs_core.paths import resolve_knowledge_base_dir

    return resolve_knowledge_base_dir().parent / "cache" / "pdf_web"


def pdf_web_cache_path(source_path: str) -> Optional[str]:
    """缓存键含 mtime+size：文档重新解析后自动失效，无需手工清理。

    键里含**进程内视角的绝对路径**：容器里是 /app/...、宿主机是宿主路径，
    两侧各自构建各自的副本（同卷目录、同键概率极低），互不干扰。
    """
    try:
        stat = os.stat(source_path)
    except OSError:
        return None
    key = hashlib.sha1(
        f"{source_path}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")
    ).hexdigest()
    return str(pdf_web_cache_dir() / f"{key}.pdf")


def prune_pdf_web_cache(cache_dir: Path) -> None:
    """纯缓存：超上限按最久未访问删除，删掉只是下次重新生成。"""
    try:
        limit = int(os.getenv("PDF_WEB_CACHE_MAX_MB", "2048")) * 1024 * 1024
    except ValueError:
        limit = 2048 * 1024 * 1024
    try:
        entries = [(item.stat().st_mtime, item.stat().st_size, item) for item in cache_dir.glob("*.pdf")]
    except OSError:
        return
    total = sum(size for _, size, _ in entries)
    if total <= limit:
        return
    for _, size, item in sorted(entries):
        try:
            item.unlink()
            total -= size
        except OSError:
            continue
        if total <= limit:
            break


def build_web_pdf(source_path: str, cache_path: str) -> bool:
    """生成重排成对象流的预览副本；校验页数一致才落缓存（os.replace 原子替换）。"""
    tmp_path: Optional[str] = None
    try:
        import fitz  # PyMuPDF

        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        tmp_path = f"{cache_path}.{os.getpid()}.{threading.get_ident()}.tmp.pdf"
        with fitz.open(source_path) as source_doc:
            page_count = source_doc.page_count
            source_doc.save(tmp_path, garbage=4, deflate=True, use_objstms=1)
        with fitz.open(tmp_path) as check_doc:
            if check_doc.page_count != page_count:
                raise ValueError(f"页数不一致: {check_doc.page_count} != {page_count}")
        os.replace(tmp_path, cache_path)
        tmp_path = None
        prune_pdf_web_cache(Path(os.path.dirname(cache_path)))
        logger.info("[Preview] 已生成 PDF 预览副本: %s", os.path.basename(source_path))
        return True
    except Exception as error:  # 优化失败绝不影响预览本身
        logger.warning("[Preview] PDF 预览副本生成失败，回退原文件: %s (%s)", source_path, error)
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return False


def get_or_build_web_pdf(source_path: str) -> Optional[str]:
    """返回重排成对象流的预览副本路径；不满足条件或副本未就绪一律返回 None（回退原文件）。

    只用于在线预览（下载走 raw=1 拿原件）。
    缓存未命中时**不同步等待转码**：大 PDF（几百页 / 几十 MB）重写对象流要几十秒到分钟级，
    同步构建会让首开用户在收到第一字节前就等满这段时间（459 页实踩 >30s）。
    现改为后台线程构建、本次直接回原件——原件同样支持 Range 按需加载，只是首屏稍慢；
    同一文档下一次打开自动命中副本。
    """
    if not pdf_web_optimize_enabled():
        return None
    try:
        if os.path.getsize(source_path) < _PDF_WEB_MIN_BYTES:
            return None
    except OSError:
        return None

    cache_path = pdf_web_cache_path(source_path)
    if not cache_path:
        return None
    if os.path.isfile(cache_path):
        return cache_path

    with _locks_guard:
        if cache_path in _building:
            return None
        _building.add(cache_path)

    def _background_build() -> None:
        try:
            build_web_pdf(source_path, cache_path)
        finally:
            with _locks_guard:
                _building.discard(cache_path)

    threading.Thread(target=_background_build, name="pdf-web-cache-build", daemon=True).start()
    return None


def prewarm_for_document(library_id: str, doc_id: str, file_path: str) -> None:
    """解析收尾预热：对「预览实际会服务的 PDF」后台起一次副本构建（fire-and-forget）。

    预览服务的对象 = render_pdf（office 转换产物或上传即 PDF）或源文件本身；
    是否真构建（>1MB、开关开、未在建）由 get_or_build_web_pdf 统一裁决。
    """
    from docs_core.docs_file_io import file_storage

    try:
        manifest = file_storage.get_doc_manifest(library_id, doc_id)
    except Exception:
        manifest = {}
    candidates = []
    render_pdf = str(manifest.get("render_pdf") or "").strip()
    if render_pdf:
        candidates.append(render_pdf)
    if file_path:
        candidates.append(file_path)
    for candidate in candidates:
        if not candidate.lower().endswith(".pdf") or not os.path.isfile(candidate):
            continue
        if get_or_build_web_pdf(candidate):
            return  # 已有现成副本，无需再建


__all__ = [
    "pdf_web_optimize_enabled",
    "pdf_web_cache_dir",
    "pdf_web_cache_path",
    "prune_pdf_web_cache",
    "build_web_pdf",
    "get_or_build_web_pdf",
    "prewarm_for_document",
]

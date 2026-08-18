"""step04 总控：把 03 解析产物构建成结构化图（nodes + edges），落盘 jsonl + meta。

编排流程：
    03 解析产物 ──► solo_engine（构建 nodes/edges，失败即中断）
                        │
                        ▼
                  PoPo 信号增强（可选，软失败，失败回滚）
                        │
                        ▼
                  统一标题仲裁（无信号也执行）
                        │
                        ▼
                  落盘 jsonl + meta（含 build_id 关联）
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import docs_core.paths as paths
from docs_core.step04_structure.solo_engine import StructuredResult, build_structured_from_rawfiles
from docs_core.step04_structure.shared.jsonl_io import (
    _stamp_markdown_build_id,
    extract_build_id_from_markdown,
    new_or_reuse_build_id,
)
import docs_core.docs_file_io as _afs

logger = logging.getLogger(__name__)


# 延迟获取 AnGIneer LLM 客户端，避免循环导入
def _get_llm_client():
    try:
        from ai_inference.llm_client import llm_client
        return llm_client
    except ImportError:
        return None


__all__ = ["build_structured_index_for_doc"]


# 分析步骤回调：无回调时静默跳过（API 直调等场景不受影响）
def _emit_step(
    on_step: Optional[Callable[[str, str, str], None]],
    step: str,
    status: str = "done",
    detail: str = "",
) -> None:
    if on_step is not None:
        try:
            on_step(step, status, detail)
        except Exception:
            logger.warning("分析步骤回调失败 step=%s", step, exc_info=True)


def _extract_printed_page_label(text: Any) -> str:
    """纸面页码解析：优先“第 N 页”，其次纯数字/带装饰数字，最后罗马数字（前言页）。"""
    value = str(text or "").strip()
    if not value:
        return ""
    m = re.search(r"第\s*(\d+)\s*页", value)
    if m:
        return m.group(1)
    m = re.match(r"^\s*[-—–]?\s*(\d+)\s*[-—–]?\s*$", value)
    if m:
        return m.group(1)
    if re.match(r"^[IVXLCDM]{1,10}$", value):
        return value
    return ""


def _build_graph_page_label_map(nodes: List[Dict[str, Any]]) -> Dict[int, str]:
    """从 page_number/page_footer 块文本提取 page_idx -> 纸面页码。"""
    label_map: Dict[int, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        block_type = str(node.get("block_type") or "").strip().lower()
        if block_type not in ("page_number", "page_footer"):
            continue
        try:
            page_idx = int(node.get("page_idx") or 0)
        except (TypeError, ValueError):
            continue
        if page_idx in label_map:
            continue
        label = _extract_printed_page_label(node.get("plain_text"))
        if label:
            label_map[page_idx] = label
    return label_map


def _build_graph_outlines(
    nodes: List[Dict[str, Any]],
    page_label_map: Optional[Dict[int, str]] = None,
) -> List[Dict[str, Any]]:
    """从 title 节点构建扁平 outline：outline_id/title/level/page_idx/anchor_block_id/parent_outline_id/printed_page_label。"""
    title_nodes = [
        node for node in nodes
        if str(node.get("block_type") or "").strip() == "title"
        and str(node.get("plain_text") or "").strip()
        and node.get("derived_level") is not None
    ]
    label_map = page_label_map or {}
    title_nodes.sort(key=lambda node: (
        int(node.get("page_idx") or 0),
        int(node.get("block_seq") or 0),
    ))
    outline_id_by_uid: Dict[str, str] = {}
    outlines: List[Dict[str, Any]] = []
    for node in title_nodes:
        uid = str(node.get("block_uid") or node.get("id") or "").strip()
        if not uid:
            continue
        outline_id = f"outline:{uid}"
        outline_id_by_uid[uid] = outline_id
        outlines.append({
            "outline_id": outline_id,
            "title": str(node.get("plain_text") or "").strip(),
            "level": int(node.get("derived_level")),
            "page_idx": int(node.get("page_idx") or 0),
            "anchor_block_id": uid,
            "parent_outline_id": None,
            "printed_page_label": label_map.get(int(node.get("page_idx") or 0)) or None,
        })
    for node in title_nodes:
        uid = str(node.get("block_uid") or node.get("id") or "").strip()
        parent_uid = str(node.get("parent_uid") or "").strip()
        if not uid or not parent_uid:
            continue
        outline = next(
            (item for item in outlines if item["anchor_block_id"] == uid),
            None,
        )
        if outline is not None and parent_uid in outline_id_by_uid:
            outline["parent_outline_id"] = outline_id_by_uid[parent_uid]
    return outlines


def _build_graph_pages_from_middle(middle_payload: Any) -> tuple[Optional[int], List[Dict[str, Any]]]:
    """从 middle.json pdf_info 提取 (pageCount, pages)。"""
    if not isinstance(middle_payload, dict):
        return None, []
    pdf_info = middle_payload.get("pdf_info")
    if not isinstance(pdf_info, list):
        return None, []
    pages: List[Dict[str, Any]] = []
    for idx, page in enumerate(pdf_info):
        if not isinstance(page, dict):
            continue
        size = page.get("page_size") or []
        if not isinstance(size, (list, tuple)) or len(size) < 2:
            continue
        try:
            pages.append({
                "pageIdx": int(page.get("page_idx", idx)),
                "width": float(size[0]),
                "height": float(size[1]),
            })
        except (TypeError, ValueError):
            continue
    return (len(pdf_info), pages) if pdf_info else (None, [])


def _build_graph_pages(
    library_id: str,
    doc_id: str,
    nodes: List[Dict[str, Any]],
) -> tuple[Optional[int], List[Dict[str, Any]]]:
    """构建 graph meta 的 pages；优先 middle.json，不完整或缺失时用节点 page_width/height 兜底。"""
    by_page: Dict[int, tuple[float, float]] = {}
    for node in nodes:
        page_idx = int(node.get("page_idx") or 0)
        width = node.get("page_width")
        height = node.get("page_height")
        if isinstance(width, (int, float)) and isinstance(height, (int, float)) and width > 0 and height > 0:
            by_page.setdefault(page_idx, (float(width), float(height)))

    def _node_pages() -> tuple[Optional[int], List[Dict[str, Any]]]:
        if by_page:
            pages = [
                {"pageIdx": page_idx, "width": width, "height": height}
                for page_idx, (width, height) in sorted(by_page.items())
            ]
            return max(by_page) + 1, pages
        return None, []

    middle_path = paths.get_mineru_raw_dir(library_id, doc_id) / "middle.json"
    if not middle_path.exists():
        middle_path = paths.get_parsed_dir(library_id, doc_id) / "middle.json"
    if middle_path.exists():
        try:
            middle_payload = json.loads(middle_path.read_text(encoding="utf-8"))
            page_count, pages = _build_graph_pages_from_middle(middle_payload)
            if pages:
                node_page_count, node_pages = _node_pages()
                if node_pages and (page_count is None or page_count < max(p["pageIdx"] for p in node_pages) + 1):
                    # middle.json 页数不完整（如分块合并丢失后半段），改用节点尺寸兜底
                    return node_page_count, node_pages
                return page_count, pages
        except (OSError, json.JSONDecodeError):
            pass
    return _node_pages()


def _extract_pdf_metadata(pdf_path: Optional[str]) -> Dict[str, Optional[str]]:
    """从 PDF 元数据提取 author/creatorTool/createdAt/modifiedAt；失败或缺字段给 null。"""
    result: Dict[str, Optional[str]] = {
        "author": None,
        "creatorTool": None,
        "createdAt": None,
        "modifiedAt": None,
    }
    if not pdf_path or not Path(pdf_path).exists():
        return result
    try:
        import fitz
    except ImportError:
        return result
    try:
        with fitz.open(str(pdf_path)) as pdf:
            metadata = pdf.metadata or {}
            result["author"] = metadata.get("author") or None
            result["creatorTool"] = metadata.get("creator") or metadata.get("producer") or None
            result["createdAt"] = metadata.get("creationDate") or None
            result["modifiedAt"] = metadata.get("modificationDate") or None
    except Exception:
        return result
    return result


def _build_doc_meta(
    library_id: str,
    doc_id: str,
    page_count: Optional[int] = None,
) -> Dict[str, Any]:
    """构建 graph meta 的 docMeta：fileName/pageCount/author/creatorTool/createdAt/modifiedAt。"""
    doc_info = _afs.file_storage.get_doc_manifest(library_id, doc_id)
    source_file = doc_info.get("source_file")
    file_name = str(Path(source_file).name) if source_file else None
    pdf_metadata = _extract_pdf_metadata(doc_info.get("render_pdf") or source_file)
    return {
        "fileName": file_name,
        "pageCount": page_count,
        "author": pdf_metadata["author"],
        "creatorTool": pdf_metadata["creatorTool"],
        "createdAt": pdf_metadata["createdAt"],
        "modifiedAt": pdf_metadata["modifiedAt"],
    }


# 保存 doc_blocks_graph.jsonl + doc_blocks_graph_meta.json
def _save_doc_blocks_graph(
    library_id: str,
    doc_id: str,
    result: StructuredResult,
) -> str:
    from docs_core.step04_structure.shared.jsonl_io import atomic_write_text
    from docs_core.step04_structure.shared.markdown_projection import build_faithful_markdown

    md_path = paths.get_parsed_markdown_path(library_id, doc_id)
    if not md_path.exists():
        # 保留既有契约：structure 输入缺失时显式失败，而不是静默生成半成品
        raise RuntimeError(
            f"build_id 盖章失败：content.md 缺失或与 meta 不一致"
            f"（请检查 parsed/content.md 是否可写）"
        )
    build_id = new_or_reuse_build_id(library_id, doc_id)

    # 以 jsonl 节点为唯一真相，生成保真 Markdown 投影，并在写 jsonl 前回填行号
    md_text, line_ranges = build_faithful_markdown(result.nodes, build_id)
    for node in result.nodes:
        uid = str(node.get("block_uid") or node.get("id") or "").strip()
        span = line_ranges.get(uid)
        node["markdown_line_start"] = span["start"] if span else None
        node["markdown_line_end"] = span["end"] if span else None

    jsonl_path = paths.get_graph_jsonl_path(library_id, doc_id)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for node in result.nodes:
            f.write(json.dumps(node, ensure_ascii=False) + "\n")

    atomic_write_text(md_path, md_text)
    # edited/current.md 若已存在（用户改过），仅盖章保持版本一致，不重写内容
    edited_md_path = paths.get_edited_markdown_path(library_id, doc_id)
    _stamp_markdown_build_id(edited_md_path, build_id)

    md_build_id = extract_build_id_from_markdown(md_path.read_text(encoding="utf-8"))
    if md_build_id != build_id:
        raise RuntimeError(
            f"build_id 盖章失败：content.md 缺失或与 meta 不一致"
            f"（meta={build_id}, md={md_build_id}）"
        )

    meta_path = paths.get_graph_meta_path(library_id, doc_id)
    page_count, pages = _build_graph_pages(library_id, doc_id, result.nodes)
    doc_meta = _build_doc_meta(library_id, doc_id, page_count)
    page_label_map = _build_graph_page_label_map(result.nodes)
    meta = {
        "edges": result.edges,
        "stats": result.stats,
        "generated_at": datetime.now().isoformat(),
        "build_id": build_id,
        "docMeta": doc_meta,
        "outlines": _build_graph_outlines(result.nodes, page_label_map),
        "pages": pages,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return str(meta_path)


# Phase 7/8：PoPo 信号应用（续接/表格合并注入 + 层级信号融合；有则增强、无则跳过，
# 任何异常都不阻断 solo 管线）
def _apply_popo_signals(
    library_id: str,
    doc_id: str,
    nodes: list,
    *,
    edges: Optional[list] = None,
    llm_client=None,
    llm_model: Optional[str] = None,
    use_llm: bool = False,
    on_step: Optional[Callable[[str, str, str], None]] = None,
) -> tuple[list, Dict[str, Any], Dict[str, Any]]:
    """返回 (nodes, injection_stats, popo_candidates)。"""
    from docs_core.step04_structure.popo.popo_signal_aligner import align_popo_blocks
    from docs_core.step04_structure.popo.popo_block_merger import merge_blocks
    from docs_core.step04_structure.popo.popo_signal_injector import inject_popo_signals
    from docs_core.step04_structure.popo.popo_signal_level_fusion import (
        build_popo_level_map,
        build_popo_tree_level_map,
    )

    popo_candidates: Dict[str, Any] = {}
    try:
        enriched = _afs.file_storage.read_popo_enriched_blocks(library_id, doc_id)
    except FileNotFoundError:
        _emit_step(on_step, "PoPo 结果读取", "skipped", "无 enriched_blocks.json")
        return nodes, {
            "injection": {"skipped_reason": "no_popo"},
            "heuristic": {"applied": 0, "skipped": 0, "skipped_reason": "no_popo"},
            "merge": {"applied": 0, "rejected": 0, "skipped_reason": "no_popo"},
        }, popo_candidates
    middle_path = paths.get_mineru_raw_dir(library_id, doc_id) / "middle.json"
    if not middle_path.exists():
        _emit_step(on_step, "PoPo 结果读取", "failed", "缺少 middle.json")
        return nodes, {
            "injection": {"skipped_reason": "no_middle"},
            "heuristic": {"applied": 0, "skipped": 0, "skipped_reason": "no_middle"},
            "merge": {"applied": 0, "rejected": 0, "skipped_reason": "no_middle"},
        }, popo_candidates
    try:
        middle = json.loads(middle_path.read_text(encoding="utf-8"))
        alignment = align_popo_blocks(doc_id, middle, enriched)
        if alignment.degraded:
            _emit_step(
                on_step,
                "popo 结果对齐检查",
                "failed",
                "; ".join(alignment.reasons[:3]) or "对齐校验失败",
            )
            logger.warning(
                "PoPo 信号对齐降级，跳过注入: doc=%s reasons=%s",
                doc_id,
                alignment.reasons[:3],
            )
            skipped = {"applied": 0, "rejected": 0, "skipped_reason": "alignment_degraded"}
            return nodes, {
                "injection": skipped,
                "heuristic": {"applied": 0, "skipped": 0, "skipped_reason": "alignment_degraded"},
                "merge": skipped,
            }, popo_candidates
        _emit_step(
            on_step,
            "popo 结果对齐检查",
            "done",
            f"aligned {len(alignment.solo_block_uid_map)} blocks",
        )
        nodes, inject_stats = inject_popo_signals(doc_id, nodes, enriched, alignment)
        injected = int(inject_stats.get("applied") or 0)
        rejected = int(inject_stats.get("rejected") or 0)
        _emit_step(
            on_step,
            "PoPo 信号注入",
            "done" if injected > 0 or rejected == 0 else "failed",
            f"applied {injected}, rejected {rejected}",
        )
        from docs_core.step04_structure.popo.popo_table_continuation import (
            attach_table_continuation_headers,
            detect_table_continuations,
        )

        nodes_by_uid = {
            str(node.get("block_uid") or node.get("id") or ""): node
            for node in nodes
        }
        heuristic_applied = 0
        heuristic_skipped = 0
        for instruction in detect_table_continuations(nodes, doc_id=doc_id):
            source = nodes_by_uid.get(instruction["source_uid"])
            if source is None or source.get("table_merge_id"):
                heuristic_skipped += 1
                continue
            source["table_merge_id"] = instruction["target_uid"]
            heuristic_applied += 1
        _emit_step(
            on_step,
            "续表启发式检测",
            "done",
            f"applied {heuristic_applied}, skipped {heuristic_skipped}",
        )
        fragment_page_by_uid: Dict[str, int] = {}
        for node in nodes:
            target_uid = node.get("table_merge_id")
            if not target_uid:
                continue
            target = nodes_by_uid.get(str(target_uid))
            if target is not None:
                fragment_page_by_uid[str(target_uid)] = int(target.get("page_idx") or 0)
        head_fragment_pages: Dict[str, List[int]] = {}
        for node in nodes:
            if node.get("block_type") != "table" or not node.get("table_merge_id"):
                continue
            head_uid = str(node.get("block_uid") or node.get("id") or "").strip()
            pages: List[int] = []
            seen: set[str] = set()
            current = node
            while current and current.get("table_merge_id"):
                target_uid = str(current["table_merge_id"])
                target = nodes_by_uid.get(target_uid)
                if target is None or target_uid in seen:
                    break
                seen.add(target_uid)
                pages.append(int(target.get("page_idx") or 0))
                current = target
            if pages:
                head_fragment_pages[head_uid] = pages
        nodes, merge_stats = merge_blocks(doc_id, nodes, edges=edges)
        for node in nodes:
            node.pop("table_merge_id", None)
        attachment_count = attach_table_continuation_headers(
            nodes, fragment_page_by_uid, head_fragment_pages
        )
        _emit_step(
            on_step,
            "续表附件化",
            "done",
            f"attached {attachment_count}",
        )
        merged = int(merge_stats.get("applied") or 0)
        rejected = int(merge_stats.get("rejected") or 0)
        _emit_step(
            on_step,
            "PoPo 块合并",
            "done" if merged > 0 or rejected == 0 else "failed",
            f"merged {merged}, rejected {rejected}",
        )
        level_map = build_popo_level_map(enriched, alignment)
        popo_levels = {
            alignment.solo_block_uid_map[source_id]: level
            for source_id, level in level_map.items()
            if source_id in alignment.solo_block_uid_map
        }
        tree_path = paths.get_popo_document_tree_path(library_id, doc_id)
        tree_levels: Dict[str, int] = {}
        if tree_path.exists():
            tree = json.loads(tree_path.read_text(encoding="utf-8"))
            tree_levels = build_popo_tree_level_map(tree, enriched, alignment)
        popo_candidates = {"popo_levels": popo_levels, "tree_levels": tree_levels}
        return nodes, {
            "injection": inject_stats,
            "heuristic": {"applied": heuristic_applied, "skipped": heuristic_skipped},
            "merge": merge_stats,
        }, popo_candidates
    except Exception as exc:
        _emit_step(on_step, "PoPo 信号处理", "failed", f"{type(exc).__name__}: {str(exc)[:120]}")
        logger.warning("PoPo 信号注入异常，跳过: doc=%s error=%s", doc_id, exc)
        skipped = {"applied": 0, "rejected": 0, "skipped_reason": f"error:{type(exc).__name__}"}
        return nodes, {
            "injection": skipped,
            "heuristic": {"applied": 0, "skipped": 0, "skipped_reason": f"error:{type(exc).__name__}"},
            "merge": skipped,
        }, popo_candidates


# 统一标题仲裁（无论有无 PoPo 信号都执行）：
# solo 规则层级（derived_level）落 jsonl 前，交给 resolve_title_levels
# 分类（adopt/consistent/disputed/review）并一次写回。
def _resolve_title_levels(
    nodes: list,
    *,
    doc_id: str,
    popo_candidates: Optional[Dict[str, Any]] = None,
    llm_client=None,
    llm_model: Optional[str] = None,
    use_llm: bool = False,
    on_step: Optional[Callable[[str, str, str], None]] = None,
) -> tuple[list, Dict[str, Any]]:
    from docs_core.step04_structure.shared.title_level_resolver import (
        resolve_title_levels,
    )

    candidates = popo_candidates or {}
    updated, stats = resolve_title_levels(
        nodes,
        popo_levels=candidates.get("popo_levels"),
        tree_levels=candidates.get("tree_levels"),
        llm_client=llm_client,
        llm_model=llm_model,
        use_llm=use_llm,
    )
    if not stats.get("total_titles") or not use_llm:
        _emit_step(
            on_step,
            "统一标题仲裁",
            "skipped",
            "无标题或未启用 LLM" if not stats.get("total_titles") else "llm 未配置",
        )
    else:
        _emit_step(
            on_step,
            "统一标题仲裁",
            "done",
            f"{stats.get('total_titles', 0)} titles, "
            f"consistent {stats.get('consistent', 0)}, disputed {stats.get('disputed', 0)}",
        )
    return updated, stats


# 为文档构建结构化索引（step04：只落 jsonl + meta；SQLite 由 step05 从 jsonl 重建）
def build_structured_index_for_doc(
    library_id: str,
    doc_id: str,
    strategy: str = "doc_blocks_graph_v1",
    options: Optional[Dict[str, Any]] = None,
    on_step: Optional[Callable[[str, str, str], None]] = None,
) -> Dict[str, Any]:
    opts = options or {}
    use_llm = opts.get("use_llm", True)
    llm_model = str(opts.get("llm_model") or "").strip() or None
    derive_version = opts.get("derive_version", "v1")

    parsed_dir = paths.get_parsed_dir(library_id, doc_id)
    raw_dir = paths.resolve_structure_input_dir(library_id, doc_id)
    paths.resolve_structured_input_dir(raw_dir)

    llm_client = None
    if use_llm:
        llm_client = _get_llm_client()

    doc_name = ""
    doc_info = _afs.file_storage.get_doc_manifest(library_id, doc_id)
    if doc_info.get("source_file"):
        doc_name = Path(doc_info["source_file"]).name

    result = build_structured_from_rawfiles(
        parsed_dir=parsed_dir,
        doc_id=doc_id,
        doc_name=doc_name,
        llm_client=llm_client,
        options={
            "use_llm": use_llm,
            "llm_model": llm_model,
            "derive_version": derive_version,
        },
    )

    if result.stats.get("error"):
        raise ValueError(f"构建结构失败: {result.stats.get('error')}")

    _emit_step(on_step, "solo 规则构建", "done", f"{len(result.nodes)} blocks")
    signal_stats: Dict[str, Any] = {"applied": 0, "rejected": 0, "skipped_reason": "skipped"}
    title_review_stats: Dict[str, Any] = {"total_titles": 0, "llm_status": "disabled", "updated": 0}
    formula_stats: Dict[str, Any] = {"total_formulas": 0, "enriched": 0, "llm_status": "disabled"}
    table_stats: Dict[str, Any] = {"total_tables": 0, "enriched": 0, "skipped": 0}
    if result.nodes:
        result.nodes, signal_stats, popo_candidates = _apply_popo_signals(
            library_id,
            doc_id,
            result.nodes,
            edges=result.edges,
            llm_client=llm_client,
            llm_model=llm_model,
            use_llm=use_llm,
            on_step=on_step,
        )
        result.nodes, title_review_stats = _resolve_title_levels(
            result.nodes,
            doc_id=doc_id,
            popo_candidates=popo_candidates,
            llm_client=llm_client,
            llm_model=llm_model,
            use_llm=use_llm,
            on_step=on_step,
        )
        from docs_core.step04_structure.shared.formula_semantics import (
            enrich_graph_nodes_formula_semantics,
        )
        result.nodes, formula_stats = enrich_graph_nodes_formula_semantics(
            result.nodes,
            use_llm=use_llm,
            llm_client=llm_client,
            llm_model=llm_model,
        )
        _emit_step(on_step, "公式语义 enrich", "done", f"{formula_stats['enriched']} formulas")
        from docs_core.step04_structure.shared.table_semantics import (
            enrich_graph_nodes_table_semantics,
        )
        result.nodes, table_stats = enrich_graph_nodes_table_semantics(result.nodes)
        _emit_step(on_step, "表格语义 enrich", "done", f"{table_stats['enriched']} tables")

    stats = {
        "nodes_count": len(result.nodes),
        "edges_count": len(result.edges),
        "index_rows_count": len(result.index_rows),
        "llm_status": title_review_stats["llm_status"],
        "llm_model": llm_model,
        "derive_version": derive_version,
        "popo_signal": signal_stats,
        "title_level_review": title_review_stats,
        "formula_semantics": formula_stats,
        "table_semantics": table_stats,
    }
    # 让落盘的 meta.stats 携带管线级 stats（含 popo/标题复核/公式语义），而非 solo_engine 原始 stats
    result.stats = stats
    graph_path = _save_doc_blocks_graph(library_id, doc_id, result)
    _emit_step(on_step, "jsonl + meta 落盘", "done", graph_path)

    return {
        "saved_count": len(result.nodes),
        "stats": {**stats, "graph_path": graph_path},
    }

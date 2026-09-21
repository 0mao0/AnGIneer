"""图表 VLM 描述器：为 doc_blocks_graph.jsonl 中的图表块生成 figure_description。

作为解析管线 soft 阶段 figure_describe 的核心实现（structure 之后、fts 之前），
也支持脚本级独立调用（scripts/open_ragbench/generate_figure_descriptions.py 薄包装）。

存储约定：
- 本模块只负责把描述写回 doc_blocks_graph.jsonl 的 figure_description 字段（JSON 落点）；
- SQLite/FTS/向量/图谱的落库由现有 step05/06/07 自动携带（canonical_builder 消费该字段）。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

import docs_core.paths as paths

logger = logging.getLogger(__name__)

FIGURE_TYPES = {"chart", "image", "figure", "image_block"}

PROMPT = (
    "You are analyzing a figure extracted from an academic paper. "
    "Describe what this figure shows in 2-4 concise English sentences. "
    "Include: the type of figure (chart/table/illustration), the main content or trend, "
    "any notable data points or values, and the key takeaway. "
    "Be specific and factual based only on the image."
)


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env_str(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def is_enabled() -> bool:
    """阶段总开关：FIGURE_DESCRIBE_ENABLED=0 时整体跳过。"""
    return _env_str("FIGURE_DESCRIBE_ENABLED", "1") != "0"


def vlm_configs() -> List[Dict[str, str]]:
    """图描述 VLM 端点列表（FIGURE_DESCRIBE_CONFIGS JSON 数组，数组顺序=优先级，第一项为默认）。

    每项: {name, url, api_key, model}；url 为完整 chat/completions 端点，model 必填
    （缺 model 的条目跳过并告警）。连接失败/超时/HTTP 错误自动尝试下一项（与
    MINERU_CONFIGS/POPO_CONFIGS 同族约定）。

    兼容旧单变量（FIGURE_DESCRIBE_VLM_URL/API_KEY/MODEL + ANGINEER_CHAT_API_KEY）：
    只在 CONFIGS 未配置时作为一项兜底。**不再内置任何硬编码端点**——此前默认
    url=ai.bim-ace.com + key 回退 ANGINEER_CHAT_API_KEY，等于「没配置就静默走 company」
    （2026-09-21 排查实踩：生产 figure_describe 每篇解析都跑、全程走 company，
    DGX 已验证的视觉能力闲置，且 company 下线即全线故障）。
    """
    raw = _env_str("FIGURE_DESCRIBE_CONFIGS")
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("FIGURE_DESCRIBE_CONFIGS 非法 JSON，忽略: %s", raw[:200])
            data = None
        if data is not None and not isinstance(data, list):
            logger.warning("FIGURE_DESCRIBE_CONFIGS 需为 JSON 数组，忽略: %s", raw[:200])
            data = None
        if isinstance(data, list):
            configs: List[Dict[str, str]] = []
            for idx, item in enumerate(data):
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                model = str(item.get("model") or "").strip()
                if not url:
                    continue
                if not model:
                    logger.warning("FIGURE_DESCRIBE_CONFIGS 第 %d 项缺 model，跳过", idx + 1)
                    continue
                configs.append({
                    "name": str(item.get("name") or f"endpoint-{idx + 1}"),
                    "url": url,
                    "api_key": str(item.get("api_key") or item.get("key") or "").strip(),
                    "model": model,
                })
            if configs:
                return configs
    legacy_url = _env_str("FIGURE_DESCRIBE_VLM_URL")
    if legacy_url:
        return [{
            "name": "legacy-single",
            "url": legacy_url,
            # 兼容旧脚本用的 ANGINEER_CHAT_API_KEY（均只读环境变量，不落任何硬编码密钥）
            "api_key": _env_str("FIGURE_DESCRIBE_VLM_API_KEY") or _env_str("ANGINEER_CHAT_API_KEY"),
            "model": _env_str("FIGURE_DESCRIBE_VLM_MODEL", "Qwen3.6-35B-A3B-FP8"),
        }]
    return []


def _mime_for(path: Path) -> str:
    suffix = path.suffix.lower()
    return "image/png" if suffix == ".png" else "image/jpeg"


def describe_image(image_path: Path, timeout: int = 120) -> str:
    """对单张图片调 VLM 生成描述。按 vlm_configs() 顺序逐个端点尝试，
    全部失败抛异常（聚合各端点错误），由调用方决定容错策略。"""
    configs = vlm_configs()
    if not configs:
        raise RuntimeError("未配置图描述 VLM 端点（FIGURE_DESCRIBE_CONFIGS）")
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    errors: List[str] = []
    for cfg in configs:
        payload = {
            "model": cfg["model"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{_mime_for(image_path)};base64,{b64}"}},
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
        }
        headers = {"Authorization": f"Bearer {cfg['api_key']}"} if cfg["api_key"] else {}
        try:
            resp = requests.post(cfg["url"], json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError(f"Unexpected chat response: {data}") from exc
            text = str(content or "").strip()
            if not text:
                raise RuntimeError(f"端点 {cfg['name']} 返回空描述")
            return text
        except Exception as exc:  # noqa: BLE001 —— 单端点失败换下一端点
            errors.append(f"{cfg['name']}: {type(exc).__name__}: {exc}")
            logger.warning("图描述端点 %s 失败，尝试下一端点: %s", cfg["name"], exc)
    raise RuntimeError("图描述全部端点失败: " + " | ".join(errors))


def figure_nodes(library_id: str, doc_id: str) -> List[Tuple[int, Dict[str, Any]]]:
    """返回 (行号, 节点) 列表：仅图表类型节点。"""
    graph_path = paths.get_graph_jsonl_path(library_id, doc_id)
    if not graph_path.exists():
        return []
    nodes: List[Tuple[int, Dict[str, Any]]] = []
    for line_no, line in enumerate(graph_path.read_text(encoding="utf-8").splitlines()):
        try:
            node = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(node.get("block_type") or "").strip() in FIGURE_TYPES:
            nodes.append((line_no, node))
    return nodes


def resolve_image_path(library_id: str, doc_id: str, image_path: str) -> Path:
    p = Path(str(image_path or ""))
    if not p.is_absolute():
        p = paths.get_parsed_dir(library_id, doc_id) / p
    return p


def describe_figures_in_graph(
    library_id: str,
    doc_id: str,
    *,
    on_node: Optional[Callable[[str, str, str], None]] = None,
    cancel_check: Optional[Callable[[], None]] = None,
    timeout: int = 120,
    retries: int = 1,
    max_workers: int = 4,
) -> Dict[str, int]:
    """为文档中缺失描述的图表块生成描述并写回 jsonl（断点续跑：跳过已有描述）。

    on_node(block_uid, status, detail)：单块进度回调（done/error/missing_image）。
    cancel_check：取消检查回调（每块处理前后调用，抛取消异常向上传播）。
    返回统计：total/described/already/missing_images/errors。
    全部待处理块均失败（且有待处理块）时抛 RuntimeError，供阶段标记 failed（soft）。
    """
    graph_path = paths.get_graph_jsonl_path(library_id, doc_id)
    lines = graph_path.read_text(encoding="utf-8").splitlines()
    targets: List[Tuple[int, Dict[str, Any]]] = []
    for line_no, node in figure_nodes(library_id, doc_id):
        if str(node.get("figure_description") or "").strip():
            continue
        targets.append((line_no, node))

    stats = {
        "total": len(targets),
        "described": 0,
        "already": sum(1 for _, n in figure_nodes(library_id, doc_id) if str(n.get("figure_description") or "").strip()),
        "missing_images": 0,
        "errors": 0,
    }
    if not targets:
        if on_node is not None:
            on_node("", "done", "无待描述图块")
        return stats

    def _emit(uid: str, status: str, detail: str) -> None:
        if on_node is not None:
            on_node(uid, status, detail)

    def _describe_one(block_uid: str, image_path: Path) -> Optional[str]:
        last_error = ""
        for attempt in range(max(1, retries + 1)):
            try:
                return describe_image(image_path, timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
        _emit(block_uid, "error", last_error)
        return None

    updated: Dict[str, str] = {}
    # 并发由调用方单点决定：阶段路径固定传 1，远端在飞请求数由 parse_pipeline 的图描述闸门控制；
    # 脚本/测试可自行放开。
    import concurrent.futures

    if max_workers > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {}
            for _, node in targets:
                uid = str(node.get("block_uid") or node.get("id") or "")
                image_path = str(node.get("image_path") or "").strip()
                if not image_path:
                    stats["missing_images"] += 1
                    continue
                resolved = resolve_image_path(library_id, doc_id, image_path)
                if not resolved.exists():
                    stats["missing_images"] += 1
                    _emit(uid, "missing_image", str(resolved))
                    continue
                futures[pool.submit(_describe_one, uid, resolved)] = uid
            for future in concurrent.futures.as_completed(futures):
                if cancel_check is not None:
                    cancel_check()
                uid = futures[future]
                description = future.result()
                if description:
                    updated[uid] = description
                    _emit(uid, "done", "")
    else:
        for _, node in targets:
            if cancel_check is not None:
                cancel_check()
            uid = str(node.get("block_uid") or node.get("id") or "")
            image_path = str(node.get("image_path") or "").strip()
            if not image_path:
                stats["missing_images"] += 1
                continue
            resolved = resolve_image_path(library_id, doc_id, image_path)
            if not resolved.exists():
                stats["missing_images"] += 1
                _emit(uid, "missing_image", str(resolved))
                continue
            description = _describe_one(uid, resolved)
            if description:
                updated[uid] = description
                _emit(uid, "done", "")

    stats["errors"] = stats["total"] - len(updated) - stats["missing_images"]
    if updated:
        changed = 0
        for line_no, line in enumerate(lines):
            try:
                node = json.loads(line)
            except json.JSONDecodeError:
                continue
            uid = str(node.get("block_uid") or node.get("id") or "")
            if uid in updated:
                node["figure_description"] = updated[uid]
                lines[line_no] = json.dumps(node, ensure_ascii=False)
                changed += 1
        if changed:
            graph_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    stats["described"] = len(updated)

    if stats["described"] == 0 and stats["total"] > 0 and stats["missing_images"] < stats["total"]:
        raise RuntimeError(
            f"图描述全部失败（total={stats['total']}, errors={stats['errors']}, "
            f"missing_images={stats['missing_images']}）"
        )
    return stats

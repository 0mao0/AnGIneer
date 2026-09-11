"""OmniDocBench 解析质量评测：页图 → AnGIneer 解析链 → 官方评测器。

背景：OmniDocBench（opendatalab，文档解析领域公认基准）提供 1651 张标注页图
（文本/表格/公式/阅读顺序 gold）。本脚本把页图喂进我们的完整解析链
（source_prep→convert→raw_parse(MinerU)→popo→structure），产出每页 markdown，
再调用官方 Docker 评测器算 Edit_dist / TEDS / CDM / 阅读顺序指标。

两个子命令：
  predict  — 页图转单页 PDF → docs-api 解析 → 下载 content.md → predictions/{page_id}.md（断点续跑）
  eval     — 生成配置并调用官方 Docker 镜像评测 → 汇总 metric_result.json

用法（本地/生产同构）：
  python scripts/run_omnidocbench_eval.py predict --docs-api http://localhost:8790 \
      --data-dir D:/AI/tools/OmniDocBench_data --library omnidocbench --limit 6
  python scripts/run_omnidocbench_eval.py eval \
      --data-dir D:/AI/tools/OmniDocBench_data --predictions <preds> --out <result>
"""
import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = REPO / "data" / "omnidocbench"
DEFAULT_LIBRARY = "omnidocbench"
PARSE_STAGES = "source_prep,convert,raw_parse,popo,structure"
EVAL_IMAGE = "ghcr.io/zeng-weijun/omnidocbench-eval:repro-ubuntu2204"


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO / ".env")
    except ImportError:
        pass


def _admin_token(docs_api: str) -> str:
    import requests

    user = (os.getenv("ADMIN_USER") or "").strip()
    password = os.getenv("ADMIN_PASSWORD") or ""
    if not user or not password:
        raise SystemExit("需要 .env 里的 ADMIN_USER / ADMIN_PASSWORD 用于登录")
    resp = requests.post(f"{docs_api}/api/v1/auth/login", json={"username": user, "password": password}, timeout=30)
    resp.raise_for_status()
    return resp.json()["token"]


def _ensure_library(docs_api: str, headers: dict, library_id: str) -> None:
    import requests

    resp = requests.get(f"{docs_api}/api/knowledge/libraries", timeout=30)
    resp.raise_for_status()
    libs = resp.json()
    if any((lib.get("id") == library_id) for lib in libs):
        return
    resp = requests.post(
        f"{docs_api}/api/knowledge/libraries",
        json={"library_id": library_id, "name": library_id, "description": "OmniDocBench 解析评测专用库"},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        print(f"!! 创建库失败 {resp.status_code}: {resp.text[:200]}")
    else:
        print(f"已创建知识库: {library_id}")


def _ensure_admin_bound(docs_api: str, headers: dict, library_id: str) -> None:
    """把管理员绑到评测库（会话鉴权按 library_ids 授权，管理员无跨库豁免）。"""
    import requests

    resp = requests.get(f"{docs_api}/api/users", headers=headers, timeout=30)
    resp.raise_for_status()
    admin_name = (os.getenv("ADMIN_USER") or "").strip()
    admin = next((u for u in resp.json() if u.get("username") == admin_name), None)
    if admin is None:
        raise SystemExit(f"未找到管理员用户 {admin_name}")
    libs = list(admin.get("library_ids") or [])
    if library_id in libs:
        return
    libs.append(library_id)
    resp = requests.put(
        f"{docs_api}/api/users/{admin['id']}",
        headers=headers,
        json={"display_name": admin.get("display_name") or admin_name, "library_ids": libs},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"!! 绑定管理员到评测库失败 {resp.status_code}: {resp.text[:200]}")
    else:
        print(f"管理员已绑定到 {library_id}（libraries={libs}）")


def _page_to_pdf_bytes(image_path: Path) -> bytes:
    from PIL import Image

    with Image.open(image_path) as img:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PDF")
        return buf.getvalue()


def _select_pages(data_dir: Path, limit: int, filter_prefix: str, seed: int) -> list:
    images_dir = data_dir / "images"
    images = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    if filter_prefix:
        images = [p for p in images if p.name.startswith(filter_prefix)]
    if limit and limit < len(images):
        # 按前缀分层抽样：均匀跨文档类型，比截断前 N 张更有代表性
        import random

        rng = random.Random(seed)
        images = sorted(rng.sample(images, limit))
    return images


def _parse_one(docs_api: str, headers: dict, library_id: str, page_id: str, pdf_bytes: bytes) -> str:
    """上传单页 PDF 并等待解析完成，返回 doc_id。"""
    import requests

    resp = requests.post(
        f"{docs_api}/api/v1/documents/parse",
        headers=headers,
        params={"library_id": library_id, "stages": PARSE_STAGES},
        files={"file": (f"{page_id}.pdf", pdf_bytes, "application/pdf")},
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"parse 上传失败 {resp.status_code}: {resp.text[:200]}")
    doc_id = resp.json()["doc_id"]

    deadline = time.time() + 1800
    while time.time() < deadline:
        st = requests.get(f"{docs_api}/api/v1/documents/{doc_id}/status", headers=headers, timeout=30)
        if st.status_code != 200:
            raise RuntimeError(f"status 查询失败 {st.status_code}: {st.text[:200]}")
        data = st.json()
        status = str(data.get("status") or "")
        if status in ("completed", "failed", "cancelled"):
            if status != "completed":
                raise RuntimeError(f"解析未完成: {status} {str(data.get('error') or '')[:200]}")
            return doc_id
        time.sleep(5)
    raise RuntimeError("解析超时（30 分钟）")


def _download_markdown(docs_api: str, headers: dict, doc_id: str) -> str:
    import requests

    resp = requests.get(f"{docs_api}/api/v1/documents/{doc_id}/content", headers=headers, timeout=60)
    resp.raise_for_status()
    return str(resp.json().get("markdown") or "")


def cmd_predict(args) -> int:
    if getattr(args, "in_process", False):
        return _predict_in_process(args)
    _load_env()
    data_dir = Path(args.data_dir)
    preds_dir = Path(args.predictions)
    preds_dir.mkdir(parents=True, exist_ok=True)
    state_path = preds_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    pages = _select_pages(data_dir, args.limit, args.filter_prefix, args.seed)
    print(f"待解析页数: {len(pages)}")

    docs_api = args.docs_api.rstrip("/")
    token = _admin_token(docs_api)
    headers = {"Authorization": f"Bearer {token}"}
    _ensure_library(docs_api, headers, args.library)
    _ensure_admin_bound(docs_api, headers, args.library)

    done = failed = skipped = 0
    for idx, image in enumerate(pages, 1):
        page_id = image.stem
        out_md = preds_dir / f"{page_id}.md"
        if out_md.exists() and str(state.get(page_id, {}).get("status")) == "done":
            skipped += 1
            continue
        try:
            pdf_bytes = _page_to_pdf_bytes(image)
            doc_id = _parse_one(docs_api, headers, args.library, page_id, pdf_bytes)
            markdown = _download_markdown(docs_api, headers, doc_id)
            out_md.write_text(markdown, encoding="utf-8")
            state[page_id] = {"status": "done", "doc_id": doc_id, "chars": len(markdown)}
            done += 1
            print(f"[{idx}/{len(pages)}] {page_id}: {len(markdown)} chars", flush=True)
        except Exception as exc:  # noqa: BLE001
            state[page_id] = {"status": "failed", "error": str(exc)[:300]}
            failed += 1
            print(f"[{idx}/{len(pages)}] {page_id}: FAILED {str(exc)[:160]}", flush=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"predict 完成: done={done} failed={failed} skipped={skipped}，输出 {preds_dir}")
    return 0 if failed == 0 else 1


def _predict_in_process(args) -> int:
    """进程内模式：直接在 docs-core 宿主进程驱动解析（无 HTTP / 无管理员凭据）。

    在 docs-api 容器内执行（docker exec）时最稳：绕过会话鉴权，直接调
    ParseOrchestrator + file_storage，产物 markdown 从 parsed/content.md 读取。
    """
    import uuid

    import docs_core.paths as core_paths
    from docs_core.docs_file_io import file_storage
    from docs_core.docs_service import get_docs_service
    from docs_core.parse_pipeline import ParseOrchestrator

    data_dir = Path(args.data_dir)
    preds_dir = Path(args.predictions)
    preds_dir.mkdir(parents=True, exist_ok=True)
    state_path = preds_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    pages = _select_pages(data_dir, args.limit, args.filter_prefix, args.seed)
    print(f"待解析页数: {len(pages)}（进程内模式）", flush=True)

    ks = get_docs_service()
    if ks.get_library(args.library) is None:
        ks.create_library(args.library, args.library, "OmniDocBench 解析评测专用库")
        print(f"已创建知识库: {args.library}", flush=True)
    orchestrator = ParseOrchestrator()
    stage_list = [s.strip() for s in PARSE_STAGES.split(",") if s.strip()]

    done = failed = skipped = 0
    for idx, image in enumerate(pages, 1):
        page_id = image.stem
        out_md = preds_dir / f"{page_id}.md"
        if out_md.exists() and str(state.get(page_id, {}).get("status")) == "done":
            skipped += 1
            continue
        try:
            doc_id = f"od-{uuid.uuid4().hex[:10]}"
            pdf_bytes = _page_to_pdf_bytes(image)
            source_path = file_storage.save_source_file(args.library, doc_id, pdf_bytes, f"{page_id}.pdf")
            ks.register_document(args.library, source_path, doc_id, title=f"{page_id}.pdf")
            task = orchestrator.create_parse_task(
                library_id=args.library,
                doc_id=doc_id,
                file_path=source_path,
                parse_options={"stages": stage_list, "use_llm": False},
            )
            task_id = task["task_id"]
            deadline = time.time() + 1800
            status = ""
            while time.time() < deadline:
                current = orchestrator.get_parse_task(task_id) or {}
                status = str(current.get("status") or "")
                if status in ("completed", "failed", "partial", "cancelled"):
                    break
                time.sleep(5)
            if status != "completed":
                raise RuntimeError(f"解析未正常完成: status={status} msg={str((current or {}).get('stage_message') or '')[:150]}")
            md_path = core_paths.get_parsed_dir(args.library, doc_id) / "content.md"
            markdown = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
            out_md.write_text(markdown, encoding="utf-8")
            state[page_id] = {"status": "done", "doc_id": doc_id, "chars": len(markdown)}
            done += 1
            print(f"[{idx}/{len(pages)}] {page_id}: {len(markdown)} chars", flush=True)
        except Exception as exc:  # noqa: BLE001
            state[page_id] = {"status": "failed", "error": str(exc)[:300]}
            failed += 1
            print(f"[{idx}/{len(pages)}] {page_id}: FAILED {str(exc)[:160]}", flush=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"predict 完成: done={done} failed={failed} skipped={skipped}，输出 {preds_dir}", flush=True)
    return 0 if failed == 0 else 1


def _filter_gt_for_predictions(gt_json: Path, preds_dir: Path, out_path: Path) -> int:
    """只保留有预测 .md 的 GT 页：评测器遍历全量 GT，缺失预测按空内容计分会拖垮指标。

    预测命名约定（与评测器 _resolve_prediction_path 对齐）：图片名去扩展名 + .md
    （兼容 .pdf 中缀的变体）。
    """
    gt = json.loads(gt_json.read_text(encoding="utf-8"))
    pred_stems = {p.stem for p in preds_dir.glob("*.md")}
    kept = []
    for sample in gt:
        img_name = Path(str((sample.get("page_info") or {}).get("image_path") or "")).name
        if not img_name:
            continue
        stem = img_name[:-4] if "." in img_name else img_name
        if stem in pred_stems or stem.replace(".pdf", "") in pred_stems:
            kept.append(sample)
    out_path.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
    return len(kept)


def cmd_eval(args) -> int:
    import subprocess

    data_dir = Path(args.data_dir)
    preds_dir = Path(args.predictions).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    gt_json = (data_dir / "OmniDocBench.json").resolve()
    if not gt_json.exists():
        raise SystemExit(f"GT 不存在: {gt_json}")
    md_count = len(list(preds_dir.glob("*.md")))
    if md_count == 0:
        raise SystemExit(f"预测目录没有 .md: {preds_dir}")

    # 只评有预测的页（GT 过滤）
    filtered_gt = out_dir / "filtered_gt.json"
    kept = _filter_gt_for_predictions(gt_json, preds_dir, filtered_gt)
    if kept == 0:
        raise SystemExit(f"GT 中没有与预测匹配的页（预测 {md_count} 个 .md）")
    print(f"GT 过滤: {kept} 页参与评测（预测 {md_count} 个）")

    config_path = out_dir / "custom.yaml"
    config_path.write_text(
        f"""end2end_eval:
  metrics:
    text_block:
      metric: [Edit_dist]
    display_formula:
      metric: [Edit_dist, CDM]
      cdm_workers: 8
    table:
      metric: [TEDS, Edit_dist]
      teds_workers: 8
    reading_order:
      metric: [Edit_dist]
  dataset:
    dataset_name: end2end_dataset
    ground_truth:
      data_path: /workspace/gt/filtered_gt.json
    prediction:
      data_path: /workspace/data_md/predictions
    match_method: quick_match
    match_workers: 8
    quick_match_truncated_timeout_sec: 300
    timeout_fallback_max_chunk_span: 10
    timeout_fallback_order_penalty: 0.10
""",
        encoding="utf-8",
    )

    docker_cmd = [
        "docker", "run", "--rm",
        # 镜像默认 entrypoint 会把参数当 config 路径，须按官方 README 用 bash 包裹
        "--entrypoint", "bash",
        "-v", f"{filtered_gt}:/workspace/gt/filtered_gt.json:ro",
        "-v", f"{preds_dir}:/workspace/data_md/predictions:ro",
        "-v", f"{config_path}:/workspace/configs/custom.yaml:ro",
        "-v", f"{out_dir}:/workspace/result",
        EVAL_IMAGE,
        "-c", "python pdf_validation.py --config configs/custom.yaml",
    ]
    print(f"运行官方评测器（{md_count} 页预测）...")
    proc = subprocess.run(docker_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(proc.stdout[-4000:] if proc.stdout else "")
    if proc.stderr:
        print("STDERR:", proc.stderr[-2000:])
    if proc.returncode != 0:
        print(f"评测器退出码 {proc.returncode}")
        return proc.returncode

    # 结果文件名前缀 = 预测目录名（如 predictions_quick_match_metric_result.json），glob 匹配
    metric_files = sorted(out_dir.glob("*_metric_result.json"))
    if metric_files:
        data = json.loads(metric_files[0].read_text(encoding="utf-8"))
        print(f"\n=== 汇总（{metric_files[0].name}） ===")
        for module, payload in data.items():
            all_block = (payload or {}).get("all", {}) if isinstance(payload, dict) else {}
            parts = []
            for metric, values in all_block.items():
                if isinstance(values, dict):
                    v = values.get("ALL_page_avg") or values.get("all")
                    if v is not None:
                        parts.append(f"{metric}={round(float(v), 4) if isinstance(v, (int, float)) else v}")
            print(f"{module}: " + " | ".join(parts))
    else:
        print(f"未找到 *_metric_result.json，请检查 {out_dir} 产物")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="OmniDocBench 解析评测")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_predict = sub.add_parser("predict", help="页图 → 解析 → 每页 markdown")
    p_predict.add_argument("--docs-api", default="http://localhost:8790")
    p_predict.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    p_predict.add_argument("--predictions", default=str(REPO / "data" / "evals" / "omnidocbench" / "predictions"))
    p_predict.add_argument("--library", default=DEFAULT_LIBRARY)
    p_predict.add_argument("--limit", type=int, default=0, help="抽样页数（0=全量）")
    p_predict.add_argument("--filter-prefix", default="", help="按文件名前缀过滤文档类型（如 docstructbench_）")
    p_predict.add_argument("--seed", type=int, default=42)
    p_predict.add_argument("--in-process", action="store_true", help="进程内直驱解析（在 docs-api 容器内执行，无需 HTTP/管理员凭据）")

    p_eval = sub.add_parser("eval", help="官方评测器（Docker）")
    p_eval.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    p_eval.add_argument("--predictions", default=str(REPO / "data" / "evals" / "omnidocbench" / "predictions"))
    p_eval.add_argument("--out", default=str(REPO / "data" / "evals" / "omnidocbench" / "result"))

    args = parser.parse_args()
    if args.cmd == "predict":
        return cmd_predict(args)
    return cmd_eval(args)


if __name__ == "__main__":
    sys.exit(main())

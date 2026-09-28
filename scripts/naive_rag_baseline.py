"""臂 2 朴素 RAG 基线：官方题集上的通用配方对照（预注册见 docs/plan-rag-baseline-arms.md）。

配方（预注册，不逐题调优）：PyMuPDF 全文抽取 → 1800 字符/150 重叠段落级切片 →
EMBEDDING_CONFIGS 首项嵌入 → 余弦 top-5 → LLM_CONFIGS 首项直答（temperature=0）→
evaluate_via_deepeval 同引擎判分。语料 = 服务器活库 lib-b07ed174 的 182 篇
（server_b07_pdfmap.json），本地 PDF 零缺口。

用法（仓库根目录）：
  python scripts/naive_rag_baseline.py build              # 抽取+切片+嵌入（可重入，按清单幂等）
  python scripts/naive_rag_baseline.py run --limit 100    # 检索+生成（断点续跑）
  python scripts/naive_rag_baseline.py run                # 全量 1040
  python scripts/naive_rag_baseline.py judge              # 同引擎判分（断点续跑）
  python scripts/naive_rag_baseline.py report             # 汇总 summary.md
"""
import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ARM_DIR = REPO / "data" / "evals" / "baseline_arms" / "arm2_naive"
DATASET = REPO / "data" / "evals" / "datasets" / "open-ragbench-subset-v4.json"
QRELS = REPO / "data" / "open_ragbench" / "raw" / "qrels.json"
PDF_MAP = REPO / "data" / "evals" / "baseline_arms" / "server_b07_pdfmap.json"
PDF_DIR = REPO / "data" / "open_ragbench" / "pdfs"

CHUNK_CHARS = 1800
CHUNK_OVERLAP = 150
TOP_K = 5
EMBED_BATCH = 32
RUN_CONCURRENCY = 6
JUDGE_CONCURRENCY = 10
GENERATOR_TEMPERATURE = 0.0
GENERATOR_LABEL = ""  # 臂 3 复用本脚本的 report 时覆盖为实际模型名
REPORT_TITLE = "臂 2 朴素 RAG 结果（口径见 docs/plan-rag-baseline-arms.md）"  # 臂 3 覆盖为自身标题
ARXIV_TAG = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")

for _src in ("services/evals-core/src", "services/docs-core/src"):
    sys.path.insert(0, str(REPO / _src))

_PROMPT = (
    "Answer the question using only the provided passages.\n\n"
    "Passages:\n{passages}\n\n"
    "Question: {question}\n\n"
    "If the passages do not contain enough information to answer, say so briefly."
)


def load_env() -> None:
    env_path = REPO / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def load_llm_config() -> dict:
    entries = json.loads(os.environ.get("LLM_CONFIGS", "[]"))
    if not entries:
        raise SystemExit("LLM_CONFIGS 未配置")
    return entries[0]


def chunk_text(text: str) -> list:
    """段落边界优先的固定长度切片（预注册：1800/150）。"""
    chunks: list = []
    buffer = ""

    def flush():
        nonlocal buffer
        if buffer.strip():
            chunks.append(buffer.strip())
        buffer = buffer[-CHUNK_OVERLAP:] if buffer else ""

    for para in text.split("\n"):
        para = para.rstrip()
        if len(buffer) + len(para) + 1 <= CHUNK_CHARS:
            buffer = f"{buffer}\n{para}" if buffer else para
            continue
        while len(para) > CHUNK_CHARS:          # 超长段落硬切
            flush()
            buffer = para[:CHUNK_CHARS]
            para = para[CHUNK_CHARS - CHUNK_OVERLAP:]
        else:
            flush()
            buffer = para
    flush()
    return chunks


def cmd_build() -> int:
    import fitz

    out_chunks = ARM_DIR / "chunks.jsonl"
    out_emb = ARM_DIR / "embeddings.npy"
    if out_chunks.is_file() and out_emb.is_file():
        print("索引已存在（幂等跳过）；重建请先删除 chunks.jsonl / embeddings.npy")
        return 0

    pdf_map = json.loads(PDF_MAP.read_text(encoding="utf-8"))
    stems = sorted({v["pdf"][:-4] for v in pdf_map.values() if v.get("pdf")})
    print(f"语料 {len(stems)} 篇（服务器活库清单），开始抽取与切片…")

    from docs_core.step06_vectors.embedding_provider import create_default_embedding_provider
    from docs_core.step06_vectors.embedding_provider import HashEmbeddingProvider

    provider = create_default_embedding_provider()
    if isinstance(provider, HashEmbeddingProvider):
        raise SystemExit("嵌入 provider 退化为 hash——检查 EMBEDDING_CONFIGS")

    rows: list = []
    for i, stem in enumerate(stems):
        doc = fitz.open(str(PDF_DIR / f"{stem}.pdf"))
        full_text = "\n".join(page.get_text() for page in doc)
        doc.close()
        for chunk in chunk_text(full_text):
            rows.append({"chunk_id": f"{stem}:{len(rows)}", "doc": stem, "text": chunk})
        if (i + 1) % 40 == 0:
            print(f"  已抽取 {i + 1}/{len(stems)} 篇，切片 {len(rows)}")
    print(f"切片完成：{len(rows)} 块，开始嵌入（batch={EMBED_BATCH}）…")

    vectors = []
    for start in range(0, len(rows), EMBED_BATCH):
        batch = [r["text"] for r in rows[start:start + EMBED_BATCH]]
        vecs = provider.embed_texts(batch)
        if any(not v for v in vecs):
            raise SystemExit(f"嵌入返回空向量 batch@{start}")
        vectors.extend(vecs)
        if (start // EMBED_BATCH) % 20 == 0:
            print(f"  已嵌入 {start + len(batch)}/{len(rows)}")
    dim = len(vectors[0])
    if dim <= 512:
        raise SystemExit(f"嵌入维度异常（dim={dim}），疑似 hash 档")

    import numpy as np

    np.save(out_emb, np.asarray(vectors, dtype=np.float32))
    with out_chunks.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (ARM_DIR / "index_meta.json").write_text(json.dumps(
        {"docs": len(stems), "chunks": len(rows), "dim": dim,
         "chunk_chars": CHUNK_CHARS, "overlap": CHUNK_OVERLAP, "top_k": TOP_K,
         "embedder": os.environ.get("EMBEDDING_CONFIGS", "")[:120]}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"索引完成：{len(rows)} 块 / dim={dim} → {out_chunks.parent}")
    return 0


def _retrieve(query_vec, chunk_vecs):
    import numpy as np

    q = np.asarray(query_vec, dtype=np.float32)
    mat = np.asarray(chunk_vecs, dtype=np.float32)
    denom = (np.linalg.norm(q) * np.linalg.norm(mat, axis=1)) + 1e-9
    sims = (mat @ q) / denom
    top = np.argsort(-sims)[:TOP_K]
    return [(int(i), float(sims[i])) for i in top]


def _answer_once(llm: dict, question: str, passages: list) -> str:
    import requests

    body = {
        "model": llm["model"],
        "messages": [{"role": "user", "content": _PROMPT.format(
            passages="\n\n".join(f"[{i + 1}] {t}" for i, t in enumerate(passages)),
            question=question)}],
        "temperature": GENERATOR_TEMPERATURE,
        "max_tokens": 1024,
    }
    url = llm["base_url"].rstrip("/") + "/chat/completions"
    last_error = None
    for attempt in range(3):
        try:
            resp = requests.post(url, json=body, timeout=180,
                                 headers={"Authorization": f"Bearer {llm['api_key']}"})
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"生成失败 {question[:40]}: {last_error}")


def cmd_run(limit: int) -> int:
    items = json.loads(DATASET.read_text(encoding="utf-8"))["items"]
    qrels = json.loads(QRELS.read_text(encoding="utf-8"))
    chunks = [json.loads(line) for line in (ARM_DIR / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    import numpy as np

    vecs = np.load(ARM_DIR / "embeddings.npy")
    out_path = ARM_DIR / "predictions.jsonl"
    done = set()
    if out_path.is_file():
        done = {json.loads(line)["question_id"] for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()}
    todo = [x for x in items if x["question_id"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"待答 {len(todo)}/{len(items)}（已完成 {len(done)}）")

    from docs_core.step06_vectors.embedding_provider import create_default_embedding_provider

    provider = create_default_embedding_provider()
    llm = load_llm_config()
    lock = threading.Lock()
    out_fh = out_path.open("a", encoding="utf-8")
    counter = {"n": 0}

    def work(item: dict):
        qvec = provider.embed_texts([item["question"]])[0]
        top = _retrieve(qvec, vecs)
        passages = [chunks[i]["text"] for i, _ in top]
        answer = _answer_once(llm, item["question"], passages)
        record = {
            "question_id": item["question_id"],
            "question": item["question"],
            "answer": answer,
            "gold_answer": item["answer"]["gold_answer"],
            "checks": item["answer"].get("correctness_checks") or [],
            "is_refusal_expected": "refusal" in (item.get("tags") or []),
            "gold_doc": qrels.get(item["question_id"], {}).get("doc_id")
            or next((t for t in (item.get("tags") or []) if ARXIV_TAG.fullmatch(t)), None),
            "retrieved_docs": list(dict.fromkeys(chunks[i]["doc"] for i, _ in top)),
            "retrieved_items": [{"text": chunks[i]["text"]} for i, _ in top],
        }
        with lock:
            out_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_fh.flush()
            counter["n"] += 1
            if counter["n"] % 25 == 0:
                print(f"  已答 {counter['n']}/{len(todo)}")

    with ThreadPoolExecutor(max_workers=RUN_CONCURRENCY) as pool:
        futures = [pool.submit(work, item) for item in todo]
        errors = []
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
    out_fh.close()
    if errors:
        print(f"!! {len(errors)} 题失败（重跑同一命令可断点续跑）：{errors[:3]}")
        return 1
    print(f"完成：{out_path}")
    return 0


def cmd_judge(limit: int = 0) -> int:
    sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))
    from evals_core.runner.judge_deepeval import evaluate_via_deepeval

    predictions = [json.loads(line) for line in (ARM_DIR / "predictions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    out_path = ARM_DIR / "judge_results.jsonl"
    done = set()
    if out_path.is_file():
        done = {json.loads(line)["question_id"] for line in out_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line).get("judge_used")}  # 判分失败（judge_used=None）不算完成，重跑时重判
    todo = [p for p in predictions if p["question_id"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"待判 {len(todo)}/{len(predictions)}")
    lock = threading.Lock()
    out_fh = out_path.open("a", encoding="utf-8")
    counter = {"n": 0}

    def work(pred: dict):
        checks = pred.get("checks") or []
        if isinstance(checks, str):
            checks = json.loads(checks or "[]")
        result = evaluate_via_deepeval(
            question=pred["question"], answer=pred["answer"],
            gold_answer=pred["gold_answer"], checks=checks,
            prediction={"retrieved_items": pred.get("retrieved_items") or []})
        record = {"question_id": pred["question_id"],
                  "semantic_passed": result.get("semantic_passed"),
                  "semantic_score": result.get("semantic_score"),
                  "judge_used": result.get("judge_used"),
                  "semantic_fallback": result.get("semantic_fallback")}
        with lock:
            out_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_fh.flush()
            counter["n"] += 1
            if counter["n"] % 25 == 0:
                print(f"  已判 {counter['n']}/{len(todo)}")

    with ThreadPoolExecutor(max_workers=JUDGE_CONCURRENCY) as pool:
        futures = [pool.submit(work, p) for p in todo]
        errors = []
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
    out_fh.close()
    if errors:
        print(f"!! {len(errors)} 题判分失败（重跑可续）：{errors[:3]}")
        return 1
    print(f"判分完成：{out_path}")
    return 0


def cmd_report() -> int:
    sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))
    from evals_core.runner.answer_eval import is_refusal

    preds = {json.loads(line)["question_id"]: json.loads(line)
             for line in (ARM_DIR / "predictions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    judges = {json.loads(line)["question_id"]: json.loads(line)
              for line in (ARM_DIR / "judge_results.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    rows = []
    for qid, pred in preds.items():
        judge = judges.get(qid)
        if not judge or judge.get("semantic_passed") is None:
            continue
        rows.append({**pred, "passed": bool(judge["semantic_passed"]),
                     "fallback": bool(judge.get("semantic_fallback"))})
    answerable = [r for r in rows if not r["is_refusal_expected"]]
    refusal = [r for r in rows if r["is_refusal_expected"]]
    failed = [j for j in judges.values() if not j.get("judge_used")]  # judge 调用整体失败（2026-09-26 教训：84% 失败曾静默缩分母）
    hit = sum(1 for r in rows if r["gold_doc"] and r["gold_doc"] in (r["retrieved_docs"] or []))
    hit_den = sum(1 for r in rows if r["gold_doc"])
    hard = sum(1 for r in refusal if not is_refusal(r["answer"]))

    def pct(n: int, d: int) -> str:
        return f"{n / d * 100:.1f}% ({n}/{d})" if d else "n/a"

    lines = [
        f"# {REPORT_TITLE}", "",
        f"- 可答题正确率（主对比，vs 全链 88.6%）：**{pct(sum(r['passed'] for r in answerable), len(answerable))}**",
        f"- 整体正确率（vs 全链 84.9%）：{pct(sum(r['passed'] for r in rows), len(rows))}",
        f"- 检索 hit@5 doc 级（vs 全链 96.5%）：{pct(hit, hit_den)}",
        f"- 拒答题硬答率（39 题无答案，预期接近 100%）：{pct(hard, len(refusal))}",
        f"- 判分兜底（关键词断言）占比：{pct(sum(1 for r in rows if r['fallback']), len(rows))}",
        f"- **判分失败：{len(failed)} 题**" + ("　⚠ 超过 5%，正确率不可用——用同命令重跑 judge 补判" if len(failed) > 0.05 * len(judges) else ""),
        f"- 样本：判分成功 {len(rows)} / 失败 {len(failed)} / 预测 {len(preds)} / 题集 1040", "",
        f"（生成 {GENERATOR_LABEL or load_llm_config()['model']} · temperature={GENERATOR_TEMPERATURE} · 判分=nightly 同引擎同默认链 · EVAL_DEEPVAL_EXTRA=0）",
    ]
    summary = "\n".join(lines) + "\n"
    (ARM_DIR / "summary.md").write_text(summary, encoding="utf-8")
    print(summary)
    return 0


FULL_CHAIN = {  # 臂 1 全链（2026-09-24 v4 nightly 门禁基线，docs/plan-rag-baseline-arms.md）
    "answerable": 88.6, "overall": 84.9, "hit5": 96.5,
}


def cmd_chart() -> int:
    """臂 2 vs 臂 1 同尺对比图（README 回答成绩小节用）。数值取自 summary 与 v4 基线。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    preds = {json.loads(line)["question_id"]: json.loads(line)
             for line in (ARM_DIR / "predictions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    judges = {json.loads(line)["question_id"]: json.loads(line)
              for line in (ARM_DIR / "judge_results.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    answerable_passed = answerable_n = 0
    overall_passed = overall_n = 0
    hit = hit_n = 0
    for qid, pred in preds.items():
        judge = judges.get(qid)
        if not judge or judge.get("semantic_passed") is None:
            continue
        passed = bool(judge["semantic_passed"])
        overall_n += 1
        overall_passed += passed
        if not pred["is_refusal_expected"]:
            answerable_n += 1
            answerable_passed += passed
        if pred["gold_doc"]:
            hit_n += 1
            hit += pred["gold_doc"] in (pred["retrieved_docs"] or [])
    naive = {"answerable": answerable_passed / answerable_n * 100, "overall": overall_passed / overall_n * 100,
             "hit5": hit / hit_n * 100}

    metrics = [("可答题正确率\n(1001 题)", "answerable"), ("整体正确率\n(1040 题)", "overall"),
               ("检索 hit@5\n(doc 级)", "hit5")]
    fig, ax = plt.subplots(figsize=(10.5, 5.8), dpi=100)
    width = 0.36
    # 对比图配色定版（2026-09-28）：AnGIneer 紫（logo 色系）恒在每组第一位，其余浅蓝/浅绿
    for i, (vals, label, face, hatch) in enumerate((
            (FULL_CHAIN, "AnGIneer 全链", "#8b5cf6", None),
            (naive, "朴素 RAG（通用配方）", "#9dc3e6", None),
    )):
        pos = [x + (i - 0.5) * width for x in range(len(metrics))]
        bars = ax.bar(pos, [vals[k] for _, k in metrics], width=width, label=label, zorder=3,
                      color=face)
        for rect, (_, k) in zip(bars, metrics):
            ax.annotate(f"{vals[k]:.1f}%", (rect.get_x() + rect.get_width() / 2, vals[k]),
                        ha="center", va="bottom", fontsize=10.5, fontweight="bold")
    ax.set_xticks(range(len(metrics)))
    ax.set_xticklabels([m[0] for m in metrics], fontsize=11)
    ax.set_ylim(0, 105)
    ax.set_ylabel("%（越高越好）", fontsize=11)
    ax.set_title("同 1040 题 · 同语料库 · 同判分引擎：通用配方 vs AnGIneer 全链", fontsize=12.5)
    ax.legend(loc="lower right", frameon=False, fontsize=10)
    ax.grid(axis="y", alpha=0.25, zorder=0)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    out = REPO / "docs" / "images" / "naive-rag-compare.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    print(f"图已生成 → {out}")
    print(f"  朴素 RAG: 可答 {naive['answerable']:.1f} / 整体 {naive['overall']:.1f} / hit@5 {naive['hit5']:.1f}")
    print(f"  全链:     可答 {FULL_CHAIN['answerable']} / 整体 {FULL_CHAIN['overall']} / hit@5 {FULL_CHAIN['hit5']}")
    return 0


def main() -> int:
    load_env()
    ARM_DIR.mkdir(parents=True, exist_ok=True)
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    p_run = sub.add_parser("run")
    p_run.add_argument("--limit", type=int, default=0, help="只答前 N 题未完成题（试点用）")
    p_judge = sub.add_parser("judge")
    p_judge.add_argument("--limit", type=int, default=0, help="只判前 N 题待判题（与生成并行的分批用）")
    sub.add_parser("report")
    sub.add_parser("chart")
    args = ap.parse_args()
    if args.cmd == "run":
        return cmd_run(args.limit)
    if args.cmd == "judge":
        return cmd_judge(args.limit)
    if args.cmd == "chart":
        return cmd_chart()
    return cmd_report()


if __name__ == "__main__":
    sys.exit(main())

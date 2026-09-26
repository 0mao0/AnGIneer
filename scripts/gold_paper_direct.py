"""臂 3 金开卷直读：把每题对应的官方论文全文直接喂给 LLM，不经任何 RAG。

口径（预注册见 docs/plan-rag-baseline-arms.md「臂 3」段）：
- 语料 = qrels 指定的该题 gold 论文**原始 PDF**（PyMuPDF 抽文本，不经我们的解析管线）；
- 每题一次调用，附全文（超长按 MAX_PAPER_CHARS 截断并记 truncated 标记）；
- 生成模型可配置（--config-name 取 LLM_CONFIGS 中的 name，默认 Qwen3.8-Flash-Next）；
- 逐题记录 usage（prompt/completion tokens）→ 汇总 tokens.json，供顶级模型费用外推；
- 判分/报告复用 naive_rag_baseline 的同引擎实现（同一 rubric/阈值）。

用法（仓库根目录）：
  python scripts/gold_paper_direct.py run --limit 20 --concurrency 2   # 试点
  python scripts/gold_paper_direct.py run --concurrency 2              # 全量（低并发避 nightly）
  python scripts/gold_paper_direct.py stats                            # token 用量与论文覆盖
  EVAL_DEEPVAL_EXTRA=0 python scripts/gold_paper_direct.py judge
  EVAL_DEEPVAL_EXTRA=0 python scripts/gold_paper_direct.py report
"""
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import naive_rag_baseline as naive
from naive_rag_baseline import ARXIV_TAG, DATASET, QRELS, PDF_DIR, load_env, load_llm_config

REPO = naive.REPO
ARM_DIR = REPO / "data" / "evals" / "baseline_arms" / "arm3_gold_pdf"
TXT_CACHE = ARM_DIR / "paper_text"
MAX_PAPER_CHARS = 160_000     # 单篇上限（约 40k tokens）；超出截前 N 字符并记 truncated
DEFAULT_CONFIG_NAME = "Qwen3.8-Flash-Next"

_PROMPT = (
    "You are given the full text of a research paper.\n\n"
    "Paper:\n{paper}\n\n"
    "Question: {question}\n\n"
    "Answer the question based only on this paper. "
    "If the paper does not contain enough information to answer, say so briefly."
)


def find_llm(config_name: str) -> dict:
    entries = json.loads(os.environ.get("LLM_CONFIGS", "[]"))
    for entry in entries:
        if str(entry.get("name")) == config_name:
            return entry
    raise SystemExit(f"LLM_CONFIGS 中找不到配置 {config_name!r}（可选：{[e.get('name') for e in entries]}）")


def paper_text(stem: str) -> tuple:
    """返回 (文本, 是否截断)；按论文缓存到 paper_text/<stem>.txt。"""
    TXT_CACHE.mkdir(parents=True, exist_ok=True)
    cached = TXT_CACHE / f"{stem}.txt"
    if not cached.is_file():
        import fitz

        doc = fitz.open(str(PDF_DIR / f"{stem}.pdf"))
        cached.write_text("\n".join(page.get_text() for page in doc), encoding="utf-8")
        doc.close()
    text = cached.read_text(encoding="utf-8")
    if len(text) > MAX_PAPER_CHARS:
        return text[:MAX_PAPER_CHARS], True
    return text, False


def _call(llm: dict, question: str, paper: str) -> tuple:
    import requests

    body = {
        "model": llm["model"],
        "messages": [{"role": "user", "content": _PROMPT.format(paper=paper, question=question)}],
        "temperature": naive.GENERATOR_TEMPERATURE,
        "max_tokens": 1024,
    }
    url = llm["base_url"].rstrip("/") + "/chat/completions"
    last_error = None
    for attempt in range(3):
        try:
            resp = requests.post(url, json=body, timeout=600,
                                 headers={"Authorization": f"Bearer {llm['api_key']}"})
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage") or {}
            return data["choices"][0]["message"]["content"], {
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
            }
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"生成失败 {question[:40]}: {last_error}")


def cmd_run(limit: int, concurrency: int, config_name: str, offset: int) -> int:
    items = json.loads(DATASET.read_text(encoding="utf-8"))["items"]
    if offset:
        items = items[offset:]
    qrels = json.loads(QRELS.read_text(encoding="utf-8"))
    llm = find_llm(config_name)
    out_path = ARM_DIR / "predictions.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.is_file():
        done = {json.loads(line)["question_id"] for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()}
    todo = [x for x in items if x["question_id"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"臂3 直读：待答 {len(todo)}（已完成 {len(done)}）· 模型 {llm['model']} · 并发 {concurrency}")

    lock = threading.Lock()
    out_fh = out_path.open("a", encoding="utf-8")
    tokens = {"prompt": 0, "completion": 0, "calls": 0}
    counter = {"n": 0, "missing": 0, "truncated": 0}

    def work(item: dict):
        gold_doc = qrels.get(item["question_id"], {}).get("doc_id") \
            or next((t for t in (item.get("tags") or []) if ARXIV_TAG.fullmatch(t)), None)
        has_pdf = bool(gold_doc) and (PDF_DIR / f"{gold_doc}.pdf").is_file()
        if has_pdf:
            paper, truncated = paper_text(gold_doc)
        else:
            paper, truncated = "(no paper provided)", False
        answer, usage = _call(llm, item["question"], paper)
        record = {
            "question_id": item["question_id"],
            "question": item["question"],
            "answer": answer,
            "gold_answer": item["answer"]["gold_answer"],
            "checks": item["answer"].get("correctness_checks") or [],
            "is_refusal_expected": "refusal" in (item.get("tags") or []),
            "gold_doc": gold_doc,
            "paper_provided": has_pdf,
            "paper_truncated": truncated,
            "paper_chars": len(paper),
            "retrieved_docs": [gold_doc] if has_pdf else [],
            "retrieved_items": [{"text": paper[:1000]}] if has_pdf else [],
            "usage": usage,
        }
        with lock:
            out_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_fh.flush()
            tokens["prompt"] += usage["prompt_tokens"]
            tokens["completion"] += usage["completion_tokens"]
            tokens["calls"] += 1
            if not has_pdf:
                counter["missing"] += 1
            if truncated:
                counter["truncated"] += 1
            counter["n"] += 1
            if counter["n"] % 10 == 0:
                print(f"  已答 {counter['n']}/{len(todo)}（缺论文 {counter['missing']} · 截断 {counter['truncated']}）")
            (ARM_DIR / "tokens.json").write_text(json.dumps(tokens, ensure_ascii=False, indent=1), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(work, item) for item in todo]
        errors = []
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
    out_fh.close()
    if errors:
        print(f"!! {len(errors)} 题失败（重跑同命令可续）：{errors[:3]}")
        return 1
    print(f"完成：{out_path}（本轮 {tokens['calls']} 次调用，prompt {tokens['prompt']} / completion {tokens['completion']} tokens）")
    return 0


def cmd_stats() -> int:
    rows = [json.loads(line) for line in (ARM_DIR / "predictions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    prompt = sum((r.get("usage") or {}).get("prompt_tokens", 0) for r in rows)
    completion = sum((r.get("usage") or {}).get("completion_tokens", 0) for r in rows)
    missing = sum(1 for r in rows if not r.get("paper_provided"))
    truncated = sum(1 for r in rows if r.get("paper_truncated"))
    n = len(rows)
    per_q = (prompt / n) if n else 0
    per_out = (completion / n) if n else 0
    print(f"样本 {n} 题 | prompt token 合计 {prompt:,}（均 {per_q:,.0f}/题）| completion {completion:,}（均 {per_out:,.0f}/题）| 缺论文 {missing} | 截断 {truncated}")
    if per_q:
        print("\n顶级模型费用外推（全量 1001 可答题，输入用本臂实测均值、输出用实测均值）：")
        for name, in_price, out_price in (("Gemini 2.5 Pro", 1.25, 10.0), ("GPT-4.1", 2.0, 8.0), ("Claude Sonnet", 3.0, 15.0)):
            cost = 1001 * per_q / 1e6 * in_price + 1001 * per_out / 1e6 * out_price
            print(f"  {name}: ≈ ${cost:,.0f}（输入 {in_price}/M × {per_q:,.0f} tok/题；输出 {out_price}/M × {per_out:,.0f} tok/题）")
    return 0


def cmd_judge(limit: int, concurrency: int) -> int:
    naive.ARM_DIR = ARM_DIR  # 复用臂 2 的判分/报告实现，仅换目录
    naive.JUDGE_CONCURRENCY = concurrency  # 低并发避 nightly 窗口（臂 2 默认 10 只适用于离线时段）
    return naive.cmd_judge(limit)


def cmd_report() -> int:
    naive.ARM_DIR = ARM_DIR
    naive.GENERATOR_LABEL = f"{DEFAULT_CONFIG_NAME}（网关，非顶级模型；口径降级声明见预注册）"
    return naive.cmd_report()


def cmd_chart() -> int:
    naive.ARM_DIR = ARM_DIR
    return naive.cmd_chart()


def main() -> int:
    load_env()
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--limit", type=int, default=0)
    p_run.add_argument("--offset", type=int, default=0)
    p_run.add_argument("--concurrency", type=int, default=2, help="低并发避 nightly（默认 2）")
    p_run.add_argument("--config-name", default=DEFAULT_CONFIG_NAME)
    sub.add_parser("stats")
    p_judge = sub.add_parser("judge")
    p_judge.add_argument("--limit", type=int, default=0)
    p_judge.add_argument("--concurrency", type=int, default=2, help="低并发避 nightly（默认 2）")
    sub.add_parser("report")
    sub.add_parser("chart")
    args = ap.parse_args()
    if args.cmd == "run":
        return cmd_run(args.limit, args.concurrency, args.config_name, args.offset)
    if args.cmd == "judge":
        return cmd_judge(args.limit, args.concurrency)
    if args.cmd == "report":
        return cmd_report()
    if args.cmd == "chart":
        return cmd_chart()
    return cmd_stats()


if __name__ == "__main__":
    sys.exit(main())

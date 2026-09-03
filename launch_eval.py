"""LawBench v1 评测启动器：NVFP4 模型（tailscale 直连 spark-4c47，绕开慢 Nginx）。
用法: python launch_eval.py [question_id]   # 省略 = 全量 500 题
"""
import os, sys, time, json, datetime

# ---- tailscale 直连覆盖（在 import ai_inference 之前设置，load_dotenv 不覆盖已有 env）----
TOKEN = "a5308358ca209309bbc722214e1e58ddaf9666a85eeca4b1"
os.environ["LLM_CONFIGS"] = json.dumps([{
    "name": "Qwen3.6-35B-A3B", "model": "qwen3.6-35b", "api_key": TOKEN,
    "base_url": "http://spark-4c47:8000/v1", "priority": 10,
}], ensure_ascii=False)
os.environ["DOCS_EMBEDDING_API_URL"] = "http://spark-4c47:8004/v1"
os.environ["DOCS_EMBEDDING_API_KEY"] = TOKEN
os.environ["DOCS_RERANKER_API_URL"] = "http://spark-4c47:8005/rerank"
os.environ["DOCS_RERANKER_API_KEY"] = TOKEN

ROOT = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))  # launch_eval.py 位于 AnGIneer 根目录
os.chdir(ROOT)
print(f"[launcher] ROOT={ROOT}", flush=True)

SERVICES = os.path.join(ROOT, 'services')
for pkg in ("ai-inference", "angineer-core", "sop-core", "docs-core",
            "geo-core", "engtools", "evals-core", "tree-core"):
    sys.path.insert(0, os.path.join(SERVICES, pkg, 'src'))

os.environ.setdefault("EVAL_CONCURRENCY", "3")
# argv: [dataset_id] [question_id] [resume_run_id]
DATASET = sys.argv[1] if len(sys.argv) > 1 else "lawbench-1-1-v1"
QUESTION = sys.argv[2] if len(sys.argv) > 2 else None
if QUESTION in ("-", "ALL", ""):
    QUESTION = None
RESUME = sys.argv[3] if len(sys.argv) > 3 else None
print(f"[launcher] dataset={DATASET} question={QUESTION or 'ALL'} resume={RESUME or '-'}", flush=True)

from evals_core.runner.suite_runner import start_eval_run, get_eval_run

run = start_eval_run(
    dataset_id=DATASET,
    question_id=QUESTION,
    save=True,
    override_doc_ids=None,
    resume_run_id=RESUME,
    config_name="Qwen3.6-35B-A3B",
)
run_id = run.get("run_id")
print(f"[launcher] run_id={run_id} status={run.get('status')}", flush=True)

last = None
while True:
    time.sleep(15)
    try:
        st = get_eval_run(run_id, light=True)
    except Exception as e:
        print(f"[launcher] poll err: {e}", flush=True)
        continue
    status = st.get("status")
    done = st.get("completed_questions")
    total = st.get("total_questions")
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {status} {done}/{total}"
    if line != last:
        print(line, flush=True)
        last = line
    if status in ("completed", "failed", "cancelled"):
        break

st = get_eval_run(run_id, light=False)
summary = st.get("summary_scores") or {}
print("[launcher] FINAL:", json.dumps(summary, ensure_ascii=False), flush=True)
print("[launcher] DONE", flush=True)

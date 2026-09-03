"""open-ragbench v2 评测完成监控：完成后写结果文件 + 退出。"""
import sqlite3, json, time, datetime, os

DB = r'D:\AI\AnGIneer\data\evals\evals.sqlite'
OUT = r'D:\AI\AnGIneer\logs\orbench_v2_FINAL.json'

def get_run():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT run_id, status, total_questions FROM eval_run WHERE dataset_id='open-ragbench-subset-v2' ORDER BY started_at DESC LIMIT 1")
    r = cur.fetchone()
    if not r:
        conn.close()
        return None
    rid, status, total = r
    cur.execute("SELECT COUNT(*) FROM eval_run_detail WHERE run_id=? AND status='completed'", (rid,))
    done = cur.fetchone()[0]
    ok = 0
    cur.execute("SELECT scores FROM eval_run_detail WHERE run_id=? AND status='completed'", (rid,))
    for (scores,) in cur.fetchall():
        if not scores:
            continue
        try:
            s = json.loads(scores)
        except Exception:
            continue
        if s.get("semantic_passed") is True or (s.get("score") or 0) >= 0.65:
            ok += 1
    cur.execute("SELECT summary_scores FROM eval_run WHERE run_id=?", (rid,))
    row = cur.fetchone()
    summary = json.loads(row[0]) if row and row[0] else None
    conn.close()
    return {"run_id": rid, "status": status, "total": total, "done": done, "ok": ok,
            "acc": (ok / done * 100) if done else 0.0, "summary": summary}

last = ""
while True:
    try:
        st = get_run()
        if st:
            line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {st['status']} {st['done']}/{st['total']} acc={st['acc']:.2f}%"
            if line != last:
                print(line, flush=True)
                last = line
            if st["status"] in ("completed", "failed", "cancelled"):
                with open(OUT, "w", encoding="utf-8") as f:
                    json.dump(st, f, ensure_ascii=False, indent=2)
                print("FINAL WRITTEN to", OUT, flush=True)
                if st["summary"]:
                    s = st["summary"]
                    print(f"overall={s.get('overall_score')} correct={s.get('correct')}/{s.get('total')} answer_score={s.get('answer_score')} retrieval={s.get('retrieval_score')}", flush=True)
                break
    except Exception as e:
        print(f"poll err: {e}", flush=True)
    time.sleep(60)

import sqlite3
import json

DB_PATH = r"d:\AI\AnGIneer\data\evals\evals.sqlite"
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute("SELECT * FROM eval_question WHERE question_id = 'eval3_2020_up_001'").fetchall()
for r in rows:
    item = dict(r)
    for key in ("tags", "doc_ids", "retrieval_gold", "answer_gold", "sql_gold", "sop_gold"):
        if item.get(key):
            try:
                item[key] = json.loads(item[key])
            except Exception:
                pass
    print(json.dumps(item, ensure_ascii=False, indent=2))

if not rows:
    print("No question found with id 'eval3_2020_up_001'")
    all_rows = conn.execute("SELECT question_id FROM eval_question WHERE question_id LIKE '%2020_up_00%' ORDER BY question_id").fetchall()
    print(f"\nSimilar IDs:")
    for r in all_rows:
        print(f"  {r['question_id']}")

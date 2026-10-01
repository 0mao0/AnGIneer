"""题集按生产意图分类器（L0-L4 同口径）逐题定级（默认 dry-run，--apply 从缓存回写 intent_level）。

用法：--dataset <dataset_id>（默认 FinanceBench）；缓存 data/scratch/<dataset>_levels.json。

背景：入库时 intent_level 全为默认 L1，题集卡「层级分布」无信息量；用户要求按自家
L0-L4 重新分类（2026-10-01）。分类器 = angineer_core.classifier.IntentClassifier（生产
路由同款，规则快路径 + LLM 兜底），SOP 传空列表（只判层级，不做 SOP 匹配）。
产出：逐题 level；--apply 经 manager.update_question 回写 eval_question.intent_level。
"""
import argparse
import json
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")

from evals_core.dataset import manager  # noqa: E402
from angineer_core.classifier import IntentClassifier  # noqa: E402

SPOT_CHECK_N = 20
SEED = 42
MAX_WORKERS = 4
# 分级结果缓存：--apply 只从缓存写库，杜绝「边 LLM 判级边写库」在网关抖动时把
# 静默降级的 L1 成批写进去（分类器 LLM 失败不抛错、默认返回 L1，见 classifier error_sink）。
def _cache_path(dataset_id: str) -> Path:
    return REPO / "data" / "scratch" / f"{dataset_id.replace('.', '_')}_levels.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="FinanceBench 按生产分类器定级 L0-L4（dry-run 默认，--apply 从缓存回写）")
    parser.add_argument("--dataset", default="financebench-open-150-v1", help="题集 dataset_id")
    parser.add_argument("--apply", action="store_true", help="从缓存分级结果回写 intent_level（不重新判级）")
    parser.add_argument("--votes", type=int, default=1, help="判级轮数（>1 时按多数票定版，抑制分类器边界抖动）")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()

    dataset_id = args.dataset
    CACHE_PATH = _cache_path(dataset_id)
    questions = manager.list_questions(dataset_id)
    if not questions:
        print(f"题集 {dataset_id} 为空或不存在")
        return 2

    if args.apply:
        if not CACHE_PATH.is_file():
            print(f"缓存不存在：{CACHE_PATH}——先跑一次不带 --apply 的判级")
            return 2
        results = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        missing = [q["question_id"] for q in questions if q["question_id"] not in results]
        if missing:
            print(f"缓存缺 {len(missing)} 题，先重新判级")
            return 2
    else:
        clf = IntentClassifier(sops=[])

        def grade(q):
            try:
                r = clf.classify_intent(q["question"])
                return q["question_id"], str(r.intent_level), r.intent_type, ""
            except Exception as exc:  # noqa: BLE001
                return q["question_id"], "", "", f"{type(exc).__name__}: {exc}"

        vote_tables = {q["question_id"]: Counter() for q in questions}
        for pass_i in range(max(1, args.votes)):
            run = {}
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for qid, level, _itype, err in pool.map(grade, questions):
                    if err:
                        print(f"[ERR] {qid}: {err}")
                    run[qid] = level
            for qid, lv in run.items():
                if lv:
                    vote_tables[qid][lv] += 1
            print(f"-- 第 {pass_i + 1}/{max(1, args.votes)} 轮: {dict(sorted(Counter(v for v in run.values() if v).items()))}")

        results = {}
        empty = [qid for qid, c in vote_tables.items() if not c]
        if empty:
            print(f"\n{len(empty)} 题所有轮次都失败——不缓存不回写")
            return 2
        ties = []
        for qid, c in vote_tables.items():
            top = c.most_common()
            if len(top) > 1 and top[0][1] == top[1][1]:
                ties.append(qid)
            results[qid] = top[0][0]
        if ties:
            print(f"平票 {len(ties)} 题（取字典序首位）: {sorted(ties)[:5]}{'...' if len(ties) > 5 else ''}")
        print(f"\n多数票定版分布（n={len(results)}）: {dict(sorted(Counter(results.values()).items()))}")

        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"分级结果已缓存 -> {CACHE_PATH}")

    dist = Counter(results.values())
    print(f"\n分级分布（n={len(results)}）: {dict(sorted(dist.items()))}")

    spot = random.Random(SEED).sample(sorted(results), min(SPOT_CHECK_N, len(results)))
    qtext = {q["question_id"]: q["question"] for q in questions}
    print(f"\n=== 抽检 {len(spot)} 题（seed={SEED}）===")
    for qid in spot:
        print(f"[{results[qid]}] {qtext[qid][:88]}")

    if not args.apply:
        print("\ndry-run 未回写（--apply 从缓存落库）")
        return 0

    for qid, level in results.items():
        manager.update_question(DATASET_ID, qid, {"intent_level": level})
    print(f"\n已回写 {len(results)} 题 intent_level -> {DATASET_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

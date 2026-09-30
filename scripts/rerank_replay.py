"""rerank 二排策略离线 replay 实验台（stage 0）。

背景：v4.1 nightly（962 道 section 题）hit@1≈0.785，其中 wrong_section_bias
（gold 在 top5 但没排第 1）占 misses 的 80%，且 top1 与 gold 的 rerank 分
几乎持平（中位分差 0.001）——bge reranker 在近似候选间区分度不足。

本脚本不重跑检索，直接消费 data/evals/replay/rerank-replay-v1.json
（从 evals.sqlite 冻结的 top8 候选，含 332 道 miss + 332 道对照），
离线对比重排策略对 hit@1 的影响：

  baseline  冻结顺序（sanity check：miss 组应全 0、对照组应全 1）
  tiebreak  平分组内加次级信号重排（条款号命中/section 词重叠/类型先验）
  llm       LLM 二排（复用 retrieval.llm_rerank_system_prompt v1）

投影口径：全量 1924 个 run-question 中 hit@1=0 共 414（0.785 基线），
其中 wrong_section_bias 332（本数据集 miss 组全覆盖）、
missed_exact_target 82（重排救不回，未采样）；对照组从 1510 道
hit@1=1 中抽 332。projected = 0.785 + (332/1924)*fixed_rate - 0.785*broken_rate。

用法：
  python scripts/rerank_replay.py --strategy baseline
  python scripts/rerank_replay.py --strategy tiebreak --grid
  python scripts/rerank_replay.py --strategy llm --limit 40 --workers 4
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "services", "ai-inference", "src"))
sys.path.insert(0, os.path.join(REPO, "services", "angineer-core", "src"))

DATA_PATH = os.environ.get(
    "RERANK_REPLAY_DATA",
    os.path.join(REPO, "data", "evals", "replay", "rerank-replay-v1.json"))
CACHE_PATH = os.path.join(REPO, "data", "evals", "replay", "llm_rerank_cache.json")

TOTAL_RUN_QUESTIONS = 1924
BASELINE_HIT1 = 1510 / TOTAL_RUN_QUESTIONS
MISS_WEIGHT = 332 / TOTAL_RUN_QUESTIONS

_RELEVANCE_PREFIX = re.compile(r"^【相关性[^】]*】\s*")
_CLAUSE_RE = re.compile(r"\d+(?:\.\d+){1,3}")


def norm_path(p):
    p = str(p or "")
    p = re.sub(r"\(\d+\)\s*$", "", p)
    p = p.replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", " ", p).strip().lower()


def section_hit(pred, golds):
    for g in golds:
        g2 = norm_path(g)
        if not g2:
            continue
        if pred == g2 or pred.endswith(g2) or g2 in pred:
            return True
    return False


def clean_text(t):
    return _RELEVANCE_PREFIX.sub("", str(t or "")).strip()


def bigrams(s):
    s = re.sub(r"\s+", "", str(s or ""))
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s} if s else set()


def load_dataset():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)["items"]


def split_groups(items):
    misses = [c for c in items if not c["hit1"]]
    controls = [c for c in items if c["hit1"]]
    return misses, controls


def evaluate(items, order_fn):
    fixed = broken = 0
    for case in items:
        cands = case["candidates"]
        if not cands:
            continue
        order = order_fn(case)
        top = cands[order[0]]
        now_hit = section_hit(norm_path(top.get("section_path")), case["gold_section_paths"])
        if not case["hit1"] and now_hit:
            fixed += 1
        if case["hit1"] and not now_hit:
            broken += 1
    return fixed, broken


def report(name, misses, controls, order_fn):
    f_miss, _ = evaluate(misses, order_fn)
    _, b_ctrl = evaluate(controls, order_fn)
    fixed_rate = f_miss / len(misses) if misses else 0.0
    broken_rate = b_ctrl / len(controls) if controls else 0.0
    projected = BASELINE_HIT1 + MISS_WEIGHT * fixed_rate - BASELINE_HIT1 * broken_rate
    print(f"[{name}] miss 救回 {f_miss}/{len(misses)} ({fixed_rate:.1%}) | "
          f"对照翻车 {b_ctrl}/{len(controls)} ({broken_rate:.1%}) | "
          f"projected hit@1 = {projected:.3f}")
    return projected


def baseline_order(case):
    return list(range(len(case["candidates"])))


TYPE_PRIOR = {"content": 1.0, "list_procedure": 0.8, "table_summary": 0.5,
              "table_row": 0.4, "formula": 0.3, "figure": 0.3}


def make_tiebreak(eps, w_clause, w_overlap, w_type):
    def order_fn(case):
        cands = case["candidates"]
        scores = []
        for c in cands:
            try:
                scores.append(float(c.get("rerank_score")))
            except (TypeError, ValueError):
                scores.append(0.0)
        if not scores:
            return list(range(len(cands)))
        s1 = max(scores)
        q = case["question"] or ""
        q_clauses = set(_CLAUSE_RE.findall(q))
        q_bg = bigrams(q)

        def key(idx):
            c = cands[idx]
            sp = str(c.get("section_path") or "")
            boost = 0.0
            if q_clauses and any(cl in sp for cl in q_clauses):
                boost += w_clause
            head = sp + " " + str(c.get("title") or "")
            head_bg = bigrams(head)
            if q_bg and head_bg:
                boost += w_overlap * len(q_bg & head_bg) / len(q_bg)
            if case.get("question_type") == "definition_qa":
                boost += w_type * TYPE_PRIOR.get(c.get("chunk_type") or c.get("entity_type"), 0.6)
            tie = scores[idx] >= s1 - eps
            return (scores[idx] + (boost if tie else 0.0), -idx)

        return sorted(range(len(cands)), key=key, reverse=True)

    return order_fn


LLM_RERANK_SYSTEM_PROMPT = """你是工程规范文档检索的重排器。给定用户查询和一批候选片段，把与查询主题最相关的片段排到最前。

规则：
1. 依据"候选内容是否真正回答或覆盖查询主题"判断相关度，语义相关优先；
2. 只因为命中通用词（如"计算""方法""要求""规定""公式""按式"等）而与查询主题无关的候选，必须排到后面；
3. 与查询主题无关的候选排在最后；
4. 输出 JSON 对象，ranking 为按相关度从高到低排列的候选编号数组，例如 {"ranking": [3, 0, 1]}；
5. 不要输出 ranking 以外的字段。"""


LLM_RERANK_DEF_PROMPT = """你是工程规范文档检索的重排器。用户的查询是在问某个术语/概念的定义或含义。

规则：
1. 只有「明确给出该术语定义、释义或界定」的候选才算真正相关，排最前；
2. 只是在行文中提到该词、使用该词，但没有解释其含义的候选，必须排到后面；
3. 与查询术语无关的候选排在最后；
4. 定义句常出现在候选中段，请通读全文再判断，不要只看开头；
5. 输出 JSON 对象，ranking 为按相关度从高到低排列的候选编号数组，例如 {"ranking": [3, 0, 1]}；
6. 不要输出 ranking 以外的字段。"""


def llm_rank_one(case, top_n, max_chars, prompt, model=None):
    from ai_inference.llm_client import chat_result_guarded, get_llm_client
    from ai_inference.llm_response_parser import extract_json_from_text

    cands = case["candidates"][:top_n]
    lines = []
    for i, c in enumerate(cands):
        title = " ".join(str(c.get("title") or "").split())[:60]
        text = " ".join(clean_text(c.get("text")).split())[:max_chars]
        lines.append(f"[{i}] {title}\n{text}")
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"查询：{case['question']}\n\n候选：\n" + "\n\n".join(lines)},
    ]
    client = get_llm_client(config_name=model)
    result = chat_result_guarded(client, messages, mode="instruct", config_name=model)
    parsed = extract_json_from_text(result.text, strict=True)
    raw_order = parsed.get("ranking") or []
    order, seen = [], set()
    for raw in raw_order:
        try:
            idx = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(cands) and idx not in seen:
            seen.add(idx)
            order.append(idx)
    if not order:
        raise ValueError("empty ranking")
    full = order + [i for i in range(len(cands)) if i not in seen]
    full += list(range(len(cands), len(case["candidates"])))
    return full


DUEL_PROMPT = """你是工程规范文档检索的裁判员。用户的查询是在问某个术语/概念的定义或含义。

给你两个候选片段，判断哪一个更可能是该查询的最佳答案来源。

规则：
1. 明确给出该术语定义、释义或界定的候选获胜；
2. 都只是提到该词时，信息与查询更贴合的获胜；
3. 通读全文再判断，定义句可能出现在中段；
4. 输出 JSON 对象，winner 为 "A" 或 "B"，例如 {"winner": "B"}；
5. 不要输出 winner 以外的字段。"""


def llm_duel_one(case, challenger_idx, max_chars, model=None):
    from ai_inference.llm_client import chat_result_guarded, get_llm_client
    from ai_inference.llm_response_parser import extract_json_from_text

    cands = case["candidates"]
    a = cands[0]
    b = cands[challenger_idx]

    def fmt(c):
        title = " ".join(str(c.get("title") or "").split())[:60]
        text = " ".join(clean_text(c.get("text")).split())[:max_chars]
        return f"{title}\n{text}"

    messages = [
        {"role": "system", "content": DUEL_PROMPT},
        {"role": "user", "content": (
            f"查询：{case['question']}\n\n"
            f"候选A：\n{fmt(a)}\n\n候选B：\n{fmt(b)}")},
    ]
    client = get_llm_client(config_name=model)
    result = chat_result_guarded(client, messages, mode="instruct", config_name=model)
    parsed = extract_json_from_text(result.text, strict=True)
    winner = str(parsed.get("winner") or "").strip().upper()
    if winner not in ("A", "B"):
        raise ValueError(f"bad winner: {winner!r}")
    return winner


def run_duel(items, max_chars, limit, workers, model):
    cache = load_cache()
    todo = []
    for case in items:
        key = f"{case['run_id']}:{case['question_id']}:duel{mtag(model)}"
        deffull = cache.get(f"{case['run_id']}:{case['question_id']}:deffull{mtag(model)}")
        if not deffull or deffull[0] == 0 or key in cache:
            continue
        todo.append((key, case, deffull[0]))
        if limit and len(todo) >= limit:
            break
    print(f"duel: 本次调用 {len(todo)} 题")
    errors = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(llm_duel_one, case, ch, max_chars, model): key
                for key, case, ch in todo}
        for fut in cf.as_completed(futs):
            key = futs[fut]
            try:
                cache[key] = fut.result()
            except Exception as exc:
                errors += 1
                print(f"  duel 失败 {key}: {exc}")
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    print(f"duel: 失败 {errors}，缓存总量 {len(cache)}")

    def order_fn(case):
        n = len(case["candidates"])
        base_key = f"{case['run_id']}:{case['question_id']}"
        deffull = cache.get(base_key + ":deffull" + mtag(model))
        if not deffull or deffull[0] == 0 or max(deffull) >= n:
            return list(range(n))
        duel = cache.get(base_key + ":duel" + mtag(model))
        if duel == "B":
            return deffull
        return list(range(n))

    return order_fn


def run_duel2(items, max_chars, limit, workers, model):
    cache = load_cache()
    todo = []
    for case in items:
        base_key = f"{case['run_id']}:{case['question_id']}"
        deffull = cache.get(base_key + ":deffull" + mtag(model))
        if not deffull or deffull[0] != 0:
            continue
        key = base_key + ":duel2" + mtag(model)
        if key in cache or len(case["candidates"]) < 2:
            continue
        todo.append((key, case, 1))
        if limit and len(todo) >= limit:
            break
    print(f"duel2: 本次调用 {len(todo)} 题")
    errors = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(llm_duel_one, case, ch, max_chars, model): key
                for key, case, ch in todo}
        for fut in cf.as_completed(futs):
            key = futs[fut]
            try:
                cache[key] = fut.result()
            except Exception as exc:
                errors += 1
                print(f"  duel2 失败 {key}: {exc}")
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    print(f"duel2: 失败 {errors}，缓存总量 {len(cache)}")

    def order_fn(case):
        n = len(case["candidates"])
        base_key = f"{case['run_id']}:{case['question_id']}"
        deffull = cache.get(base_key + ":deffull" + mtag(model))
        if deffull and deffull[0] != 0 and max(deffull) < n:
            if cache.get(base_key + ":duel" + mtag(model)) == "B":
                return deffull
            return list(range(n))
        if n >= 2 and cache.get(base_key + ":duel2" + mtag(model)) == "B":
            return [1, 0] + list(range(2, n))
        return list(range(n))

    return order_fn


def run_wide(items, top_n, max_chars, limit, workers, model=None):
    cache = load_cache()
    todo = []
    for case in items:
        key = f"{case['run_id']}:{case['question_id']}:wide{mtag(model)}"
        if key not in cache:
            todo.append((key, case))
        if limit and len(todo) >= limit:
            break
    print(f"wide: 本次调用 {len(todo)} 题")
    errors = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(llm_rank_one, case, top_n, max_chars,
                          LLM_RERANK_DEF_PROMPT, model): key for key, case in todo}
        for fut in cf.as_completed(futs):
            key = futs[fut]
            try:
                cache[key] = fut.result()
            except Exception as exc:
                errors += 1
                print(f"  wide 失败 {key}: {exc}")
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    print(f"wide: 失败 {errors}，缓存总量 {len(cache)}")

    def order_fn(case):
        n = len(case["candidates"])
        key = f"{case['run_id']}:{case['question_id']}:wide{mtag(model)}"
        cached = cache.get(key)
        if not cached or max(cached) >= n:
            return list(range(n))
        return cached

    return order_fn


def run_wide_duel(items, max_chars, limit, workers, model=None):
    cache = load_cache()
    todo = []
    for case in items:
        base_key = f"{case['run_id']}:{case['question_id']}"
        wide = cache.get(base_key + ":wide" + mtag(model))
        if not wide or wide[0] == 0:
            continue
        key = base_key + ":wideduel" + mtag(model)
        if key in cache:
            continue
        todo.append((key, case, wide[0]))
        if limit and len(todo) >= limit:
            break
    print(f"wideduel: 本次调用 {len(todo)} 题")
    errors = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(llm_duel_one, case, ch, max_chars, model): key
                for key, case, ch in todo}
        for fut in cf.as_completed(futs):
            key = futs[fut]
            try:
                cache[key] = fut.result()
            except Exception as exc:
                errors += 1
                print(f"  wideduel 失败 {key}: {exc}")
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    print(f"wideduel: 失败 {errors}，缓存总量 {len(cache)}")

    def order_fn(case):
        n = len(case["candidates"])
        base_key = f"{case['run_id']}:{case['question_id']}"
        wide = cache.get(base_key + ":wide" + mtag(model))
        if not wide or wide[0] == 0 or max(wide) >= n:
            return list(range(n))
        if cache.get(base_key + ":wideduel" + mtag(model)) == "B":
            return wide
        return list(range(n))

    return order_fn


def report_groups(name, items, order_fn):
    groups = {"wsb": [0, 0], "met": [0, 0], "control": [0, 0]}
    for case in items:
        g = case.get("group") or ("control" if case["hit1"] else "wsb")
        cands = case["candidates"]
        if not cands:
            continue
        order = order_fn(case)
        top = cands[order[0]]
        now_hit = section_hit(norm_path(top.get("section_path")), case["gold_section_paths"])
        if g in ("wsb", "met"):
            groups[g][1] += 1
            groups[g][0] += bool(now_hit)
        else:
            groups["control"][1] += 1
            groups["control"][0] += bool(not now_hit)
    fw, nw = groups["wsb"]
    fm, nm = groups["met"]
    bc, nc = groups["control"]
    projected = (BASELINE_HIT1 + (332 / TOTAL_RUN_QUESTIONS) * (fw / nw if nw else 0)
                 + (82 / TOTAL_RUN_QUESTIONS) * (fm / nm if nm else 0)
                 - BASELINE_HIT1 * (bc / nc if nc else 0))
    print(f"[{name}] wsb 救回 {fw}/{nw} ({fw/nw:.1%}) | met 救回 {fm}/{nm} ({fm/nm:.1%}) | "
          f"对照翻车 {bc}/{nc} ({bc/nc:.1%}) | projected hit@1 = {projected:.3f}")
    return projected


def mtag(model):
    return "" if not model else ":" + re.sub(r"[^A-Za-z0-9]", "", model)


def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def run_llm(items, top_n, max_chars, limit, workers, variant, model=None):
    prompt = LLM_RERANK_SYSTEM_PROMPT if variant == "v1" else LLM_RERANK_DEF_PROMPT
    cache = load_cache()
    todo = []
    for case in items:
        key = f"{case['run_id']}:{case['question_id']}:{variant}{mtag(model)}"
        if key not in cache:
            todo.append((key, case))
        if limit and len(todo) >= limit:
            break
    print(f"llm({variant}): 本次调用 {len(todo)} 题")
    errors = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(llm_rank_one, case, top_n, max_chars, prompt, model): key
                for key, case in todo}
        for fut in cf.as_completed(futs):
            key = futs[fut]
            try:
                cache[key] = fut.result()
            except Exception as exc:
                errors += 1
                print(f"  llm 失败 {key}: {exc}")
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    print(f"llm({variant}): 失败 {errors}，缓存总量 {len(cache)}")

    def order_fn(case):
        key = f"{case['run_id']}:{case['question_id']}:{variant}{mtag(model)}"
        cached = cache.get(key)
        n = len(case["candidates"])
        if not cached or max(cached) >= n:
            return list(range(n))
        return cached

    return order_fn


def make_fuse(variant, w):
    cache = load_cache()

    def order_fn(case):
        cands = case["candidates"]
        n = len(cands)
        key = f"{case['run_id']}:{case['question_id']}:{variant}"
        llm_order = cache.get(key)
        if not llm_order or max(llm_order) >= n:
            return list(range(n))
        llm_pos = {orig: pos for pos, orig in enumerate(llm_order)}
        base = []
        for i in range(n):
            try:
                s = float(cands[i].get("rerank_score"))
            except (TypeError, ValueError):
                s = 0.0
            base.append(s)
        s_max = max(base) if base else 1.0
        s_min = min(base) if base else 0.0
        span = (s_max - s_min) or 1.0

        def key_fn(i):
            norm_bge = (base[i] - s_min) / span
            llm_score = (n - 1 - llm_pos.get(i, n - 1)) / max(n - 1, 1)
            return norm_bge + w * llm_score

        return sorted(range(n), key=key_fn, reverse=True)

    return order_fn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", choices=["baseline", "tiebreak", "llm", "fuse", "duel",
                                           "duel2", "wide", "wideduel"], required=True)
    ap.add_argument("--eps", type=float, default=0.005)
    ap.add_argument("--w-clause", type=float, default=0.05)
    ap.add_argument("--w-overlap", type=float, default=0.05)
    ap.add_argument("--w-type", type=float, default=0.02)
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--top-n", type=int, default=8)
    ap.add_argument("--max-chars", type=int, default=300)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--variant", choices=["v1", "def", "deffull"], default="v1")
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    items = load_dataset()
    misses, controls = split_groups(items)
    print(f"数据集: miss {len(misses)} / control {len(controls)}")

    if args.strategy == "baseline":
        report("baseline", misses, controls, baseline_order)
    elif args.strategy == "tiebreak":
        if args.grid:
            best = (None, -1.0)
            for eps in (0.001, 0.005, 0.01):
                for wc in (0.0, 0.05, 0.2):
                    for wo in (0.0, 0.02, 0.05, 0.2):
                        for wt in (0.0, 0.02, 0.1):
                            if wc == wo == wt == 0.0:
                                continue
                            name = f"eps={eps} wc={wc} wo={wo} wt={wt}"
                            p = report(name, misses, controls,
                                       make_tiebreak(eps, wc, wo, wt))
                            if p > best[1]:
                                best = (name, p)
            print(f"BEST: {best[0]} -> {best[1]:.3f}")
        else:
            report(f"tiebreak eps={args.eps}", misses, controls,
                   make_tiebreak(args.eps, args.w_clause, args.w_overlap, args.w_type))
    elif args.strategy == "fuse":
        best = (None, -1.0)
        for variant in ("v1", "def", "deffull"):
            for w in (0.05, 0.1, 0.2, 0.4, 0.8, 1.5):
                p = report(f"fuse-{variant} w={w}", misses, controls,
                           make_fuse(variant, w))
                if p > best[1]:
                    best = (f"{variant} w={w}", p)
        print(f"BEST: {best[0]} -> {best[1]:.3f}")
    elif args.strategy == "duel":
        order_fn = run_duel(items, args.max_chars, args.limit, args.workers, args.model)
        report("duel", misses, controls, order_fn)
    elif args.strategy == "duel2":
        order_fn = run_duel2(items, args.max_chars, args.limit, args.workers, args.model)
        report("duel2", misses, controls, order_fn)
    elif args.strategy == "wide":
        order_fn = run_wide(items, args.top_n, args.max_chars, args.limit,
                            args.workers, args.model)
        report_groups("wide", items, order_fn)
    elif args.strategy == "wideduel":
        order_fn = run_wide_duel(items, args.max_chars, args.limit, args.workers, args.model)
        report_groups("wideduel", items, order_fn)
    else:
        order_fn = run_llm(items, args.top_n, args.max_chars, args.limit,
                           args.workers, args.variant, args.model)
        report(f"llm-{args.variant}", misses, controls, order_fn)


if __name__ == "__main__":
    main()

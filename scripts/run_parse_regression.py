"""A 层解析回归一键入口：predict → A②（结构层×2）→ A①（官方镜像）→ 归档 → Δ。

方案与评估见 docs/plan-parse-regression-entry.md，口径定义见 docs/parse-struct-eval.md。
本脚本只是**编排薄壳**：真正干活的还是既有两个入口（口径一行不改）——
  scripts/run_omnidocbench_eval.py predict / eval   （A①：页图→解析→markdown→官方评测器）
  scripts/eval_parse_struct.py                      （A②：jsonl 结构层，两方）
归档与 Δ 是纯逻辑，在 evals_core.parse_regression（可单测）。

用法：
  # 全跑（约 1.2–1.5h：predict 52min + A②×2 4min + A① 10–20min）
  python scripts/run_parse_regression.py --limit 200 --seed 42

  # 干跑：复用现成预测、不跑 18GB 镜像，只验归档与 Δ（~4min）
  python scripts/run_parse_regression.py --skip-predict --skip-official --limit 50 \\
      --predictions data/evals/omnidocbench/predictions_eval200

  # 把已有的离线产物入档为"参考基线"（不跑任何评测器）
  python scripts/run_parse_regression.py --import-official <dir> --import-chain <json> \\
      --import-mineru <json> --tag baseline-20260913 --note "离线重投影，非同一次解析"

   跳过 predict / A① 必须显式给 --skip-*，且跳过理由会写进 meta 与 summary（不静默）。
   Δ 不影响退出码（这是评测入口不是 CI 门禁）；页集合不同的两次分不可比，默认不出 Δ。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))
sys.path.insert(0, str(SCRIPTS))          # 复用 predict 的抽样函数，保证与基线口径完全一致

from evals_core import parse_regression as pr  # noqa: E402
from run_omnidocbench_eval import PARSE_STAGES, _select_pages  # noqa: E402

DEFAULT_LIBRARY_DIR = REPO / "data" / "knowledge_base" / "libraries" / "omnidocbench" / "documents"
DEFAULT_OUT_ROOT = REPO / "data" / "evals" / "parse_regression"
EVAL_IMAGE = "ghcr.io/zeng-weijun/omnidocbench-eval:repro-ubuntu2204"
# 数据集（页图 + OmniDocBench.json）的候选目录：一键跑不该要求背路径。按顺序取第一个
# 真的有 images/ 的；都找不到才报错并列出候选（env: OMNIDOCBENCH_DATA 优先）
DATA_DIR_CANDIDATES = (
    Path(os.getenv("OMNIDOCBENCH_DATA") or ""),
    REPO / "data" / "omnidocbench",
    Path("D:/AI/tools/OmniDocBench_data"),
    Path.home() / "OmniDocBench_data",
)
# 三方表两列（参考模型 / MinerU 单独）的官方产物目录：只认显式给出的 env/CLI，**不再硬编码自动探测**
# （2026-09-23 实踩：硬编码候选把 09-13 的 mineru_only_result 静默填进「MinerU 单独」列——那是修复前
# 模型、另一次批量解析的产物，与本次"我们全链"列不同尺，曾据此得出"我们链表格弱于 MinerU"的假结论，
# 见 docs/plan-parse-regression-entry.md）。给了就会在 summary 里标注"固定基线、非同批解析"。
SOURCE_DIR_CANDIDATES = {
    "ref": (Path(os.getenv("OMNIDOCBENCH_REF_RESULT") or ""),),
    "mineru": (Path(os.getenv("OMNIDOCBENCH_MINERU_RESULT") or ""),),
}


def _resolve_data_dir(arg: str) -> Path:
    """定数据集目录：显式参数 > 候选里第一个含 images/ 的。"""
    if arg:
        path = Path(arg)
        if not (path / "images").is_dir():
            raise SystemExit(f"--data-dir 下没有 images/：{path}")
        return path
    tried = []
    for cand in DATA_DIR_CANDIDATES:
        if not str(cand) or str(cand) == ".":
            continue
        tried.append(str(cand))
        if (cand / "images").is_dir():
            return cand
    raise SystemExit("找不到 OmniDocBench 数据集（需含 images/ 与 OmniDocBench.json）。\n"
                     "用 --data-dir 指定，或设环境变量 OMNIDOCBENCH_DATA。已试：\n  "
                     + "\n  ".join(tried))


def _resolve_gt(arg_gt: str, data_dir: Path) -> Path:
    path = Path(arg_gt) if arg_gt else data_dir / "OmniDocBench.json"
    if not path.is_file():
        raise SystemExit(f"GT 不存在: {path}（可用 --gt 指定）")
    return path


def _resolve_source(kind: str) -> str:
    """三方表可选的固定列：候选目录里有官方 metric_result 才用，否则留空。"""
    for cand in SOURCE_DIR_CANDIDATES[kind]:
        if str(cand) and str(cand) != "." and pr.find_metric_result(cand) is not None:
            return str(cand)
    return ""


def _key(name) -> str:
    """页名归一键：去图片扩展名，再去可能残留的 .pdf 中缀（与官方 GT 过滤同一套规则）。"""
    return pr.norm_page(name).replace(".pdf", "")


def _run_step(label: str, cmd: list, skipped: list) -> int:
    print(f"\n=== {label} ===\n$ {' '.join(str(c) for c in cmd)}", flush=True)
    try:
        proc = subprocess.run(cmd, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"!! {label} 启动失败: {exc}", flush=True)
        skipped.append(f"{label}: 启动失败 {exc}")
        return -1
    if proc.returncode != 0:
        print(f"!! {label} 退出码 {proc.returncode}", flush=True)
        skipped.append(f"{label}: 退出码 {proc.returncode}（该步产物可能不完整）")
    return proc.returncode


def _git_env() -> dict:
    def _git(*args) -> str:
        try:
            out = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=20)
            return out.stdout.strip() if out.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    return {
        "git_describe": _git("describe", "--tags", "--always", "--dirty"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "python": sys.version.split()[0],
    }


def _docker_image_id() -> str:
    try:
        out = subprocess.run(["docker", "images", "--no-trunc", "--format", "{{.ID}} {{.Repository}}:{{.Tag}}"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in (out.stdout or "").splitlines():
        if EVAL_IMAGE in line:
            return line.split()[0][:24]
    return ""


def _mineru_versions(state_path: Path, library_dir: Path) -> str:
    """汇总参与本次评分的各篇 mineru_raw/middle.json 版本（版式一致性核查）。"""
    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    seen = {}
    for item in (state or {}).values():
        doc_id = str((item or {}).get("doc_id") or "")
        if not doc_id:
            continue
        middle = Path(library_dir) / doc_id / "parsed" / "mineru_raw" / "middle.json"
        try:
            version = str(json.loads(middle.read_text(encoding="utf-8")).get("_version_name") or "")
        except (OSError, ValueError):
            continue
        if version:
            seen[version] = seen.get(version, 0) + 1
    if not seen:
        return ""
    return " / ".join(f"{v}(n={n})" for v, n in sorted(seen.items()))


def _filter_gt(gt_path: Path, keys: set, out_path: Path) -> int:
    """只留选中页的 GT：A② 的 --limit 是"GT 顺序前 N 页"，与抽样口径不同，必须显式给页集合。"""
    samples = json.loads(Path(gt_path).read_text(encoding="utf-8"))
    kept = [s for s in samples
            if _key(Path(str((s.get("page_info") or {}).get("image_path") or "")).name) in keys]
    pr.write_json(out_path, kept)
    return len(kept)


def _build_delta(root: Path, spec: str, mode: str, cur_official: dict, cur_struct: dict,
                 cur_pages: list, baseline_id: str = "", cur_kind: str = "run") -> dict:
    base_dir = pr.resolve_baseline(root, spec)
    if base_dir is None:
        reason = ("已指定 --baseline none：本次不出 Δ（要对比就去掉这个参数）"
                  if spec == "none" else
                  f"首次跑：{spec} 指针不存在——本次即成为基线，Δ 从下次跑开始")
        return {"gate": "none", "reason": reason}
    base = pr.load_run(base_dir)
    rel = pr.page_set_relation(cur_pages, base["meta"].get("page_ids") or [])
    delta = {"baseline_id": baseline_id or base_dir.name, "baseline_dir": str(base_dir),
             "relation": rel, "mode": mode}
    notes = []
    if base["meta"].get("kind") != "run":
        # 基线是离线重投影产物（非同一次解析，方案修正 2）：Δ 量的是"尺子差"，不是回归
        notes.append(f"基线 {base_dir.name} 是离线重投影产物（非同一次 fresh 解析）——"
                     f"本次 Δ 是换量尺的差，**不可当回归判据**")
    if cur_kind != "run":
        notes.append("本次是离线重投影产物（入档模式）——Δ 反映换量尺，不是本次跑出来的变化")
    if notes:
        delta["note"] = "；".join(notes)
    if not rel["equal"] and mode != "intersect":
        delta["gate"] = "none"
        delta["reason"] = (f"页集合不同（本次 {rel['cur_count']} / 基线 {rel['base_count']} / 交集 "
                           f"{rel['intersection']}）——少评几页会虚高或虚低，默认不出 Δ；"
                           f"确要比可加 --delta-mode intersect（只重算 A①，且非官方重跑口径）")
        return delta
    delta["gate"] = "ok"
    if rel["equal"]:
        base_official, base_struct = base["official"], base["struct_chain"]
    else:
        # 交集重算：官方逐页/逐表产物取平均；A② 产物只有整轮聚合、没有逐块明细，无法重算
        base_official = pr.recompute_official_by_intersection(base_dir / "official", set(cur_pages))
        base_struct = {}
        delta["note"] = ((delta.get("note", "") + "；") if delta.get("note") else "") + \
            "A② 结构层无法按交集重算（产物无逐块明细），该项只在页集合相同时才比"
    delta["groups"] = {
        "official": pr.compare(cur_official, base_official),
        "struct_chain": pr.compare(cur_struct, base_struct) if base_struct else [],
    }
    return delta


def _ssh_bin(name: str) -> str:
    """优先用 Windows 原生 OpenSSH：Git Bash 自带的 ssh/scp 会把中文用户名 HOME 转 GBK 乱码路径
    （AGENTS.md 记录的实踩），表现为偶发 'Host key verification failed'。"""
    native = Path(f"C:/Windows/System32/OpenSSH/{name}.exe")
    return str(native) if native.is_file() else name


def _publish(run_dir: Path, files: tuple, dest: str) -> bool:
    """把结论层文件同步到看板目录（`host:/path` 走 ssh/scp；本地路径直接拷，便于自测）。

    只传白名单（meta/summary/publish/结构层 json+报告，合计 ~140KB）：predictions/、official/、
    gt_subset.json 是复现用的，留在本机。远端会先 mkdir <dest>/<run_id>/（scp 不会隐式建目录）。
    """
    srcs = [str(run_dir / name) for name in files if (run_dir / name).is_file()]
    if not srcs:
        print("!! 没有可发布的文件", flush=True)
        return False

    host, remote = _split_dest(dest)
    if not host:                             # 本地路径：直接拷（也用于自测）
        target_dir = Path(remote) / run_dir.name
        target_dir.mkdir(parents=True, exist_ok=True)
        for src in srcs:
            shutil.copy2(src, target_dir / Path(src).name)
        print(f"已发布 {len(srcs)} 个文件 → {target_dir}", flush=True)
        return True

    remote_dir = f"{remote.rstrip('/')}/{run_dir.name}"
    ssh, scp = _ssh_bin("ssh"), _ssh_bin("scp")
    print(f"\n=== 发布到看板 ===\n$ {ssh} {host} mkdir -p {remote_dir}\n"
          f"$ {scp} <{len(srcs)} 个文件> {host}:{remote_dir}/", flush=True)
    try:
        mk = subprocess.run([ssh, host, f"mkdir -p {remote_dir}"], text=True,
                            encoding="utf-8", errors="replace")
        if mk.returncode != 0:
            print(f"!! 远端建目录失败（ssh 退出码 {mk.returncode}）；本机文件未动 {run_dir}", flush=True)
            return False
        proc = subprocess.run([scp, *srcs, f"{host}:{remote_dir}/"], text=True,
                              encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"!! 发布失败（找不到 ssh/scp？）: {exc}", flush=True)
        return False
    if proc.returncode != 0:
        print(f"!! 发布失败（scp 退出码 {proc.returncode}）；本机文件未动 {run_dir}", flush=True)
        return False
    print(f"已发布 {len(srcs)} 个文件 → {host}:{remote_dir}/", flush=True)
    return True


def _split_dest(dest: str) -> tuple:
    """scp 目标 → (host, path)；本地路径返回 ("", path)。

    不能只看有没有冒号：Windows 盘符（C:\\...、D:/...）也带冒号，会把本地路径误判成远端。
    判定规则：冒号前不含 / \\ 且长度 > 1（user@host 也算）才是远端主机。
    """
    if ":" in dest:
        head, _, tail = dest.partition(":")
        if len(head) > 1 and "/" not in head and "\\" not in head:
            return head, tail
    return "", dest


def _maybe_publish(args, run_dir: Path) -> None:
    """写好的 publish.json + 白名单文件同步到看板目录；没给目标就提示怎么给，不静默。"""
    if args.publish is None:
        return
    dest = _publish_target(args.publish)
    if not dest:
        print("!! 给了 --publish 但没有目标：带目标（如 root@host:/path/）"
              "或设环境变量 PARSE_REGRESSION_PUBLISH", flush=True)
        return
    _publish(run_dir, pr.PUBLISH_FILES, dest)


def _publish_target(arg) -> str:
    if arg is None:
        return ""
    if arg != "__env__":
        return str(arg)
    return (os.getenv("PARSE_REGRESSION_PUBLISH") or "").strip()


def _republish_mode(args) -> int:
    """给已归档的 run 重算并写 publish.json（旧 run 早于看板功能时补档，或改了指标名/标签后刷新）。

    不重跑任何评测：只读归档里的 meta/struct_*/official，按当前代码重建载荷与 Δ。
    """
    root = Path(args.out_root)
    run_dir = root / args.republish
    if not run_dir.is_dir():
        raise SystemExit(f"归档不存在: {run_dir}")
    run = pr.load_run(run_dir)
    meta = run["meta"]
    if not meta:
        raise SystemExit(f"{run_dir} 缺 meta.json，无法重建载荷")
    sources = meta.get("sources") or {}
    ref = args.sources_ref or sources.get("ref_official") or ""
    mineru_src = args.sources_mineru or sources.get("mineru_official") or ""
    official_ref = pr.load_official_metrics(Path(ref)) if ref else {}
    official_mineru = pr.load_official_metrics(Path(mineru_src)) if mineru_src else {}
    chain_path = run_dir / "struct_chain.json"
    chain_result = json.loads(chain_path.read_text(encoding="utf-8")) if chain_path.is_file() else {}
    mineru_path = run_dir / "struct_mineru.json"
    mineru_result = json.loads(mineru_path.read_text(encoding="utf-8")) if mineru_path.is_file() else {}
    pointer = pr.read_pointer(root, "baseline.json") or {}
    if pointer.get("run_id") == args.republish and args.baseline in ("", "baseline"):
        # 它就是当前基线：与自己比全是 0，没意义——如实写成"本次即基线"
        delta = {"gate": "none", "reason": "本次即当前基线（Δ 从下一次跑开始）"}
    else:
        delta = _build_delta(root, args.baseline, args.delta_mode, run["official"], run["struct_chain"],
                             meta.get("page_ids") or [], cur_kind=str(meta.get("kind") or "run"))
    conclusions = pr.build_conclusions(run["official"], run["struct_chain"], run["struct_mineru"],
                                       official_ref, official_mineru,
                                       chain_result.get("by_category"), chain_result.get("by_data_source"),
                                       mineru_result.get("by_category"), mineru_result.get("by_data_source"))
    pr.write_publish(run_dir, pr.build_publish_payload(
        meta, run["official"], run["struct_chain"], run["struct_mineru"], delta,
        official_ref, official_mineru, chain_result, conclusions, mineru_result))
    # summary.md 也重渲染：结论是按数字算的，旧归档文件里没有这一段
    (run_dir / "summary.md").write_text(
        pr.render_summary(meta, run["official"], run["struct_chain"], run["struct_mineru"],
                          official_mineru, official_ref, delta, conclusions), encoding="utf-8")
    print(f"已重建 publish.json + summary.md: {run_dir}")
    _maybe_publish(args, run_dir)
    return 0


def _import_mode(args) -> int:
    """把已有离线产物入档（不做任何评测），meta 如实标注来源与非 fresh 事实。"""
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    run_id = args.tag or pr.run_id_for(ts, "import")   # 入档用 --tag 当目录名（如 baseline-20260913）
    root = Path(args.out_root)
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    official = pr.load_official_metrics(Path(args.import_official)) if args.import_official else {}
    copied = pr.copy_official(Path(args.import_official), run_dir / "official") if args.import_official else 0
    chain_json = Path(args.import_chain) if args.import_chain else None
    mineru_json = Path(args.import_mineru) if args.import_mineru else None
    struct_chain = struct_mineru = {}
    if chain_json and chain_json.is_file():
        struct_chain = pr.load_structure_metrics(chain_json)
        pr.write_json(run_dir / "struct_chain.json", json.loads(chain_json.read_text(encoding="utf-8")))
    if mineru_json and mineru_json.is_file():
        struct_mineru = pr.load_structure_metrics(mineru_json)
        pr.write_json(run_dir / "struct_mineru.json", json.loads(mineru_json.read_text(encoding="utf-8")))

    pages = set(pr.official_page_set(run_dir / "official"))
    if chain_json and chain_json.is_file():
        pages |= pr.structure_page_set(json.loads(chain_json.read_text(encoding="utf-8")))
    pages = sorted(pages)
    # 三方表的两列固定基线（参考模型 / MinerU 单独），有就给，没有就空着并写明原因
    official_ref = pr.load_official_metrics(Path(args.sources_ref)) if args.sources_ref else {}
    official_mineru = pr.load_official_metrics(Path(args.sources_mineru)) if args.sources_mineru else {}
    meta = {
        "run_id": run_id, "ts": ts, "kind": "offline-reprojection",
        "run_date": pr.run_date_from_tag(args.tag or "", ts),
        "note": args.note or "离线产物入档：非同一次解析（见 docs/plan-parse-regression-entry.md 修正 2）",
        "args": {"import_official": args.import_official, "import_chain": args.import_chain,
                 "import_mineru": args.import_mineru, "tag": args.tag},
        "page_ids": pages, "page_ids_hash": pr.page_ids_hash(pages), "pages_scored": len(pages),
        "stages": PARSE_STAGES, "environment": _git_env(),
        "sources": {"official": args.import_official, "chain": args.import_chain,
                    "mineru": args.import_mineru, "ref_official": args.sources_ref,
                    "mineru_official": args.sources_mineru},
        "skipped": ["predict 未跑（入档模式）", "A② 未跑（入档模式）", "A① 未跑（入档模式）"],
    }
    pr.write_json(run_dir / "meta.json", meta)
    (run_dir / "summary.md").write_text(
        pr.render_summary(meta, official, struct_chain, struct_mineru, official_mineru, official_ref),
        encoding="utf-8")
    chain_result = json.loads(chain_json.read_text(encoding="utf-8")) if (chain_json and chain_json.is_file()) else {}
    pr.write_publish(run_dir, pr.build_publish_payload(
        meta, official, struct_chain, struct_mineru, None, official_ref, official_mineru, chain_result))
    _maybe_publish(args, run_dir)
    print(f"入档完成: {run_dir}（官方产物 {copied} 个文件，页 {len(pages)}）")
    print(f"  meta   : {run_dir / 'meta.json'}")
    print(f"  summary: {run_dir / 'summary.md'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="A 层解析回归一键入口（A① 官方 markdown + A② 结构层）")
    ap.add_argument("--limit", type=int, default=200, help="抽样页数（与旧基线同 seed 时可嵌套比对）")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--tag", default="", help="本次 run 命名（默认只有时间戳）")
    ap.add_argument("--predict-mode", choices=["in-process", "http"], default="in-process")
    ap.add_argument("--docs-api", default="http://localhost:8790", help="仅 --predict-mode http 用")
    ap.add_argument("--skip-predict", action="store_true")
    ap.add_argument("--skip-official", action="store_true", help="不跑 18GB 镜像（A① 空着）")
    ap.add_argument("--predictions", default="", help="预测目录（--skip-predict 时指向现成目录）")
    ap.add_argument("--data-dir", default="", help="OmniDocBench 数据集目录（含 images/）；留空自动探测")
    ap.add_argument("--gt", default="", help="OmniDocBench.json；留空取 <data-dir>/OmniDocBench.json")
    ap.add_argument("--library", default="omnidocbench")
    ap.add_argument("--library-dir", default=str(DEFAULT_LIBRARY_DIR))
    ap.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    ap.add_argument("--baseline", default="baseline", help="baseline(默认) | latest | none | <run_id> | 目录")
    ap.add_argument("--delta-mode", choices=["strict", "intersect"], default="strict",
                    help="页集合不等时：strict=不出 Δ（默认）；intersect=按交集重算 A①（非官方口径）")
    ap.add_argument("--set-baseline", action="store_true", help="把本次 run 钉为基线")
    ap.add_argument("--sources-ref", default="", help="参考模型官方产物目录（三方表第一列）；须显式指定"
                                                      "（或 env OMNIDOCBENCH_REF_RESULT），不给则该列留空")
    ap.add_argument("--sources-mineru", default="", help="MinerU 单独官方产物目录（三方表第二列）；须显式指定"
                                                         "（或 env OMNIDOCBENCH_MINERU_RESULT），不给则该列留空")
    ap.add_argument("--republish", default="", help="给已归档的 run 重建 publish.json（只看不跑）")
    ap.add_argument("--import-official", default="", help="入档模式：官方产物目录")
    ap.add_argument("--import-chain", default="", help="入档模式：A② 我们全链 structure_result.json")
    ap.add_argument("--import-mineru", default="", help="入档模式：A② MinerU 原生 structure_result.json")
    ap.add_argument("--note", default="", help="入档模式：写进 meta/summary 的一句话说明")
    ap.add_argument("--publish", nargs="?", const="__env__", default=None,
                    help="结果同步到服务器看板（可给 scp 目标，如 root@host:/path/；"
                         "不给目标则读环境变量 PARSE_REGRESSION_PUBLISH）")
    args = ap.parse_args()

    if args.republish:
        return _republish_mode(args)
    if args.import_official or args.import_chain:
        return _import_mode(args)

    root = Path(args.out_root)
    data_dir = _resolve_data_dir(args.data_dir)
    gt_path = _resolve_gt(args.gt, data_dir)
    library_dir = Path(args.library_dir)
    args.sources_ref = args.sources_ref or _resolve_source("ref")
    args.sources_mineru = args.sources_mineru or _resolve_source("mineru")
    print(f"数据集: {data_dir}\nGT: {gt_path}\n产物库: {library_dir}")
    if not library_dir.is_dir():
        print(f"!! 产物库目录不存在，A② 会读不到 jsonl: {library_dir}")
    if args.sources_ref or args.sources_mineru:
        print(f"三方表固定列: 参考模型={args.sources_ref or '—'} / MinerU={args.sources_mineru or '—'}")

    ts = datetime.now().strftime("%Y%m%d-%H%M")
    run_id = pr.run_id_for(ts, args.tag)
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    preds_dir = Path(args.predictions) if args.predictions else run_dir / "predictions"
    timing, skipped = {}, []

    # ① 抽样（与 predict 同一个函数、同一个 seed：抽样可嵌套是"小批能与基线比"的前提）
    pages = _select_pages(data_dir, args.limit, "", args.seed)
    page_keys = {_key(p.name) for p in pages}
    print(f"抽样 {len(pages)} 页（limit={args.limit} seed={args.seed}）")
    gt_subset = run_dir / "gt_subset.json"
    kept = _filter_gt(gt_path, page_keys, gt_subset)
    print(f"GT 子集: {kept} 页 → {gt_subset}")

    # ② predict
    if args.skip_predict:
        reason = f"predict 跳过（--skip-predict，复用 {preds_dir}）"
        print(f"!! {reason}", flush=True)
        skipped.append(reason)
    else:
        cmd = [sys.executable, str(SCRIPTS / "run_omnidocbench_eval.py"), "predict",
               "--data-dir", str(data_dir), "--predictions", str(preds_dir),
               "--library", args.library, "--limit", str(args.limit), "--seed", str(args.seed)]
        cmd += ["--in-process"] if args.predict_mode == "in-process" else ["--docs-api", args.docs_api]
        t0 = time.time()
        _run_step("② predict（页图→解析→markdown）", cmd, skipped)
        timing["predict"] = time.time() - t0

    # ③ A② ×2（chain / mineru）——都用同一份 GT 子集
    state_json = preds_dir / "state.json"
    for source, name in (("chain", "struct_chain"), ("mineru", "struct_mineru")):
        raw_dir = run_dir / f"_{name}_raw"
        cmd = [sys.executable, str(SCRIPTS / "eval_parse_struct.py"), "--gt", str(gt_subset),
               "--state", str(state_json), "--library-dir", str(library_dir),
               "--out", str(raw_dir), "--pred-source", source]
        t0 = time.time()
        _run_step(f"③ A② 结构层（{source}）", cmd, skipped)
        timing[f"struct_{source}"] = time.time() - t0
        result_json = raw_dir / "structure_result.json"
        if result_json.is_file():
            (run_dir / f"{name}.json").write_text(result_json.read_text(encoding="utf-8"), encoding="utf-8")
            report = raw_dir / "structure_report.md"
            if report.is_file():
                (run_dir / f"{name}_report.md").write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            skipped.append(f"A② {source}: 无 structure_result.json")

    # ④ A① 官方评测器
    if args.skip_official:
        reason = "A① 官方镜像跳过（--skip-official）"
        print(f"!! {reason}", flush=True)
        skipped.append(reason)
    else:
        cmd = [sys.executable, str(SCRIPTS / "run_omnidocbench_eval.py"), "eval",
               "--data-dir", str(data_dir), "--predictions", str(preds_dir), "--out", str(run_dir / "official")]
        t0 = time.time()
        _run_step("④ A① 官方 markdown 评测器（Docker）", cmd, skipped)
        timing["official"] = time.time() - t0

    # ⑤ 归档
    struct_chain = pr.load_structure_metrics(run_dir / "struct_chain.json")
    struct_mineru = pr.load_structure_metrics(run_dir / "struct_mineru.json")
    official = pr.load_official_metrics(run_dir / "official")
    pages_official = pr.official_page_set(run_dir / "official")
    pages_chain = pr.structure_page_set(json.loads((run_dir / "struct_chain.json").read_text(encoding="utf-8"))
                                        if (run_dir / "struct_chain.json").is_file() else {})
    scored = sorted(pages_official | pages_chain)
    if not scored:                     # 两步都没成（全跳过）→ 退回抽样集合，便于人工核对
        scored = sorted(page_keys)
        skipped.append("两层都没产出分数，page_ids 回落为抽样集合")
    official_ref = pr.load_official_metrics(Path(args.sources_ref)) if args.sources_ref else {}
    official_mineru = pr.load_official_metrics(Path(args.sources_mineru)) if args.sources_mineru else {}
    meta = {
        "run_id": run_id, "ts": ts, "kind": "run", "run_date": pr._date_from_ts(ts),
        "args": {"limit": args.limit, "seed": args.seed, "tag": args.tag,
                 "predict_mode": args.predict_mode, "skip_predict": args.skip_predict,
                 "skip_official": args.skip_official, "predictions": str(preds_dir),
                 "data_dir": str(data_dir), "gt": str(gt_path), "library": args.library,
                 "library_dir": str(library_dir)},
        "page_ids": scored, "page_ids_hash": pr.page_ids_hash(scored), "pages_scored": len(scored),
        "pages_sampled": len(pages), "pages_official": len(pages_official), "pages_struct_chain": len(pages_chain),
        "stages": PARSE_STAGES,
        "environment": {**_git_env(), "eval_image": EVAL_IMAGE, "eval_image_id": _docker_image_id()},
        "mineru_version": _mineru_versions(state_json, library_dir),
        "timing": {k: round(v, 1) for k, v in timing.items()},
        "sources": {"ref_official": args.sources_ref, "mineru_official": args.sources_mineru},
        "gt_subset": str(gt_subset), "skipped": skipped,
    }
    delta = _build_delta(root, args.baseline, args.delta_mode, official, struct_chain, scored)
    chain_result = (json.loads((run_dir / "struct_chain.json").read_text(encoding="utf-8"))
                    if (run_dir / "struct_chain.json").is_file() else {})
    mineru_result = (json.loads((run_dir / "struct_mineru.json").read_text(encoding="utf-8"))
                     if (run_dir / "struct_mineru.json").is_file() else {})
    conclusions = pr.build_conclusions(official, struct_chain, struct_mineru, official_ref, official_mineru,
                                       chain_result.get("by_category"), chain_result.get("by_data_source"),
                                       mineru_result.get("by_category"), mineru_result.get("by_data_source"))
    pr.write_json(run_dir / "meta.json", meta)
    (run_dir / "summary.md").write_text(
        pr.render_summary(meta, official, struct_chain, struct_mineru, official_mineru, official_ref, delta,
                          conclusions),
        encoding="utf-8")
    pointer = {"run_id": run_id, "dir": run_id, "ts": ts, "limit": args.limit, "seed": args.seed,
               "page_ids_hash": meta["page_ids_hash"], "kind": "run"}
    pr.write_pointer(root, "latest.json", pointer)
    if args.set_baseline:
        pr.write_pointer(root, "baseline.json", pointer)
        print(f"基线指针已更新（--set-baseline）→ {run_id}")
    elif pr.read_pointer(root, "baseline.json") is None and not args.skip_predict:
        # 首次"真跑"（含 predict）自动成为基线；--skip-predict 的复用式干跑不当基线候选
        pr.write_pointer(root, "baseline.json", pointer)
        print(f"基线指针初始化（首次真跑）→ {run_id}")
    elif pr.read_pointer(root, "baseline.json") is None:
        print("基线指针未设：本次是 --skip-predict 的复用式跑（要钉基线请加 --set-baseline）")

    # ⑥ 看板载荷 +（可选）同步到服务器
    pr.write_publish(run_dir, pr.build_publish_payload(
        meta, official, struct_chain, struct_mineru, delta, official_ref, official_mineru, chain_result,
        conclusions, mineru_result))
    _maybe_publish(args, run_dir)

    # ⑦ 控制台 Δ
    print("\n=== A① 官方口径（我们） ===")
    for key, val in official.items():
        print(f"  {pr.METRIC_LABELS.get(key, key):22} {pr.fmt_metric(val, key in pr.HIGHER_IS_BETTER)}")
    print("\n=== A② 结构层（我们全链） ===")
    for key, val in struct_chain.items():
        print(f"  {pr.METRIC_LABELS.get(key, key):22} {pr.fmt_metric(val, True)}")
    print(f"\n=== Δ vs 基线 {delta.get('baseline_id', '—')} ===")
    if delta.get("gate") != "ok":
        print(f"  不出 Δ：{delta.get('reason', '')}")
    else:
        rel = delta["relation"]
        if not rel["equal"]:
            print(f"  ⚠ 页集合不同（本次 {rel['cur_count']} / 基线 {rel['base_count']} / 交集 {rel['intersection']}）"
                  f"——按交集重算，**非官方重跑口径**")
        for row in (delta.get("groups") or {}).get("official", []):
            print(f"  [A①] {row['label']:22} 本次 {pr.fmt_metric(row['cur'], row['higher_is_better']):>8}"
                  f"  基线 {pr.fmt_metric(row['base'], row['higher_is_better']):>8}  Δ {pr.fmt_delta(row)}")
        for row in (delta.get("groups") or {}).get("struct_chain", []):
            print(f"  [A②] {row['label']:22} 本次 {pr.fmt_metric(row['cur'], True):>8}"
                  f"  基线 {pr.fmt_metric(row['base'], True):>8}  Δ {pr.fmt_delta(row)}")
    print(f"\n归档: {run_dir}")
    print(f"  meta   : {run_dir / 'meta.json'}")
    print(f"  summary: {run_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

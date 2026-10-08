"""gate.load_baseline 指针路径解析回归。

事故（2026-09-07 nightly）：基线在 Windows 机器钉住后拷到 Linux 服务器，指针 raw 为
"data\\evals\\baseline\\<file>"（反斜杠）；POSIX Path().name 不切反斜杠，整串被当文件名
拼出 /app/data/evals/baseline/data\\evals\\baseline\\<file> 双重路径 → FileNotFoundError，
nightly 无结论失败。修复：读侧先归一化分隔符（gate），写侧存 as_posix（compare_runs pin）。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

EVALS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(EVALS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(EVALS_CORE_SRC))

from evals_core.nightly import gate  # noqa: E402
from evals_core.runner import anomaly  # noqa: E402

SNAPSHOT = {
    "run_id": "run-abc123",
    "dataset_id": "open-ragbench-subset-v2",
    "status": "completed",
    "details": [],
}


class LoadBaselinePathTests(unittest.TestCase):
    def _make_baseline_dir(self, raw: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        base = Path(tmp.name)
        json.dump({"label": "L1", "run_id": SNAPSHOT["run_id"],
                   "dataset_id": SNAPSHOT["dataset_id"], "raw": raw},
                  open(base / "baseline_run.json", "w", encoding="utf-8"), ensure_ascii=False)
        json.dump(SNAPSHOT,
                  open(base / "open-ragbench-subset-v2-run-abc123.baseline.json",
                       "w", encoding="utf-8"), ensure_ascii=False)
        self._tmp = tmp
        return base

    def tearDown(self) -> None:
        if hasattr(self, "_tmp"):
            self._tmp.cleanup()

    def test_windows_sep_raw_resolves(self):
        """Windows 钉的基线（反斜杠 raw）在 Linux 上也能按文件名解析（回归 2026-09-07 nightly 事故）。"""
        base = self._make_baseline_dir(r"data\evals\baseline\open-ragbench-subset-v2-run-abc123.baseline.json")
        loaded = gate.load_baseline(base)
        self.assertEqual(loaded.get("run_id"), "run-abc123")
        self.assertEqual(loaded.get("_baseline_label"), "L1")

    def test_posix_raw_resolves(self):
        """as_posix 新格式（pin 修复后）正常解析。"""
        base = self._make_baseline_dir("data/evals/baseline/open-ragbench-subset-v2-run-abc123.baseline.json")
        loaded = gate.load_baseline(base)
        self.assertEqual(loaded.get("run_id"), "run-abc123")

    def test_plain_filename_raw_resolves(self):
        """纯文件名形态（与指针同目录）正常解析。"""
        base = self._make_baseline_dir("open-ragbench-subset-v2-run-abc123.baseline.json")
        loaded = gate.load_baseline(base)
        self.assertEqual(loaded.get("run_id"), "run-abc123")


class PerDatasetBaselinePointerTests(unittest.TestCase):
    """分数据集基线（2026-10-08）：观察集专属指针优先，主集回退全局指针行为不变。

    旧全局单指针下附加观察集（financebench-open-150-v1 等）拿主集基线做交集 →
    题集零交集「无基线可比」、门禁永远空转。"""

    FB_SNAPSHOT = {
        "run_id": "run-fb02d5", "dataset_id": "financebench-open-150-v1",
        "status": "completed",
        "details": [{"question_id": "fb-q1", "status": "completed", "quality": "good",
                     "scores": {"semantic_passed": True}, "all_scores": "{}",
                     "error": "", "latency_ms": 1}],
    }

    def _base(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        base = Path(tmp.name)
        global_raw = "open-ragbench-subset-v2-run-abc123.baseline.json"
        json.dump({"label": "G", "run_id": "run-abc123", "dataset_id": "open-ragbench-subset-v2",
                   "raw": global_raw},
                  open(base / "baseline_run.json", "w", encoding="utf-8"))
        json.dump(SNAPSHOT, open(base / global_raw, "w", encoding="utf-8"))
        fb_raw = "financebench-open-150-v1-run-fb02d5.baseline.json"
        json.dump({"label": "FB", "run_id": "run-fb02d5",
                   "dataset_id": "financebench-open-150-v1", "raw": fb_raw},
                  open(base / "baseline_run.financebench-open-150-v1.json", "w", encoding="utf-8"))
        json.dump(self.FB_SNAPSHOT, open(base / fb_raw, "w", encoding="utf-8"))
        self._tmp = tmp
        return base

    def tearDown(self) -> None:
        if hasattr(self, "_tmp"):
            self._tmp.cleanup()

    def test_owned_pointer_wins_for_its_dataset(self):
        base = self._base()
        loaded = gate.load_baseline(base, dataset_id="financebench-open-150-v1")
        self.assertEqual(loaded.get("run_id"), "run-fb02d5")
        self.assertEqual(loaded.get("_baseline_label"), "FB")

    def test_other_dataset_falls_back_to_global(self):
        base = self._base()
        loaded = gate.load_baseline(base, dataset_id="open-ragbench-subset-v2")
        self.assertEqual(loaded.get("run_id"), "run-abc123")
        self.assertEqual(loaded.get("_baseline_label"), "G")

    def test_no_dataset_id_uses_global(self):
        base = self._base()
        loaded = gate.load_baseline(base)
        self.assertEqual(loaded.get("run_id"), "run-abc123")


class MissingBaselineTests(unittest.TestCase):
    """缺失路径的可操作报错（2026-09-13 实踩：指针被 git 跟踪 → 部署 reset 抹掉刚 pin 的基线）。

    缺指针曾是裸 FileNotFoundError 崩栈，看不出"没钉过"还是"快照丢了"；
    现在两种缺失各给引导语，值班者一步定位。
    """

    def test_missing_pointer_guides_repin(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError) as cm:
                gate.load_baseline(Path(td))
            msg = str(cm.exception)
            self.assertIn("基线指针不存在", msg)
            self.assertIn("compare_runs.py pin", msg)

    def test_missing_snapshot_names_pointer_target(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            json.dump({"label": "L9", "run_id": "run-gone",
                       "raw": "data/evals/baseline/run-gone.baseline.json"},
                      open(base / "baseline_run.json", "w", encoding="utf-8"), ensure_ascii=False)
            with self.assertRaises(FileNotFoundError) as cm:
                gate.load_baseline(base)
            msg = str(cm.exception)
            self.assertIn("基线快照不存在", msg)
            self.assertIn("run-gone", msg)


class BaselineNotTrackedByGitTests(unittest.TestCase):
    """根因回归：基线指针必须**不被 git 跟踪**。

    被跟踪时每次 deploy 的 `git reset --hard origin/main` 都把它覆盖回仓库里那版
    （2026-09-13：R3 钉后 43 分钟被抹，nightly 拿 R2 旧基线跑出假绿灯；R2 是 v2 题集，
    39 道拒答题对门禁永久隐身）。直接查仓库索引，防再次误提交。
    """

    def test_baseline_json_untracked(self):
        """允许 .gitkeep 占位（保证目录存在），但任何 .json（指针/快照）都不许被跟踪。"""
        import subprocess
        repo = Path(__file__).resolve().parents[3]
        out = subprocess.run(["git", "ls-files", "data/evals/baseline/"],
                             cwd=str(repo), capture_output=True, text=True)
        if out.returncode != 0:  # 无 git 环境（源码包分发）跳过
            self.skipTest("非 git 工作副本")
        tracked_json = [line for line in out.stdout.splitlines()
                        if line.strip().endswith(".json")]
        self.assertEqual(
            tracked_json, [],
            f"data/evals/baseline/ 下有被 git 跟踪的基线文件 {tracked_json}——基线是运行时状态，"
            f"被跟踪会在每次部署被 git reset --hard 覆盖（2026-09-13 假绿灯事故）")


class GateJudgeFailToleranceTests(unittest.TestCase):
    """门禁的红档触发器：阈值内放行的判分缺失题不得再把结论打红。

    2026-09-26 补发当天结论时实踩 —— 残余 1 题判分崩、实测 +2.02pp 且 CI 上界 3.94pp（无显著
    回归），门禁却因「新 run 存在未清零异常: judge_fail=1」判红，把流水线刚做的阈值放行顶了回去，
    群里收到的是一条「🔴 评测回归」。豁免只按上层交进来的题号、只豁免判分侧。
    """

    def _reasons(self, anomalies=None, **kwargs):
        return gate.evaluate_gate({}, anomalies if anomalies is not None
                                  else {anomaly.JUDGE_FAIL: ["q-judge-broken"]},
                                  (None, None), None, {}, **kwargs)

    def test_unjudged_questions_red_the_gate_when_not_tolerated(self):
        """没被放行的判分缺失照旧判红（默认严格，豁免必须显式交进来）。"""
        self.assertEqual(self._reasons(), ["新 run 存在未清零异常: judge_fail=1"])
        self.assertEqual(self._reasons(tolerated=[]), ["新 run 存在未清零异常: judge_fail=1"])

    def test_tolerated_judge_fail_does_not_red_the_gate(self):
        self.assertEqual(self._reasons(tolerated=["q-judge-broken"]), [])

    def test_only_the_tolerated_ids_are_exempted(self):
        """题号必须逐字对上：不能因为上层放行了某些题就把整类异常都免掉。"""
        self.assertEqual(self._reasons(tolerated=["别的题"]), ["新 run 存在未清零异常: judge_fail=1"])
        self.assertEqual(self._reasons(anomalies={anomaly.JUDGE_FAIL: ["a", "b"]}, tolerated=["a"]),
                         ["新 run 存在未清零异常: judge_fail=1"])

    def test_exec_error_is_never_exempted(self):
        """问答链路本身炸的题不在豁免范围 —— 即便上层把它的题号一起交进来。"""
        anomalies = {anomaly.JUDGE_FAIL: ["a"], anomaly.EXEC_ERROR: ["b"]}
        self.assertEqual(self._reasons(anomalies, tolerated=["a", "b"]),
                         ["新 run 存在未清零异常: exec_error=1"])

    def test_slow_stays_out_of_the_gate_as_before(self):
        self.assertEqual(self._reasons({anomaly.SLOW: ["q1", "q2"]}, tolerated=["q1"]), [])


if __name__ == "__main__":
    unittest.main()

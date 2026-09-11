"""nightly 路径约定：全部从 result_store._DB_PATH 推导（容器/本机同构），env 可覆写供测试。

data 根目录结构（deploy 的 ../data 卷挂载，aichat-api 容器内即 /app/data）：
  data/evals/evals.sqlite
  data/evals/nightly/<YYYY-MM-DD>/{nightly.json,report.md}   ← 结论存档（保留 30 天）
  data/evals/nightly_settings.json                            ← 调度配置
  data/evals/baseline/                                        ← 钉住的基线快照
  data/evals/datasets/<dataset_id>.json                       ← 题集（题干摘录来源）
  data/open_ragbench/subset/subset_manifest_v2.json           ← 题型归属 manifest
"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from evals_core.storage import result_store

BJT = timezone(timedelta(hours=8))
# v3 = v2(487) + 拒答集 v2(39) 合并；拒答题带 refusal_expected，报告「拒答专项」自动拆分
DATASET_DEFAULT = "open-ragbench-subset-v3"
MANIFEST_DEFAULT = "open_ragbench/subset/subset_manifest_v3.json"


def _db_path() -> Path:
    return Path(result_store._DB_PATH)


def data_root() -> Path:
    """data/ 根（evals.sqlite 在 data/evals/ 下）。"""
    return _db_path().resolve().parent.parent


def evals_dir() -> Path:
    return _db_path().parent


def nightly_root() -> Path:
    env = os.getenv("NIGHTLY_ROOT", "").strip()
    return Path(env) if env else evals_dir() / "nightly"


def settings_file() -> Path:
    env = os.getenv("NIGHTLY_SETTINGS_FILE", "").strip()
    return Path(env) if env else evals_dir() / "nightly_settings.json"


def baseline_dir() -> Path:
    env = os.getenv("NIGHTLY_BASELINE_DIR", "").strip()
    return Path(env) if env else evals_dir() / "baseline"


def dataset_json_path(dataset_id: str) -> Path:
    env_dir = os.getenv("NIGHTLY_DATASET_DIR", "").strip()
    base = Path(env_dir) if env_dir else evals_dir() / "datasets"
    return base / f"{dataset_id}.json"


def manifest_path() -> Path:
    env = os.getenv("NIGHTLY_MANIFEST", "").strip()
    return Path(env) if env else data_root() / MANIFEST_DEFAULT


def today_bjt() -> str:
    return datetime.now(BJT).strftime("%Y-%m-%d")


def now_bjt_iso(timespec: str = "seconds") -> str:
    return datetime.now(BJT).isoformat(timespec=timespec)

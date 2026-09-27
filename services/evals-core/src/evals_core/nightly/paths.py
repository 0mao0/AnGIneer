"""nightly 路径约定：全部从 result_store._DB_PATH 推导（容器/本机同构），env 可覆写供测试。

data 根目录结构（deploy 的 ../data 卷挂载，aichat-api 容器内即 /app/data）：
  data/evals/evals.sqlite
  data/evals/nightly/<YYYY-MM-DD>/runs/<HHMM-6hex>/{nightly.json,report.md,material_parity.*}
      ← 结论存档：每 run 一挡（2026-09-27 起同日多跑互不覆盖；保留 90 天，见 archive.KEEP_DAYS_DEFAULT）
  data/evals/nightly/<YYYY-MM-DD>/{nightly.json,report.md,...}
      ← 旧版「当日单档」布局，只读兼容（列表照样出现、老档不迁移）
  data/evals/nightly_settings.json                            ← 调度配置
  data/evals/baseline/                                        ← 钉住的基线快照
  data/evals/datasets/<dataset_id>.json                       ← 题集（题干摘录来源）
  data/open_ragbench/subset/subset_manifest_v2.json           ← 题型归属 manifest
"""
import os
import uuid
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


def new_run_slot() -> str:
    """归档挡位名（runs/<slot>/ 目录）：北京时间 HHMM + 6 位随机后缀。

    同日多跑各占一挡、互不覆盖；随机后缀防同分钟双派发撞名。
    注意与 nightly_control 里调度器的 slot（每日排班去重键）不是一回事。"""
    return datetime.now(BJT).strftime("%H%M") + "-" + uuid.uuid4().hex[:6]

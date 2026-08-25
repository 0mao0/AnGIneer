"""共享路径、常量、端点与 JSON 读写。"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "open_ragbench"
RAW_DIR = DATA_DIR / "raw"
PDF_DIR = DATA_DIR / "pdfs"
SUBSET_DIR = DATA_DIR / "subset"
REPORTS_DIR = DATA_DIR / "reports"
LOGS_DIR = DATA_DIR / "logs"

SUBSET_MANIFEST = SUBSET_DIR / "subset_manifest.json"
IMPORT_STATE = SUBSET_DIR / "import_state.json"
KEYS_FILE = SUBSET_DIR / "keys.json"
EVAL_DATASET_FILE = REPO_ROOT / "data" / "evals" / "datasets" / "open-ragbench-subset-v1.json"

DATASET_ID = "open-ragbench-subset-v1"
LIBRARY_NAME = "OpenRAGBenchmark-Subset"
KEY_USER_NAME = "openragbench-subset"
STAGES = "all"
SOURCES = ["text", "text-image", "text-table", "text-table-image"]

HF_FILES = {
    "pdf_urls.json": "pdf/arxiv/pdf_urls.json",
    "queries.json": "pdf/arxiv/queries.json",
    "answers.json": "pdf/arxiv/answers.json",
    "qrels.json": "pdf/arxiv/qrels.json",
}


def ensure_dirs() -> None:
    for directory in (RAW_DIR, PDF_DIR, SUBSET_DIR, REPORTS_DIR, LOGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


class Endpoints:
    def __init__(self, docs_api: str = "http://localhost:8790", aichat_api: str = "http://localhost:8791"):
        self.docs_api = docs_api.rstrip("/")
        self.aichat_api = aichat_api.rstrip("/")

    @property
    def login(self) -> str:
        return f"{self.docs_api}/api/v1/auth/login"

    @property
    def libraries(self) -> str:
        return f"{self.docs_api}/api/knowledge/libraries"

    @property
    def api_keys(self) -> str:
        return f"{self.docs_api}/api/api-keys"

    @property
    def parse(self) -> str:
        return f"{self.docs_api}/api/v1/documents/parse"

    def status(self, doc_id: str) -> str:
        return f"{self.docs_api}/api/v1/documents/{doc_id}/status"

    @property
    def eval_import(self) -> str:
        return f"{self.aichat_api}/api/evals/datasets/import"

    @property
    def eval_runs(self) -> str:
        return f"{self.aichat_api}/api/evals/runs"

    def eval_run(self, run_id: str) -> str:
        return f"{self.aichat_api}/api/evals/runs/{run_id}"

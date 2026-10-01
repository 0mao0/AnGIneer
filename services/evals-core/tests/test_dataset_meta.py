"""eval_dataset.meta（题集卡元信息）存取与迁移回归。"""

import sys
import tempfile
import unittest
from pathlib import Path

EVALS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(EVALS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(EVALS_CORE_SRC))

from evals_core.dataset import manager
from evals_core.storage import result_store

META = {
    "publisher": "Patronus AI",
    "domain": "金融",
    "purpose": "测 SEC 申报文件开放问答",
    "source_url": "https://github.com/patronus-ai/financebench",
    "distribution": [{"label": "metrics-generated", "count": 50}],
    "leaderboard": [{"label": "GPT-4-Turbo 单库RAG", "score": "50%"}],
}

PAYLOAD = {
    "dataset": {
        "dataset_id": "meta-card-test",
        "title": "meta card test",
        "schema_version": "eval.bundle.v2",
        "version": "1.0",
        "library_id": "default",
        "meta": META,
    },
    "items": [
        {
            "question_id": "mq-1",
            "question": "q",
            "task_type": "definition",
            "intent_level": "L1",
            "library_id": "default",
        },
    ],
}


class DatasetMetaStoreTests(unittest.TestCase):
    """meta 列的存取、更新白名单、脏数据兜底与旧库迁移。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._original_db_path = result_store._DB_PATH
        self._original_local = result_store._LOCAL
        self._original_datasets_dir = manager._DATASETS_DIR
        result_store._DB_PATH = str(Path(self._tmp.name) / "evals.sqlite")
        result_store._LOCAL = None
        manager._DATASETS_DIR = str(Path(self._tmp.name) / "datasets")

    def tearDown(self) -> None:
        local = result_store._get_thread_local()
        conn = getattr(local, "conn", None)
        if conn is not None:
            conn.close()
        result_store._LOCAL = self._original_local
        result_store._DB_PATH = self._original_db_path
        manager._DATASETS_DIR = self._original_datasets_dir
        self._tmp.cleanup()

    def test_update_dataset_writes_and_reads_meta(self) -> None:
        """update_dataset 写 meta 后 get 返回原 dict；title 等其它字段不受影响。"""
        manager.import_bundle(PAYLOAD, source_file="test.json")
        updated = manager.update_dataset("meta-card-test", {"meta": META})
        self.assertEqual(updated["meta"], META)
        self.assertEqual(updated["title"], "meta card test")
        row = manager.get_dataset("meta-card-test")
        self.assertEqual(row["meta"], META)

    def test_dirty_meta_falls_back_to_empty_dict(self) -> None:
        """meta 列为非法 JSON 时读出 {}，接口不炸。"""
        manager.import_bundle(PAYLOAD, source_file="test.json")
        conn = result_store._get_conn()
        conn.execute(
            "UPDATE eval_dataset SET meta = 'not-json' WHERE dataset_id = ?",
            ("meta-card-test",),
        )
        conn.commit()
        row = manager.get_dataset("meta-card-test")
        self.assertEqual(row["meta"], {})

    def test_import_export_round_trips_meta(self) -> None:
        """bundle 带 meta 导入 → get/export 原样保留。"""
        payload = {
            "dataset": {**PAYLOAD["dataset"]},
            "items": [dict(item) for item in PAYLOAD["items"]],
        }
        manager.import_bundle(payload, source_file="roundtrip.json")
        row = manager.get_dataset("meta-card-test")
        self.assertEqual(row["meta"], META)
        exported = manager.export_dataset("meta-card-test")
        self.assertEqual(exported["dataset"]["meta"], META)

    def test_import_without_meta_defaults_empty(self) -> None:
        """不带 meta 的 bundle 导入后 meta 为 {}（旧题集兼容）。"""
        payload = {
            "dataset": {
                "dataset_id": "no-meta-test",
                "title": "no meta test",
                "schema_version": "eval.bundle.v2",
                "version": "1.0",
                "library_id": "default",
            },
            "items": [dict(item) for item in PAYLOAD["items"]],
        }
        manager.import_bundle(payload, source_file="nometa.json")
        row = manager.get_dataset("no-meta-test")
        self.assertEqual(row["meta"], {})

    def test_legacy_db_without_meta_column_migrates(self) -> None:
        """旧库（无 meta 列）经 init_db 自动补列：存量行读出 {}，且可继续写 meta。"""
        result_store.init_db()
        conn = result_store._get_conn()
        conn.executescript("""
            DROP TABLE eval_dataset;
            CREATE TABLE eval_dataset (
                dataset_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'knowledge',
                description TEXT NOT NULL DEFAULT '',
                schema_version TEXT NOT NULL DEFAULT 'eval.bundle.v2',
                version TEXT NOT NULL DEFAULT '1.0',
                library_id TEXT NOT NULL DEFAULT 'default',
                question_count INTEGER NOT NULL DEFAULT 0,
                source_file TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO eval_dataset (dataset_id, title) VALUES ('legacy-1', 'legacy');
        """)
        conn.commit()
        conn.close()
        result_store._LOCAL = None  # 强制重连，下次 manager 调用触发 init_db 迁移

        rows = manager.list_datasets()
        legacy = next(r for r in rows if r["dataset_id"] == "legacy-1")
        self.assertEqual(legacy["meta"], {})
        updated = manager.update_dataset("legacy-1", {"meta": {"publisher": "AnGIneer"}})
        self.assertEqual(updated["meta"], {"publisher": "AnGIneer"})


if __name__ == "__main__":
    unittest.main()

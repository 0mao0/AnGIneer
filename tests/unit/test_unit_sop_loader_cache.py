"""SOP 加载缓存单测（需求 §5.6）：mtime 信号失效（跨实例写可见）+ TTL=0 停用。

回归动机：原实现每请求全量重读 60 个 JSON + 因 raw/ 黑板缺失每请求重写 index.json
（实测 ~47ms/请求 + 一次磁盘写）；缓存化后写路径（含 sop_routes 的独立 loader 实例）
落盘 → mtime 变化 → 下次 load_all 自动重建。
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-core/src")))

from sop_core.sop_loader import SopLoader  # noqa: E402


def write_sop(sop_dir, sop_id, payload):
    os.makedirs(sop_dir, exist_ok=True)
    with open(os.path.join(sop_dir, f"{sop_id}.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def make_sop(sop_id, status="published"):
    return {
        "id": sop_id,
        "name_zh": f"SOP {sop_id}",
        "description": f"desc {sop_id}",
        "status": status,
        "blackboard": {"required": [], "outputs": ["result"]},
        "steps": [{"id": "s1", "tool": "auto"}],
    }


class SopLoaderCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sop_base = self._tmp.name
        self.json_dir = os.path.join(self.sop_base, "json")
        write_sop(self.json_dir, "sop-a", make_sop("sop-a"))
        write_sop(self.json_dir, "sop-b", make_sop("sop-b", status="draft"))
        self._old_ttl = os.environ.get("ANGINEER_SOP_CACHE_TTL")
        os.environ.pop("ANGINEER_SOP_CACHE_TTL", None)

    def tearDown(self):
        if self._old_ttl is None:
            os.environ.pop("ANGINEER_SOP_CACHE_TTL", None)
        else:
            os.environ["ANGINEER_SOP_CACHE_TTL"] = self._old_ttl
        self._tmp.cleanup()

    def _index_mtime_ns(self):
        return os.stat(os.path.join(self.sop_base, "index.json")).st_mtime_ns

    def test_cache_hit_no_index_rewrite_and_shared_objects(self):
        loader = SopLoader(self.sop_base)
        first = loader.load_all()
        self.assertEqual([s.id for s in first], ["sop-a"])  # draft 不可见
        mtime = self._index_mtime_ns()
        second = loader.load_all()
        self.assertIs(second[0], first[0])  # 命中共享对象
        self.assertEqual(self._index_mtime_ns(), mtime)  # 重复 load 不重写 index.json

    def test_blackboard_less_raw_sop_no_per_request_rewrite(self):
        # 回归核心：raw/ 无黑板 SOP 在旧实现会触发每请求 refresh_index 重写 index.json
        raw_dir = os.path.join(self.sop_base, "raw")
        os.makedirs(raw_dir, exist_ok=True)
        with open(os.path.join(raw_dir, "raw-sop.md"), "w", encoding="utf-8") as f:
            f.write("# raw SOP\n\n步骤说明")
        loader = SopLoader(self.sop_base)
        loader.load_all()
        mtime = self._index_mtime_ns()
        for _ in range(3):
            loader.load_all()
        self.assertEqual(self._index_mtime_ns(), mtime)

    def test_cross_instance_write_visible(self):
        writer = SopLoader(self.sop_base)
        reader = SopLoader(self.sop_base)
        self.assertEqual([s.id for s in reader.load_all()], ["sop-a"])
        self.assertTrue(writer.update_status("sop-b", "published"))
        self.assertEqual([s.id for s in reader.load_all()], ["sop-a", "sop-b"])  # mtime 失效生效

    def test_ttl_zero_disables_cache(self):
        os.environ["ANGINEER_SOP_CACHE_TTL"] = "0"
        loader = SopLoader(self.sop_base)
        first = loader.load_all()
        second = loader.load_all()
        self.assertIsNot(second[0], first[0])  # 每次重建 → 新对象（等价旧行为）


if __name__ == "__main__":
    unittest.main()

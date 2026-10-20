import hashlib
import io
import json
import os
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from docs_core.corpus_package import (  # noqa: E402
    BundleError,
    REEMBED_BLOCK_MESSAGE,
    check_conflict_gate,
    check_embed_gate,
    check_package_files,
    open_bundle,
)


# ---------------------------------------------------------------- v2 bundle（P2-1）

_EMBED = "model-A"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _inner_zip_bytes(lib_id: str, *, embed: str = _EMBED, tamper_file: bool = False,
                     drop_file: bool = False) -> bytes:
    entries = {
        "registry/rows.json": json.dumps(
            {"libraries": [{"library_id": lib_id, "group_name": "g"}], "groups": []}).encode(),
        "meta/rows.json": json.dumps({"nodes": [], "tree_nodes": [], "libraries": []}).encode(),
        "index/index.sqlite": b"sqlite-bytes",
        "graph/graph.sqlite": b"graph-bytes",
        f"files/knowledge/libraries/{lib_id}/a.txt": b"a",
    }
    files_manifest = {arc: _sha(data) for arc, data in entries.items()}
    if tamper_file:
        entries["index/index.sqlite"] = b"TAMPERED"  # manifest 记的还是原文 sha
    if drop_file:
        entries.pop("graph/graph.sqlite")  # manifest 里仍在 → 缺文件
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for arc, data in entries.items():
            z.writestr(zipfile.ZipInfo(arc), data)
        man = {"kind": "library", "schema_version": 2, "library_id": lib_id, "name": lib_id,
               "group_name": "g", "embed_model": embed, "page_base": 0,
               "counts": {}, "files": files_manifest}
        z.writestr(zipfile.ZipInfo("manifest.json"), json.dumps(man))
    return buf.getvalue()


def _bundle_zip(path: Path, libs=("lib-a",), *, embed: str = _EMBED,
                corrupt_inner_sha: bool = False, corrupt_bytes: bool = False,
                schema: int = 2, **inner_kwargs) -> Path:
    blobs = {lib: _inner_zip_bytes(lib, embed=embed, **inner_kwargs) for lib in libs}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        lib_entries = []
        for lib in libs:
            blob = blobs[lib]
            z.writestr(zipfile.ZipInfo(f"libraries/{lib}.zip"), blob)
            digest = "0" * 64 if corrupt_inner_sha else _sha(blob)
            entry = f"libraries/{lib}.zip"
            lib_entries.append({"library_id": lib, "name": lib, "group_name": "g",
                                "entry": entry, "sha256": digest,
                                "bytes": len(blob) + (7 if corrupt_bytes else 0), "counts": {}})
        outer = {"kind": "bundle", "schema_version": schema, "embed_model": embed, "page_base": 0,
                 "libraries": lib_entries, "files": {}}
        z.writestr(zipfile.ZipInfo("manifest.json"), json.dumps(outer))
    return path


class V2OpenBundleTests(unittest.TestCase):
    def _with_bundle(self, td, **kwargs):
        path = _bundle_zip(Path(td) / "std-20261018.zip", ("lib-a", "lib-b"), **kwargs)
        return open_bundle(path)

    def test_open_bundle_spools_and_exposes_manifests(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with self._with_bundle(td) as b:
                self.assertEqual(b.mode, "bundle")
                self.assertEqual(b.embed_model, _EMBED)
                self.assertEqual([lb.library_id for lb in b.libraries], ["lib-a", "lib-b"])
                for lb in b.libraries:
                    self.assertEqual(lb.manifest["kind"], "library")
                    self.assertTrue(lb.zip_path.is_file())
                    self.assertIn(f"files/knowledge/libraries/{lb.library_id}/a.txt", lb.files_index)
                    with lb.open_entry("registry/rows.json") as f:
                        self.assertEqual(json.loads(f.read())["libraries"][0]["library_id"], lb.library_id)
            # close 后临时文件清除
            for lb in b.libraries:
                self.assertFalse(lb.zip_path.exists())

    def test_single_library_zip_accepted(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            inner = Path(td) / "lib-a.zip"
            inner.write_bytes(_inner_zip_bytes("lib-a"))
            with open_bundle(inner) as b:
                self.assertEqual(b.mode, "library")
                self.assertEqual([lb.library_id for lb in b.libraries], ["lib-a"])

    def test_schema_999_aborts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            path = _bundle_zip(Path(td) / "x.zip", ("lib-a",), schema=999)
            with self.assertRaises(BundleError):
                with open_bundle(path):
                    pass

    def test_v1_directory_rejected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(BundleError) as ctx:
                with open_bundle(Path(td)):
                    pass
            self.assertIn("v1", str(ctx.exception))

    def test_schema_1_rejected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            path = _bundle_zip(Path(td) / "v1.zip", ("lib-a",), schema=1)
            with self.assertRaises(BundleError):
                with open_bundle(path):
                    pass

    def test_inner_embed_model_inconsistent_with_outer_aborts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            # 手工拼不一致：外层 model-A + 内层 model-B
            blob = _inner_zip_bytes("lib-a", embed="model-B")
            path = Path(td) / "z.zip"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
                z.writestr(zipfile.ZipInfo("libraries/lib-a.zip"), blob)
                outer = {"kind": "bundle", "schema_version": 2, "embed_model": _EMBED, "page_base": 0,
                         "libraries": [{"library_id": "lib-a", "name": "lib-a", "group_name": "g",
                                        "entry": "libraries/lib-a.zip", "sha256": _sha(blob),
                                        "bytes": len(blob), "counts": {}}], "files": {}}
                z.writestr(zipfile.ZipInfo("manifest.json"), json.dumps(outer))
            with self.assertRaises(BundleError):
                with open_bundle(path):
                    pass


class V2IntegrityTests(unittest.TestCase):
    def test_valid_bundle_passes(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with open_bundle(_bundle_zip(Path(td) / "ok.zip", ("lib-a", "lib-b"))) as b:
                check_package_files(b)  # 不抛

    def test_outer_sha_mismatch_aborts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with open_bundle(_bundle_zip(Path(td) / "bad.zip", ("lib-a",), corrupt_inner_sha=True)) as b:
                with self.assertRaises(BundleError) as ctx:
                    check_package_files(b)
                self.assertIn("sha256", str(ctx.exception))

    def test_outer_bytes_mismatch_aborts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with open_bundle(_bundle_zip(Path(td) / "bad.zip", ("lib-a",), corrupt_bytes=True)) as b:
                with self.assertRaises(BundleError):
                    check_package_files(b)

    def test_inner_file_tampered_aborts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with open_bundle(_bundle_zip(Path(td) / "t.zip", ("lib-a",), tamper_file=True)) as b:
                with self.assertRaises(BundleError) as ctx:
                    check_package_files(b)
                self.assertIn("index/index.sqlite", str(ctx.exception))

    def test_missing_inner_file_aborts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with open_bundle(_bundle_zip(Path(td) / "m.zip", ("lib-a",), drop_file=True)) as b:
                with self.assertRaises(BundleError) as ctx:
                    check_package_files(b)
                self.assertIn("graph/graph.sqlite", str(ctx.exception))


class V2GateTests(unittest.TestCase):
    def test_embed_gate_v2_mismatch_aborts_with_recourse(self):
        with self.assertRaises(BundleError) as ctx:
            check_embed_gate({"embed_model": "model-A"}, env_model="model-B")
        msg = str(ctx.exception)
        self.assertTrue(msg.startswith(REEMBED_BLOCK_MESSAGE))
        self.assertIn("不支持 reembed", msg)
        self.assertIn("重新导出", msg)

    def test_embed_gate_v2_match_and_empty(self):
        check_embed_gate({"embed_model": "model-A"}, env_model="model-A")  # 不抛
        with self.assertRaises(BundleError):
            check_embed_gate({"embed_model": ""}, env_model="model-A")

    def test_conflict_gate_reports_library_collection_index(self):
        result = check_conflict_gate(
            package_libs=[{"library_id": "lib-a"}, {"library_id": "lib-b"}],
            package_node_ids=["n-new"],
            target_library_ids={"lib-a"},
            target_node_ids={"n-old"},
            target_collections={"lib-b", "standards"},   # lib-b 的桶名（=lib_id）被占
            existing_index_files=["lib-b"],
        )
        joined = " | ".join(result["clashes"])
        self.assertIn("lib-a", joined)        # 同名库
        self.assertIn("lib-b", joined)        # collection 名冲突 + index.sqlite 已存在
        self.assertEqual(result["warnings"], [])

    def test_conflict_gate_clean_passes(self):
        result = check_conflict_gate(
            package_libs=[{"library_id": "lib-new"}],
            package_node_ids=["n-new"],
            target_library_ids={"lib-old"},
            target_node_ids={"n-old"},
            target_collections={"standards"},
            existing_index_files=[],
        )
        self.assertEqual(result["clashes"], [])

    def test_conflict_gate_entity_name_warning(self):
        result = check_conflict_gate(
            package_libs=[{"library_id": "lib-new"}],
            package_node_ids=[],
            target_library_ids=set(), target_node_ids=set(),
            target_collections=set(), existing_index_files=[],
            package_entities=[{"entity_id": "e-pkg", "name": "码头前沿", "library_id": "lib-other"}],
            target_entities={("码头前沿", "lib-other"): "e-target"},
        )
        self.assertEqual(result["clashes"], [])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("码头前沿", result["warnings"][0])


if __name__ == "__main__":
    unittest.main()

import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path


class NonSeekableSink:
    """模拟 HTTP 响应流：只能顺序写（无 seek/tell）。"""

    def __init__(self):
        self.data = bytearray()

    def write(self, b):
        self.data.extend(b)
        return len(b)

    def flush(self):
        pass


class ZipByteCounter:
    """计数/sha256 wrapper，只暴露 write/flush。

    zipfile 构造内层 ZipFile 时探测 tell()，AttributeError/OSError 即判定不可 seek，
    自动走 _Tellable + data descriptor 流式路径（实测 py3.11.17 容器 / py3.12.6 本机一致）。
    """

    def __init__(self, fh):
        self._fh = fh
        self.sha = hashlib.sha256()
        self.nbytes = 0

    def write(self, b):
        self.sha.update(b)
        self.nbytes += len(b)
        return self._fh.write(b)

    def flush(self):
        return self._fh.flush()


_PAYLOAD = [
    ("index/index.sqlite", b"SQLite format 3\x00" + bytes(1024)),
    ("files/knowledge/libraries/lib-a/documents/d1/source/a.pdf", b"%PDF-1.5 " + bytes(range(256)) * 50),
]


def _build_nested_bundle(force_zip64: bool = False):
    sink = NonSeekableSink()
    outer = zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED)
    counter = None
    with outer.open("libraries/lib-a.zip", "w") as entry:
        counter = ZipByteCounter(entry)
        inner = zipfile.ZipFile(counter, "w", zipfile.ZIP_STORED)
        for name, payload in _PAYLOAD:
            with inner.open(zipfile.ZipInfo(name), "w", force_zip64=force_zip64) as f:
                f.write(payload)
        inner.close()
    outer.writestr("manifest.json", b'{"schema_version": 2, "kind": "bundle"}')
    outer.close()
    return bytes(sink.data), counter


class NestedZipStreamTests(unittest.TestCase):
    """P1-1 spike 结论固化（docs/plan-kb-per-library-package.md Task P1-1）。

    实测记录（2026-10-17，py3.11.17 容器 / py3.12.6 本机，结论一致）：
    - 内层 zip 流式写进外层 entry 写句柄可行，外层 sink 不可 seek 无碍；
    - 契约选择 ZipByteCounter（无 tell）强制 data descriptor 路径：确定性跨版本，
      并顺带产出 sha256/字节数供 manifest（naive 直传外层句柄也可行，但依赖
      _ZipWriteFile.tell() 抛 OSError 的隐式行为，不作契约）；
    - force_zip64=True 小文件走通（>4G 内层包 zip64 路径的廉价回归）；
    - 坑与兜底：若未来某 Python 版本破坏该路径，替代法=内层 zip 先落临时文件再流入外层。
    """

    def test_stream_counter_is_last_and_hashes_match(self):
        blob, counter = _build_nested_bundle()
        outer = zipfile.ZipFile(io.BytesIO(blob))
        self.assertEqual(outer.testzip(), None)
        self.assertEqual(outer.namelist(), ["libraries/lib-a.zip", "manifest.json"])
        inner_bytes = outer.read("libraries/lib-a.zip")
        self.assertEqual(len(inner_bytes), counter.nbytes)
        self.assertEqual(hashlib.sha256(inner_bytes).hexdigest(), counter.sha.hexdigest())

    def test_inner_zip_valid_and_streaming_flags(self):
        blob, _ = _build_nested_bundle()
        inner_bytes = zipfile.ZipFile(io.BytesIO(blob)).read("libraries/lib-a.zip")
        inner = zipfile.ZipFile(io.BytesIO(inner_bytes))
        self.assertEqual(inner.testzip(), None)
        for name, payload in _PAYLOAD:
            self.assertEqual(inner.read(name), payload)
            self.assertTrue(inner.getinfo(name).flag_bits & 0x08, name)  # bit3=data descriptor=流式写入

    def test_inner_zip_is_standalone_extractable(self):
        blob, _ = _build_nested_bundle()
        inner_bytes = zipfile.ZipFile(io.BytesIO(blob)).read("libraries/lib-a.zip")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "lib-a.zip"
            p.write_bytes(inner_bytes)
            with zipfile.ZipFile(p) as standalone:  # 单独交付形态：小包可独立解出
                self.assertEqual(standalone.testzip(), None)
                names = standalone.namelist()
            self.assertEqual(sorted(names), sorted(n for n, _ in _PAYLOAD))

    def test_force_zip64_small_entry_streams(self):
        blob, _ = _build_nested_bundle(force_zip64=True)
        inner_bytes = zipfile.ZipFile(io.BytesIO(blob)).read("libraries/lib-a.zip")
        inner = zipfile.ZipFile(io.BytesIO(inner_bytes))
        self.assertEqual(inner.testzip(), None)
        for name, payload in _PAYLOAD:
            self.assertEqual(inner.read(name), payload)


if __name__ == "__main__":
    unittest.main()

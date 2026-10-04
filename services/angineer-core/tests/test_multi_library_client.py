"""retrieve 载荷：library_ids 透传；不传时载荷无该键（旧服务端兼容）。"""
from angineer_core.docs_retrieval_client import DocsRetrievalClient


class _FakeResponse:
    # 现码不读 raise_for_status，判 resp.status_code != 200（docs_retrieval_client.py:99）
    status_code = 200

    def raise_for_status(self): pass

    def json(self): return {"items": [], "total": 0}


class TestRetrievePayloadLibraryIds:
    def test_multi_adds_library_ids(self, monkeypatch):
        captured = {}
        def fake_post(url, json=None, **kwargs):
            assert url.endswith("/api/knowledge/internal/retrieve")  # 端点钉死（A6 定稿路径）
            captured.update(json or {})
            return _FakeResponse()
        monkeypatch.setattr("requests.post", fake_post)  # 实名已核验：docs_retrieval_client.py:12 用 requests
        client = DocsRetrievalClient(base_url="http://x")
        client.retrieve(
            mode="text", query="q", library_id="libA",
            library_ids=["libA", "libB"], top_k=20,
        )
        assert captured["library_ids"] == ["libA", "libB"]
        assert captured["library_id"] == "libA"

    def test_single_omits_library_ids(self, monkeypatch):
        captured = {}
        def fake_post(url, json=None, **kwargs):
            assert url.endswith("/api/knowledge/internal/retrieve")
            captured.update(json or {})
            return _FakeResponse()
        monkeypatch.setattr("requests.post", fake_post)
        client = DocsRetrievalClient(base_url="http://x")
        client.retrieve(mode="text", query="q", library_id="libA", top_k=20)
        assert "library_ids" not in captured

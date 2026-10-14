# -*- coding: utf-8 -*-
"""SOP 链路冒烟（evals_core.chain_smoke）单测：HTTP 与客户端导入两处接缝注入假实现。

不碰真实服务；覆盖 ok/warn/fail 三态聚合、快照兜底检出（H2 的诚实信号）、
bundle 缺字段检出与卡片行裁剪。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/evals-core/src")))

from evals_core import chain_smoke


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def _fake_request(routes):
    """routes: {url 片段: _Resp | 返回 _Resp 的 callable}；未命中抛错（防漏桩）。"""
    def _req(method, url, **kw):
        for frag, resp in routes.items():
            if frag in url:
                return resp() if callable(resp) else resp
        raise AssertionError(f"未打桩的请求: {method} {url}")
    return _req


_OK_ROUTES = {
    "/api/sops/full": _Resp(200, {"sops": [{"id": "s1"}]}),
    "/api/graph/entities/search": _Resp(200, [{"entity_id": "e1", "name": "边坡"}]),
    "/api/graph/relations/": _Resp(200, [{"library_id": "l", "doc_id": "d"}]),
    "/api/sops/synthesize": _Resp(412, {}),
}


class SeverityTests(unittest.TestCase):
    def _run(self, routes, **kw):
        with mock.patch.object(chain_smoke, "_request", _fake_request(routes)), \
                mock.patch.object(chain_smoke, "_import_client", lambda *a: None):
            return chain_smoke.run_smoke(
                sop_api_url="http://s1", docs_api_url="http://d1", **kw)

    def _status(self, result):
        return {h["name"]: h["status"] for h in result["hops"]}

    def test_all_ok_with_skips(self):
        """全端点健康：ok 收口；客户端不可导入只降为 skip，不拖低 severity。"""
        r = self._run(_OK_ROUTES)
        self.assertEqual(r["severity"], "ok")
        st = self._status(r)
        self.assertEqual(st["sop-api /api/sops/full"], "ok")
        self.assertEqual(st["docs-api 关系端点"], "ok")
        self.assertEqual(st["sop-api /synthesize 活性"], "ok")
        self.assertEqual(st["aichat→sop-api 真客户端"], "skip")
        self.assertIn("跳跳过", chain_smoke.render_line(r))

    def test_empty_graph_is_warn_not_fail(self):
        routes = dict(_OK_ROUTES)
        routes["/api/graph/entities/search"] = _Resp(200, [])
        r = self._run(routes)
        self.assertEqual(r["severity"], "warn")
        self.assertEqual(self._status(r)["docs-api 关系端点"], "skip")

    def test_relation_field_missing_fails(self):
        """Task1 字段契约（library_id/doc_id 序列化）：缺即链语义已坏。"""
        routes = dict(_OK_ROUTES)
        routes["/api/graph/relations/"] = _Resp(200, [{"source_id": "x"}])
        r = self._run(routes)
        self.assertEqual(r["severity"], "fail")
        self.assertIn("library_id/doc_id", self._status_detail(r, "docs-api 关系端点"))

    def _status_detail(self, result, name):
        return next(h["detail"] for h in result["hops"] if h["name"] == name)

    def test_entity_missing_fields_fails(self):
        routes = dict(_OK_ROUTES)
        routes["/api/graph/entities/search"] = _Resp(200, [{"name": "缺 entity_id"}])
        self.assertEqual(self._run(routes)["severity"], "fail")

    def test_sop_api_down_fails(self):
        routes = dict(_OK_ROUTES)
        routes["/api/sops/full"] = _Resp(503)
        routes["/api/sops/synthesize"] = _Resp(502)
        self.assertEqual(self._run(routes)["severity"], "fail")

    def test_synthesize_403_is_warn_404_is_fail(self):
        """403=打到公网门（改走内网口即可）；404=部署不含 L4 端点（硬失败）。"""
        routes = dict(_OK_ROUTES)
        routes["/api/sops/synthesize"] = _Resp(403)
        self.assertEqual(self._run(routes)["severity"], "warn")
        routes = dict(_OK_ROUTES)
        routes["/api/sops/synthesize"] = _Resp(404)
        self.assertEqual(self._run(routes)["severity"], "fail")

    def test_library_filter_variant_probed_when_lib_given(self):
        r = self._run(_OK_ROUTES, library_id="lib-x")
        self.assertEqual(self._status(r)["实体搜索·按库过滤"], "ok")


class ClientHopTests(unittest.TestCase):
    """H2 诚实信号：_fetch() 返回 None = 上游链断，快照兜底正在静默掩蔽。"""

    class _Step:
        def __init__(self, tool="auto", inputs=None, outputs=None):
            self.tool = tool
            self.inputs = inputs if inputs is not None else {}
            self.outputs = outputs if outputs is not None else {}

    class _Sop:
        def __init__(self, sid, steps):
            self.id = sid
            self.steps = steps

    def _client_mod(self, fetched, sops):
        Step, Sop = self._Step, self._Sop

        class _Client:
            def __init__(self, base_url=None, ttl=None, timeout=None):
                pass

            def _fetch(self):
                return fetched

            def load_published(self):
                return sops

        return type("M", (), {"SopApiClient": _Client})

    def _run(self, fetched, sops):
        def _import(name, service):
            return self._client_mod(fetched, sops) if name == "sop_api_client" else None
        with mock.patch.object(chain_smoke, "_request", _fake_request(_OK_ROUTES)), \
                mock.patch.object(chain_smoke, "_import_client", _import):
            return chain_smoke.run_smoke(sop_api_url="http://s1", docs_api_url="http://d1")

    def _hop(self, result):
        return next(h for h in result["hops"] if "真客户端" in h["name"])

    def test_snapshot_fallback_detected(self):
        r = self._run(fetched=None, sops=[self._Sop("s1", [self._Step()])])
        self.assertEqual(self._hop(r)["status"], "fail")
        self.assertIn("快照兜底", self._hop(r)["detail"])

    def test_step_contract_missing_fields_detected(self):
        r = self._run(fetched=[], sops=[self._Sop("s1", [self._Step(tool="")])])
        self.assertEqual(self._hop(r)["status"], "fail")
        self.assertIn("步骤契约缺字段", self._hop(r)["detail"])

    def test_healthy_client_passes(self):
        r = self._run(fetched=[], sops=[self._Sop("s1", [self._Step()])])
        self.assertEqual(self._hop(r)["status"], "ok")
        self.assertEqual(r["severity"], "ok")


class RenderTests(unittest.TestCase):
    def test_empty_result_returns_empty(self):
        self.assertEqual(chain_smoke.render_line(None), "")
        self.assertEqual(chain_smoke.render_detail(None), "")

    def test_line_clips_long_detail(self):
        r = {"severity": "fail", "hops": [
            {"name": "断点", "status": "fail", "detail": "x" * 300},
            {"name": "正常跳", "status": "ok", "detail": ""}]}
        line = chain_smoke.render_line(r)
        self.assertIn("…", line)
        self.assertLess(len(line), 200)

    def test_detail_lists_every_hop(self):
        r = {"severity": "warn", "sop_api_url": "http://s1", "docs_api_url": "http://d1",
             "hops": [{"name": "H1", "status": "ok", "detail": ""},
                      {"name": "H2", "status": "warn", "detail": "空图"}]}
        text = chain_smoke.render_detail(r)
        self.assertIn("[ok] H1", text)
        self.assertIn("[warn] H2：空图", text)
        self.assertIn("http://s1", text)


if __name__ == "__main__":
    unittest.main()

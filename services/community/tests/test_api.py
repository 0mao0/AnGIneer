"""路由层端到端（TestClient + 假上游）：A3 草稿不可见 / A4 gold 不外泄 / A5 三类投稿 /
A6 归属 / A7 日限 / A9 未绑定不出树 / A10 后端不吞字面文本。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from community import models
from community.routes import build_community_router
from community.service import CommunityService
from community.store import CommunityStore
from community.taxonomy_seed import seed_tree
from fakes import FakeEvalSource, FakeSopSource


def make_client(tmp_path, eval_src=None, sop_src=None, principal=None, daily_limit="50"):
    store = CommunityStore(db_path=str(tmp_path / "community.sqlite"))
    seed_tree(store)
    svc = CommunityService(store, eval_src=eval_src or FakeEvalSource(),
                           sop_src=sop_src or FakeSopSource())
    app = FastAPI()
    app.include_router(build_community_router(svc, principal), prefix="/api/community")
    return store, TestClient(app)


PUBLISHED_SOP = {
    "id": "sop-1", "name_zh": "航道乘潮水深计算", "status": "published",
    "steps": [{"id": "step-1", "tool": "calc"}, {"id": "step-2", "tool": "auto"}],
}
DRAFT_SOP = {"id": "sop-draft", "name_zh": "内部草稿流程", "status": "draft", "steps": []}


def test_tree_nodes_and_official_items(tmp_path):
    store, client = make_client(
        tmp_path,
        eval_src=FakeEvalSource([{"dataset_id": "ds-1", "title": "航道题集", "question_count": 7}]),
    )
    store.bind(scope_id="eval", kind="dataset", ref_id="ds-1", node_id="eval:sp-waterway-channel")
    body = client.get("/api/community/tree?scope=eval").json()
    assert body["scope"] == "eval"
    assert {n["node_id"] for n in body["nodes"]} >= {"eval:dom-waterway", "eval:sp-waterway-channel"}
    item = next(i for i in body["items"] if i["origin"] == "official")
    assert item["item_id"] == "official:ds-1"
    assert item["question_count"] == 7
    # 未绑定题集不出现在条目里
    assert all(i["ref_id"] != "ds-hidden" for i in body["items"])


def test_unbound_dataset_invisible(tmp_path):
    eval_src = FakeEvalSource([{"dataset_id": "ds-1", "title": "航道题集"}])
    _, client = make_client(tmp_path, eval_src=eval_src)
    assert client.get("/api/community/datasets/ds-1").status_code == 404
    assert client.get("/api/community/datasets/ds-1/questions").json() == {
        "items": [], "total": 0, "offset": 0, "limit": 50,
    }


def _gold_probe_source():
    return FakeEvalSource([{
        "dataset_id": "ds-1", "title": "航道题集", "question_count": 1,
        "questions": [{
            "question_id": "q-1", "question": "设计水深怎么取？", "intent_level": "L3",
            "tags": ["水运"],
            "answer_gold": {"reference_answer": "参考答案文本"}, "sql_gold": {"sql": "SELECT 1"},
        }],
    }])


def test_questions_default_shows_reference_answer_only(tmp_path):
    """A4（10-15 业主改判后）：默认放参考答案（answer 键），其余 gold 列任何开关下都不出。"""
    eval_src = _gold_probe_source()
    store, client = make_client(tmp_path, eval_src=eval_src)
    store.bind(scope_id="eval", kind="dataset", ref_id="ds-1", node_id="eval:sp-waterway-channel")
    q = client.get("/api/community/datasets/ds-1/questions").json()["items"][0]
    assert q["answer"] == "参考答案文本"
    for gold in ("answer_gold", "sql_gold", "retrieval_gold", "sop_gold"):
        assert gold not in q
    assert eval_src.question_calls and eval_src.question_calls[0]["show_gold"] is True


def test_questions_blind_mode_omits_answer_key(tmp_path, monkeypatch):
    """盲测档（COMMUNITY_SHOW_GOLD=0）：answer 键整个不进响应。"""
    monkeypatch.setenv("COMMUNITY_SHOW_GOLD", "0")
    eval_src = _gold_probe_source()
    store, client = make_client(tmp_path, eval_src=eval_src)
    store.bind(scope_id="eval", kind="dataset", ref_id="ds-1", node_id="eval:sp-waterway-channel")
    q = client.get("/api/community/datasets/ds-1/questions").json()["items"][0]
    assert "answer" not in q
    assert eval_src.question_calls[-1]["show_gold"] is False


def test_sop_draft_invisible_even_if_upstream_leaks(tmp_path):
    """A3：假上游把草稿漏出来，绑定/复核双闸也必须 404。"""
    store, client = make_client(tmp_path, sop_src=FakeSopSource([PUBLISHED_SOP, DRAFT_SOP]))
    store.bind(scope_id="sop", kind="sop", ref_id="sop-1", node_id="sop:sp-waterway-channel")
    store.bind(scope_id="sop", kind="sop", ref_id="sop-draft", node_id="sop:sp-waterway-channel")
    assert client.get("/api/community/sops/sop-1").status_code == 200
    assert client.get("/api/community/sops/sop-draft").status_code == 404
    tree = client.get("/api/community/tree?scope=sop").json()
    assert [i["ref_id"] for i in tree["items"]] == ["sop-1"]


def test_submission_dataset_and_echo_in_tree(tmp_path):
    """A5：投稿题集全量接收，即时回显带 origin=user。"""
    _, client = make_client(tmp_path)
    resp = client.post("/api/community/submissions", json={
        "scope": "eval", "kind": "dataset", "node_id": "eval:sp-waterway-channel",
        "title": "网友航道题集",
        "payload": {"items": [{"question": "乘潮水位怎么查？", "intent_level": "L2", "answer": "查表"}]},
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "received" and body["author_label"] == "游客"
    tree = client.get("/api/community/tree?scope=eval").json()
    user_item = next(i for i in tree["items"] if i["origin"] == "user")
    assert user_item["ref_id"] == body["submission_id"]
    assert user_item["question_count"] == 1
    # 投稿题集的题目走同一投影，可匿名读取
    qs = client.get(f"/api/community/datasets/{body['submission_id']}/questions?origin=user").json()
    assert qs["items"][0]["question"] == "乘潮水位怎么查？"


def test_submission_question_to_official_dataset(tmp_path):
    store, client = make_client(tmp_path, eval_src=FakeEvalSource([{"dataset_id": "ds-1", "title": "航道题集"}]))
    store.bind(scope_id="eval", kind="dataset", ref_id="ds-1", node_id="eval:sp-waterway-channel")
    ok = client.post("/api/community/submissions", json={
        "scope": "eval", "kind": "question", "parent_ref": "ds-1",
        "payload": {"question": "补充题", "intent_level": "L9"},  # 非法等级→回落 L1
    })
    assert ok.status_code == 201
    body = client.get("/api/community/datasets/ds-1/questions").json()
    assert all(q["intent_level"] in models.INTENT_LEVELS for q in body["items"])


def test_submission_comment_requires_step_and_lists(tmp_path):
    store, client = make_client(tmp_path, sop_src=FakeSopSource([PUBLISHED_SOP]))
    store.bind(scope_id="sop", kind="sop", ref_id="sop-1", node_id="sop:sp-waterway-channel")
    bad = client.post("/api/community/submissions", json={
        "scope": "sop", "kind": "sop_comment", "parent_ref": "sop-1", "step_ref": "no-such-step",
        "payload": {"comment": "步骤2 公式口径建议……"},
    })
    assert bad.status_code == 404
    ok = client.post("/api/community/submissions", json={
        "scope": "sop", "kind": "sop_comment", "parent_ref": "sop-1", "step_ref": "step-2",
        "payload": {"comment": "步骤2 公式口径建议……"},
    })
    assert ok.status_code == 201
    comments = client.get("/api/community/sops/sop-1/comments").json()["comments"]
    assert len(comments) == 1
    assert comments[0]["step_ref"] == "step-2"
    assert comments[0]["author_label"] == "游客"


def test_logged_in_author_label_and_owner_key(tmp_path):
    """A6：登录投稿走传入的归属键与显示名。"""
    store, client = make_client(
        tmp_path, sop_src=FakeSopSource([PUBLISHED_SOP]),
        principal=lambda request: ("u:7", 7, "张三"),
    )
    resp = client.post("/api/community/submissions", json={
        "scope": "sop", "kind": "sop_comment", "parent_ref": "missing",
        "payload": {"comment": "无目标应 404"},
    })
    assert resp.status_code == 404
    store.bind(scope_id="sop", kind="sop", ref_id="sop-1", node_id="sop:sp-waterway-channel")
    resp = client.post("/api/community/submissions", json={
        "scope": "sop", "kind": "sop_comment", "parent_ref": "sop-1",
        "payload": {"comment": "登录用户的意见"},
    })
    assert resp.status_code == 201
    assert resp.json()["author_label"] == "张三"
    row = store.get_submission(resp.json()["submission_id"])
    assert row["author_owner_key"] == "u:7" and row["author_user_id"] == 7


def test_daily_limit_429(tmp_path, monkeypatch):
    """A7：兜底日限（主防线在 nginx，本条只证应用层不摆烂）。"""
    monkeypatch.setenv("COMMUNITY_DAILY_LIMIT", "3")
    _, client = make_client(tmp_path, principal=lambda request: ("g:xyz", None, "游客"))
    r = client.post("/api/community/submissions", json={
        "scope": "eval", "kind": "question", "parent_ref": "sub-nonexistent",
        "payload": {"question": "目标不存在"},
    })
    assert r.status_code == 404  # 校验失败的请求不落库、不吃配额
    ds = client.post("/api/community/submissions", json={
        "scope": "eval", "kind": "dataset",
        "payload": {"items": [{"question": "题集内题"}]},
    }).json()["submission_id"]  # 配额 1/3
    assert client.post("/api/community/submissions", json={
        "scope": "eval", "kind": "question", "parent_ref": ds, "payload": {"question": "第1题"},
    }).status_code == 201  # 配额 2/3
    assert client.post("/api/community/submissions", json={
        "scope": "eval", "kind": "question", "parent_ref": ds, "payload": {"question": "第2题"},
    }).status_code == 201  # 配额 3/3
    third = client.post("/api/community/submissions", json={
        "scope": "eval", "kind": "question", "parent_ref": ds, "payload": {"question": "第3题"},
    })
    assert third.status_code == 429


def test_xss_payload_stored_verbatim(tmp_path):
    """A10 后端侧：字面文本原样存原样出（转义/剥标签都归前端渲染纪律，后端不动内容）。"""
    evil = '<img src=x onerror=alert(1)><script>alert(2)</script>'
    _, client = make_client(tmp_path)
    r = client.post("/api/community/submissions", json={
        "scope": "eval", "kind": "dataset", "title": evil,
        "payload": {"items": [{"question": evil}], "description": evil},
    })
    assert r.status_code == 201
    sid = r.json()["submission_id"]
    card = client.get(f"/api/community/datasets/{sid}?origin=user").json()
    assert card["title"] == evil and card["description"] == evil
    q = client.get(f"/api/community/datasets/{sid}/questions?origin=user").json()["items"][0]
    assert q["question"] == evil


def test_invalid_payload_400(tmp_path):
    _, client = make_client(tmp_path)
    cases = [
        {"scope": "eval", "kind": "unknown_kind", "payload": {}},
        {"scope": "bad", "kind": "dataset", "payload": {"items": [{"question": "x"}]}},
        {"scope": "eval", "kind": "dataset", "payload": {"items": []}},          # 空题集
        {"scope": "eval", "kind": "question", "payload": {"question": ""}},      # 空题干
        {"scope": "eval", "kind": "question", "parent_ref": "ds-x", "payload": {"question": "x"}},  # 未绑官方题集→404
    ]
    for body in cases:
        resp = client.post("/api/community/submissions", json=body)
        assert resp.status_code in (400, 404), (body, resp.status_code)
    assert client.post("/api/community/submissions", content="not-json").status_code == 400


def test_sop_source_status_recheck_filters_draft():
    """SopSource 内置复核：上游把草稿混进 /full 响应也进不了缓存。"""
    from community.sources.sop_source import SopSource
    kept = SopSource._keep_published([PUBLISHED_SOP, DRAFT_SOP, "not-a-dict", {"id": "x"}])
    assert [s["id"] for s in kept] == ["sop-1"]

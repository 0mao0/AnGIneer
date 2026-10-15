"""store DAO：meta marker / 节点只补不覆盖 / 绑定 / 投稿 / 日限计数。"""
import pytest

from community import models
from community.store import CommunityStore


@pytest.fixture()
def store(tmp_path):
    return CommunityStore(db_path=str(tmp_path / "community.sqlite"))


def test_meta_marker_roundtrip(store):
    assert store.get_meta("autobind_done:eval") is None
    store.set_meta("autobind_done:eval", "bound=1;total=2")
    assert store.get_meta("autobind_done:eval") == "bound=1;total=2"
    store.set_meta("autobind_done:eval", "bound=9;total=9")
    assert store.get_meta("autobind_done:eval") == "bound=9;total=9"


def test_ensure_node_only_fills_missing(store):
    store.ensure_node("dom-x", scope_id="eval", title="公路", parent_id=None, sort_order=0)
    # 后台改过名 → 种子重跑不得打回
    store.ensure_node("dom-x", scope_id="eval", title="发版默认名", parent_id=None, sort_order=7)
    node = store.get_node("dom-x")
    assert node["title"] == "公路"
    assert node["sort_order"] == 0


def test_node_id_is_globally_unique(store):
    """tree_node.node_id 是全局主键：两棵树靠 `<scope>:` 前缀共存（种子已按此落库）。"""
    store.ensure_node("eval:dom-x", scope_id="eval", title="公路", parent_id=None, sort_order=0)
    store.ensure_node("sop:dom-x", scope_id="sop", title="公路", parent_id=None, sort_order=0)
    assert [n["node_id"] for n in store.list_nodes("eval")] == ["eval:dom-x"]
    assert [n["node_id"] for n in store.list_nodes("sop")] == ["sop:dom-x"]
    # 裸同名不会被第二个 scope 顶掉
    store.ensure_node("eval:dom-x", scope_id="sop", title="不该建", parent_id=None, sort_order=9)
    assert len(store.list_nodes("sop")) == 1


def test_bind_unique_and_unbind(store):
    b1 = store.bind(scope_id="eval", kind="dataset", ref_id="d1", node_id="sp-a")
    store.bind(scope_id="eval", kind="dataset", ref_id="d1", node_id="sp-b")  # 同 ref 重绑=移挂
    rows = store.list_bindings("eval")
    assert len(rows) == 1
    assert rows[0]["node_id"] == "sp-b"
    assert b1["binding_id"] == "bind:eval:dataset:d1"
    assert store.is_bound(scope_id="eval", kind="dataset", ref_id="d1")
    assert store.unbind(scope_id="eval", kind="dataset", ref_id="d1") is True
    assert store.is_bound(scope_id="eval", kind="dataset", ref_id="d1") is False


def test_submission_roundtrip_and_filters(store):
    row = store.insert_submission(
        scope_id="eval", kind="dataset", payload={"items": [{"question": "q"}]},
        node_id="sp-a", title="题集一", author_owner_key="g:abc", author_label="游客",
    )
    sid = row["submission_id"]
    assert sid.startswith("sub-")
    got = store.get_submission(sid)
    assert got["payload"]["items"][0]["question"] == "q"
    assert got["status"] == models.STATUS_RECEIVED
    rows, total = store.list_submissions(scope_id="eval", kinds=["dataset"])
    assert total == 1 and rows[0]["submission_id"] == sid
    # parent_ref 过滤（给投稿题集追加的单题）
    store.insert_submission(
        scope_id="eval", kind="question", payload={"question": "追加题"},
        parent_ref=sid, author_owner_key="g:abc",
    )
    rows, total = store.list_submissions(scope_id="eval", kinds=["question"], parent_ref=sid)
    assert total == 1 and rows[0]["payload"]["question"] == "追加题"


def test_count_submissions_since_window(store):
    for _ in range(3):
        store.insert_submission(scope_id="eval", kind="question", payload={"question": "q"},
                                author_owner_key="g:abc")
    assert store.count_submissions_since("g:abc", hours=24) == 3
    assert store.count_submissions_since("g:other", hours=24) == 0
    assert store.count_submissions_since("", hours=24) == 0

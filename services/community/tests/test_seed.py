"""种子语义（§9.1/B2）：节点幂等只补；自动绑定只跑首次（A13）。"""
import pytest

from community import models, taxonomy_seed
from community.store import CommunityStore
from fakes import FakeEvalSource, FakeSopSource  # pytest prepend 模式会把 tests/ 注入 sys.path


@pytest.fixture()
def store(tmp_path):
    return CommunityStore(db_path=str(tmp_path / "community.sqlite"))


def test_seed_tree_both_scopes_idempotent(store):
    created = taxonomy_seed.seed_tree(store)
    assert created > 0
    again = taxonomy_seed.seed_tree(store)
    assert again == 0  # 第二次零新建（幂等只补）
    assert len(store.list_nodes("eval")) == len(store.list_nodes("sop"))
    assert store.get_node("eval:sp-waterway-channel")["title"] == "航道"
    assert store.get_node("sop:sp-waterway-channel")["title"] == "航道"


def test_autobind_first_run_keyword_match(store):
    eval_src = FakeEvalSource([
        {"dataset_id": "ds-1", "title": "航道乘潮水位题集", "question_count": 3},
        {"dataset_id": "ds-2", "title": "完全无关的内部题库", "question_count": 5},
    ])
    result = taxonomy_seed.autobind_once(store, eval_src, FakeSopSource([]))
    assert result[models.SCOPE_EVAL]["bound"] == 1
    assert store.list_bindings("eval")[0]["node_id"] == "eval:sp-waterway-channel"
    assert store.get_meta(f"{models.META_AUTOBIND_DONE}:eval") is not None


def test_autobind_never_reruns_after_marker(store):
    """A13：marker 置位后新造命中关键词的内容不会自动上树。"""
    eval_src = FakeEvalSource([{"dataset_id": "ds-1", "title": "航道题集"}])
    taxonomy_seed.autobind_once(store, eval_src, FakeSopSource([]))
    # 模拟「导入新内容后重启」：假源多出一条同样命中关键词的题集
    eval_src.datasets["ds-new"] = {"dataset_id": "ds-new", "title": "新导入了航道题库", "question_count": 2}
    result = taxonomy_seed.autobind_once(store, eval_src, FakeSopSource([]))
    assert result == {}  # 已置位，直接跳过
    bound_refs = [b["ref_id"] for b in store.list_bindings("eval")]
    assert "ds-new" not in bound_refs


def test_autobind_marker_set_even_when_zero(store):
    """空库环境首跑绑到 0 条也必须置位，否则哪天导入内容就悄悄全公开。"""
    taxonomy_seed.autobind_once(store, FakeEvalSource([]), FakeSopSource([]))
    assert store.get_meta(f"{models.META_AUTOBIND_DONE}:eval") == "bound=0;total=0"


def test_autobind_keyword_priority_first_match_wins(store):
    eval_src = FakeEvalSource([{"dataset_id": "ds-1", "title": "某疏浚吹填区航道整治", "question_count": 1}])
    taxonomy_seed.autobind_once(store, eval_src, FakeSopSource([]))
    # 表序里航道先于疏浚 → 命中航道
    assert store.list_bindings("eval")[0]["node_id"] == "eval:sp-waterway-channel"

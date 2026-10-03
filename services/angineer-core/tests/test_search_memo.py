"""检索 memo（赌博式预检复用）键一致性与三态行为测试。

施工单 docs/plan-retrieval-speedup-v3.md 变更 A：

F2 死亡探针（落地前就该存在）：
- 键一致性：预检侧（route_pre 构造）与主路侧（build_qa_config 构造）的 memo 键必须
  逐字段一致——键位漂移 = memo 永不命中且零报错（静默失效面），本测试锁死。

F3 三态 memo 的行为锁（四锁）：
- ① 正常共享：在途等待复用，第二次检索不发生（形态复现，F3 落地前必须红）；
- ② 预检失败回收：共享 allocator 的孤儿号段回滚，主路自跑号段连续；
- ③ 等待超时自跑不跳号：主路超时回落自跑，迟到方写结果作废；
- ④ 键位漂移即红：_from_speculative / marker_allocator 不得影响键。

系统级依赖：ANGINEER_ROUTE_PARALLEL=1（键非 None 的前提）、ANGINEER_MEMO_INFLIGHT=1。
"""

import threading
import time

import pytest

from angineer_core import agent_tools
from angineer_core.agent_tools import (
    _SEARCH_MEMO,
    _SEARCH_MEMO_LOCK,
    MarkerAllocator,
    RetrieverAdapter,
    _search_memo_key,
)

QUERY = "内河航道养护有什么技术要求？"


@pytest.fixture(autouse=True)
def _memo_env(monkeypatch):
    monkeypatch.setenv("ANGINEER_ROUTE_PARALLEL", "1")
    monkeypatch.setenv("ANGINEER_MEMO_INFLIGHT", "1")
    monkeypatch.delenv("ANGINEER_MEMO_WAIT_BUDGET_SEC", raising=False)
    with _SEARCH_MEMO_LOCK:
        _SEARCH_MEMO.clear()
    yield
    with _SEARCH_MEMO_LOCK:
        _SEARCH_MEMO.clear()


def _spec_tool(**overrides):
    """route_pre._run 的构造形状（fire_speculative_first_search）。"""
    params = dict(
        library_id="default",
        doc_ids=[],
        doc_nodes=[],
        top_k=20,
        task_type="content_qa",
        filters=None,
        rerank=True,
        config_name=None,
        mode="instruct",
    )
    params.update(overrides)
    return RetrieverAdapter.knowledge_search(**params)


def _main_tool(**overrides):
    """build_qa_config 的构造形状（主路 L1 注入）。"""
    params = dict(
        library_id="default",
        doc_ids=[],
        doc_nodes=[],
        top_k=20,
        task_type="content_qa",
        filters=None,
        rerank=True,
        marker_allocator=None,
        config_name=None,
        mode="instruct",
    )
    params.update(overrides)
    return RetrieverAdapter.knowledge_search(**params)


class _Capture(Exception):
    pass


def test_memo_key_speculative_matches_main_path(monkeypatch):
    """F2 键一致性：预检侧与主路侧构造的键必须逐字段相等。"""
    captured = []

    def fake_impl(**kwargs):
        captured.append(dict(kwargs))
        raise _Capture

    monkeypatch.setattr(agent_tools, "_run_knowledge_search_impl", fake_impl)

    for tool in (_spec_tool(), _main_tool()):
        with pytest.raises(_Capture):
            tool.handler(query=QUERY)

    assert len(captured) == 2
    assert _search_memo_key(captured[0]) == _search_memo_key(captured[1])


def test_memo_key_ignores_speculative_flag_and_allocator():
    """④ 键位漂移即红：旗标与 allocator 实例不得进入键。"""
    base = dict(
        query=QUERY,
        library_id="default",
        doc_ids=[],
        doc_nodes=[],
        top_k=20,
        task_type="content_qa",
        filters=None,
        dense=None,
        sparse=None,
        clause=None,
        prefix="K",
        rerank=True,
        retrieval_client=None,
        config_name=None,
        mode="instruct",
    )
    with_flag = {**base, "_from_speculative": True}
    with_alloc = {**base, "marker_allocator": MarkerAllocator()}
    assert _search_memo_key(base) == _search_memo_key(with_flag)
    assert _search_memo_key(base) == _search_memo_key(with_alloc)


def test_no_second_search_when_speculative_inflight(monkeypatch):
    """① 正常共享（形态复现）：在途等待复用，第二次检索不发生。F3 落地前必须红。"""
    calls = []
    release = threading.Event()

    def fake_impl(**kwargs):
        calls.append(dict(kwargs))
        release.wait(timeout=5.0)
        return {"items": [{"n": len(calls)}], "ok": True}

    monkeypatch.setattr(agent_tools, "_run_knowledge_search_impl", fake_impl)
    tool = _spec_tool()

    def _spec():
        tool.handler(query=QUERY, _from_speculative=True)

    t = threading.Thread(target=_spec, name="spec", daemon=True)
    t.start()
    time.sleep(0.2)  # 让预检先登记在途

    main_tool = _spec_tool()
    result = main_tool.handler(query=QUERY)

    release.set()
    t.join(timeout=5.0)
    assert len(calls) == 1, f"主路自跑了第二份检索（calls={len(calls)}）"
    assert result.get("ok") is True
    assert result.get("_prefetch_ms") is not None


def test_speculative_failure_reclaims_marker_range(monkeypatch):
    """② 预检失败回收：孤儿号段回滚，主路自跑号段连续（K1、K2，不跳 K3）。F3 落地前红。"""
    alloc = MarkerAllocator()
    calls = []

    def fake_impl(**kwargs):
        calls.append(dict(kwargs))
        marks = kwargs.get("marker_allocator")
        if marks is not None:
            marks.next("K")
            marks.next("K")
        if len(calls) == 1:
            raise RuntimeError("预检炸了")
        return {"items": [], "ok": True}

    monkeypatch.setattr(agent_tools, "_run_knowledge_search_impl", fake_impl)
    tool = _spec_tool(marker_allocator=alloc)

    with pytest.raises(RuntimeError):
        tool.handler(query=QUERY, _from_speculative=True)

    result = _spec_tool(marker_allocator=alloc).handler(query=QUERY)
    assert result.get("ok") is True
    assert alloc._counters.get("K", 0) == 2, f"号段跳号：{alloc._counters}"


def test_wait_timeout_self_run_and_late_store_dropped(monkeypatch):
    """③ 等待超时自跑不跳号：主路超时回落自跑，迟到方写结果作废。F3 落地前红。"""
    monkeypatch.setenv("ANGINEER_MEMO_WAIT_BUDGET_SEC", "0.3")
    alloc = MarkerAllocator()
    calls = []
    release_spec = threading.Event()

    def fake_impl(**kwargs):
        calls.append(dict(kwargs))
        marks = kwargs.get("marker_allocator")
        if marks is not None:
            marks.next("K")
        if len(calls) == 1:
            release_spec.wait(timeout=5.0)  # 预检挂住，超出等待预算
            return {"items": [{"who": "spec"}], "ok": True}
        return {"items": [{"who": "main"}], "ok": True}

    monkeypatch.setattr(agent_tools, "_run_knowledge_search_impl", fake_impl)
    tool = _spec_tool(marker_allocator=alloc)

    def _spec():
        tool.handler(query=QUERY, _from_speculative=True)

    t = threading.Thread(target=_spec, name="spec", daemon=True)
    t.start()
    time.sleep(0.2)

    result = _spec_tool(marker_allocator=alloc).handler(query=QUERY)
    assert result["items"][0]["who"] == "main", "主路应自跑并拿到自己的结果"
    release_spec.set()
    t.join(timeout=5.0)
    time.sleep(0.05)

    with _SEARCH_MEMO_LOCK:
        entry = _SEARCH_MEMO.get(_search_memo_key({k: v for k, v in calls[1].items()}))
    assert entry is not None and isinstance(entry, tuple), "主路自跑结果应作为成品入库"
    assert entry[1]["items"][0]["who"] == "main", "迟到的预检结果不得覆盖主路成品"
    # 主路超时先回收预检孤儿号（K1 归零）再自跑，自跑复用 K1——回收重用、不跳号
    assert alloc._counters.get("K", 0) == 1, f"回收重用语义：{alloc._counters}"


def test_done_state_hit_unchanged(monkeypatch):
    """成品语义回归锁：预检先完成 → 主路命中复用，带 _prefetch_ms。"""
    seen = []

    def fake_impl(**kwargs):
        seen.append(dict(kwargs))
        return {"items": [{"n": len(seen)}], "ok": True}

    monkeypatch.setattr(agent_tools, "_run_knowledge_search_impl", fake_impl)
    _spec_tool().handler(query=QUERY, _from_speculative=True)
    result = _spec_tool().handler(query=QUERY)
    assert len(seen) == 1
    assert result.get("ok") is True
    assert result.get("_prefetch_ms") is not None


def test_handler_control_keys_stripped_before_impl(monkeypatch):
    """壳层控制键（cancel_event/_from_speculative）不得透传 impl。"""
    seen = {}

    def fake_impl(**kwargs):
        seen.update(kwargs)
        return {"items": [], "ok": True}

    monkeypatch.setattr(agent_tools, "_run_knowledge_search_impl", fake_impl)
    _spec_tool().handler(query=QUERY, cancel_event=None, _from_speculative=False)
    assert "cancel_event" not in seen
    assert "_from_speculative" not in seen


def test_impl_signature_covers_factory_keys():
    """签名子集锁（v0.2.88 生产 TypeError 事故）：工厂/handler 可转发的键必须全是
    真 impl 的形参——mock 用 **kwargs 吞参会掩盖签名漂移，只能对真签名锁。"""
    import inspect

    impl_params = set(inspect.signature(agent_tools._run_knowledge_search_impl).parameters)
    factory_params = set(inspect.signature(RetrieverAdapter.knowledge_search).parameters)
    unknown = factory_params - impl_params
    assert not unknown, f"工厂形参 impl 不认识（透传即 TypeError）: {unknown}"

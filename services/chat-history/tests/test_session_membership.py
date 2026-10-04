"""会话列表/按库删除：library_ids_json 成员判定（多库会话命中任一勾选库；路径注入见 conftest.py）。"""
from angineer_core.agent_messages import AgentMessage

from chat_history.store.sqlite_store import SqliteHistoryStore


class TestLibraryMembership:
    def _store(self, tmp_path):
        store = SqliteHistoryStore(db_path=str(tmp_path / "chat.sqlite"))
        store.append("u:1", "s-multi", "h1", [AgentMessage(role="user", content="q")],
                     {"run_id": "r1", "library_id": "libA", "library_ids": ["libA", "libB"]})
        store.append("u:1", "s-single", "h2", [AgentMessage(role="user", content="q")],
                     {"run_id": "r2", "library_id": "libC", "library_ids": ["libC"]})
        return store

    def test_list_by_library_hits_membership(self, tmp_path):
        store = self._store(tmp_path)
        ids_a = {r["session_id"] for r in store.list_sessions("u:1", library_id="libA")}
        ids_b = {r["session_id"] for r in store.list_sessions("u:1", library_id="libB")}
        ids_c = {r["session_id"] for r in store.list_sessions("u:1", library_id="libC")}
        assert ids_a == {"s-multi"}
        assert ids_b == {"s-multi"}
        assert ids_c == {"s-single"}

    def test_delete_by_library_hits_membership(self, tmp_path):
        store = self._store(tmp_path)
        assert store.delete_sessions_by_library("u:1", "libB") == 1
        remaining = {r["session_id"] for r in store.list_sessions("u:1")}
        assert remaining == {"s-single"}
        # 会话行删除必须连带清理消息行（钉住 delete_sessions_by_library 的消息清理循环）
        assert store.get_messages("u:1", "s-multi") == []

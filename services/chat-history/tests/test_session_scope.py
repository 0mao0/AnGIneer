"""会话级历史：换 scope 续接同一会话——seq 连号、load 跨 scope 有序（路径注入见 conftest.py）。"""
from angineer_core.agent_messages import AgentMessage

from chat_history.store.sqlite_store import SqliteHistoryStore


def _msg(role: str, content: str) -> AgentMessage:
    return AgentMessage(role=role, content=content)


class TestSessionLevelHistory:
    def test_cross_scope_seq_continuity_and_load(self, tmp_path):
        store = SqliteHistoryStore(db_path=str(tmp_path / "chat.sqlite"))
        seqs1 = store.append("u:1", "s1", "hashA", [_msg("user", "q1"), _msg("assistant", "a1")],
                             {"run_id": "r1", "library_id": "libA", "library_ids": ["libA"]})
        seqs2 = store.append("u:1", "s1", "hashB", [_msg("user", "q2"), _msg("assistant", "a2")],
                             {"run_id": "r2", "library_id": "libB", "library_ids": ["libA", "libB"]})
        assert seqs1 == [1, 2]
        assert seqs2 == [3, 4]  # 换 scope 不重开 seq
        loaded = store.load("u:1", "s1", "hashB")
        assert [m.content for m in loaded] == ["q1", "a1", "q2", "a2"]  # 跨 scope 全量按 seq

    def test_session_row_scope_updated_each_run(self, tmp_path):
        store = SqliteHistoryStore(db_path=str(tmp_path / "chat.sqlite"))
        store.append("u:1", "s1", "hashA", [_msg("user", "q1")],
                     {"run_id": "r1", "library_id": "libA", "library_ids": ["libA"], "doc_ids": ["d1"]})
        store.append("u:1", "s1", "hashB", [_msg("user", "q2")],
                     {"run_id": "r2", "library_id": "libB", "library_ids": ["libA", "libB"], "doc_ids": []})
        row = store.get_session("u:1", "s1")
        assert row["library_id"] == "libB"
        assert row["scope_hash"] == "hashB"
        import json
        assert json.loads(row["library_ids_json"]) == ["libA", "libB"]
        assert json.loads(row["doc_ids_json"]) == []

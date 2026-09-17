"""chat.sqlite 保留期 GC（计划 §5 步 4；运维脚本，与主流程解耦）。

策略（docs/plan-chat-history.md §7 默认值）：
  ANGINEER_CHAT_RETENTION_DAYS（默认 90）：消息 / 审计 run / 会话 / 游客档统一按此清；
  chat_sessions 按 updated_at 过期清（活跃会话自动续命），chat_guests 按 last_seen_at。

用法（仓库根目录执行；容器内 python /app/scripts/chat_db_gc.py）：
  python scripts/chat_db_gc.py              # 只统计将清行数，不动数据（dry-run）
  python scripts/chat_db_gc.py --apply      # 执行删除
  python scripts/chat_db_gc.py --apply --vacuum
      # VACUUM 独占写锁，请在无对话运行时执行；chat.sqlite 体量小，通常秒级
"""
import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "chat-history" / "src"))
sys.path.insert(0, str(REPO / "services" / "shared" / "src"))
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description="chat.sqlite 保留期 GC")
    parser.add_argument("--apply", action="store_true", help="真正删除（默认 dry-run 只统计）")
    parser.add_argument("--vacuum", action="store_true", help="删除后 VACUUM 归还空间")
    parser.add_argument("--days", type=int, default=None,
                        help="保留天数（默认读 env ANGINEER_CHAT_RETENTION_DAYS，再默认 90）")
    args = parser.parse_args()

    import os
    days = args.days
    if days is None:
        try:
            days = int(os.getenv("ANGINEER_CHAT_RETENTION_DAYS", "90") or 90)
        except ValueError:
            days = 90
    days = max(1, days)

    from chat_history.store import DB_PATH, init_db

    init_db()  # 表不存在时先建（新部署首次跑 GC 不炸）
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        stats = {}
        for name, where in (
            ("messages", "created_at<?"),
            ("runs", "created_at<?"),
            ("sessions", "updated_at<?"),
            ("guests", "COALESCE(last_seen_at, created_at)<?"),
        ):
            table = {"messages": "chat_messages", "runs": "chat_runs",
                     "sessions": "chat_sessions", "guests": "chat_guests"}[name]
            stats[name] = conn.execute(
                f"SELECT COUNT(*) AS c FROM {table} WHERE {where}", (cutoff,)
            ).fetchone()["c"]

        print(f"chat.sqlite: {DB_PATH}")
        print(f"保留期: {days} 天（cutoff={cutoff}）")
        for name, n in stats.items():
            print(f"  将清 {name}: {n} 行")

        if args.apply and any(stats.values()):
            from chat_history.store import SqliteHistoryStore
            result = SqliteHistoryStore().gc_expired(days)
            print("已清:", result)
        elif not args.apply:
            print("dry-run：未动数据。加 --apply 执行。")

        if args.vacuum:
            print("VACUUM 中……（独占写锁）")
            conn.execute("VACUUM")
            print("VACUUM 完成")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

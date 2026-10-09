"""组换名迁移（2026-10-09 业主令）：系统库组 `standards` → `system`；规范库组 `guifan` → `standards`。

背景：`standards` 这个名字属于规范语料（现自建组 guifan 的库）；系统默认组（默认知识库所在）
应为 `system`。两组**互换名字**，存储层同步改：库注册表、组 sqlite 文件、qdrant 集合。

四步（幂等，按状态续跑；默认 DRY RUN）：
1. 库注册表 `data/registry.sqlite`：行重写 group_name/collection/sqlite_file
   （先 standards→system，再 guifan→standards——顺序反了会把新 standards 行再次卷走）
2. 组 sqlite：`knowledge/groups/standards.sqlite` → `system.sqlite`；`guifan.sqlite` → `standards.sqlite`
   （含 -wal/-shm sidecar；**docs-api 必须停机**，Windows 上打开中的文件无法改名）
3. 自建组表 `library_groups`：删 `guifan` 行（`standards` 自此是内置组，显示名走前端 GROUP_LABELS）
4. qdrant 真改名（快照恢复，不重算向量）：standards(旧系统数据) → 集合 system；
   guifan(规范数据) → 集合 standards；逐点数据校验后删旧集合。
   顺序=先给 standards 腾名再建新 standards；集合归属靠「采样点 payload 的 library_id ∈ 注册表哪组」判定。

前置/收尾：迁移期间 docs-api 停机；完成、重启 docs-api 前先确认代码已带新组名
（library_registry.DEFAULT_GROUP='system' + GROUP_DEFAULTS 含 system/standards 双内置组）。

用法（本机或 docs-api 容器内）：
    python scripts/migrate_group_rename.py           # DRY RUN 预览（打印将做的每一步）
    python scripts/migrate_group_rename.py --yes     # 落盘执行（可重复跑，按状态续）
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "services", "docs-core", "src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:  # .env 里 QDRANT_URL（本机 localhost:6333 / 服务器容器网 qdrant:6333）
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001
    pass

OLD_SYS, NEW_SYS = "standards", "system"      # 系统库组：standards → system
OLD_STD, NEW_STD = "guifan", "standards"      # 规范库组：guifan → standards


def _plan(msg: str) -> None:
    print(("  [执行] " if APPLY else "  [DRY] ") + msg)


APPLY = False


# ---------------------------------------------------------------- 步骤 1：库注册表
def migrate_registry(data_root: Path) -> None:
    db = data_root / "registry.sqlite"
    if not db.exists():
        print(f"注册表不存在：{db}（跳过）")
        return
    conn = sqlite3.connect(db)
    try:
        n_sys = conn.execute("SELECT COUNT(*) FROM library_registry WHERE group_name=?", (NEW_SYS,)).fetchone()[0]
        n_old = conn.execute("SELECT COUNT(*) FROM library_registry WHERE group_name=?", (OLD_SYS,)).fetchone()[0]
        n_std = conn.execute("SELECT COUNT(*) FROM library_registry WHERE group_name=?", (OLD_STD,)).fetchone()[0]
        if n_sys > 0:
            print(f"注册表：已迁移（group '{NEW_SYS}' 有 {n_sys} 行），跳过")
            return
        if n_old == 0 and n_std == 0:
            print("注册表：既无旧组行也无新组行，状态不明，跳过（请人工核对）")
            return
        _plan(f"注册表：{n_old} 行 {OLD_SYS} → {NEW_SYS}（group/collection/sqlite_file 同步）")
        _plan(f"注册表：{n_std} 行 {OLD_STD} → {NEW_STD}（group/collection/sqlite_file 同步）")
        if APPLY:
            conn.execute(
                "UPDATE library_registry SET group_name=?, collection=?, sqlite_file=? WHERE group_name=?",
                (NEW_SYS, NEW_SYS, f"knowledge/groups/{NEW_SYS}.sqlite", OLD_SYS),
            )
            conn.execute(
                "UPDATE library_registry SET group_name=?, collection=?, sqlite_file=? WHERE group_name=?",
                (NEW_STD, NEW_STD, f"knowledge/groups/{NEW_STD}.sqlite", OLD_STD),
            )
            conn.commit()
            print("  → 注册表已更新")
    finally:
        conn.close()


# ---------------------------------------------------------------- 步骤 2：组 sqlite 文件
def _db_owner_libs(path: Path) -> set[str]:
    """读 canonical_documents.library_id 集合（判别文件归属：系统组 vs 规范组）。"""
    if not path.exists():
        return set()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return {r[0] for r in conn.execute("SELECT DISTINCT library_id FROM canonical_documents")}
        finally:
            conn.close()
    except sqlite3.Error:
        return set()


def migrate_sqlite_files(data_root: Path, sys_libs: set[str], std_libs: set[str]) -> None:
    groups = data_root / "knowledge" / "groups"
    f_old_sys = groups / f"{OLD_SYS}.sqlite"
    f_new_sys = groups / f"{NEW_SYS}.sqlite"
    f_old_std = groups / f"{OLD_STD}.sqlite"
    f_new_std = groups / f"{NEW_STD}.sqlite"

    # DRY RUN 也按顺序推演（a 步移动后，b 步看到的才是腾空的名字）
    moved: set[Path] = set()

    def exists(p: Path) -> bool:
        return p.exists() and p not in moved

    # a) standards.sqlite（系统数据）→ system.sqlite
    if exists(f_new_sys):
        print(f"sqlite：{f_new_sys.name} 已存在，跳过第一步")
    elif exists(f_old_sys):
        owner = _db_owner_libs(f_old_sys)
        if owner and not owner & sys_libs:
            print(f"sqlite：{f_old_sys.name} 装的是 {sorted(owner)[:3]}…（非系统组库），需人工核对，跳过")
        else:
            _plan(f"sqlite：{f_old_sys.name} → {f_new_sys.name}（含 -wal/-shm）")
            if APPLY:
                _rename_with_sidecars(f_old_sys, f_new_sys)
            moved.add(f_old_sys)
    else:
        print(f"sqlite：{f_old_sys.name} 不存在，跳过（可能已迁移）")

    # b) guifan.sqlite（规范数据）→ standards.sqlite
    if exists(f_new_std):
        print(f"sqlite：{f_new_std.name} 已存在，跳过第二步")
    elif exists(f_old_std):
        _plan(f"sqlite：{f_old_std.name} → {f_new_std.name}（含 -wal/-shm）")
        if APPLY:
            _rename_with_sidecars(f_old_std, f_new_std)
        moved.add(f_old_std)
    else:
        print(f"sqlite：{f_old_std.name} 不存在，跳过（可能已迁移）")


def _rename_with_sidecars(src: Path, dst: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        s = Path(str(src) + suffix)
        if s.exists():
            os.replace(s, Path(str(dst) + suffix))
    print(f"  → {src.name} 完成")


# ---------------------------------------------------------------- 步骤 3：自建组表
def migrate_custom_group_row(data_root: Path) -> None:
    db = data_root / "registry.sqlite"
    if not db.exists():
        return
    conn = sqlite3.connect(db)
    try:
        n = conn.execute("SELECT COUNT(*) FROM library_groups WHERE group_name=?", (OLD_STD,)).fetchone()[0]
        if n == 0:
            print(f"自建组表：无 {OLD_STD} 行，跳过")
            return
        _plan(f"自建组表：删 {OLD_STD} 行（{NEW_STD} 转内置组，显示名由前端 GROUP_LABELS 提供）")
        if APPLY:
            conn.execute("DELETE FROM library_groups WHERE group_name=?", (OLD_STD,))
            conn.commit()
            print("  → 已删除")
    finally:
        conn.close()


# ---------------------------------------------------------------- 步骤 3b：订阅表（V2 用户组订阅）
def migrate_subscriptions(data_root: Path) -> None:
    """users.sqlite 的 user_group_subscriptions.group_name 若引用旧组名则改写。

    本地/生产当前均为空表（V2 未启用），纯防御：改名后不该留旧组名的悬挂行。
    """
    db = data_root / "platform" / "users.sqlite"
    if not db.exists():
        print("订阅表：users.sqlite 不存在，跳过")
        return
    conn = sqlite3.connect(db)
    try:
        has = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='user_group_subscriptions'"
        ).fetchone()[0]
        if not has:
            print("订阅表：无 user_group_subscriptions 表，跳过")
            return
        n_sys = conn.execute(
            "SELECT COUNT(*) FROM user_group_subscriptions WHERE group_name=?", (OLD_SYS,)
        ).fetchone()[0]
        n_std = conn.execute(
            "SELECT COUNT(*) FROM user_group_subscriptions WHERE group_name=?", (OLD_STD,)
        ).fetchone()[0]
        if not n_sys and not n_std:
            print("订阅表：无旧组名行，跳过")
            return
        _plan(f"订阅表：{n_sys} 行 {OLD_SYS} → {NEW_SYS}；{n_std} 行 {OLD_STD} → {NEW_STD}")
        if APPLY:
            # 先移旧的系统行，再移规范行，避免互相卷走（顺序同注册表）
            conn.execute(
                "UPDATE user_group_subscriptions SET group_name=? WHERE group_name=?", (NEW_SYS, OLD_SYS)
            )
            conn.execute(
                "UPDATE user_group_subscriptions SET group_name=? WHERE group_name=?", (NEW_STD, OLD_STD)
            )
            conn.commit()
            print("  → 订阅表已更新")
    finally:
        conn.close()


# ---------------------------------------------------------------- 步骤 4：qdrant 真改名
class Qdrant:
    def __init__(self, url: str) -> None:
        import httpx

        self.c = httpx.Client(base_url=url.rstrip("/"), timeout=httpx.Timeout(600.0))

    def collections(self) -> list[str]:
        r = self.c.get("/collections")
        r.raise_for_status()
        return [x["name"] for x in r.json()["result"]["collections"]]

    def count(self, name: str) -> int:
        r = self.c.post(f"/collections/{name}/points/count", json={"exact": True})
        r.raise_for_status()
        return int(r.json()["result"]["count"])

    def sample_libs(self, name: str, limit: int = 100) -> set[str]:
        r = self.c.post(
            f"/collections/{name}/points/scroll",
            json={"limit": limit, "with_payload": ["library_id"], "with_vector": False},
        )
        r.raise_for_status()
        out: set[str] = set()
        for p in r.json()["result"]["points"]:
            lid = (p.get("payload") or {}).get("library_id")
            if lid:
                out.add(str(lid))
        return out

    def snapshot(self, name: str) -> tuple[str, Path]:
        r = self.c.post(f"/collections/{name}/snapshots")
        r.raise_for_status()
        snap = r.json()["result"]["name"]
        tmp = Path(tempfile.gettempdir()) / f"qdrant_{name}_{snap}"
        with self.c.stream("GET", f"/collections/{name}/snapshots/{snap}") as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_bytes(1 << 20):
                    f.write(chunk)
        return snap, tmp

    def restore_into(self, src_name: str, dst_name: str, snap_file: Path) -> None:
        with open(snap_file, "rb") as f:
            r = self.c.post(
                f"/collections/{dst_name}/snapshots/upload",
                params={"priority": "snapshot", "wait": "true"},
                files={"snapshot": (snap_file.name, f, "application/octet-stream")},
            )
        if r.status_code >= 400:
            raise RuntimeError(f"恢复 {dst_name} 失败：{r.status_code} {r.text[:300]}")

    def drop_snapshot(self, name: str, snap: str) -> None:
        try:
            self.c.delete(f"/collections/{name}/snapshots/{snap}")
        except Exception:  # noqa: BLE001
            pass

    def drop_collection(self, name: str) -> None:
        r = self.c.delete(f"/collections/{name}")
        r.raise_for_status()


def migrate_qdrant(qdrant_url: str, sys_libs: set[str], std_libs: set[str]) -> None:
    """分步：先给 standards 腾名（旧系统数据→system），再让 guifan 顶上 standards。
    集合归属判定靠采样点 payload 的 library_id 落在注册表哪一组。"""
    q = Qdrant(qdrant_url)
    names = q.collections()
    print(f"qdrant 集合：{names}")

    # A) standards 名位：装系统数据 → 复制到 system；装规范数据 → 已是目标
    if OLD_SYS in names:
        who = q.sample_libs(OLD_SYS)
        if who & std_libs and not who & sys_libs:
            print(f"qdrant：{OLD_SYS} 已装规范数据（已是新 standards），跳过")
        elif who & sys_libs:
            _copy_collection(q, OLD_SYS, NEW_SYS)
        else:
            print(f"qdrant：{OLD_SYS} 采样判不出归属（libs={sorted(who)}），跳过并请人工核对")
    else:
        print(f"qdrant：{OLD_SYS} 集合不存在（可能已迁移）")

    # B) guifan → standards（名字刚腾出来）
    if OLD_STD in names:
        _copy_collection(q, OLD_STD, NEW_STD)
    else:
        print(f"qdrant：{OLD_STD} 集合不存在（可能已迁移）")


def _copy_collection(q: Qdrant, src: str, dst: str) -> None:
    n_src = q.count(src)
    if dst in q.collections():
        n_dst = q.count(dst)
        if n_dst == n_src:
            print(f"qdrant：{dst} 已存在且点数一致（{n_dst}），直接删旧的 {src}")
            if APPLY:
                q.drop_collection(src)
            return
        if not APPLY:
            # DRY RUN：A 步尚占用 dst 名位属正常，落盘时会先释放
            _plan(f"qdrant：待 {dst} 名位释放（A 步删旧集合）后，{src}（{n_src} 点）→ {dst}")
            return
        raise RuntimeError(f"{dst} 已存在但点数不一致（{n_dst} vs {n_src}），人工核对后再跑")
    _plan(f"qdrant：{src}（{n_src} 点）快照 → 恢复为集合 {dst} → 校验点数 → 删 {src}")
    if not APPLY:
        return
    snap, tmp = q.snapshot(src)
    try:
        print(f"  → 快照 {snap} 已下载（{tmp.stat().st_size / 1024**2:.0f}MB），开始恢复 …")
        q.restore_into(src, dst, tmp)
    finally:
        q.drop_snapshot(src, snap)
        tmp.unlink(missing_ok=True)
    n_dst = q.count(dst)
    if n_dst != n_src:
        raise RuntimeError(f"恢复后点数不一致：{dst}={n_dst} vs {src}={n_src}（旧集合保留，未删）")
    print(f"  → {dst} 校验通过（{n_dst} 点），删旧集合 {src}")
    q.drop_collection(src)


# ---------------------------------------------------------------- main
def _group_libs(data_root: Path, group: str) -> set[str]:
    db = data_root / "registry.sqlite"
    if not db.exists():
        return set()
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {r[0] for r in conn.execute("SELECT library_id FROM library_registry WHERE group_name=?", (group,))}
    finally:
        conn.close()


def main() -> int:
    global APPLY
    ap = argparse.ArgumentParser(description="组换名迁移 standards→system / guifan→standards（默认 DRY RUN）")
    ap.add_argument("--yes", action="store_true", help="确认落盘（缺省 DRY RUN）")
    ap.add_argument("--skip-qdrant", action="store_true", help="只做注册表与 sqlite（qdrant 另行处理）")
    args = ap.parse_args()
    APPLY = args.yes

    from docs_core import library_registry

    data_root = library_registry.resolve_data_root()
    print(f"data_root = {data_root}   {'执行模式' if APPLY else 'DRY RUN（加 --yes 落盘）'}\n")

    print("① 库注册表")
    migrate_registry(data_root)
    # 归属集合按相位取：迁移完成（存在 group='system' 行）用新名，否则用旧名——
    # qdrant/sqlite 里睡的是同一批库，名字怎么换不改变谁的数据。
    if _group_libs(data_root, NEW_SYS):
        sys_libs = _group_libs(data_root, NEW_SYS)
        std_libs = _group_libs(data_root, NEW_STD)
        print("   （相位：已迁移）")
    else:
        sys_libs = _group_libs(data_root, OLD_SYS)
        std_libs = _group_libs(data_root, OLD_STD)
        print("   （相位：迁移前）")
    print(f"   系统组库={sorted(sys_libs)}\n   规范组库={sorted(std_libs)}\n")

    print("② 组 sqlite 文件")
    migrate_sqlite_files(data_root, sys_libs, std_libs)

    print("\n③ 自建组表")
    migrate_custom_group_row(data_root)

    print("\n③b 订阅表")
    migrate_subscriptions(data_root)

    if not args.skip_qdrant:
        print("\n④ qdrant 集合换名")
        migrate_qdrant(os.getenv("QDRANT_URL", "http://localhost:6333"), sys_libs, std_libs)

    print("\n完成" + ("" if APPLY else "（DRY RUN，未落盘）"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

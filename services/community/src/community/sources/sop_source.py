"""sop-api 只读适配：published SOP 列表 / 详情。

形态照 aichat-api 的 SopApiClient（TTL 缓存 → HTTP → 末次快照兜底），
两点差异：
1. 返回**原始 dict** 不重建 SOP 模型——公开页只做展示，无需 angineer_core；
2. 本模块**不写快照**（快照唯一写者仍是 aichat 侧客户端），这里只读它兜底。

草稿保护双保险：请求带 `status=published`，返回后逐条复核 status——
上游若把 status 过滤实现改坏，这里也不会把草稿带进公开面。
"""
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


def _default_base_url() -> str:
    # 容器内走 compose 服务名；本机 dev 经 .env 覆盖为 http://127.0.0.1:8792
    return (os.getenv("SOP_API_URL") or "").strip() or "http://sop-api:8792"


def _default_ttl() -> float:
    raw = (os.getenv("ANGINEER_SOP_CACHE_TTL") or "").strip()
    if raw:
        try:
            return max(float(raw), 0.0)
        except ValueError:
            pass
    return 300.0


def _default_snapshot_path() -> Path:
    from shared.paths import resolve_data_file  # noqa: PLC0415
    return Path(resolve_data_file("SOP_API_SNAPSHOT_PATH", "platform/sop_published_snapshot.json"))


class SopSource:
    """只读 published SOP 源：TTL → HTTP → 快照。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        ttl: Optional[float] = None,
        timeout: float = 5.0,
        snapshot_path: Optional[Path] = None,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = (base_url or _default_base_url()).rstrip("/")
        self.ttl = _default_ttl() if ttl is None else ttl
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.trust_env = False  # 绕系统代理（同 sop_api_client 的旧坑）
        self.snapshot_path = Path(snapshot_path) if snapshot_path else _default_snapshot_path()
        self._cache: List[Dict[str, Any]] = []
        self._cache_built_at = 0.0
        self._lock = threading.Lock()

    def list_published(self) -> List[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            if self._cache and self.ttl > 0 and (now - self._cache_built_at) <= self.ttl:
                return list(self._cache)
        fetched = self._fetch()
        if fetched is not None:
            with self._lock:
                self._cache = fetched
                self._cache_built_at = now
            return list(fetched)
        snapshot = self._read_snapshot()
        if snapshot is not None:
            logger.warning("sop-api 不可达，公开页 SOP 用末次快照（%d 条）", len(snapshot))
            return snapshot
        logger.error("sop-api 不可达且无快照，公开页 SOP 列表为空")
        return []

    def list_briefs(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for sop in self.list_published():
            out.append({
                "sop_id": sop.get("id", ""),
                "title": sop.get("name_zh") or sop.get("name_en") or sop.get("id", ""),
                "description": sop.get("description", "") or "",
                "confidence": sop.get("confidence"),
                "step_count": len(sop.get("steps") or []),
            })
        return out

    def get(self, sop_id: str) -> Optional[Dict[str, Any]]:
        for sop in self.list_published():
            if sop.get("id") == sop_id:
                return sop
        return None

    # ---- 内部 ----

    def _fetch(self) -> Optional[List[Dict[str, Any]]]:
        url = f"{self.base_url}/api/sops/full"
        try:
            resp = self.session.get(url, params={"status": "published"}, timeout=self.timeout)
            resp.raise_for_status()
            items = resp.json().get("sops") or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("拉取 published SOP 失败（%s）: %s", url, exc)
            return None
        return self._keep_published(items)

    @staticmethod
    def _keep_published(items: List[Any]) -> List[Dict[str, Any]]:
        """逐条复核 status——上游过滤坏掉也不放草稿进公开面。"""
        return [s for s in items if isinstance(s, dict) and s.get("status") == "published"]

    def _read_snapshot(self) -> Optional[List[Dict[str, Any]]]:
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, list):
            return None
        sops = self._keep_published(payload)
        return sops or None


_default_source: Optional[SopSource] = None
_default_lock = threading.Lock()


def default_source() -> SopSource:
    """进程内共享的 SopSource（TTL 缓存要有单例才有效）。"""
    global _default_source
    with _default_lock:
        if _default_source is None:
            _default_source = SopSource()
        return _default_source

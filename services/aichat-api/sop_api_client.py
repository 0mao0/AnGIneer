"""sop-api HTTP 客户端：执行面 published SOP 列表拉取 + 末次快照兜底。

plan-sop-api-l4 Task 1.3：SOP 数据面唯一写者是 sop-api 服务；本客户端只读。
sop-api 不可用时降级末次成功快照（比直读文件更稳：文件损坏不致路由池全灭）。
与 SopLoader 的 duck-type 兼容点：`load_all()`（agent_policy / chat_agent 调用签名），
本地源码直跑时按相对路径定位仓库 data/ 目录。
"""
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from angineer_core.base_contracts import SOP, Step
from sop_core.sop_loader import _normalize_step_dict

logger = logging.getLogger(__name__)

_SNAPSHOT_ENV = "SOP_API_SNAPSHOT_PATH"


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


class SopApiClient:
    """只读 SOP 列表客户端：TTL 缓存 → HTTP → 快照。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        ttl: Optional[float] = None,
        timeout: float = 5.0,
    ):
        self.base_url = (base_url or _default_base_url()).rstrip("/")
        self.ttl = _default_ttl() if ttl is None else ttl
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False  # 绕系统代理（localhost 请求被劫走的旧坑，同 eec9438）
        self._cache: List[SOP] = []
        self._cache_built_at: float = 0.0
        self._lock = threading.Lock()
        self.snapshot_path = Path(
            os.getenv(_SNAPSHOT_ENV)
            or Path(__file__).resolve().parent / "../../data/platform/sop_published_snapshot.json"
        )
        self._snapshot_warned = False

    # ---- 与 SopLoader 的兼容签名（调用点零改动） ----
    def load_all(self, include_status: Any = None) -> List[SOP]:
        return self.load_published()

    def load_published(self) -> List[SOP]:
        now = time.time()
        with self._lock:
            if self._cache and self.ttl > 0 and (now - self._cache_built_at) <= self.ttl:
                return list(self._cache)
        fetched = self._fetch()
        if fetched is not None:
            with self._lock:
                self._cache = fetched
                self._cache_built_at = now
            self._write_snapshot(fetched)
            self._snapshot_warned = False
            return list(fetched)
        snapshot = self._read_snapshot()
        if snapshot is not None:
            if not self._snapshot_warned:
                logger.warning("sop-api 不可达，使用末次快照（%d 条 published）", len(snapshot))
                self._snapshot_warned = True
            return snapshot
        logger.error("sop-api 不可达且无快照，SOP 路由池为空")
        return []

    # ---- 内部 ----
    def _fetch(self) -> Optional[List[SOP]]:
        url = f"{self.base_url}/api/sops/full"
        try:
            resp = self.session.get(url, params={"status": "published"}, timeout=self.timeout)
            resp.raise_for_status()
            items = resp.json().get("sops") or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("拉取 published SOP 失败（%s）: %s", url, exc)
            return None
        sops = self._build_sops(items)
        logger.info("sop-api published 列表拉取成功：%d 条", len(sops))
        return sops

    @staticmethod
    def _build_sops(items: List[dict]) -> List[SOP]:
        sops: List[SOP] = []
        for data in items:
            if not isinstance(data, dict):
                continue
            try:
                steps = [Step(**_normalize_step_dict(s)) for s in (data.get("steps") or [])]
                sops.append(SOP(
                    id=data.get("id") or "",
                    name_zh=data.get("name_zh") or "",
                    name_en=data.get("name_en") or "",
                    description=data.get("description") or "",
                    steps=steps or [Step(id="execute", tool="auto")],
                    blackboard=data.get("blackboard"),
                    status=data.get("status") or "published",
                    confidence=float(data.get("confidence") or 0.0),
                    source=data.get("source") or {},
                    review=data.get("review") or {},
                    stats=data.get("stats") or {},
                ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("SOP %s 解析失败，跳过: %s", data.get("id"), exc)
        return sops

    def _write_snapshot(self, sops: List[SOP]) -> None:
        try:
            path = Path(self.snapshot_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = [s.model_dump() for s in sops]
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("SOP 快照写盘失败（%s）: %s", self.snapshot_path, exc)

    def _read_snapshot(self) -> Optional[List[SOP]]:
        try:
            payload = json.loads(Path(self.snapshot_path).read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, list):
            return None
        sops = self._build_sops(payload)
        return sops or None


def build_l4_hooks(client: "SopApiClient", budget: Dict[str, int]):
    """L4 回调对（synth, crystallize）；budget 由装配层按问题创建（每问题至多 1 次合成）。"""

    def synth(query: str, library_id: str = "", doc_ids: Optional[List[str]] = None):
        if budget.get("used", 0) >= 1:
            return None
        budget["used"] = budget.get("used", 0) + 1
        try:
            resp = client.session.post(
                f"{client.base_url}/api/sops/synthesize",
                json={"query": query, "library_id": library_id or "",
                      "doc_ids": list(doc_ids or []), "llm_enabled": True},
                timeout=120.0,
            )
            if resp.status_code != 200:
                logger.info("L4 synthesize 未命中（%s）: %s", resp.status_code, resp.text[:200])
                return None
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("L4 synthesize 调用失败: %s", exc)
            return None

    def crystallize(sop: Dict[str, Any], source_query: str, summary: str):
        try:
            client.session.post(
                f"{client.base_url}/api/sops/crystallize",
                json={"sop": sop, "source_query": source_query, "review_note": summary[:200]},
                timeout=15.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("L4 crystallize 调用失败（不阻断）: %s", exc)

    return synth, crystallize

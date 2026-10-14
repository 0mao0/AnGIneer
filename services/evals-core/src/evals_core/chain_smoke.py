# -*- coding: utf-8 -*-
"""SOP 链路冒烟（B 层夜巡断言）：用真客户端打 aichat→sop-api→docs-api 最小链，只告警不阻断。

背景（2026-10-13 解耦自审收尾项）：模块边界守卫只断言 import 文本，"契约在、链断、
静默降级"测不出来——本仓实踩两例都属此类：sop-api 的 docs_graph_client 走复数 URL
``/api/graphs/...`` 恒 404 且被宽 except 吞掉（generate-from-doc 静默 412）、docs-core 的
``WarningItem.from_row`` 字段错位（bundle 命中带 warning 的实体即 500）。本模块不打桩，
直接以真实客户端代码路径各发一发真 HTTP，验证"链还通、字段还在"。

定性（与素材检查/拒答前提对账同层）：这是链路存活断言，不是评测分数；任何异常只落
一行报告 + 企微告警，不设门禁、不阻断 nightly。"跳过（skip）"跳（如未配库/文档）不降级。

口径：只读/幂等——synthesize 以 ``llm_enabled=false`` 调（不烧 LLM、不落盘）；
crystallize（写面）不冒烟。默认地址与真实客户端同源（``SOP_API_URL`` /
``ANGINEER_DOCS_API_URL``，容器内缺省走 compose 服务名）。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("evals_core.chain_smoke")

_SEVERITY_OK = "ok"
_SEVERITY_WARN = "warn"
_SEVERITY_FAIL = "fail"

_HOP_OK, _HOP_WARN, _HOP_FAIL, _HOP_SKIP = "ok", "warn", "fail", "skip"


# ---------- 运行面解析 ----------

def _resolve_sop_url(override: Optional[str]) -> str:
    """与 aichat-api/sop_api_client._default_base_url 同源同序（容器缺省走服务名）。"""
    return ((override or os.getenv("SOP_API_URL") or "").strip().rstrip("/")
            or "http://sop-api:8792")


def _resolve_docs_url(override: Optional[str]) -> str:
    """与 sop-api/docs_graph_client._default_docs_api_url 同源同序。"""
    if override and override.strip():
        return override.strip().rstrip("/")
    for var in ("ANGINEER_DOCS_API_URL", "DOCS_API_URL"):
        raw = (os.getenv(var) or "").strip()
        if raw:
            return raw.rstrip("/")
    return "http://docs-api:8790"


def _client_dirs(service: str) -> List[str]:
    """真实客户端模块的两个落点：本仓库源码树（开发机）+ 容器内 /app/services/<svc>。"""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[4]  # services/evals-core/src/evals_core/x.py
    return [str(repo_root / "services" / service), f"/app/services/{service}"]


def _import_client(module_name: str, service: str):
    """导入真实客户端模块；原生不可用时暂借落点目录。失败返回 None（冒烟降级为跳过/失败）。"""
    import importlib
    import sys

    try:
        return importlib.import_module(module_name)
    except Exception:  # noqa: BLE001 回退落点目录再试
        pass
    added: List[str] = []
    for d in _client_dirs(service):
        if os.path.isdir(d) and d not in sys.path:
            sys.path.insert(0, d)
            added.append(d)
    try:
        return importlib.import_module(module_name)
    except Exception:  # noqa: BLE001 本环境没有该服务源码（如 nightly 住 aichat 容器）
        return None
    finally:
        for d in added:
            try:
                sys.path.remove(d)  # 模块已缓存；目录只在导入期借一下，不污染调用方进程
            except ValueError:
                pass


def _request(method: str, url: str, **kw):
    import requests

    session = requests.Session()
    session.trust_env = False  # 绕系统代理（httpx/requests 同款旧坑 eec9438）
    try:
        return session.request(method, url, timeout=kw.pop("timeout", 15.0), **kw)
    finally:
        session.close()


def _hop(hops: List[dict], name: str, status: str, detail: str = "") -> None:
    hops.append({"name": name, "status": status, "detail": detail})


def _exc_detail(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:120]}"


# ---------- 检查 ----------

def run_smoke(*, sop_api_url: Optional[str] = None, docs_api_url: Optional[str] = None,
              library_id: Optional[str] = None, doc_id: Optional[str] = None,
              query: Optional[str] = None) -> dict:
    """打一遍最小链。返回 {severity, hops[{name,status,detail}], sop_api_url, docs_api_url, ...}。

    severity：fail=任一跳硬失败（链断）；warn=有软异常（空数据/公网门/合成退化）；
    ok=全部通过（skip 不降级）。本函数不抛异常，环境级问题也收口成 hop=fail。

    可选覆盖：library_id/doc_id 缺省读 ``SMOKE_LIBRARY_ID``/``SMOKE_DOC_ID``（配了才打
    bundle 一跳）；查询词缺省 ``SMOKE_QUERY`` 或 "设计"。
    """
    sop = _resolve_sop_url(sop_api_url)
    docs = _resolve_docs_url(docs_api_url)
    lib = (library_id if library_id is not None else os.getenv("SMOKE_LIBRARY_ID", "")).strip()
    doc = (doc_id if doc_id is not None else os.getenv("SMOKE_DOC_ID", "")).strip()
    q = (query or os.getenv("SMOKE_QUERY") or "设计").strip()
    hops: List[dict] = []
    ents: List[Any] = []

    # H1: sop-api 存活 + published 列表端点（执行面唯一数据源的入口）
    try:
        r = _request("GET", f"{sop}/api/sops/full", params={"status": "published"})
        if r.status_code != 200:
            _hop(hops, "sop-api /api/sops/full", _HOP_FAIL, f"HTTP {r.status_code}")
        else:
            items = (r.json() or {}).get("sops") or []
            _hop(hops, "sop-api /api/sops/full", _HOP_OK, f"published {len(items)} 条")
    except Exception as exc:  # noqa: BLE001 连不上=链断
        _hop(hops, "sop-api /api/sops/full", _HOP_FAIL, _exc_detail(exc))

    # H2: aichat 真客户端（sop_api_client）→ 归一化后的 Step 契约
    # _fetch() 是链路的诚实信号：返回 None 即 HTTP/解析已失败（此时 load_published
    # 会静默走快照兜底，光看返回值掩蔽链断——快照兜底本身是设计，但冒烟要看见它启动）。
    client_mod = _import_client("sop_api_client", "aichat-api")
    if client_mod is None:
        _hop(hops, "aichat→sop-api 真客户端", _HOP_SKIP, "sop_api_client 不可导入（本环境无 aichat 源码）")
    else:
        try:
            client = client_mod.SopApiClient(base_url=sop, ttl=0.0, timeout=10.0)
            fetched = client._fetch() if hasattr(client, "_fetch") else None
            sops = client.load_published()
            bad = []
            for s in (sops or []):
                for st in (getattr(s, "steps", None) or []):
                    if (not getattr(st, "tool", "")
                            or not isinstance(getattr(st, "inputs", None), dict)
                            or not isinstance(getattr(st, "outputs", None), dict)):
                        bad.append(getattr(s, "id", "?"))
                        break
            if hasattr(client, "_fetch") and fetched is None:
                _hop(hops, "aichat→sop-api 真客户端", _HOP_FAIL,
                     "HTTP 拉取降级（快照兜底已启动）——上游链断或响应解析失败")
            elif bad:
                _hop(hops, "aichat→sop-api 真客户端", _HOP_FAIL, f"步骤契约缺字段: {bad[:3]}")
            elif not sops:
                _hop(hops, "aichat→sop-api 真客户端", _HOP_WARN, "客户端可用但 published 池为空")
            else:
                _hop(hops, "aichat→sop-api 真客户端", _HOP_OK, f"归一化后 SOP {len(sops)} 条")
        except Exception as exc:  # noqa: BLE001
            _hop(hops, "aichat→sop-api 真客户端", _HOP_FAIL, _exc_detail(exc))

    # H3: docs-api 实体搜索（raw；顺带验证 library_id 过滤参数存在）
    try:
        r = _request("GET", f"{docs}/api/graph/entities/search", params={"q": q})
        if r.status_code != 200:
            _hop(hops, "docs-api 实体搜索", _HOP_FAIL, f"HTTP {r.status_code}")
        else:
            body = r.json()
            ents = body if isinstance(body, list) else []
            if not all(isinstance(e, dict) and e.get("entity_id") and e.get("name") for e in ents):
                _hop(hops, "docs-api 实体搜索", _HOP_FAIL, "返回项缺 entity_id/name")
            else:
                _hop(hops, "docs-api 实体搜索", _HOP_OK if ents else _HOP_WARN,
                     f"q=「{q}」命中 {len(ents)}" + ("" if ents else "（空图或词不在库）"))
    except Exception as exc:  # noqa: BLE001
        _hop(hops, "docs-api 实体搜索", _HOP_FAIL, _exc_detail(exc))
    if lib:
        try:
            r = _request("GET", f"{docs}/api/graph/entities/search", params={"q": q, "library_id": lib})
            _hop(hops, "实体搜索·按库过滤", _HOP_OK if r.status_code == 200 else _HOP_FAIL,
                 f"HTTP {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            _hop(hops, "实体搜索·按库过滤", _HOP_FAIL, _exc_detail(exc))

    # H4: 关系端点字段契约（Task 1 增补的 library_id/doc_id 必须序列化出来）
    entity_id = ""
    for e in ents:
        if isinstance(e, dict) and e.get("entity_id"):
            entity_id = str(e["entity_id"])
            break
    if not entity_id:
        _hop(hops, "docs-api 关系端点", _HOP_SKIP, "无实体可查（H3 空）")
    else:
        try:
            r = _request("GET", f"{docs}/api/graph/relations/{entity_id}")
            if r.status_code != 200:
                _hop(hops, "docs-api 关系端点", _HOP_FAIL, f"HTTP {r.status_code}")
            else:
                body = r.json()
                rels = body if isinstance(body, list) else []
                missing = [x for x in rels if isinstance(x, dict)
                           and ("library_id" not in x or "doc_id" not in x)]
                if missing:
                    _hop(hops, "docs-api 关系端点", _HOP_FAIL,
                         f"{len(missing)}/{len(rels)} 条缺 library_id/doc_id（字段契约）")
                else:
                    _hop(hops, "docs-api 关系端点", _HOP_OK, f"{len(rels)} 条，字段齐")
        except Exception as exc:  # noqa: BLE001
            _hop(hops, "docs-api 关系端点", _HOP_FAIL, _exc_detail(exc))

    # H5: bundle 真客户端（sop-api 的 HttpGraphReader）——曾静默 18 天的坏形态探针
    if not (lib and doc):
        _hop(hops, "bundle 真客户端", _HOP_SKIP, "未配 SMOKE_LIBRARY_ID/SMOKE_DOC_ID")
    else:
        gm = _import_client("docs_graph_client", "sop-api")
        if gm is None or not hasattr(gm, "HttpGraphReader"):
            _hop(hops, "bundle 真客户端", _HOP_SKIP, "docs_graph_client 不可导入（本环境无 sop-api 源码）")
        else:
            try:
                reader = gm.HttpGraphReader.from_bundle(lib, doc, base_url=docs, timeout=25.0)
                if reader is None:
                    _hop(hops, "bundle 真客户端", _HOP_FAIL,
                         "from_bundle=None（404/5xx/解析失败——此类已被宽 except 吞过一次）")
                else:
                    ne, nr = len(reader._entities), len(reader._relations)
                    _hop(hops, "bundle 真客户端", _HOP_OK if (ne or nr) else _HOP_WARN,
                         f"entities={ne} relations={nr}" + ("" if (ne or nr) else "（该文档图谱为空）"))
            except Exception as exc:  # noqa: BLE001
                _hop(hops, "bundle 真客户端", _HOP_FAIL, _exc_detail(exc))

    # H6: L4 合成活性（llm_enabled=false：确定性骨架、不落盘、不烧模型）
    payload = {"query": q, "library_id": lib or "", "doc_ids": [doc] if doc else [],
               "llm_enabled": False}
    try:
        r = _request("POST", f"{sop}/api/sops/synthesize", json=payload, timeout=60.0)
        code = r.status_code
        if code in (200, 412):
            _hop(hops, "sop-api /synthesize 活性", _HOP_OK, f"HTTP {code}（llm 关，不落盘）")
        elif code == 403:
            _hop(hops, "sop-api /synthesize 活性", _HOP_WARN, "HTTP 403（公网门）——该走内网口")
        elif code == 422:
            _hop(hops, "sop-api /synthesize 活性", _HOP_WARN, "HTTP 422（合成产物校验未过，退化信号）")
        elif code == 404:
            _hop(hops, "sop-api /synthesize 活性", _HOP_FAIL, "HTTP 404（端点缺失/部署不含 L4）")
        else:
            _hop(hops, "sop-api /synthesize 活性", _HOP_FAIL, f"HTTP {code}")
    except Exception as exc:  # noqa: BLE001
        _hop(hops, "sop-api /synthesize 活性", _HOP_FAIL, _exc_detail(exc))

    fails = [h for h in hops if h["status"] == _HOP_FAIL]
    warns = [h for h in hops if h["status"] == _HOP_WARN]
    severity = _SEVERITY_FAIL if fails else (_SEVERITY_WARN if warns else _SEVERITY_OK)
    result = {"severity": severity, "hops": hops, "sop_api_url": sop, "docs_api_url": docs,
              "library_id": lib, "doc_id": doc, "query": q}
    logger.info("SOP 链路冒烟完成：%s", render_line(result))
    return result


# ---------- 渲染 ----------

def render_line(result: Optional[dict]) -> str:
    """结论卡片里的一行摘要（与素材检查/拒答前提行并列）。空结果返回空串不占版面。"""
    if not result:
        return ""
    hops = result.get("hops") or []
    okn = sum(1 for h in hops if h.get("status") == _HOP_OK)
    line = f"SOP 链路冒烟：{result.get('severity', '?')}（{okn}/{len(hops)} 跳通过"
    fails = [h for h in hops if h.get("status") == _HOP_FAIL]
    if fails:
        shown = []
        for h in fails[:3]:
            d = str(h.get("detail") or "")
            shown.append(str(h.get("name")) + (f"（{d[:60]}{'…' if len(d) > 60 else ''}）" if d else ""))
        line += "；异常 " + "、".join(shown)
    skips = [h for h in hops if h.get("status") == _HOP_SKIP]
    if skips:
        line += f"；{len(skips)} 跳跳过"
    return line + "）"


def render_detail(result: Optional[dict]) -> str:
    """独立告警消息正文：逐跳状态（异常时随企微单独推一条）。"""
    if not result:
        return ""
    lines = [f"SOP 链路冒烟（aichat→sop-api→docs-api）：{result.get('severity')}",
             f"sop-api={result.get('sop_api_url')}  docs-api={result.get('docs_api_url')}"]
    for h in (result.get("hops") or []):
        detail = f"：{h.get('detail')}" if h.get("detail") else ""
        lines.append(f"- [{h.get('status')}] {h.get('name')}{detail}")
    return "\n".join(lines)

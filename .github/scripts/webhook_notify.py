"""Send WeCom webhook notification for deployment.

CI 脚本自包含：无法 import shared，内嵌最小 notify 逻辑。
仅允许 qyapi.weixin.qq.com 白名单（比 shared.notify 更严格）。
"""
import ipaddress
import json
import os
import socket
import subprocess
import sys
import urllib.request
from datetime import datetime
from urllib.parse import urlparse


# --- 内嵌 notify（CI 自包含） ---

def _validate_webhook_ci(url: str) -> str:
    """CI 专用：仅 https + 企微机器人白名单域名。"""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise SystemExit("WEBHOOK must use https")
    host = parsed.hostname or ""
    if host != "qyapi.weixin.qq.com":
        raise SystemExit(f"WEBHOOK host not allowed: {host!r} (only qyapi.weixin.qq.com)")
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise SystemExit(f"WEBHOOK host does not resolve: {exc}")
    if not infos:
        raise SystemExit("WEBHOOK host resolved to no addresses")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise SystemExit(f"WEBHOOK host resolves to disallowed address: {ip}")
    return url


def _send_markdown_ci(webhook: str, content: str) -> None:
    """CI 专用：发送 Markdown 消息，禁止重定向。"""
    payload = json.dumps(
        {"msgtype": "markdown", "markdown": {"content": content}},
        ensure_ascii=False,
    ).encode("utf-8")

    class _ForbidRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise urllib.error.HTTPError(newurl, code, "redirects are forbidden for webhook", headers, fp)

    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    opener = urllib.request.build_opener(_ForbidRedirect())
    resp = opener.open(req)
    print("WeCom notify status:", resp.status)

    try:
        body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"::error::WeCom notify response body unparsable: {exc}")
        sys.exit(1)
    if int(body.get("errcode", 0)) != 0:
        print(f"::error::WeCom notify rejected: errcode={body.get('errcode')} errmsg={body.get('errmsg')}")
        sys.exit(1)
    print("WeCom notify delivered (errcode=0)")


# --- 消息构建 ---

def _git(args):
    return subprocess.Popen(
        ["git"] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=repo,
    ).communicate()[0].decode().strip()


repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sha = _git(["log", "-1", "--format=%H"])[:7]
msg = _git(["log", "-1", "--format=%s"])
ref = _git(["rev-parse", "--abbrev-ref", "HEAD"])

fe = os.environ.get("FE", "?")
adm = os.environ.get("ADM", "?")
api = os.environ.get("API", "?")
run_url = os.environ.get("RUN_URL", "")
prev_sha = os.environ.get("PREV_SHA", "").strip()

commit_lines = []
prev_exists = False
if prev_sha:
    check = subprocess.run(
        ["git", "cat-file", "-e", prev_sha + "^{commit}"],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    prev_exists = check.returncode == 0
if prev_exists:
    log = _git(["log", "--oneline", "--no-merges", f"{prev_sha}..HEAD"])
    all_commits = [line for line in log.splitlines() if line.strip()]
    commit_lines = all_commits[:15]
    total = len(all_commits)
else:
    total = 1


def _release_version() -> str:
    try:
        with open(os.path.join(repo, "package.json"), encoding="utf-8") as fh:
            version = str(json.load(fh).get("version") or "")
        if version:
            return version if version.startswith("v") else "v" + version
    except Exception:
        pass
    return _git(["describe", "--tags", "--abbrev=0"]) or "unknown"


def _short(line: str, limit: int = 90) -> str:
    line = line.strip()
    if len(line) <= limit:
        return line
    head, _, rest = line.partition(" ")
    if head and len(rest) > limit - 8:
        return f"{head} {rest[: limit - 9].rstrip()}…"
    return line[: limit - 1] + "…"


# 状态感知（2026-10-21 实踩）：本步骤是 if: always()，旧文案写死「部署完成」——
# v0.3.2 构建失败（dockerignore 缺白名单）时群里照样收到「✅ 部署完成」，
# 运维会以为已上线。现在按 job.status 出标题，失败时明确写「生产可能仍是上一版」。
status = (os.environ.get("STATUS") or "success").strip().lower()
ok = status == "success"
content_parts = [
    "## ✅ AnGIneer 部署完成" if ok else "## ❌ AnGIneer 部署失败",
    f"> **版本:** `{_release_version()}`",
]
if not ok:
    content_parts.append(f"> **状态:** `{status or 'unknown'}`")

if prev_exists and total > 0:
    content_parts.append(f"> **本次提交:** `{total}` 个")
    for line in commit_lines:
        content_parts.append(f"> {_short(line)}")
    if total > len(commit_lines):
        content_parts.append(f"> … 共 {total} 个提交")
else:
    content_parts.append(f"> **提交:** `{sha}` - {_short(msg, 120)}")
content_parts += [
    f"> **分支:** `{ref}`",
    f"> **时间:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
    "",
]
if not ok:
    content_parts.append("> ⚠️ 构建或健康检查未通过：生产可能仍是上一版，请看 Actions 日志")
    content_parts.append("")
content_parts += [
    "**服务状态**",
    f"> 前台: `{fe}`",
    f"> 管理后台: `{adm}`",
    f"> API 文档: `{api}`",
]
if run_url:
    content_parts.append("")
    content_parts.append(f"[查看 Actions]({run_url})")

WECOM_CONTENT_MAX_BYTES = 4096
content = "\n".join(content_parts)
while len(content.encode("utf-8")) > WECOM_CONTENT_MAX_BYTES:
    commit_idx = next(
        (i for i, p in enumerate(content_parts) if p.startswith("> ") and len(p) > 8 and not p.startswith(("> **", "> 前台", "> 管理后台", "> API 文档", "> 分支", "> 时间", "> 提交", "> 本次"))),
        None,
    )
    if commit_idx is None or len(content_parts) <= 2:
        break
    content_parts.pop(commit_idx)
    content = "\n".join(content_parts)
if len(content.encode("utf-8")) > WECOM_CONTENT_MAX_BYTES:
    raw = content.encode("utf-8")
    content = raw[: WECOM_CONTENT_MAX_BYTES].decode("utf-8", errors="ignore") + "…"

if "--dry-run" in sys.argv:
    print("===== dry-run: markdown content =====")
    print(content)
    print(f"===== content bytes: {len(content.encode('utf-8'))} / 4096")
    sys.exit(0)

# --- 发送 ---

webhook = os.environ.get("WEBHOOK", "")
if not webhook:
    print("WEBHOOK not set, skipping")
    sys.exit(0)
webhook = _validate_webhook_ci(webhook)
_send_markdown_ci(webhook, content)

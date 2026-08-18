"""Send WeCom webhook notification for deployment."""
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime

webhook = os.environ.get("WEBHOOK", "")
if not webhook:
    print("WEBHOOK not set, skipping")
    sys.exit(0)


def _git(args):
    return subprocess.Popen(
        ["git"] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=repo,
    ).communicate()[0].decode().strip()


# repo root is parent of .github/scripts/ directory
repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sha = _git(["log", "-1", "--format=%H"])[:7]
msg = _git(["log", "-1", "--format=%s"])
ref = _git(["rev-parse", "--abbrev-ref", "HEAD"])

fe = os.environ.get("FE", "?")
adm = os.environ.get("ADM", "?")
api = os.environ.get("API", "?")
run_url = os.environ.get("RUN_URL", "")
prev_sha = os.environ.get("PREV_SHA", "").strip()

# 汇总本次 push 的提交：部署工作流在上一次部署后记录的 HEAD（PREV_SHA）到当前 HEAD 的提交列表
commit_lines = []
prev_exists = False
if prev_sha:
    check = subprocess.run(
        ["git", "cat-file", "-e", prev_sha + "^{commit}"],
        cwd=repo,
        capture_output=True,
    )
    prev_exists = check.returncode == 0
if prev_exists:
    log = _git(["log", "--oneline", "--no-merges", f"{prev_sha}..HEAD"])
    all_commits = [line for line in log.splitlines() if line.strip()]
    commit_lines = all_commits[:15]
    total = len(all_commits)
else:
    total = 1

content_parts = ["## ✅ AnGIneer 部署完成"]
if prev_exists:
    content_parts.append(f"> **本次提交:** `{total}` 个")
    for line in commit_lines:
        content_parts.append(f"> {line}")
    if total > len(commit_lines):
        content_parts.append(f"> … 共 {total} 个提交")
else:
    content_parts.append(f"> **提交:** `{sha}` - {msg}")
content_parts += [
    f"> **分支:** `{ref}`",
    f"> **时间:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
    "",
    "**服务状态**",
    f"> 前台: `{fe}`",
    f"> 管理后台: `{adm}`",
    f"> API 文档: `{api}`",
]
if run_url:
    content_parts.append("")
    content_parts.append(f"[查看 Actions]({run_url})")
content = "\n".join(content_parts)

payload = json.dumps(
    {"msgtype": "markdown", "markdown": {"content": content}},
    ensure_ascii=False,
).encode("utf-8")
req = urllib.request.Request(
    webhook,
    data=payload,
    headers={"Content-Type": "application/json; charset=utf-8"},
)
resp = urllib.request.urlopen(req)
print("WeCom notify status:", resp.status)

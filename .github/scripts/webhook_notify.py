"""Send WeCom webhook notification for deployment."""
import json
import os
import subprocess
import sys
import urllib.request

webhook = os.environ.get("WEBHOOK", "")
if not webhook:
    print("WEBHOOK not set, skipping")
    sys.exit(0)

def _git(args):
    return subprocess.Popen(["git"] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=repo).communicate()[0].decode().strip()

# repo root is parent of .github/scripts/ directory
repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sha = _git(["log", "-1", "--format=%H"])[:7]
msg = _git(["log", "-1", "--format=%s"])
ref = _git(["rev-parse", "--abbrev-ref", "HEAD"])

fe = os.environ.get("FE", "?")
adm = os.environ.get("ADM", "?")
api = os.environ.get("API", "?")
run_url = os.environ.get("RUN_URL", "")

content = f"""## ✅ AnGIneer 部署完成
> **提交:** `{sha}` - {msg}
> **分支:** `{ref}`
> **时间:** `{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`

**服务状态**
> 前台: `{fe}`
> 管理后台: `{adm}`
> API 文档: `{api}`

[查看 Actions]({run_url})"""

payload = json.dumps({"msgtype": "markdown", "markdown": {"content": content}}).encode()
req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"})
resp = urllib.request.urlopen(req)
print("WeCom notify status:", resp.status)

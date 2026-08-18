"""Send WeCom webhook notification for @angineer/* package release."""
import json
import os
import sys
import urllib.request
from datetime import datetime

webhook = os.environ.get("WEBHOOK", "")
if not webhook:
    print("WEBHOOK not set, skipping")
    sys.exit(0)

package = os.environ.get("PACKAGE", "angineer")
tag = os.environ.get("TAG", "")
sha = os.environ.get("SHA", "")[:7]
run_url = os.environ.get("RUN_URL", "")
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

lines = [f"## 🚀 {package} 发布"]
if tag:
    lines.append(f"> **版本:** `{tag}`")
if sha:
    lines.append(f"> **提交:** `{sha}`")
lines.append(f"> **时间:** `{now}`")
if run_url:
    lines.append(f"\n[查看 Actions]({run_url})")
content = "\n".join(lines)

payload = json.dumps({"msgtype": "markdown", "markdown": {"content": content}}).encode()
req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"})
resp = urllib.request.urlopen(req)
print("WeCom notify status:", resp.status)

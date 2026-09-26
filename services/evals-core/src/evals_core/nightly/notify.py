"""nightly 结果 → 企微卡片（三态严格区分；算法真相源，scripts 侧 CLI 复用）。

nightly 首跑实踩：评测步骤中途炸了、门禁产物不存在，旧内联脚本却把"未获取到
gate.json"渲染成绿色"评测通过"——从此绿色必须有 gate 结论背书，缺一律 error。

卡片必须带真实结果与基线差异（Δpp+CI、过渡矩阵）——用户视角是"测试集重新跑一遍
的结果和与基线的区别"，不是一句"通过"。
"""
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from shared.notify import (
    send_markdown as _send_markdown,
    split_webhooks as _split_webhooks,
    target_label as _target_label,
)

STATE_GREEN, STATE_RED, STATE_ERROR = "green", "red", "error"
_HEADS = {STATE_GREEN: "**🟢 AnGIneer nightly 评测通过**",
          STATE_RED: "**🔴 AnGIneer nightly 评测回归**",
          STATE_ERROR: "**⚠️ AnGIneer nightly 评测执行失败**"}


def _pct(value):
    return f"{value * 100:.2f}%" if isinstance(value, (int, float)) else "—"


def fmt_span(started_at, completed_at) -> Tuple[str, str]:
    """run 起止（UTC → 北京时间）与时长。字段缺失一律 '—'，通知不许造时间。"""
    try:
        start = datetime.fromisoformat(str(started_at)) + timedelta(hours=8)
        end = datetime.fromisoformat(str(completed_at)) + timedelta(hours=8)
        minutes = max(0, int((end - start).total_seconds() // 60))
        span = f"{start:%m-%d %H:%M} – {end:%H:%M}"
        duration = f"{minutes // 60}h{minutes % 60:02d}m"
        return span, duration
    except (TypeError, ValueError):
        return "—", "—"


def build_message(raw: Optional[dict], gate: Optional[dict], state: str, error_note: str = "",
                  material_line: str = "", judge_line: str = "") -> str:
    """一行一项：时间 / 时长 / 结果 / 分析（+ 判分缺失 + 素材检查）。

    material_line：B 层素材检查摘要（形如 "素材检查：ok（200 篇，内容未落地 0）"）。
    传了就多一行——体检通过与否都要在卡片里可见，否则"结论绿"无法说明素材层是否正常。

    judge_line：判分缺失摘要（由 pipeline._judge_missing_line 生成，形如
    "判分缺失：2 题判分未产出、已在阈值内放行（…）"）。阈值放行后卡片仍是绿色，
    这一行是唯一的知情口——不写就等于把"没判过的题"藏进"通过"里。
    """
    summary = (raw or {}).get("summary_scores") or {}
    span, duration = fmt_span((raw or {}).get("started_at"), (raw or {}).get("completed_at"))
    lines = [_HEADS.get(state, _HEADS[STATE_ERROR])]
    lines.append(f"时间：{span}")
    lines.append(f"时长：{duration}")
    if summary:
        lines.append(
            f"结果：**{_pct(summary.get('overall_score'))}**"
            f"（正确 {summary.get('correct', '?')}/{summary.get('total', '?')}）"
            f"｜judge 异常 {summary.get('judge_failed_count', '?')}"
            f"｜执行错误 {summary.get('errored', 0)}"
        )
    else:
        lines.append("结果：—（未产出评测结果）")
    if gate:
        m = gate.get("matrix") or {}
        delta = gate.get("delta")
        if isinstance(delta, (int, float)):
            pp = abs(delta) * 100
            move = "提升" if delta > 0.002 else ("下降" if delta < -0.002 else "基本持平")
            net = m.get("pf", 0) - m.get("fp", 0)
            tail = "，存在显著回归" if state == STATE_RED else ("，无显著回归" if delta > -0.002 else "，需关注")
            lines.append(f"分析：较基线{move} {pp:.1f} 个百分点（净{'增' if net >= 0 else '退'} {abs(net)} 题）{tail}。")
        else:
            lines.append("分析：门禁产物不完整，见服务器日志。")
    elif state == STATE_ERROR:
        lines.append(f"分析：评测环节未完成（{error_note or '见服务器日志'}），无结论。")
    else:
        lines.append("分析：门禁产物缺失，见服务器日志。")
    if judge_line:
        lines.append(judge_line)
    if material_line:
        lines.append(material_line)
    return "\n".join(lines)


def append_links(text: str, site_url: str = "", run_label: str = "") -> str:
    """查看链接：站点优先；有 run 记录可加一条溯源说明。"""
    if site_url:
        return text + f"\n查看：[夜间维护]({site_url})"
    return text


def split_webhooks(raw: str) -> List[str]:
    """WEBHOOK 配置支持逗号/分号/空白（含换行）分隔多个群机器人，去重保序。"""
    return _split_webhooks(raw)


def target_label(url: str) -> str:
    """日志用目标标识：只留 scheme://host，绝不回显含 key 的完整 URL。"""
    return _target_label(url)


def send(webhook: str, text: str) -> str:
    """单群推送：发送前校验 URL，发送后校验企微返回的 errcode。"""
    return _send_markdown(webhook, text)

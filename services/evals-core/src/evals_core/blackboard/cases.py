"""M0 主集题集（arms §3 的 22 题）：原文 + 出处，逐题可回查。

复现口径（照 arms §3 的约定）：题面与铺垫轮**一律用真实提问原文**，
判定链 = 该会话 ``seq <= case.seq`` 的全部消息（铺垫轮即 seq 更小的真实提问链），
所以这里只记 ``(session_id, seq, question)``，不硬编码每一条链——避免链与库漂移。

D5（合成题）**不在主集**：arms §3.4 明确它不计入分母，故不列入 CASES。
"""
from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class Case:
    """一条 M0 用例。"""

    case_id: str
    kind: str        # A 序数/指示代词 · B 值复用 · C 条款回引 · D 跨轮综合
    session_id: str
    seq: int         # 判分题在会话内的消息序号（chat_messages.seq）
    question: str    # 判分题原文（须与库内逐字一致，test 会校验）
    criterion: str   # 判定要点（简版；完整版见 arms §3）


CASES: Tuple[Case, ...] = (
    # —— A 类：序数 / 指示代词指涉（7）——
    Case("A1", "A", "chat-amin-test-0929", 20, "刚才第二条提到的规范，具体说了什么？",
         "正确指认「第二条」并按该轮答案复述规范要求；题面有歧义，可判作废"),
    Case("A2", "A", "chat-mumg89qg-c14jeu", 21, "刚才第2题说的安全系数，具体数值是多少？",
         "给出第 2 题安全系数的具体数值 + 出处；只答「需查表」= 部分对"),
    Case("A3", "A", "chat-mumg89qg-c14jeu", 25, "那抗倾稳定呢？",
         "承接上轮抗滑口径，给抗倾安全取值与出处"),
    Case("A4", "A", "chat-mumg89qg-c14jeu", 37, "把第4题的计算过程再详细讲一遍",
         "步骤完整（含各富裕深度分量）+ 数值与第 4 轮一致"),
    Case("A5", "A", "chat-municgem-i8m5b5", 21, "刚才第二个问题说了什么",
         "机制自检题：复述第 2 轮提问原文「想知道的」+ 当时回答要点；不计入 §7.1 分母"),
    Case("A6", "A", "chat-munhocfh-r5cbj6", 5,
         "请把上面提到的每一类支座病害的成因、检查方法和处治工艺都展开详细说明",
         "类别齐全（来自第 1 轮答案清单），每类含成因/检查/处治"),
    Case("A7", "A", "docs:chat-muf9m7b1-9ohqmp", 13, "上一条里为什么没有一个引用，都是[K6] [K7]?",
         "指认上一条回答里的引用标记分布并解释"),
    # —— B 类：值复用 / 跨轮计算（5）——
    Case("B1", "B", "chat-mupdlobp-22wezs", 5,
         "帮我算一下：先查出 DWT=40000 杂货船的满载吃水 T，再加上 0.5 米富裕深度，总共多少？",
         "复用上一轮 T 值 + 给出 T+0.5 结果；T 与表不一致 = ❌"),
    Case("B2", "B", "chat-mupecuyb-zu4x4l", 9,
         "某港区设计高水位 3.5m，设计低水位 0.5m，DWT=40000 杂货船，计算航道通航水深",
         "公式 + 各分量取值 + 结果 + 规范依据"),
    Case("B3", "B", "chat-mupecuyb-zu4x4l", 13, "查一下杂货船设计船型尺度，DWT=40000 的满载吃水",
         "直接给出 T 值、不重复检索错表"),
    Case("B4", "B", "chat-muj4iiw7-2jwt5v", 41,
         "某5000吨级散货船，满载吃水T=9.8m，试计算码头前沿设计水深",
         "分量齐（龙骨下富裕深度等）+ 结果正确 + 出处"),
    Case("B5", "B", "chat-mumg89qg-c14jeu", 13, "某3万吨级杂货船，满载吃水10.5米，试计算码头前沿设计水深。",
         "同 B4 口径"),
    # —— C 类：条款回引（6）——
    Case("C1", "C", "chat-muh62u2n-94kq9h", 17, "JTS 181 里乘潮水位累积频率表怎么规定的",
         "给出条文/表号 + 频率取值口径"),
    Case("C2", "C", "docs:chat-muf9m7b1-9ohqmp", 11, "“乘潮累积频率”的具体统计",
         "统计步骤完整（样本、年限、保证率）"),
    Case("C3", "C", "docs:chat-mufo8ffw-jirdxg", 17,
         "“设计使用年限”在《港口工程荷载规范》或《码头结构设计规范》中的具体取值要求",
         "规范名 + 年限取值"),
    Case("C4", "C", "docs:chat-mufo8ffw-jirdxg", 21,
         "超过设计使用年限后，码头结构进行继续使用或改造的具体评估要求",
         "承接 C3 结论给出评估要求（检测项/评定方法）"),
    Case("C5", "C", "chat-muj4iiw7-2jwt5v", 44, "重力式码头抗滑稳定性验算应符合哪条规范要求？",
         "规范名 + 条款号 + 安全系数"),
    Case("C6", "C", "p0-accept-2", 1, "沉箱干舷高度应满足哪条规范？",
         "给出规范出处与限值"),
    # —— D 类：跨轮综合（4，主集；D5 为合成题不计入）——
    Case("D1", "D", "chat-muh62u2n-94kq9h", 5, "具体差多少",
         "给出可核对的数量口径，或明确说明证据缺失项"),
    Case("D2", "D", "docs:chat-mufmsfto-no2hkt", 6, "内河与外海有区别么",
         "至少在基准水位/方法/规范依据三项上说清区别"),
    Case("D3", "D", "docs:chat-mufn0n8m-0i0wkg", 22, "基础的混凝土用多少标号的",
         "引用上一轮给的基础尺寸前提 + 标号建议"),
    Case("D4", "D", "chat-muj4iiw7-2jwt5v", 5, "5000吨级散货船的码头前沿水深富裕高度取值是多少？",
         "表值 + 出处"),
)

CASE_IDS: Tuple[str, ...] = tuple(case.case_id for case in CASES)


def cases_by_kind(kind: str) -> List[Case]:
    """按类型取用例（A/B/C/D）。"""
    return [case for case in CASES if case.kind == kind]

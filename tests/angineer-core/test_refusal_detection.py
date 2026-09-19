"""拒答判定（is_refusal_text）的单元闸。

背景（2026-09-19 生产实测）：39 道拒答题里 18 道被判成"作答"（幻觉），整体正确率被记成
−2.85pp；真实幻觉数其实没变（15→13）。根因是判定用了连续子串「未能检索到相关答案」，
而模型会把主题插进模板——「知识库未能检索到关于「X」的定义及其探测方法的相关答案。」——
两次运行的模板原句命中数都是 0。下面的用例取的都是那一夜的真实回答原文。
"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

from angineer_core.agent_messages import (  # noqa: E402
    REFUSAL_ANSWER_TEXT,
    is_refusal_text,
)

# ── 那一夜被判错的真实回答（应为拒答）────────────────────────────────
REAL_MISSED_REFUSALS = (
    "知识库未能检索到关于“原恒星（protostars）”的定义及其在空间中探测方法的相关答案。"
    "检索结果主要涉及计算机视觉中的目标检测校准、宇宙纤维结构中的中性氢探测以及信号处理中的到达角估计。",
    "知识库未能检索到关于“为什么在 regime-switching diffusions（机制转换扩散过程）中探索"
    "非再生（non-regenerative）情况很重要”的直接证据。检索到的证据主要涉及高频交易（HFT）中的"
    "半马尔可夫和霍克斯跳跃扩散。",
    "知识库未能检索到关于“constrained D-optimal sampling”（约束D最优采样）具体优势的直接证据。",
    "基于提供的检索证据，无法直接回答“归一化注意力熵是否在训练期间随层数减少”这一具体问题。",
    "基于提供的检索证据，无法回答关于“实值图信号的 GFT 系数”这一问题。",
    "The retrieved knowledge base entries discuss blockchain transaction fees and liquidity provider fees, "
    "hence they cannot answer the question about index funds directly.",
)

# ── 那一夜同样被判错、但确实是作答（应为非拒答）──────────────────────
REAL_GENUINE_ANSWERS = (
    "基于检索到的证据，自调控回路（autoregulatory circuits）在细胞身份转换和组织稳态维持中"
    "主要扮演以下角色：\n1. **维持细胞群体比例的稳态** [K1]。",
    "是的，在所提供的知识库证据中，智能体（具体为四旋翼无人机）的轨迹被表示为时间的多项式函数。",
    "对于所有 $x \\in \\mathbb{R}^{n}$，欧几里得范数（Euclidean norm）定义为向量各分量平方和的"
    "平方根，也称为 $L^2$ 范数 [K1]。",
)


class IsRefusalTextTests(unittest.TestCase):
    def test_template_verbatim(self):
        self.assertTrue(is_refusal_text(REFUSAL_ANSWER_TEXT))

    def test_real_interpolated_variants_are_refusals(self):
        """模型把主题插进模板——这正是 2026-09-19 漏检 18 道的那一类。"""
        for text in REAL_MISSED_REFUSALS:
            self.assertTrue(is_refusal_text(text), text[:40])

    def test_legacy_wording_still_recognized(self):
        self.assertTrue(is_refusal_text("没有检索到足够证据支持最终结论。"))

    def test_real_genuine_answers_are_not_refusals(self):
        for text in REAL_GENUINE_ANSWERS:
            self.assertFalse(is_refusal_text(text), text[:40])

    def test_soft_phrase_after_citation_is_not_refusal(self):
        """引用之后的软化措辞属于正常作答（"此处无法确定"），不能当拒答。"""
        text = (
            "根据规范第 4.2 条，混凝土强度等级按立方体抗压强度标准值划分 [K1]；"
            "但对于本工程未给出的养护条件，无法确定其最终取值 [K2]。"
        )
        self.assertFalse(is_refusal_text(text))

    def test_lead_soft_markers_only_before_citation(self):
        self.assertTrue(is_refusal_text("无法回答该问题。"))
        self.assertTrue(is_refusal_text("基于提供的检索证据，无法直接回答该问题。"))
        self.assertTrue(is_refusal_text("The retrieved passages do not contain the requested figure."))

    def test_soft_partial_coverage_disclosure_is_not_refusal(self):
        """「证据不足的部分未覆盖。」是合法的部分覆盖说明，不是拒答。

        2026-09-19 实踩：把「证据不足」收进弱标记后，`make_final_answer_guard` 会把这类回答
        整段换成拒答话术（test_guard_keeps_soft_partial_coverage_disclosure 立刻变红）。
        这类软表述由 `_HALF_REFUSAL_LEAD_PATTERNS` / `strip_half_refusal_lead` 单独处理。
        """
        self.assertFalse(is_refusal_text("证据不足的部分未覆盖。已支持的内容如下：混凝土强度等级为 C30。"))
        self.assertFalse(is_refusal_text("信息不足，以下为已确认部分：混凝土强度等级为 C30。"))

    def test_empty_and_none_safe(self):
        self.assertFalse(is_refusal_text(""))
        self.assertFalse(is_refusal_text(None))  # type: ignore[arg-type]

    def test_short_normal_answer_is_not_refusal(self):
        self.assertFalse(is_refusal_text("混凝土强度等级为 C30。"))


if __name__ == "__main__":
    unittest.main()

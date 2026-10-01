"""题集卡元信息回填：给存量题集写 eval_dataset.meta（默认 dry-run，--apply 才落库）。

匹配规则：dataset_id 精确优先、title 兜底；未命中跳过并在结尾列出。
spec 与 meta 结构见 docs/req-dataset-card.md；生产在容器内重跑同脚本。
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

from evals_core.dataset import manager  # noqa: E402

# FinanceBench 锚点数字 2026-10-01 自官方仓库 /results/ 16 配置原始标注逐文件复算
# （与 arXiv 2311.11944 论文 Table 同源；每配置 150 题人工判）。
ENTRIES = [
    {
        "dataset_id": "financebench-open-150-v1",
        "title": "FinanceBench 开源子集（150 题）",
        "meta": {
            "publisher": "Patronus AI",
            "mode": "单篇RAG",
            "domain": "金融",
            "purpose": "测 SEC 申报文件（10-K/10-Q/8K/财报）开放问答：数值提取、跨表计算、趋势判断",
            "source_url": "https://github.com/patronus-ai/financebench",
            "source_note": "官方开源子集 150 题全量（metrics/domain/novel 各 50）；语料=84 篇 SEC PDF 回源 EDGAR",
            "distribution": [
                {"label": "metrics-generated", "count": 50},
                {"label": "domain-relevant", "count": 50},
                {"label": "novel-generated", "count": 50},
            ],
            "leaderboard": [
                {
                    "label": "GPT-4-Turbo 单库向量检索（现实 RAG 最优档）",
                    "score": "50%",
                    "note": "150 题人工复核；11% 错 / 39% 拒答",
                },
                {
                    "label": "GPT-4-Turbo Oracle（金证据页直给）",
                    "score": "85%",
                    "note": "非检索配置，不可与 RAG 成绩同表对比",
                },
                {
                    "label": "16 配置人工判汇总",
                    "score": "47%",
                    "note": "arXiv 2311.11944",
                },
            ],
        },
    },
    {
        "dataset_id": "open-ragbench-subset-v4.1",
        "title": "Open RAG Benchmark 子集 v4.1",
        "meta": {
            "publisher": "Vectara（Open RAG Benchmark）；AnGIneer v4.1 修订",
            "mode": "整体RAG",
            "domain": "学术（arXiv 论文）",
            "purpose": "端到端 RAG 回归主题集：182 篇 arXiv 论文，为跨学科论文拼盘（题目引用 208 篇，统计/ML 36、经金 35、物理 31、生医 22、数学 21 居前）",
            "source_url": "https://huggingface.co/datasets/vectara/open_ragbench",
            "source_note": "源头：Vectara 官方 Open RAG Benchmark（queries/qrels/answers 与论文 PDF 均取自该数据集）",
            "distribution": [
                {"label": "text", "count": 627, "note": "纯文本题"},
                {"label": "text-image", "count": 255},
                {"label": "text-table", "count": 82},
                {"label": "text-table-image", "count": 76},
            ],
        },
    },
    {
        "dataset_id": "open-ragbench-refusal-v2",
        "title": "拒答 39 题",
        "meta": {
            "publisher": "AnGIneer",
            "domain": "跨域（库外语料）",
            "purpose": "拒答守卫行为观测：超语料负样本，预期拒答（39 题）",
            "mode": "整体RAG",
            "source_note": "题面为库外通用语料问题（如 protostars），与知识库无关",
        },
    },
    {
        "dataset_id": "open-ragbench-smoke-v1",
        "title": "Open RAG Benchmark 冒烟门禁集 v1",
        "meta": {
            "publisher": "AnGIneer",
            "domain": "跨域（库外语料）",
            "purpose": "评测管道冒烟与门禁快速检查（25 题）",
            "mode": "整体RAG",
        },
    },
    {
        "dataset_id": "financebench-sens4-v1",
        "title": "Boeing_2022 配对异动 4 题第三采样",
        "meta": {
            "publisher": "AnGIneer",
            "domain": "金融",
            "purpose": "图描述补全敏感性定向探针（Boeing_2022 配对 4 题第三采样）",
            "mode": "单篇RAG",
        },
    },
    {
        "dataset_id": "pos-regress-60-v1",
        "title": "正面题回归60（方案①误伤检查）",
        "meta": {
            "publisher": "AnGIneer",
            "domain": "跨域（库外语料）",
            "purpose": "拒答方案①（相关性标签+V11）误伤检查：正面题回归 60 题",
            "mode": "整体RAG",
        },
    },
    {
        "dataset_id": "lawbench-1-1-v1",
        "title": "LawBench 1-1 法条知识",
        "meta": {
            "publisher": "OpenCompass（南京大学）",
            "domain": "法律",
            "purpose": "LawBench 任务 1-1「法条记忆」：给定法名+条号答内容（500 题）",
            "mode": "单篇RAG",
            "source_url": "https://github.com/open-compass/LawBench",
        },
    },
    {
        "dataset_id": "reviewed-exam-2020-2019",
        "title": "精筛50题",
        "meta": {
            "publisher": "AnGIneer",
            "domain": "工程（海港真题）",
            "purpose": "海港工程真题精筛 50 题（2020/2019 卷）",
            "mode": "整体RAG",
        },
    },
    {
        "dataset_id": "eval_1",
        "title": "海港水文30问",
        "meta": {
            "publisher": "AnGIneer",
            "domain": "工程（海港水文规范）",
            "purpose": "知识库基线评测集 1：海港水文规范问答 30 问（含 3 题库外拒答负样本）",
            "mode": "整体RAG",
        },
    },
    {
        "dataset_id": "clause-probe-v1",
        "title": "条款号直达探针集",
        "meta": {
            "publisher": "AnGIneer",
            "domain": "工程（条款检索）",
            "purpose": "条款号直达：只断言路由层+检索层，不跑生成/判官",
            "source_note": "16 题；题目带 probe_gold 断言块",
        },
    },
    {
        "dataset_id": "intent-router-v1",
        "title": "意图路由测试集 v1（100 题 L0-L4 分层）",
        "meta": {
            "publisher": "AnGIneer",
            "domain": "意图路由",
            "purpose": "意图分类 L0-L4 路由正确性（不跑检索/生成）",
            "source_note": "100 题；3 次重跑逐题一致",
        },
    },
]


def _match_row(rows, entry):
    if entry["dataset_id"]:
        for row in rows:
            if row["dataset_id"] == entry["dataset_id"]:
                return row
    for row in rows:
        if row["title"] == entry["title"]:
            return row
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="题集卡元信息回填（dry-run 默认，--apply 落库）")
    parser.add_argument("--apply", action="store_true", help="真正写库")
    args = parser.parse_args()

    rows = manager.list_datasets()
    unmatched = []
    matched = 0
    for entry in ENTRIES:
        row = _match_row(rows, entry)
        if not row:
            unmatched.append(entry["title"])
            continue
        matched += 1
        action = "写库" if args.apply else "将写(dry-run)"
        print(f"[{action}] {row['dataset_id']} ({row['title']}) -> keys: {sorted(entry['meta'])}")
        if args.apply:
            manager.update_dataset(row["dataset_id"], {"meta": entry["meta"]})

    configured = {(e["dataset_id"], e["title"]) for e in ENTRIES}
    leftovers = [
        r for r in rows
        if not any((did and r["dataset_id"] == did) or r["title"] == title for did, title in configured)
    ]
    print(f"命中 {matched}/{len(ENTRIES)}；库内共 {len(rows)} 个题集，未配置 meta 的：")
    for r in leftovers:
        print(f"  - {r['dataset_id']} ({r['title']})")
    if unmatched:
        # 本地/生产题集清单本就不同（如 v4.1 只在生产库），未命中降级为警告；
        # 仅当全部未命中（=脚本配置错位）才报错。
        print(f"未命中（该环境库中不存在，已跳过）: {unmatched}")
    if matched == 0:
        print("ENTRIES 全部未命中——脚本配置与库内容错位，请核对 dataset_id/title")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

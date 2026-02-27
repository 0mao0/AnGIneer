import sys
import os
import re

sys.path.insert(0, os.path.abspath("services/angineer-core/src"))
sys.path.insert(0, os.path.abspath("services/sop-core/src"))
sys.path.insert(0, os.path.abspath("services/engtools/src"))

from angineer_core.infra.llm_client import llm_client
from bs4 import BeautifulSoup
import json

KB_FILE = "data/knowledge_base/markdown/海港总体设计规范_JTS_165-2025.md"

with open(KB_FILE, "r", encoding="utf-8") as f:
    kb_content = f.read()

soup = BeautifulSoup(kb_content, "html.parser")
html_tables = soup.find_all("table")

# 找出所有表格标题（正则匹配 "表X.X" 或 "表A.X" 格式）
table_titles = re.findall(r'([^<\n]+?)\s*<table', kb_content)

# 建立表格标题到表格的映射
all_tables = []
for i, table in enumerate(html_tables):
    caption = table_titles[i] if i < len(table_titles) else f"表格 {i+1}"
    
    # 解析表头（直接取第一行，忽略rowspan/colspan）
    headers = []
    rows = table.find_all("tr")
    if rows:
        first_row = rows[0].find_all(["th", "td"])
        if first_row:
            headers = [h.get_text(strip=True) for h in first_row]
    
    # 解析数据行（从第二行开始，因为第一行是表头）
    data_rows = []
    for row in rows[1:]:
        cells = row.find_all(["th", "td"])
        if cells:
            data_rows.append([c.get_text(strip=True) for c in cells])
    
    all_tables.append({
        "index": i + 1,
        "caption": caption,
        "headers": headers,
        "rows": data_rows[:15],
        "html": str(table)  # 保留完整HTML
    })

print(f"共找到 {len(all_tables)} 个表格\n")

# 打印所有表格的caption用于调试
print("所有表格标题:")
for t in all_tables:
    print(f"  {t['index']}: {t['caption'][:80]}")

# 测试用例
TEST_QUERIES = [
    {
        "name": "油船100000吨吃水",
        "table_hint": "表A.0.2-3 油船设计船型尺度",
        "query": "100000吨油船的满载吃水是多少？"
    },
    {
        "name": "散货船50000吨吃水",
        "table_hint": "表A.0.2-2 散货船设计船型尺度",
        "query": "50000吨散货船的满载吃水是多少？"
    },
    {
        "name": "集装箱船100000吨吃水",
        "table_hint": "表A.0.2-4 集装箱船设计船型尺度",
        "query": "100000吨集装箱船的满载吃水是多少？"
    },
    {
        "name": "龙骨下富裕深度-岩石",
        "table_hint": "表6.4.5-1 航行时龙骨下最小富裕深度",
        "query": "100000吨船舶在岩石质海底的龙骨下最小富裕深度是多少？"
    },
    {
        "name": "航行下沉量",
        "table_hint": "图6.4.5 船舶航行时船体下沉值曲线",
        "query": "100000吨船舶在航速10节时的航行下沉量是多少？"
    },
    {
        "name": "波浪富裕深度",
        "table_hint": "表6.4.5-2 船、浪夹角Ψ与Z2H4的变化系数值",
        "query": "受限水域条件下波浪富裕深度Z2是多少？"
    },
    {
        "name": "富裕宽度",
        "table_hint": "表6.4.2-1 船舶与航道底边线间的富裕宽度",
        "query": "100000吨散货船的富裕宽度c是多少？"
    },
]

client = llm_client

print("=" * 80)
print("LLM 表格查询测试")
print("=" * 80)

for test in TEST_QUERIES:
    print(f"\n{'='*60}")
    print(f"测试: {test['name']}")
    print(f"表格: {test['table_hint']}")
    print(f"查询: {test['query']}")
    print("-" * 60)
    
    # 找到对应的表格（标准化后匹配）
    target_table = None
    import re
    hint_raw = test['table_hint'].replace('Ψ', 'Psi')
    hint_normalized = re.sub(r'[^0-9a-zA-Z\u4e00-\u9fa5]', '', hint_raw)
    for t in all_tables:
        caption_raw = t['caption'].replace('Ψ', 'Psi')
        caption_normalized = re.sub(r'[^0-9a-zA-Z\u4e00-\u9fa5]', '', caption_raw)
        if hint_normalized in caption_normalized or caption_normalized in hint_normalized:
            target_table = t
            break
    
    # 构造表格内容（直接使用HTML）
    if target_table:
        table_text = f"表格 {target_table['index']}: {target_table['caption']}\n"
        table_text += target_table['html']
    else:
        table_text = "未找到对应表格，请从整个知识库中搜索相关信息。"
    
    # 构造 prompt
    prompt = f"""你是一个港口工程专家。请根据以下表格内容回答问题。

{table_text}

问题: {test['query']}

请直接从表格中提取数值，不要估算。如果表格中没有精确匹配的数据，请说明区间或查找最接近的值。"""
    
    # 调用 LLM
    response = client.chat(
        model="Qwen3-4B (Public)",
        messages=[{"role": "user", "content": prompt}],
    )
    
    print(f"LLM 回答: {response[:800]}")
    print()

print("\n" + "=" * 80)
print("测试完成")
print("=" * 80)

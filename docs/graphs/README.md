# 图 A / 图 B 原型（2026-10-05）

| 文件 | 是什么 |
| --- | --- |
| `graph-a-会话轨迹-堤顶高程.svg` | **图 A 原型**：真实会话 6 轮，每轮一个节点 + 该轮真正引用的条款；
细线＝跨轮引同一部规范（主题延续）。**缺**：把连续同主题的轮聚成一个「会话节点」。 |
| `graph-b-业务逻辑-堤顶高程.svg` | **图 B 原型**：LLM 从真实检索证据内化出的计算流程图（8 要素/8 边 + 公式
+ 5 项证据缺项）。**证据薄 → 图是浅星形**。 |
| `graph-b-业务逻辑-码头前沿设计水深.svg` | 同流程、证据较厚的一题（Dm = T + Z + DeltaZ，3 上游 → 1 结果）。 |
| `*.json` | 蒸馏出的结构化图（elements / relations / formula / missing），渲染器的输入。 |

复现：
```
python .dsh-scratch/graphA_prototype.py <session_id> <slug>     # 图 A：会话 → 轨迹 SVG
python .dsh-scratch/graphB_distill.py --question "…" --slug x  # 图 B：证据 → LLM → JSON（1 次调用）
python .dsh-scratch/graphB_render.py .dsh-scratch/graphB_x.json # JSON → SVG
python .dsh-scratch/publish_graphs.py                          # 搬到本目录 + 内联样式
```

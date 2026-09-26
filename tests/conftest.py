"""测试全局约定：ops 观测落盘默认停用（P0-1 测试卫生）。

agent loop / classifier 的单测会真实执行打点路径；不加此开关，pytest 会把测试流量
写进仓库 data/ops/*.jsonl 污染生产观测。需要专门验证落盘行为的测试（如
tests/angineer-core/test_ops_metrics.py）应自行设置 ANGINEER_OPS_DIR 指向临时目录。
"""
import os

os.environ.setdefault("ANGINEER_OPS_DISABLE", "1")

"""
Pytest 配置文件，确保测试路径正确设置。

此文件在 pytest 启动时自动加载，用于配置测试环境。
"""
import sys
import os

# 获取项目根目录
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))

# 添加必要的路径到 sys.path - 使用 insert(0, ...) 确保优先级
# 注意：angineer-core 必须在 engtools 之前，因为 engtools 依赖它
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "../services/angineer-core/src"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "../services/sop-core/src"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "../services/engtools/src"))

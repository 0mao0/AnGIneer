"""docs-api 测试公共配置：把服务根目录挂上 sys.path（路由模块按 `import docs_routes` 引用）。"""
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

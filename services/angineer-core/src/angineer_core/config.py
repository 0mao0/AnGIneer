import os

def get_knowledge_dir() -> str:
    """获取知识库目录路径。"""
    env_path = os.getenv("PICO_KNOWLEDGE_DIR") or os.getenv("KNOWLEDGE_DIR")
    if env_path:
        return env_path
    base_dir = os.path.dirname(__file__)
    # Point to d:\AI\AnGIneer\data\knowledge_base
    # config.py is in services/angineer-core/src/angineer_core
    # ../../../../data/knowledge_base
    return os.path.abspath(os.path.join(base_dir, "../../../../data/knowledge_base"))

KNOWLEDGE_DIR = get_knowledge_dir()

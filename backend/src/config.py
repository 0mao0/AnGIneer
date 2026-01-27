import os

def get_knowledge_dir() -> str:
    """获取知识库目录路径。"""
    env_path = os.getenv("PICO_KNOWLEDGE_DIR") or os.getenv("KNOWLEDGE_DIR")
    if env_path:
        return env_path
    base_dir = os.path.dirname(__file__)
    return os.path.normpath(os.path.join(base_dir, "..", "knowledge"))

KNOWLEDGE_DIR = get_knowledge_dir()

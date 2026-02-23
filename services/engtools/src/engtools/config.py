import os

def get_knowledge_dir() -> str:
    """获取知识库目录路径。"""
    env_path = os.getenv("PICO_KNOWLEDGE_DIR") or os.getenv("KNOWLEDGE_DIR")
    if env_path:
        return env_path
    
    # Calculate default path relative to this file
    # This file is in services/engtools/src/engtools/config.py
    # We want to reach data/knowledge_base at the project root
    # d:\AI\AnGIneer\services\engtools\src\engtools\config.py
    # ../../../../data/knowledge_base
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(base_dir, "../../../../"))
    knowledge_dir = os.path.join(project_root, "data", "knowledge_base")
    
    return knowledge_dir

KNOWLEDGE_DIR = get_knowledge_dir()

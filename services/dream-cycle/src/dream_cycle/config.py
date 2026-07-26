"""Dream Cycle 配置模块。

通过环境变量和默认值管理 Dream Cycle 的所有可调参数。
"""

import os
from dataclasses import dataclass, field


@dataclass
class DreamCycleConfig:
    """Dream Cycle 全局配置，从环境变量加载。"""

    # 总开关
    enabled: bool = True

    # 调度
    schedule: str = "0 2 * * *"  # cron expression: 每日凌晨 2:00

    # 实体去重
    dedup_enabled: bool = True
    dedup_auto_threshold: float = 0.95   # >= 此值自动合并
    dedup_review_threshold: float = 0.7  # >= 此值人工确认
    dedup_llm_enabled: bool = True       # 是否启用 LLM 语义等价判断

    # 矛盾检测
    contradiction_enabled: bool = True
    contradiction_llm_enabled: bool = True

    # 孤立实体清理
    orphan_enabled: bool = True
    orphan_min_age_days: int = 7        # 至少存在 N 天
    orphan_auto_clean_days: int = 14    # >= 此天数自动标记 inactive

    # 过期知识
    staleness_enabled: bool = True
    staleness_llm_enabled: bool = True

    # SOP 健康统计
    sop_health_enabled: bool = True

    # 执行控制
    task_timeout_seconds: int = 1800    # 每个 task 超时 30 分钟
    batch_size: int = 1000              # 分批处理大小

    # LLM 配置
    llm_model: str = "Qwen3.6-35B-A3B"
    llm_config_name: str = "Qwen3.6-A3B"

    # 路径
    data_dir: str = ""
    reports_dir: str = ""
    audit_dir: str = ""

    # SQLite 数据库路径（从环境变量推断）
    graph_db_path: str = ""
    knowledge_index_path: str = ""
    knowledge_meta_path: str = ""

    def __post_init__(self):
        """从环境变量覆盖默认值。"""
        self._load_from_env()

    def _load_from_env(self):
        """加载环境变更配置。"""
        self.enabled = os.environ.get("DREAM_CYCLE_ENABLED", "true").lower() == "true"
        self.schedule = os.environ.get("DREAM_CYCLE_SCHEDULE", self.schedule)

        self.dedup_enabled = os.environ.get("DREAM_CYCLE_DEDUP_ENABLED", "true").lower() == "true"
        self.dedup_auto_threshold = float(os.environ.get("DREAM_CYCLE_DEDUP_AUTO_THRESHOLD", str(self.dedup_auto_threshold)))
        self.dedup_review_threshold = float(os.environ.get("DREAM_CYCLE_DEDUP_REVIEW_THRESHOLD", str(self.dedup_review_threshold)))
        self.dedup_llm_enabled = os.environ.get("DREAM_CYCLE_DEDUP_LLM_ENABLED", "true").lower() == "true"

        self.contradiction_enabled = os.environ.get("DREAM_CYCLE_CONTRADICTION_ENABLED", "true").lower() == "true"
        self.contradiction_llm_enabled = os.environ.get("DREAM_CYCLE_CONTRADICTION_LLM_ENABLED", "true").lower() == "true"

        self.orphan_enabled = os.environ.get("DREAM_CYCLE_ORPHAN_ENABLED", "true").lower() == "true"
        self.orphan_min_age_days = int(os.environ.get("DREAM_CYCLE_ORPHAN_MIN_AGE_DAYS", str(self.orphan_min_age_days)))
        self.orphan_auto_clean_days = int(os.environ.get("DREAM_CYCLE_ORPHAN_AUTO_CLEAN_DAYS", str(self.orphan_auto_clean_days)))

        self.staleness_enabled = os.environ.get("DREAM_CYCLE_STALENESS_ENABLED", "true").lower() == "true"

        self.task_timeout_seconds = int(os.environ.get("DREAM_CYCLE_TASK_TIMEOUT", str(self.task_timeout_seconds)))
        self.batch_size = int(os.environ.get("DREAM_CYCLE_BATCH_SIZE", str(self.batch_size)))

        self.llm_model = os.environ.get("DREAM_CYCLE_LLM_MODEL", self.llm_model)
        self.llm_config_name = os.environ.get("DREAM_CYCLE_LLM_CONFIG_NAME", self.llm_config_name)

        # 数据路径（默认相对于项目根目录）
        project_root = os.environ.get("ANGINEER_PROJECT_ROOT", "")
        if not project_root:
            # 从当前文件向上查找项目根（包含 services/ 的目录）
            current = os.path.dirname(os.path.abspath(__file__))
            while current and not os.path.isdir(os.path.join(current, "services")):
                parent = os.path.dirname(current)
                if parent == current:
                    break
                current = parent
            project_root = current

        self.data_dir = os.environ.get("DREAM_CYCLE_DATA_DIR", os.path.join(project_root, "data", "dream_cycle"))
        self.reports_dir = os.path.join(self.data_dir, "reports")
        self.audit_dir = os.path.join(self.data_dir, "audit")

        self.graph_db_path = os.environ.get(
            "KNOWLEDGE_GRAPH_DB_PATH",
            os.path.join(project_root, "data", "knowledge_graph.sqlite"),
        )
        self.knowledge_index_path = os.environ.get(
            "KNOWLEDGE_INDEX_DB_PATH",
            os.path.join(project_root, "data", "knowledge_base", "knowledge_index.sqlite"),
        )
        self.knowledge_meta_path = os.environ.get(
            "KNOWLEDGE_META_DB_PATH",
            os.path.join(project_root, "data", "knowledge_base", "knowledge_meta.sqlite"),
        )


_config: DreamCycleConfig | None = None


def get_config() -> DreamCycleConfig:
    """获取 Dream Cycle 全局配置单例。"""
    global _config
    if _config is None:
        _config = DreamCycleConfig()
    return _config

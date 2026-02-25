"""
时间度量模块，提供执行时间测量与分析功能。
"""
import time
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from functools import wraps
from contextlib import contextmanager
from collections import defaultdict

from angineer_core.infra.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TimingRecord:
    """时间记录。"""
    name: str
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    category: str = "default"
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def complete(self, end_time: Optional[float] = None) -> float:
        """完成计时。"""
        self.end_time = end_time or time.perf_counter()
        self.duration = self.end_time - self.start_time
        return self.duration


class TimingStats:
    """
    时间统计收集器。
    
    支持按类别收集和统计时间数据。
    """
    
    def __init__(self):
        self._records: List[TimingRecord] = []
        self._active: Dict[str, TimingRecord] = {}
        self._by_category: Dict[str, List[TimingRecord]] = defaultdict(list)
    
    def start(
        self,
        name: str,
        category: str = "default",
        metadata: Optional[Dict[str, Any]] = None
    ) -> TimingRecord:
        """
        开始计时。
        
        Args:
            name: 计时名称
            category: 类别
            metadata: 元数据
        
        Returns:
            时间记录
        """
        record = TimingRecord(
            name=name,
            start_time=time.perf_counter(),
            category=category,
            metadata=metadata or {}
        )
        self._active[name] = record
        return record
    
    def stop(self, name: str) -> Optional[float]:
        """
        停止计时。
        
        Args:
            name: 计时名称
        
        Returns:
            耗时（秒），如果计时不存在则返回 None
        """
        if name not in self._active:
            logger.warning(f"Timing not found: {name}")
            return None
        
        record = self._active.pop(name)
        duration = record.complete()
        
        self._records.append(record)
        self._by_category[record.category].append(record)
        
        return duration
    
    def get_record(self, name: str) -> Optional[TimingRecord]:
        """获取指定名称的时间记录。"""
        for record in self._records:
            if record.name == name:
                return record
        return None
    
    def get_records_by_category(self, category: str) -> List[TimingRecord]:
        """获取指定类别的所有时间记录。"""
        return self._by_category.get(category, [])
    
    def get_total_duration(self, category: Optional[str] = None) -> float:
        """
        获取总耗时。
        
        Args:
            category: 可选的类别过滤
        
        Returns:
            总耗时（秒）
        """
        if category:
            records = self._by_category.get(category, [])
        else:
            records = self._records
        
        return sum(r.duration or 0 for r in records)
    
    def get_summary(self) -> Dict[str, Any]:
        """
        获取统计摘要。
        
        Returns:
            统计摘要字典
        """
        summary = {
            "total_records": len(self._records),
            "total_duration": self.get_total_duration(),
            "categories": {}
        }
        
        for category, records in self._by_category.items():
            durations = [r.duration or 0 for r in records]
            summary["categories"][category] = {
                "count": len(records),
                "total": sum(durations),
                "average": sum(durations) / len(durations) if durations else 0,
                "min": min(durations) if durations else 0,
                "max": max(durations) if durations else 0
            }
        
        return summary
    
    def clear(self) -> None:
        """清空所有记录。"""
        self._records.clear()
        self._active.clear()
        self._by_category.clear()


class TimingContext:
    """
    时间度量上下文管理器。
    
    使用方式：
    ```python
    with TimingContext("my_operation", stats) as timing:
        # 执行操作
        pass
    print(f"耗时: {timing.duration:.2f}s")
    ```
    """
    
    def __init__(
        self,
        name: str,
        stats: Optional[TimingStats] = None,
        category: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
        log_on_exit: bool = False
    ):
        self.name = name
        self.stats = stats
        self.category = category
        self.metadata = metadata
        self.log_on_exit = log_on_exit
        self._record: Optional[TimingRecord] = None
    
    def __enter__(self) -> "TimingContext":
        if self.stats:
            self._record = self.stats.start(
                self.name, self.category, self.metadata
            )
        else:
            self._record = TimingRecord(
                name=self.name,
                start_time=time.perf_counter(),
                category=self.category,
                metadata=self.metadata or {}
            )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._record:
            duration = self._record.complete()
            
            if self.stats and self.name in self.stats._active:
                self.stats._records.append(self._record)
                self.stats._by_category[self.category].append(self._record)
                del self.stats._active[self.name]
            
            if self.log_on_exit:
                logger.info(f"[{self.category}] {self.name}: {duration:.4f}s")
    
    @property
    def duration(self) -> Optional[float]:
        """获取耗时。"""
        return self._record.duration if self._record else None


@contextmanager
def measure_time(
    name: str,
    stats: Optional[TimingStats] = None,
    category: str = "default"
):
    """
    时间测量上下文管理器。
    
    使用方式：
    ```python
    with measure_time("operation") as t:
        # 执行操作
        pass
    print(f"耗时: {t.duration}s")
    ```
    """
    context = TimingContext(name, stats, category)
    yield context.__enter__()
    context.__exit__(None, None, None)


def timed(
    name: Optional[str] = None,
    category: str = "function",
    stats: Optional[TimingStats] = None,
    log_result: bool = False
) -> Callable:
    """
    函数计时装饰器。
    
    使用方式：
    ```python
    @timed("my_function", category="api")
    def my_function():
        ...
    ```
    
    Args:
        name: 计时名称（默认使用函数名）
        category: 类别
        stats: 统计收集器
        log_result: 是否记录结果
    
    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        timing_name = name or func.__name__
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.perf_counter() - start_time
                
                if stats:
                    record = TimingRecord(
                        name=timing_name,
                        start_time=start_time,
                        end_time=start_time + duration,
                        duration=duration,
                        category=category
                    )
                    stats._records.append(record)
                    stats._by_category[category].append(record)
                
                if log_result:
                    logger.debug(f"[{category}] {timing_name}: {duration:.4f}s")
        
        return wrapper
    return decorator


class PerformanceMonitor:
    """
    性能监控器，提供全局性能监控功能。
    """
    
    _instance: Optional["PerformanceMonitor"] = None
    
    def __init__(self):
        self._stats = TimingStats()
        self._enabled = True
    
    @classmethod
    def get_instance(cls) -> "PerformanceMonitor":
        """获取单例实例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @property
    def stats(self) -> TimingStats:
        """获取统计收集器。"""
        return self._stats
    
    @property
    def enabled(self) -> bool:
        """是否启用。"""
        return self._enabled
    
    def enable(self) -> None:
        """启用监控。"""
        self._enabled = True
    
    def disable(self) -> None:
        """禁用监控。"""
        self._enabled = False
    
    def start(self, name: str, category: str = "default") -> Optional[TimingRecord]:
        """开始计时。"""
        if not self._enabled:
            return None
        return self._stats.start(name, category)
    
    def stop(self, name: str) -> Optional[float]:
        """停止计时。"""
        if not self._enabled:
            return None
        return self._stats.stop(name)
    
    def get_summary(self) -> Dict[str, Any]:
        """获取统计摘要。"""
        return self._stats.get_summary()
    
    def clear(self) -> None:
        """清空统计。"""
        self._stats.clear()
    
    @contextmanager
    def track(self, name: str, category: str = "default"):
        """跟踪代码块执行时间。"""
        if self._enabled:
            self.start(name, category)
        try:
            yield
        finally:
            if self._enabled:
                self.stop(name)


def get_monitor() -> PerformanceMonitor:
    """获取性能监控器实例。"""
    return PerformanceMonitor.get_instance()

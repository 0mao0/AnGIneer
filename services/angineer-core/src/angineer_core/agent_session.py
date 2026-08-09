"""有状态 agent 会话（P2.3）。

死锁红线：监听器 / emit / before / after 等回调内**禁止**调用 `wait_for_idle`——
结算在等监听器返回，监听器在等结算，会互相等待。
"""
import logging
import threading
import uuid
from collections import deque
from typing import Callable, Deque, List, Optional

from angineer_core.agent_events import AgentEvent
from angineer_core.agent_loop import AgentLoopConfig, run_agent_loop
from angineer_core.agent_messages import AgentMessage

logger = logging.getLogger(__name__)


class AgentSession:
    """跨 run 保留 history；支持 steer / follow_up / cancel / wait_for_idle。"""

    def __init__(self, config_factory: Callable[[], AgentLoopConfig]):
        self.config_factory = config_factory
        self.history: List[AgentMessage] = []
        self._lock = threading.RLock()
        self._idle_cond = threading.Condition(self._lock)
        self._running = False
        self._active_run_id: Optional[str] = None
        self._cancel_event = threading.Event()
        self._steer_queue: Deque[AgentMessage] = deque()
        self._follow_up_queue: Deque[AgentMessage] = deque()

    @property
    def active_run_id(self) -> Optional[str]:
        with self._lock:
            return self._active_run_id

    def run(
        self,
        user_text: str,
        emit: Optional[Callable[[AgentEvent], None]] = None,
    ) -> List[AgentMessage]:
        """执行一次 run；进行中再次调用直接抛错（单飞）。"""
        with self._lock:
            if self._running:
                raise RuntimeError("Agent run already in progress")
            self._running = True
            self._active_run_id = uuid.uuid4().hex[:12]
            self._cancel_event.clear()
            run_id = self._active_run_id

        # follow_up 队列在下一 run 开头注入（先于本次用户消息）
        with self._lock:
            while self._follow_up_queue:
                self.history.append(self._follow_up_queue.popleft())
        self.history.append(AgentMessage(role="user", content=user_text))
        start_idx = len(self.history)

        try:
            config = self.config_factory()
            run_agent_loop(
                self.history,
                config,
                emit=emit,
                cancel=self._cancel_event,
                run_id=run_id,
                pending_messages_provider=self._drain_steer,
            )
            return self.history[start_idx:]
        finally:
            with self._lock:
                self._running = False
                self._active_run_id = None
                self._idle_cond.notify_all()

    def steer(self, text: str) -> None:
        """中途插队：run 进行中进入 steering 队列，下一 turn 边界注入。"""
        with self._lock:
            if self._running:
                self._steer_queue.append(AgentMessage(role="user", content=text))
            else:
                self._follow_up_queue.append(AgentMessage(role="user", content=text))

    def follow_up(self, text: str) -> None:
        """结束后续命：进入 followUp 队列，下一 run 开头注入。"""
        with self._lock:
            self._follow_up_queue.append(AgentMessage(role="user", content=text))

    def cancel(self) -> None:
        self._cancel_event.set()

    def wait_for_idle(self, timeout: Optional[float] = None) -> bool:
        """等待 run 结束且所有 emit 完成（emit 与 run 同线程）。"""
        with self._idle_cond:
            while self._running:
                if not self._idle_cond.wait(timeout):
                    return False
            return True

    def _drain_steer(self) -> List[AgentMessage]:
        with self._lock:
            items = list(self._steer_queue)
            self._steer_queue.clear()
        return items

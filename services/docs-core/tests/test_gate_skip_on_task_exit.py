"""任务在闸门前退出时的序号让位契约：三个串行闸门都必须 skip。

回归背景：ParseOrchestrator._run_parse_task 的 finally 曾只跳过 MinerU / PoPo 闸门的序号，
漏了图描述闸门。在 raw_parse 就失败的任务（如 MinerU 504）永远不会到达图描述闸门，
它的序号会永久占据该闸门的 _next_seq，此后所有文档都卡在「等待图描述 VLM 资源」，
直到 docs-api 重启。
"""

import threading

import docs_core.parse_pipeline as pp
from docs_core.parse_pipeline import _FifoGpuGate


class _FakeMetaStore:
    def clear_parse_stages(self, doc_id: str) -> None:
        pass

    def clear_parse_stage_steps(self, doc_id: str, stage: str | None = None) -> None:
        pass

    def upsert_parse_stage(self, doc_id: str, stage: str, **kwargs) -> None:
        pass

    def list_parse_stages(self, doc_id: str) -> list:
        return []

    def insert_parse_stage_step(self, doc_id: str, stage: str, step: str, status: str, detail: str) -> None:
        pass


class _FakeNode:
    file_path = "demo.pdf"


class _FakeKS:
    def __init__(self) -> None:
        self.meta_store = _FakeMetaStore()

    def get_node(self, doc_id: str):
        return _FakeNode()

    def update_parse_task(self, task_id: str, **kwargs) -> None:
        pass

    def update_node(self, doc_id: str, **kwargs) -> None:
        pass


def _acquire_within(gate: _FifoGpuGate, seq: int, timeout: float = 1.0) -> bool:
    """拿到令牌返回 True；超时（说明被死序号挡在队首）返回 False。"""
    done = threading.Event()

    def worker() -> None:
        gate.acquire(seq)
        done.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    acquired = done.wait(timeout)
    if acquired:
        gate.release()
    return acquired


def test_task_exit_before_gate_skips_all_three_gate_sequences(monkeypatch) -> None:
    gates = {
        "_MINERU_GPU_GATE": _FifoGpuGate(1),
        "_POPO_GATE": _FifoGpuGate(1),
        "_FIGURE_DESCRIBE_GATE": _FifoGpuGate(1),
    }
    for name, gate in gates.items():
        monkeypatch.setattr(pp, name, gate)
    monkeypatch.setattr(pp, "get_docs_service", lambda: _FakeKS())

    def _boom(*args, **kwargs):
        raise RuntimeError("模拟阶段早期失败")

    monkeypatch.setattr(pp, "run_pipeline", _boom)

    # 序号 1 的任务在到达任何闸门前就失败退出
    pp.ParseOrchestrator()._run_parse_task(
        task_id="t1",
        library_id="lib",
        doc_id="doc",
        file_path="demo.pdf",
        parse_options={"stages": "all"},
        arrival_seq=1,
    )

    # 序号 2 的后续任务必须在每个闸门上立即放行，而不是永久排队
    for name, gate in gates.items():
        assert _acquire_within(gate, 2), f"{name} 未让出失败任务的序号，后续任务会永久排队"

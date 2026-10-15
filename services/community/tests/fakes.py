"""假上游：替代 evals-core / sop-api，测试不碰真实库与网络。"""
from typing import Any, Dict, List, Optional, Tuple


class FakeEvalSource:
    def __init__(self, datasets: Optional[List[Dict[str, Any]]] = None):
        self.datasets = {d["dataset_id"]: d for d in (datasets or [])}
        self.question_calls: List[Dict[str, Any]] = []

    def list_dataset_briefs(self) -> List[Dict[str, Any]]:
        return [
            {
                "dataset_id": d["dataset_id"], "title": d.get("title", ""),
                "category": d.get("category", ""), "description": d.get("description", ""),
                "question_count": d.get("question_count", 0),
            }
            for d in self.datasets.values()
        ]

    def dataset_card(self, dataset_id: str) -> Optional[Dict[str, Any]]:
        d = self.datasets.get(dataset_id)
        if d is None:
            return None
        return {
            "dataset_id": dataset_id, "title": d.get("title", ""),
            "category": d.get("category", ""), "description": d.get("description", ""),
            "question_count": d.get("question_count", 0), "version": "v1",
            "meta": d.get("meta", {}),
        }

    def list_questions(self, dataset_id, offset=0, limit=50, show_gold=False):
        # 记录调用参数：gold 开关必须能被断言（A4）
        self.question_calls.append({"dataset_id": dataset_id, "show_gold": show_gold})
        d = self.datasets.get(dataset_id)
        rows = [dict(q) for q in ((d.get("questions") or []) if d else [])]
        return rows[offset:offset + limit], len(rows)


class FakeSopSource:
    """SopSource 的替身：**与真实源同口径**——显式 draft 是草稿，缺 status 键按 published 放行
    （真实 `/api/sops/full` 条目不带 status，10-15 实踩）。"""

    def __init__(self, sops: Optional[List[Dict[str, Any]]] = None,
                 folders: Optional[List[Dict[str, Any]]] = None):
        # 假源可以含草稿——service/SopSource 的 published 复核应把它挡住
        self.sops = {s["id"]: s for s in (sops or [])}
        # 公开 SOP 页分类=经验库文件夹实时镜像（业主 2026-10-15 定），假源用 folders 喂目录
        self.folders = folders or []

    def list_folders(self) -> List[Dict[str, Any]]:
        return list(self.folders)

    def list_briefs(self) -> List[Dict[str, Any]]:
        return [
            {
                "sop_id": s["id"],
                "title": s.get("name_zh") or s.get("name_en") or s["id"],
                "description": s.get("description", ""),
                "confidence": s.get("confidence"),
                "step_count": len(s.get("steps") or []),
            }
            for s in self.sops.values() if s.get("status", "published") == "published"
        ]

    def get(self, sop_id: str) -> Optional[Dict[str, Any]]:
        s = self.sops.get(sop_id)
        return s if s and s.get("status", "published") == "published" else None

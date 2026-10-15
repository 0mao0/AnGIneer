#!/usr/bin/env python3
"""公开绑定运维 CLI：查/绑/解绑（自动绑定只跑首次之后的唯一公开通道，设计 §9.1/B2）。

用法：
    python scripts/community_bind.py list [--scope eval|sop] [--unbound]
    python scripts/community_bind.py bind <scope> <kind> <ref_id> <node_id>
    python scripts/community_bind.py unbind <scope> <kind> <ref_id>

kind：eval 用 dataset，sop 用 sop。`list --unbound` 列「上游存在但未公开」的条目，
供人工挑标题补绑——自动绑定的未命中清单从这里追。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "services", "community", "src"))

from community import models  # noqa: E402
from community.service import CommunityService  # noqa: E402


def _service() -> CommunityService:
    return CommunityService()


def cmd_list(args) -> int:
    svc = _service()
    scopes = [args.scope] if args.scope else list(models.SCOPES)
    for scope in scopes:
        bound = {b["ref_id"]: b for b in svc.store.list_bindings(scope)}
        if scope == models.SCOPE_EVAL:
            refs = [(b["dataset_id"], b["title"]) for b in svc.eval_src.list_dataset_briefs()]
            kind = models.BIND_KIND_DATASET
        else:
            refs = [(b["sop_id"], b["title"]) for b in svc.sop_src.list_briefs()]
            kind = models.BIND_KIND_SOP
        print(f"[scope={scope}] 已公开 {len(bound)} / 上游共 {len(refs)}")
        for ref_id, title in refs:
            is_bound = ref_id in bound
            if args.unbound and is_bound:
                continue
            mark = "公开" if is_bound else "未公开"
            node = bound.get(ref_id, {}).get("node_id", "")
            print(f"  [{mark}] {ref_id}  {title}  → {node}")
    return 0


def cmd_bind(args) -> int:
    svc = _service()
    if args.scope not in models.SCOPES:
        print(f"scope 须为 {'|'.join(models.SCOPES)}", file=sys.stderr)
        return 2
    if svc.store.get_node(args.node_id) is None:
        print(f"分类节点不存在: {args.node_id}（先跑启动种子或确认 slug）", file=sys.stderr)
        return 2
    svc.store.bind(scope_id=args.scope, kind=args.kind, ref_id=args.ref_id, node_id=args.node_id)
    print(f"已公开：{args.scope}/{args.kind}/{args.ref_id} → {args.node_id}")
    return 0


def cmd_unbind(args) -> int:
    svc = _service()
    removed = svc.store.unbind(scope_id=args.scope, kind=args.kind, ref_id=args.ref_id)
    print("已取消公开" if removed else "该条目本就未公开")
    return 0 if removed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列绑定/未公开条目")
    p_list.add_argument("--scope", choices=models.SCOPES)
    p_list.add_argument("--unbound", action="store_true", help="只列未公开的")
    p_list.set_defaults(func=cmd_list)

    p_bind = sub.add_parser("bind", help="把一条上游内容挂到分类节点并公开")
    p_bind.add_argument("scope", choices=models.SCOPES)
    p_bind.add_argument("kind")
    p_bind.add_argument("ref_id")
    p_bind.add_argument("node_id")
    p_bind.set_defaults(func=cmd_bind)

    p_unbind = sub.add_parser("unbind", help="取消公开")
    p_unbind.add_argument("scope", choices=models.SCOPES)
    p_unbind.add_argument("kind")
    p_unbind.add_argument("ref_id")
    p_unbind.set_defaults(func=cmd_unbind)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

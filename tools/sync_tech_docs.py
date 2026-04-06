"""同步 docs 根目录中技术文档的自动命令块。"""
import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class SyncBlock:
    doc_path: Path
    marker: str
    commands: List[str]


# 返回仓库根目录。
def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


# 读取 package.json 脚本定义。
def load_package_scripts(repo_root: Path) -> dict:
    package_json_path = repo_root / "package.json"
    payload = json.loads(package_json_path.read_text(encoding="utf-8"))
    scripts = payload.get("scripts")
    if not isinstance(scripts, dict):
        raise ValueError("package.json 中缺少 scripts 配置")
    return scripts


# 构建需要同步的文档块列表。
def build_sync_blocks(repo_root: Path, scripts: dict) -> List[SyncBlock]:
    apps_commands = [
        "pnpm install",
        "pnpm dev:frontend",
        "pnpm dev:admin",
        "pnpm build:frontend",
        "pnpm build:admin",
        "pnpm lint",
    ]
    services_commands = [
        "pnpm install",
        "pnpm dev:backend",
        "pnpm harness",
        "pnpm harness:workflow",
        "pnpm harness:tooling",
    ]
    for command in apps_commands + services_commands:
        script_name = command.replace("pnpm ", "", 1)
        if script_name == "install":
            continue
        if script_name not in scripts:
            raise ValueError(f"package.json 缺少脚本: {script_name}")
    return [
        SyncBlock(
            doc_path=repo_root / "docs" / "apps-techniques.md",
            marker="APPS_TECH_COMMANDS",
            commands=apps_commands,
        ),
        SyncBlock(
            doc_path=repo_root / "docs" / "services-techniques.md",
            marker="SERVICES_TECH_COMMANDS",
            commands=services_commands,
        ),
    ]


# 生成标记块应有的 Markdown 内容。
def render_block(block: SyncBlock) -> str:
    body = "\n".join(block.commands)
    return (
        f"<!-- AUTO_SYNC:{block.marker}:START -->\n"
        f"```bash\n"
        f"{body}\n"
        f"```\n"
        f"<!-- AUTO_SYNC:{block.marker}:END -->"
    )


# 在文档中替换对应的自动同步块。
def sync_block(block: SyncBlock, check_only: bool) -> bool:
    text = block.doc_path.read_text(encoding="utf-8")
    start_marker = f"<!-- AUTO_SYNC:{block.marker}:START -->"
    end_marker = f"<!-- AUTO_SYNC:{block.marker}:END -->"
    start_index = text.find(start_marker)
    end_index = text.find(end_marker)
    if start_index < 0 or end_index < 0 or end_index < start_index:
        raise ValueError(f"{block.doc_path} 缺少合法的自动同步标记: {block.marker}")
    end_index += len(end_marker)
    expected = render_block(block)
    current = text[start_index:end_index]
    if current == expected:
        return False
    if check_only:
        raise ValueError(f"{block.doc_path} 的自动同步区块已过期: {block.marker}")
    updated = text[:start_index] + expected + text[end_index:]
    block.doc_path.write_text(updated, encoding="utf-8", newline="\n")
    return True


# 执行全部文档块的同步或校验。
def run(check_only: bool) -> int:
    repo_root = get_repo_root()
    scripts = load_package_scripts(repo_root)
    blocks = build_sync_blocks(repo_root, scripts)
    changed_files: List[str] = []
    for block in blocks:
        changed = sync_block(block, check_only=check_only)
        if changed:
            changed_files.append(str(block.doc_path.relative_to(repo_root)))
    if check_only:
        print("技术文档命令块校验通过")
    elif changed_files:
        print("已同步技术文档命令块:")
        for item in changed_files:
            print(item)
    else:
        print("技术文档命令块已是最新")
    return 0


# 解析命令行参数。
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同步 docs 根目录下技术文档中的自动命令块")
    parser.add_argument("--check", action="store_true", help="仅检查，不写回文件")
    return parser.parse_args()


# 程序入口。
def main() -> int:
    args = parse_args()
    try:
        return run(check_only=args.check)
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""校验架构索引与权威文档的一致性。"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional


SUPPORTED_TEXT_EXTENSIONS = {
    ".md",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".vue",
    ".json",
    ".yaml",
    ".yml",
}


@dataclass
class ModuleSpec:
    id: str
    path: str = ""
    role: str = ""
    depends_on: List[str] = field(default_factory=list)
    key_symbols: List[str] = field(default_factory=list)
    exposes: List[str] = field(default_factory=list)


@dataclass
class FlowSpec:
    id: str
    purpose: str = ""
    steps: List[str] = field(default_factory=list)
    anchors: List[str] = field(default_factory=list)


# 返回仓库根目录。
def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


# 读取 UTF-8 文本文件内容。
def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# 读取 UTF-8 文本文件的所有行。
def read_lines(path: Path) -> List[str]:
    return read_text(path).splitlines()


# 查找指定顶层段落的行范围。
def find_top_level_section(lines: List[str], section_name: str) -> tuple[int, int]:
    start = -1
    for index, line in enumerate(lines):
        if line.strip() == f"{section_name}:" and not line.startswith(" "):
            start = index + 1
            break
    if start < 0:
        raise ValueError(f"architecture-map.yaml 缺少顶层段落: {section_name}")
    end = len(lines)
    for index in range(start, len(lines)):
        line = lines[index]
        if line and not line.startswith(" ") and line.endswith(":"):
            end = index
            break
    return start, end


# 提取顶层列表段落。
def parse_top_level_list(lines: List[str], section_name: str) -> List[str]:
    start, end = find_top_level_section(lines, section_name)
    values: List[str] = []
    for line in lines[start:end]:
        stripped = line.strip()
        if stripped.startswith("- "):
            values.append(stripped[2:].strip())
    return values


# 提取 `default_ports` 段落。
def parse_default_ports(lines: List[str]) -> Dict[str, str]:
    ports: Dict[str, str] = {}
    in_default_ports = False
    for line in lines:
        if line.strip() == "default_ports:":
            in_default_ports = True
            continue
        if not in_default_ports:
            continue
        if line and not line.startswith("    "):
            break
        match = re.match(r"^\s{4}([A-Za-z0-9_]+):\s*(.+)\s*$", line)
        if match:
            ports[match.group(1)] = match.group(2)
    return ports


# 提取模块定义。
def parse_modules(lines: List[str]) -> List[ModuleSpec]:
    start, end = find_top_level_section(lines, "modules")
    modules: List[ModuleSpec] = []
    current: Optional[ModuleSpec] = None
    current_list_key: Optional[str] = None

    for raw_line in lines[start:end]:
        item_match = re.match(r"^\s{2}- id:\s*(.+)\s*$", raw_line)
        if item_match:
            current = ModuleSpec(id=item_match.group(1).strip())
            modules.append(current)
            current_list_key = None
            continue
        if current is None:
            continue
        key_match = re.match(r"^\s{4}([A-Za-z0-9_]+):\s*(.*)\s*$", raw_line)
        if key_match:
            key = key_match.group(1)
            value = key_match.group(2).strip()
            if key in {"depends_on", "key_symbols", "exposes"}:
                current_list_key = key
                setattr(current, key, [])
            else:
                current_list_key = None
                setattr(current, key, value)
            continue
        list_match = re.match(r"^\s{6}-\s*(.+)\s*$", raw_line)
        if list_match and current_list_key:
            getattr(current, current_list_key).append(list_match.group(1).strip())
    return modules


# 提取流程定义。
def parse_flows(lines: List[str]) -> List[FlowSpec]:
    start, end = find_top_level_section(lines, "flows")
    flows: List[FlowSpec] = []
    current: Optional[FlowSpec] = None
    current_list_key: Optional[str] = None

    for raw_line in lines[start:end]:
        item_match = re.match(r"^\s{2}- id:\s*(.+)\s*$", raw_line)
        if item_match:
            current = FlowSpec(id=item_match.group(1).strip())
            flows.append(current)
            current_list_key = None
            continue
        if current is None:
            continue
        key_match = re.match(r"^\s{4}([A-Za-z0-9_]+):\s*(.*)\s*$", raw_line)
        if key_match:
            key = key_match.group(1)
            value = key_match.group(2).strip()
            if key in {"steps", "anchors"}:
                current_list_key = key
                setattr(current, key, [])
            else:
                current_list_key = None
                setattr(current, key, value)
            continue
        list_match = re.match(r"^\s{6}-\s*(.+)\s*$", raw_line)
        if list_match and current_list_key:
            getattr(current, current_list_key).append(list_match.group(1).strip())
    return flows


# 遍历目录中的文本文件。
def iter_text_files(directory: Path) -> Iterable[Path]:
    if not directory.exists():
        return []
    return (
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_TEXT_EXTENSIONS
    )


# 判断某个符号是否存在于模块路径内。
def symbol_exists(repo_root: Path, module_path: str, symbol: str) -> bool:
    base_dir = repo_root / module_path
    if not base_dir.exists():
        return False
    if any(token in symbol for token in ("/", "\\")) or symbol.endswith(
        (".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".md")
    ):
        return any(path.name == Path(symbol).name for path in base_dir.rglob("*") if path.is_file())
    for path in iter_text_files(base_dir):
        try:
            if symbol in read_text(path):
                return True
        except UnicodeDecodeError:
            continue
    return False


# 断言路径存在。
def require_path(repo_root: Path, relative_path: str, errors: List[str], label: str) -> None:
    if not (repo_root / relative_path).exists():
        errors.append(f"{label} 不存在: {relative_path}")


# 校验 README 是否包含关键文档入口与全局锚点。
def validate_readme_links(repo_root: Path, required_tokens: List[str], errors: List[str]) -> None:
    readme_text = read_text(repo_root / "README.md")
    required_links = [
        "docs/architecture-map.yaml",
        "docs/apps-techniques.md",
        "docs/services-techniques.md",
    ]
    for link in required_links:
        if link not in readme_text:
            errors.append(f"README.md 缺少文档入口: {link}")
    if "### 全局权威架构图（简版）" not in readme_text:
        errors.append("README.md 缺少全局权威架构图标题")
    if "### 全局不变量" not in readme_text:
        errors.append("README.md 缺少全局不变量标题")
    if "### 全局代码锚点" not in readme_text:
        errors.append("README.md 缺少全局代码锚点标题")
    for token in required_tokens:
        if token not in readme_text:
            errors.append(f"README.md 缺少全局锚点: {token}")


# 校验权威文档中是否存在关键标题。
def validate_authoritative_doc_headers(repo_root: Path, errors: List[str]) -> None:
    apps_doc = read_text(repo_root / "docs" / "apps-techniques.md")
    services_doc = read_text(repo_root / "docs" / "services-techniques.md")
    if "## 前端权威架构图（简版）" not in apps_doc:
        errors.append("docs/apps-techniques.md 缺少前端权威架构图标题")
    if "## 后端权威架构图（简版）" not in services_doc:
        errors.append("docs/services-techniques.md 缺少后端权威架构图标题")


# 校验端口约束是否仍满足仓库规则。
def validate_ports(ports: Dict[str, str], errors: List[str]) -> None:
    expected_ports = {
        "web_console": "3005",
        "admin_console": "3002",
        "api_server": "8789",
    }
    for key, expected in expected_ports.items():
        actual = ports.get(key)
        if actual != expected:
            errors.append(f"default_ports.{key} 应为 {expected}，实际为 {actual!r}")


# 校验模块、流程与锚点是否自洽。
def validate_architecture_map(repo_root: Path) -> List[str]:
    errors: List[str] = []
    map_path = repo_root / "docs" / "architecture-map.yaml"
    if not map_path.exists():
        return ["缺少 docs/architecture-map.yaml"]

    lines = read_lines(map_path)
    truth_sources = parse_top_level_list(lines, "truth_sources")
    readme_required_tokens = parse_top_level_list(lines, "readme_required_tokens")
    modules = parse_modules(lines)
    flows = parse_flows(lines)
    ports = parse_default_ports(lines)

    validate_ports(ports, errors)

    if not truth_sources:
        errors.append("truth_sources 不能为空")
    for truth_source in truth_sources:
        require_path(repo_root, truth_source, errors, "truth_source")
    if not readme_required_tokens:
        errors.append("readme_required_tokens 不能为空")

    if not modules:
        errors.append("modules 不能为空")
    module_ids = [module.id for module in modules]
    if len(module_ids) != len(set(module_ids)):
        errors.append("modules 中存在重复的 id")

    for module in modules:
        if not module.path:
            errors.append(f"module {module.id} 缺少 path")
            continue
        require_path(repo_root, module.path, errors, f"module {module.id} path")
        for dependency in module.depends_on:
            if dependency not in module_ids:
                errors.append(f"module {module.id} 依赖了未知模块: {dependency}")
        for symbol in module.key_symbols:
            if not symbol_exists(repo_root, module.path, symbol):
                errors.append(f"module {module.id} 未找到关键符号或文件: {symbol}")

    if not flows:
        errors.append("flows 不能为空")
    flow_ids = [flow.id for flow in flows]
    if len(flow_ids) != len(set(flow_ids)):
        errors.append("flows 中存在重复的 id")

    for flow in flows:
        if not flow.steps:
            errors.append(f"flow {flow.id} 缺少 steps")
        if not flow.anchors:
            errors.append(f"flow {flow.id} 缺少 anchors")
        for anchor in flow.anchors:
            require_path(repo_root, anchor, errors, f"flow {flow.id} anchor")

    validate_readme_links(repo_root, readme_required_tokens, errors)
    validate_authoritative_doc_headers(repo_root, errors)
    return errors


# 渲染校验结果文本。
def render_report(errors: List[str]) -> str:
    if not errors:
        return "architecture docs check passed"
    bullet_lines = "\n".join(f"- {item}" for item in errors)
    return f"architecture docs check failed:\n{bullet_lines}"


# 执行架构文档校验。
def run() -> int:
    repo_root = get_repo_root()
    errors = validate_architecture_map(repo_root)
    print(render_report(errors))
    return 0 if not errors else 1


# 解析命令行参数。
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校验架构索引与权威文档的一致性")
    return parser.parse_args()


# 程序入口。
def main() -> int:
    parse_args()
    try:
        return run()
    except Exception as error:
        print(f"architecture docs check failed with exception: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

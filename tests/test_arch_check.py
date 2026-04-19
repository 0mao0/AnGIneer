"""架构文档校验脚本测试。"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.check_architecture_docs import validate_architecture_map


# 写入测试文件。
def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# 构建一个最小可用的测试仓库。
def build_repo_fixture(root: Path) -> None:
    write_file(
        root / "README.md",
        "\n".join(
            [
                "### 全局权威架构图（简版）",
                "### 全局不变量",
                "### 全局代码锚点",
                "apps/web-console",
                "apps/admin-console",
                "apps/api-server",
                "packages/docs-ui",
                "packages/ui-kit",
                "services/angineer-core",
                "services/sop-core",
                "services/docs-core",
                "services/geo-core",
                "services/engtools",
                "data/knowledge_base",
                "docs/architecture-map.yaml",
                "docs/apps-techniques.md",
                "docs/services-techniques.md",
            ]
        ),
    )
    write_file(root / "AGENTS.md", "agents")
    write_file(root / "package.json", "{}")
    write_file(root / "docs" / "apps-techniques.md", "## 前端权威架构图（简版）")
    write_file(root / "docs" / "services-techniques.md", "## 后端权威架构图（简版）")
    write_file(root / "apps" / "web-console" / "src" / "open.ts", "useResourceOpen\nworkbenchStore.openResource\nWorkbench")
    write_file(root / "apps" / "admin-console" / "src" / "view.ts", "KnowledgeManage\nrouter-view")
    write_file(root / "apps" / "api-server" / "main.py", "main.py")
    write_file(root / "apps" / "api-server" / "knowledge_routes.py", "knowledge_routes")
    write_file(
        root / "packages" / "docs-ui" / "src" / "adapter.ts",
        "SmartTree\nAIChat\ncreateResourceNode\ncreateOpenResourcePayload",
    )
    write_file(root / "packages" / "ui-kit" / "src" / "index.ts", "theme")
    write_file(
        root / "services" / "docs-core" / "src" / "docs_core" / "knowledge_service.py",
        "knowledge_service.py",
    )
    write_file(
        root / "services" / "docs-core" / "src" / "docs_core" / "parser" / "mineru_parser.py",
        "mineru_parser.py",
    )
    write_file(
        root / "services" / "docs-core" / "src" / "docs_core" / "structured" / "result_store_json.py",
        "result_store_json.py\nregister_document\nParseOrchestrator.create_parse_task\nmineru_parser.parse_document\nresult_store_json.save_markdown\nresult_store_json.save_parse_artifacts\nbuild_structured_index_for_doc",
    )
    write_file(root / "services" / "angineer-core" / "src" / "index.py", "agent")
    write_file(root / "services" / "engtools" / "src" / "index.py", "tool")
    write_file(root / "services" / "sop-core" / "src" / "index.py", "sop")
    write_file(root / "services" / "geo-core" / "src" / "index.py", "geo")
    write_file(
        root / "docs" / "architecture-map.yaml",
        """version: 1
last_updated: 2026-04-06

truth_sources:
  - README.md
  - docs/apps-techniques.md
  - docs/services-techniques.md
  - AGENTS.md
  - package.json

readme_required_tokens:
  - apps/web-console
  - apps/admin-console
  - apps/api-server
  - packages/docs-ui
  - packages/ui-kit
  - services/angineer-core
  - services/sop-core
  - services/docs-core
  - services/geo-core
  - services/engtools
  - data/knowledge_base

system:
  name: AnGIneer
  repo_style: monorepo
  platforms:
    - web-console
    - admin-console
    - api-server
  default_ports:
    web_console: 3005
    admin_console: 3002
    api_server: 8789

modules:
  - id: web-console
    path: apps/web-console
    role: user_workbench
    depends_on:
      - docs-ui
      - ui-kit
      - api-server
    key_symbols:
      - useResourceOpen
      - workbenchStore.openResource
      - Workbench
  - id: admin-console
    path: apps/admin-console
    role: admin_workspace
    depends_on:
      - docs-ui
      - ui-kit
      - api-server
    key_symbols:
      - KnowledgeManage
      - router-view
  - id: api-server
    path: apps/api-server
    role: gateway
    depends_on:
      - docs-core
      - angineer-core
      - engtools
      - sop-core
      - geo-core
    key_symbols:
      - main.py
      - knowledge_routes.py
  - id: docs-ui
    path: packages/docs-ui
    role: shared_ui
    depends_on: []
    key_symbols:
      - SmartTree
      - AIChat
      - createResourceNode
      - createOpenResourcePayload
  - id: ui-kit
    path: packages/ui-kit
    role: shared_ui_kit
    depends_on: []
  - id: docs-core
    path: services/docs-core
    role: docs_core
    depends_on: []
    key_symbols:
      - knowledge_service.py
      - mineru_parser.py
      - result_store_json.py
  - id: angineer-core
    path: services/angineer-core
    role: agent_orchestration
    depends_on: []
  - id: engtools
    path: services/engtools
    role: engineering_tools
    depends_on: []
  - id: sop-core
    path: services/sop-core
    role: sop_runtime
    depends_on: []
  - id: geo-core
    path: services/geo-core
    role: geo_runtime
    depends_on: []

flows:
  - id: resource-open
    purpose: Open resources through one protocol.
    steps:
      - createResourceNode
      - createOpenResourcePayload
      - useResourceOpen.openResource
    anchors:
      - packages/docs-ui/src/adapter.ts
      - apps/web-console/src/open.ts
  - id: docs-runtime
    purpose: Parse one document into storage and index.
    steps:
      - register_document
      - ParseOrchestrator.create_parse_task
      - mineru_parser.parse_document
      - result_store_json.save_markdown
      - result_store_json.save_parse_artifacts
      - build_structured_index_for_doc
    anchors:
      - apps/api-server/knowledge_routes.py
      - services/docs-core/src/docs_core/parser/mineru_parser.py
      - services/docs-core/src/docs_core/structured/result_store_json.py
      - services/docs-core/src/docs_core/knowledge_service.py

storage:
  document_root: data/knowledge_base/libraries/{library_id}/documents/{doc_id}
  databases:
    - data/knowledge_base/knowledge_meta.sqlite
    - data/knowledge_base/knowledge_index.sqlite
  expected_layout:
    - source/
    - parsed/
    - edited/
    - structured/

invariants:
  - shared resource protocol
  - async docs parsing

change_checklist:
  - update docs with code
""",
    )


class ArchitectureDocsCheckTest(unittest.TestCase):
    """测试架构文档校验脚本。"""

    # 验证最小仓库可以通过架构校验。
    def test_arch_check_passes_on_valid_fixture(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            build_repo_fixture(repo_root)
            self.assertEqual(validate_architecture_map(repo_root), [])

    # 验证未知依赖会被架构校验拦截。
    def test_arch_check_rejects_unknown_module_dependency(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            build_repo_fixture(repo_root)
            architecture_map = repo_root / "docs" / "architecture-map.yaml"
            content = architecture_map.read_text(encoding="utf-8")
            architecture_map.write_text(content.replace("- docs-ui", "- unknown-module", 1), encoding="utf-8")
            errors = validate_architecture_map(repo_root)
            self.assertTrue(any("未知模块" in error for error in errors))

    # 验证 README 缺少全局锚点会被架构校验拦截。
    def test_arch_check_rejects_missing_readme_anchor(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            build_repo_fixture(repo_root)
            readme_path = repo_root / "README.md"
            readme_content = readme_path.read_text(encoding="utf-8")
            readme_path.write_text(readme_content.replace("services/geo-core\n", "", 1), encoding="utf-8")
            errors = validate_architecture_map(repo_root)
            self.assertTrue(any("README.md 缺少全局锚点: services/geo-core" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

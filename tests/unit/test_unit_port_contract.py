"""
单元测试：端口契约与前端配置真相源。
"""
import json
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
PORTS_JSON_FILE = ROOT_DIR / "apps" / "shared" / "ports.json"
PORTS_FILE = ROOT_DIR / "apps" / "shared" / "ports.ts"
ADMIN_TSCONFIG = ROOT_DIR / "apps" / "admin-console" / "tsconfig.json"
WEB_TSCONFIG = ROOT_DIR / "apps" / "web-console" / "tsconfig.json"
ADMIN_NODE_TSCONFIG = ROOT_DIR / "apps" / "admin-console" / "tsconfig.node.json"
WEB_NODE_TSCONFIG = ROOT_DIR / "apps" / "web-console" / "tsconfig.node.json"
ADMIN_VITE_CONFIG = ROOT_DIR / "apps" / "admin-console" / "vite.config.ts"
WEB_VITE_CONFIG = ROOT_DIR / "apps" / "web-console" / "vite.config.ts"
README_FILE = ROOT_DIR / "README.md"
START_SCRIPT = ROOT_DIR / "start.ps1"
API_SERVER_MAIN = ROOT_DIR / "apps" / "api-server" / "main.py"


class TestPortContract(unittest.TestCase):
    """测试端口契约与 Vite 配置唯一真相源。"""

    # 读取文本文件内容。
    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    # 断言文件中包含指定文本。
    def assertContains(self, path: Path, content: str):
        self.assertIn(content, self.read_text(path), f"{path} 缺少内容: {content}")

    # 读取共享端口契约 JSON。
    def read_port_contract(self) -> dict:
        return json.loads(self.read_text(PORTS_JSON_FILE))

    # 校验共享端口契约 JSON 与 TypeScript 端口导出保持一致。
    def test_shared_ports_files_contain_expected_contract(self):
        port_contract = self.read_port_contract()
        self.assertEqual(port_contract["localHost"], "localhost")
        self.assertEqual(port_contract["apiServerPort"], 8033)
        self.assertEqual(port_contract["adminConsolePort"], 3002)
        self.assertEqual(port_contract["webConsolePort"], 3005)
        self.assertContains(PORTS_FILE, "import portContract from './ports.json'")
        self.assertContains(PORTS_FILE, "export const API_SERVER_PORT = portContract.apiServerPort")
        self.assertContains(PORTS_FILE, "export const ADMIN_CONSOLE_PORT = portContract.adminConsolePort")
        self.assertContains(PORTS_FILE, "export const WEB_CONSOLE_PORT = portContract.webConsolePort")
        self.assertContains(PORTS_FILE, "export const API_PROXY_TARGET = createLocalOrigin(API_SERVER_PORT)")

    # 校验前端 Vite 配置引用共享端口常量。
    def test_vite_configs_use_shared_port_contract(self):
        self.assertContains(ADMIN_TSCONFIG, '"../shared/**/*.ts"')
        self.assertContains(ADMIN_TSCONFIG, '"../shared/**/*.json"')
        self.assertContains(ADMIN_NODE_TSCONFIG, '"../shared/**/*.json"')
        self.assertContains(ADMIN_VITE_CONFIG, "import portContract from '../shared/ports.json'")
        self.assertContains(ADMIN_VITE_CONFIG, "const ADMIN_CONSOLE_PORT = portContract.adminConsolePort")
        self.assertContains(ADMIN_VITE_CONFIG, 'const API_PROXY_TARGET = `http://${portContract.localHost}:${portContract.apiServerPort}`')
        self.assertContains(ADMIN_VITE_CONFIG, "port: ADMIN_CONSOLE_PORT")
        self.assertContains(ADMIN_VITE_CONFIG, "target: API_PROXY_TARGET")

        self.assertContains(WEB_TSCONFIG, '"../shared/**/*.ts"')
        self.assertContains(WEB_TSCONFIG, '"../shared/**/*.json"')
        self.assertContains(WEB_NODE_TSCONFIG, '"../shared/**/*.json"')
        self.assertContains(WEB_VITE_CONFIG, "import portContract from '../shared/ports.json'")
        self.assertContains(WEB_VITE_CONFIG, "const WEB_CONSOLE_PORT = portContract.webConsolePort")
        self.assertContains(WEB_VITE_CONFIG, 'const API_PROXY_TARGET = `http://${portContract.localHost}:${portContract.apiServerPort}`')
        self.assertContains(WEB_VITE_CONFIG, "port: WEB_CONSOLE_PORT")
        self.assertContains(WEB_VITE_CONFIG, "target: API_PROXY_TARGET")

    # 校验 README、启动脚本和后端入口保持相同端口契约。
    def test_docs_and_runtime_entrypoints_match_port_contract(self):
        self.assertContains(START_SCRIPT, '$portContractPath = Join-Path $rootDir "apps/shared/ports.json"')
        self.assertContains(START_SCRIPT, '$backendPort = $portContract.apiServerPort')
        self.assertContains(START_SCRIPT, '$adminPort = $portContract.adminConsolePort')
        self.assertContains(START_SCRIPT, '$frontendPort = $portContract.webConsolePort')
        self.assertContains(API_SERVER_MAIN, 'PORT_CONTRACT_PATH = os.path.join(ROOT_DIR, "apps", "shared", "ports.json")')
        self.assertContains(API_SERVER_MAIN, 'API_SERVER_PORT = int(PORT_CONTRACT["apiServerPort"])')
        self.assertContains(API_SERVER_MAIN, 'uvicorn.run(app, host="0.0.0.0", port=API_SERVER_PORT)')
        self.assertContains(README_FILE, "端口3002")
        self.assertContains(README_FILE, "端口3005")
        self.assertContains(README_FILE, "端口8033")

    # 校验冗余 Vite 生成物不会再次留在源码目录。
    def test_no_redundant_vite_config_artifacts_exist(self):
        self.assertFalse((ROOT_DIR / "apps" / "admin-console" / "vite.config.js").exists())
        self.assertFalse((ROOT_DIR / "apps" / "web-console" / "vite.config.js").exists())
        self.assertFalse((ROOT_DIR / "apps" / "web-console" / "vite.config.d.ts").exists())


if __name__ == "__main__":
    unittest.main()

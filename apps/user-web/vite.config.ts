import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { AntDesignVueResolver } from 'unplugin-vue-components/resolvers'
import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { resolve } from 'path'
import portContract from '../shared/ports.json'
import pdfWasmPlugin from '../../packages/docs-ui/vite-pdf-wasm.mjs'

const WEB_CONSOLE_PORT = portContract.webConsolePort
const DOCS_API_PROXY_TARGET = `http://${portContract.localHost}:${portContract.docsApiPort}`
const AICHAT_API_PROXY_TARGET = `http://${portContract.localHost}:${portContract.aichatApiPort}`

function getAppVersion(): string {
  try {
    return execSync('git describe --tags --abbrev=0', { encoding: 'utf-8' }).trim().replace(/^v/, '') || '0.1.0';
  } catch {
    // Docker 等环境无 git，回退读 package.json
    try {
      const pkg = JSON.parse(readFileSync(resolve(__dirname, '../../package.json'), 'utf-8'));
      return pkg.version || '0.1.0';
    } catch {
      return '0.1.0';
    }
  }
}

const APP_VERSION = getAppVersion();

/**
 * 从根 README「当前版本」行提取本版摘要，供顶栏版本号 hover 展示发版内容。
 * 该行格式为「当前版本：X.Y.Z —— 摘要」，版本号允许带/不带 v 前缀（此前只匹配
 * 「vX.Y.Z 」导致 README 用无 v 前缀格式时摘要恒为空，hover 弹层形同虚设）。
 * 无匹配返回空串（顶栏退化为纯版本号）。
 */
function extractReleaseNotes(version: string): string {
  try {
    const readme = readFileSync(resolve(__dirname, '../../README.md'), 'utf8')
    const line = readme.split(/\r?\n/).find(l => l.includes('当前版本：'))
    if (!line) return ''
    const idx = line.indexOf('当前版本：')
    const rest = line.slice(idx + '当前版本：'.length)
    const m = rest.match(/v?(\d+\.\d+\.\d+)/)
    if (!m || m[1] !== version) return ''
    let notes = rest.slice((m.index ?? 0) + m[0].length)
    notes = notes.replace(/^[\s*:：>]*[-—–]+[\s]*/, '')
    notes = notes.split('详见 [CHANGELOG.md]')[0]
    return notes.replace(/。+$/, '').trim()
  } catch {
    return ''
  }
}

const RELEASE_NOTES = extractReleaseNotes(APP_VERSION)

export default defineConfig({
  plugins: [
    vue(),
    // ant-design-vue 按需引入，替代 main.ts 的 app.use(Antd) 全量注册。
    // 全量注册实测让首包 index-*.js 达 1.57MB（对话页用不到的 Tree/Cascader/Calendar… 全在里面）。
    // importStyle:false —— antdv4 是 CSS-in-JS，样式由组件运行时注入，全局只保留 reset.css。
    // dirs:[] —— 不自动注册 src/components，保持各文件显式 import 的既有语义。
    Components({
      resolvers: [AntDesignVueResolver({ importStyle: false })],
      dirs: [],
      dts: false
    }),
    pdfWasmPlugin()
  ],
  define: {
    'import.meta.env.VITE_APP_VERSION': JSON.stringify(APP_VERSION),
    'import.meta.env.VITE_APP_RELEASE_NOTES': JSON.stringify(RELEASE_NOTES)
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@angineer/ui-kit': resolve(__dirname, '../../packages/ui-kit/src'),
      '@angineer/aichat-ui': resolve(__dirname, '../../packages/aichat-ui/src'),
      '@angineer/docs-ui': resolve(__dirname, '../../packages/docs-ui/src'),
      '@angineer/smartree': resolve(__dirname, '../../packages/smartree/src'),
      '@angineer/sop-ui': resolve(__dirname, '../../packages/sop-ui/src'),
      '@angineer/geo-ui': resolve(__dirname, '../../packages/geo-ui/src'),
      '@angineer/evals-ui': resolve(__dirname, '../../packages/evals-ui/src')
    }
  },
  css: {
    preprocessorOptions: {
      less: {
        javascriptEnabled: true,
        additionalData: `@import "${resolve(__dirname, '../../packages/ui-kit/src/styles/variables.less')}";\n`
      }
    }
  },
  server: {
    host: true,
    port: WEB_CONSOLE_PORT,
    proxy: {
      '/api/knowledge': { target: DOCS_API_PROXY_TARGET, changeOrigin: true },
      '/api/graph': { target: DOCS_API_PROXY_TARGET, changeOrigin: true },
      '/api/v1': { target: DOCS_API_PROXY_TARGET, changeOrigin: true },
      '/api/api-keys': { target: DOCS_API_PROXY_TARGET, changeOrigin: true },
      '/api/chat': { target: AICHAT_API_PROXY_TARGET, changeOrigin: true },
      '/api/sops': { target: AICHAT_API_PROXY_TARGET, changeOrigin: true },
      '/api/evals': { target: AICHAT_API_PROXY_TARGET, changeOrigin: true },
      '/api/dream-cycle': { target: AICHAT_API_PROXY_TARGET, changeOrigin: true },
      '/api/llm_configs': { target: AICHAT_API_PROXY_TARGET, changeOrigin: true },
      '/api': { target: DOCS_API_PROXY_TARGET, changeOrigin: true }
    }
  }
})

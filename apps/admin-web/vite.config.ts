import { execSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { AntDesignVueResolver } from 'unplugin-vue-components/resolvers'
import { resolve } from 'path'
import portContract from '../shared/ports.json'
import pdfWasmPlugin from '../../packages/docs-ui/vite-pdf-wasm.mjs'

const ADMIN_CONSOLE_PORT = portContract.adminConsolePort
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
 * 从根 README「当前版本」行提取本版摘要，供顶栏版本号 hover 展示发版内容（与 user-web 一致）。
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
  base: '/admin/',
  plugins: [
    vue(),
    // ant-design-vue 按需引入，替代 main.ts 的 app.use(Antd) 全量注册（与 user-web 同一套配置）。
    // 全量注册实测让入口 chunk 达 1.6MB（后台各页用不到的组件全在里头）。
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
  /**
   * 重依赖预置进预打包：这些库只被懒加载路由用到（echarts 在评测集、pdf.js/xlsx/docx-preview/katex
   * 在知识库预览栈、vue-flow 在经验库流程图）。不预置则 Vite 在「首次切到该模块」时才发现在线依赖，
   * 触发重新预打包并强制整页 reload —— 表现为切页瞬间白屏数秒且应用状态丢失。
   * 列在这里把这份代价挪到 dev server 启动时一次付清。
   */
  optimizeDeps: {
    include: ['echarts', 'pdfjs-dist', 'xlsx', 'docx-preview', 'katex', '@vue-flow/core']
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@angineer/ui-kit': resolve(__dirname, '../../packages/ui-kit/src'),
      '@angineer/aichat-ui': resolve(__dirname, '../../packages/aichat-ui/src'),
      '@angineer/docs-ui': resolve(__dirname, '../../packages/docs-ui/src'),
      '@angineer/smartree': resolve(__dirname, '../../packages/smartree/src'),
      '@angineer/evals-ui': resolve(__dirname, '../../packages/evals-ui/src'),
      '@angineer/sop-ui': resolve(__dirname, '../../packages/sop-ui/src')
    }
  },
  css: {
    preprocessorOptions: {
      less: {
        javascriptEnabled: true,
        additionalData: `@import "${resolve(__dirname, '../../packages/evals-ui/src/styles/variables.less')}";\n`
      }
    }
  },
  server: {
    host: true,
    port: ADMIN_CONSOLE_PORT,
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

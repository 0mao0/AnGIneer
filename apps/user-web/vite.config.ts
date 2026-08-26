import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { readFileSync } from 'node:fs'
import { resolve } from 'path'
import portContract from '../shared/ports.json'
import pdfWasmPlugin from '../../packages/docs-ui/vite-pdf-wasm.mjs'

const WEB_CONSOLE_PORT = portContract.webConsolePort
const DOCS_API_PROXY_TARGET = `http://${portContract.localHost}:${portContract.docsApiPort}`
const AICHAT_API_PROXY_TARGET = `http://${portContract.localHost}:${portContract.aichatApiPort}`
const rootPackage = JSON.parse(readFileSync(resolve(__dirname, '../../package.json'), 'utf-8')) as { version?: string }
const APP_VERSION = rootPackage.version || '0.1.0'

export default defineConfig({
  plugins: [vue(), pdfWasmPlugin()],
  define: {
    'import.meta.env.VITE_APP_VERSION': JSON.stringify(APP_VERSION)
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

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { readFileSync } from 'node:fs'
import { resolve } from 'path'
import portContract from '../shared/ports.json'

const WEB_CONSOLE_PORT = portContract.webConsolePort
const API_PROXY_TARGET = `http://${portContract.localHost}:${portContract.apiServerPort}`
const rootPackage = JSON.parse(readFileSync(resolve(__dirname, '../../package.json'), 'utf-8')) as { version?: string }
const APP_VERSION = rootPackage.version || '0.1.0'

export default defineConfig({
  plugins: [vue()],
  define: {
    'import.meta.env.VITE_APP_VERSION': JSON.stringify(APP_VERSION)
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@angineer/ui-kit': resolve(__dirname, '../../packages/ui-kit/src'),
      '@angineer/docs-ui': resolve(__dirname, '../../packages/docs-ui/src'),
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
    port: WEB_CONSOLE_PORT,
    proxy: {
      '/api': {
        target: API_PROXY_TARGET,
        changeOrigin: true
      }
    }
  }
})

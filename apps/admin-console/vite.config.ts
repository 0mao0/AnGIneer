import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import portContract from '../shared/ports.json'

const ADMIN_CONSOLE_PORT = portContract.adminConsolePort
const API_PROXY_TARGET = `http://${portContract.localHost}:${portContract.apiServerPort}`

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@angineer/ui-kit': resolve(__dirname, '../../packages/ui-kit/src'),
      '@angineer/docs-ui': resolve(__dirname, '../../packages/docs-ui/src'),
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
    port: ADMIN_CONSOLE_PORT,
    proxy: {
      '/api': {
        target: API_PROXY_TARGET,
        changeOrigin: true
      }
    }
  }
})

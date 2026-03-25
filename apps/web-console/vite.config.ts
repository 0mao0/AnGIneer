import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import portContract from '../shared/ports.json'

const WEB_CONSOLE_PORT = portContract.webConsolePort
const API_PROXY_TARGET = `http://${portContract.localHost}:${portContract.apiServerPort}`

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@angineer/ui-kit': resolve(__dirname, '../../packages/ui-kit/src'),
      '@angineer/docs-ui': resolve(__dirname, '../../packages/docs-ui/src'),
      '@angineer/sop-ui': resolve(__dirname, '../../packages/sop-ui/src'),
      '@angineer/geo-ui': resolve(__dirname, '../../packages/geo-ui/src')
    }
  },
  css: {
    preprocessorOptions: {
      less: {
        javascriptEnabled: true
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

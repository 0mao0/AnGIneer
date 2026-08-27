import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import Antd from 'ant-design-vue'
import App from './App.vue'
import router from './router'
import { useThemeStore } from '@angineer/ui-kit'
import 'ant-design-vue/dist/reset.css'
// monorepo 内别名直达包 src/，exports 子路径（./style）不生效，样式用 src 相对路径导入
import '@angineer/aichat-ui/styles/index.less'
import './styles/index.less'

const app = createApp(App)

const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)

app.use(pinia)
app.use(router)
app.use(Antd)

const themeStore = useThemeStore()
themeStore.initTheme()

app.mount('#app')

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import Antd from 'ant-design-vue'
import App from './App.vue'
import router from './router'
import { useThemeStore } from '@angineer/ui-kit'
import 'ant-design-vue/dist/reset.css'
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

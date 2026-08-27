import { createApp } from 'vue'
import { createPinia } from 'pinia'
import Antd from 'ant-design-vue'
import App from './App.vue'
import router from './router'
import { useThemeStore } from '@angineer/ui-kit'
import 'ant-design-vue/dist/reset.css'
// monorepo 内别名直达包 src/，exports 子路径（./style）不生效，样式用 src 相对路径导入
import '@angineer/aichat-ui/styles/index.less'
import './styles/index.less'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(Antd)

// 初始化主题
const themeStore = useThemeStore()
themeStore.initTheme()

app.mount('#app')

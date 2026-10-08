import { ref } from 'vue'

/**
 * 站点页脚（标语 + 开源项目入口）显隐开关：hero 空态显示，进入对话态隐藏
 * （2026-10-08 用户要求：对话阶段把页脚那条 26px 还给消息区）。
 * App.vue 消费；ChatHome.vue 按 hero 态写入，离开聊天页（文档深链）恢复显示。
 */
export const siteFooterVisible = ref(true)

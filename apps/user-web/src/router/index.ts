import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'ChatHome',
    component: () => import('@/views/ChatHome.vue')
  },
  {
    // 文档深链：admin 端「查看文档」经 apps/shared/ports.ts getWebDocumentUrl 打开
    // /document/:docId?library=<id>。DocumentView 只吃 props（无 useRoute），故由路由
    // 参数喂入；缺路由时 catch-all 会把该链接打回聊天首页（2026-09 线上实踩）。
    path: '/document/:docId',
    name: 'DocumentView',
    component: () => import('@/views/DocumentRouteView.vue')
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/'
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

export default router

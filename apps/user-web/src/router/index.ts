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
    // 公开测试集页（设计 docs/design-public-eval-sop-pages.md）：左分类树 + 题集只读 + 投稿
    path: '/evals',
    name: 'PublicEvalView',
    component: () => import('@/views/PublicEvalView.vue')
  },
  {
    // 公开 SOP 页：只读流程画布 + 元信息（无审核块）+ 意见投稿
    path: '/sops',
    name: 'PublicSopView',
    component: () => import('@/views/PublicSopView.vue')
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

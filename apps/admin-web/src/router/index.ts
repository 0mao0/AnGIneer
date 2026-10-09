import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { KB_SLUG_TO_KEY, KB_DEFAULT_SLUG, EVAL_DEFAULT_SLUG, isEvalViewKey } from './viewKeys'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/knowledge'
  },
  {
    // tab 段即状态（overview|detail|nightly|aichat）。参数名 kbView 与评测的 evalView
    // 分开：两模块都有 nightly 值，同名参数在 keep-alive 让两边同时挂载时会互相串台。
    // 缺段/非法段一律 replace 到默认段，地址栏不留在无段 URL 上。
    // 不写成独立 redirect 记录：可选参数路由的排名压过静态路径，独立 redirect 抢不到匹配
    // （实测 /knowledge 静默停在无段 URL，2026-10-09）。
    path: '/knowledge/:kbView?',
    name: 'knowledge',
    component: () => import('../views/KnowledgeManage.vue'),
    beforeEnter: (to) =>
      KB_SLUG_TO_KEY[String(to.params.kbView ?? '')] ? true : { path: `/knowledge/${KB_DEFAULT_SLUG}`, replace: true }
  },
  {
    path: '/project',
    name: 'project',
    component: () => import('../views/PlaceholderPage.vue')
  },
  {
    path: '/experience',
    name: 'experience',
    component: () => import('../views/ExperienceManage.vue')
  },
  {
    // 日测|夜测|解析回归。缺段时先认旧深链 ?view=nightly（企微历史卡片与
    // eval-nightly.yml），认不出才落默认段；新链接一律用路径段。
    path: '/evals/:evalView?',
    name: 'evals',
    component: () => import('../views/EvalManage.vue'),
    beforeEnter: (to) => {
      const slug = String(to.params.evalView ?? '')
      if (isEvalViewKey(slug)) return true
      const legacy = String(to.query.view ?? '')
      return { path: `/evals/${isEvalViewKey(legacy) ? legacy : EVAL_DEFAULT_SLUG}`, replace: true }
    }
  },
  {
    path: '/api-keys',
    name: 'api-keys',
    component: () => import('../views/ApiKeyManage.vue')
  },
  {
    path: '/users',
    name: 'users',
    component: () => import('../views/UserManage.vue')
  },
  {
    path: '/arch',
    name: 'arch',
    component: () => import('../views/ArchMapView.vue')
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/knowledge'
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

export default router

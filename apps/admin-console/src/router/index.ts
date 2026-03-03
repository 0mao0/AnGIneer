import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/knowledge'
  },
  {
    path: '/knowledge',
    name: 'knowledge',
    component: () => import('../views/KnowledgeManage.vue')
  },
  {
    path: '/project',
    name: 'project',
    component: () => import('../views/PlaceholderPage.vue')
  },
  {
    path: '/experience',
    name: 'experience',
    component: () => import('../views/PlaceholderPage.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router

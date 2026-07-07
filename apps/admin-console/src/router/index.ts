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
    component: () => import('../views/ExperienceManage.vue')
  },
  {
    path: '/evals',
    name: 'evals',
    component: () => import('../views/EvalManage.vue')
  },
  {
    path: '/sop-research',
    name: 'sop-research',
    component: () => import('../views/SopResearchManage.vue')
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

export default router

import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'Home',
    component: () => import('@/views/Home.vue')
  },
  {
    path: '/document/:id',
    name: 'Document',
    component: () => import('@/views/DocumentView.vue')
  },
  {
    path: '/sop/:id',
    name: 'SOP',
    component: () => import('@/views/SOPView.vue')
  },
  {
    path: '/gis',
    name: 'GIS',
    component: () => import('@/views/GISView.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router

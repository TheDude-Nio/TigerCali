import { createRouter, createWebHistory } from 'vue-router'
import { onUnauthorized } from './api'
import { auth, loadMeta, loadSession, setUser } from './store'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('./views/LoginView.vue'), meta: { public: true, bare: true } },
    { path: '/register', component: () => import('./views/RegisterView.vue'), meta: { public: true, bare: true } },
    { path: '/', component: () => import('./views/HomeView.vue') },
    { path: '/tasks/new', component: () => import('./views/TaskCreateView.vue') },
    { path: '/tasks/:id', component: () => import('./views/TaskView.vue') },
    // 标注工作台：mode=mine 标注自己的图片；mode=inspect 管理员查看/修改任意成员的图片
    { path: '/tasks/:id/label', component: () => import('./views/WorkspaceView.vue'), meta: { bare: true } },
    { path: '/tasks/:id/review/:uid', component: () => import('./views/ReviewView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior: (_to, _from, saved) => saved ?? { top: 0 },
})

router.beforeEach(async (to) => {
  await Promise.all([loadSession(), loadMeta().catch(() => null)])
  if (!to.meta.public && !auth.user) {
    return { path: '/login', query: to.fullPath !== '/' ? { redirect: to.fullPath } : {} }
  }
  if (to.meta.public && auth.user) return '/'
})

onUnauthorized(() => {
  setUser(null)
  const cur = router.currentRoute.value
  if (!cur.meta.public) router.replace({ path: '/login', query: { redirect: cur.fullPath } })
})

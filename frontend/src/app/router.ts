import type { Pinia } from "pinia"
import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router"

import AuthCallbackPage from "../pages/AuthCallbackPage.vue"
import AgentsPage from "../pages/AgentsPage.vue"
import ErrorPage from "../pages/ErrorPage.vue"
import ForbiddenPage from "../pages/ForbiddenPage.vue"
import KnowledgePage from "../pages/KnowledgePage.vue"
import LearningPage from "../pages/LearningPage.vue"
import LoginPage from "../pages/LoginPage.vue"
import PublicationsPage from "../pages/PublicationsPage.vue"
import ReviewsPage from "../pages/ReviewsPage.vue"
import VerificationPage from "../pages/VerificationPage.vue"
import WorkspacePage from "../pages/WorkspacePage.vue"
import { useAuthStore } from "../stores/auth"

const routes: RouteRecordRaw[] = [
  { path: "/", redirect: "/workspace" },
  {
    path: "/login",
    name: "login",
    component: LoginPage,
    meta: { shell: false, title: "登录" },
  },
  {
    path: "/auth/callback",
    name: "auth-callback",
    component: AuthCallbackPage,
    meta: { shell: false, title: "登录回调" },
  },
  {
    path: "/workspace",
    name: "workspace",
    component: WorkspacePage,
    meta: { requiresAuth: true, requiredScopes: ["topic1:read"], title: "工作台" },
  },
  { path: "/knowledge", name: "knowledge", component: KnowledgePage, meta: { requiresAuth: true, requiredScopes: ["topic1:read"], title: "知识拓扑" } },
  { path: "/learning", name: "learning", component: LearningPage, meta: { requiresAuth: true, requiredScopes: ["topic2:read"], title: "学习路径" } },
  { path: "/agents", name: "agents", component: AgentsPage, meta: { requiresAuth: true, requiredScopes: ["topic3:read"], title: "智能体协同" } },
  { path: "/verification", name: "verification", component: VerificationPage, meta: { requiresAuth: true, requiredScopes: ["topic4:read"], title: "可信核验" } },
  { path: "/verification/revision", name: "verification-revision", component: VerificationPage, meta: { requiresAuth: true, requiredScopes: ["topic4:read"], title: "修订闭环" } },
  { path: "/reviews", name: "reviews", component: ReviewsPage, meta: { requiresAuth: true, requiredScopes: ["topic4:review:read"], title: "人工审核" } },
  { path: "/publications", name: "publications", component: PublicationsPage, meta: { requiresAuth: true, requiredScopes: ["topic4:release:read"], title: "发布归档" } },
  {
    path: "/forbidden",
    name: "forbidden",
    component: ForbiddenPage,
    meta: { shell: false, title: "无权限" },
  },
  {
    path: "/error",
    name: "error",
    component: ErrorPage,
    meta: { shell: false, title: "系统错误" },
  },
  { path: "/:pathMatch(.*)*", redirect: "/error" },
]

export function createWorkbenchRouter(pinia: Pinia) {
  const router = createRouter({ history: createWebHistory(), routes })
  router.beforeEach(async (to) => {
    const auth = useAuthStore(pinia)
    await auth.restore()
    document.title = to.meta.title ? `${to.meta.title} | CyberControl` : "CyberControl"

    if (to.name === "login" && auth.authenticated) return { name: "workspace" }
    if (!to.meta.requiresAuth) return true
    if (!auth.authenticated) {
      return { name: "login", query: { returnTo: to.fullPath } }
    }
    const requiredScopes = to.meta.requiredScopes ?? []
    if (!auth.hasAllScopes(requiredScopes)) {
      return { name: "forbidden", query: { from: to.fullPath } }
    }
    return true
  })
  return router
}

import type { Pinia } from "pinia"
import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router"

import AuthCallbackPage from "../pages/AuthCallbackPage.vue"
import ErrorPage from "../pages/ErrorPage.vue"
import ForbiddenPage from "../pages/ForbiddenPage.vue"
import LoginPage from "../pages/LoginPage.vue"
import PlaceholderPage from "../pages/PlaceholderPage.vue"
import WorkspacePage from "../pages/WorkspacePage.vue"
import { useAuthStore } from "../stores/auth"

const protectedRoute = (
  path: string,
  name: string,
  title: string,
  status: string,
  requiredScopes: readonly string[],
): RouteRecordRaw => ({
  path,
  name,
  component: PlaceholderPage,
  props: { title, status },
  meta: { requiresAuth: true, requiredScopes, title },
})

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
  protectedRoute("/knowledge", "knowledge", "知识拓扑", "暂无知识资源", ["topic1:read"]),
  protectedRoute("/learning", "learning", "学习路径", "暂无学习路径", ["topic2:read"]),
  protectedRoute("/agents", "agents", "智能体协同", "暂无生成任务", ["topic3:read"]),
  protectedRoute("/verification", "verification", "可信核验", "暂无核验记录", ["topic4:read"]),
  protectedRoute("/reviews", "reviews", "人工审核", "暂无待审核任务", ["topic4:review:read"]),
  protectedRoute("/publications", "publications", "发布归档", "暂无发布记录", ["topic4:release:read"]),
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

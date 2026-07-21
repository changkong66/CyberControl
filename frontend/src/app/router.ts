import type { Pinia } from "pinia"
import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router"

import { useAuthStore } from "../stores/auth"
import { translate } from "../i18n"

const AccountProfilePage = () => import("../pages/AccountProfilePage.vue")
const AccountRecoveryPage = () => import("../pages/AccountRecoveryPage.vue")
const AgentsPage = () => import("../pages/AgentsPage.vue")
const AuthCallbackPage = () => import("../pages/AuthCallbackPage.vue")
const ErrorPage = () => import("../pages/ErrorPage.vue")
const ForbiddenPage = () => import("../pages/ForbiddenPage.vue")
const KnowledgePage = () => import("../pages/KnowledgePage.vue")
const LearningPage = () => import("../pages/LearningPage.vue")
const LoginPage = () => import("../pages/LoginPage.vue")
const PublicationsPage = () => import("../pages/PublicationsPage.vue")
const RegisterPage = () => import("../pages/RegisterPage.vue")
const ReviewsPage = () => import("../pages/ReviewsPage.vue")
const TenantAccountsPage = () => import("../pages/TenantAccountsPage.vue")
const VerificationPage = () => import("../pages/VerificationPage.vue")
const WorkspacePage = () => import("../pages/WorkspacePage.vue")

const routes: RouteRecordRaw[] = [
  { path: "/", redirect: "/workspace" },
  {
    path: "/login",
    name: "login",
    component: LoginPage,
    meta: { shell: false, titleKey: "routes.login" },
  },
  {
    path: "/auth/callback",
    name: "auth-callback",
    component: AuthCallbackPage,
    meta: { shell: false, titleKey: "routes.callback" },
  },
  { path: "/register", name: "register", component: RegisterPage, meta: { shell: false, titleKey: "routes.register" } },
  { path: "/account/recovery", name: "account-recovery", component: AccountRecoveryPage, meta: { shell: false, titleKey: "routes.recovery" } },
  { path: "/account/profile", name: "account-profile", component: AccountProfilePage, meta: { requiresAuth: true, requiredScopes: ["account:profile:read"], titleKey: "routes.profile" } },
  { path: "/tenant/accounts", name: "tenant-accounts", component: TenantAccountsPage, meta: { requiresAuth: true, requiredScopes: ["account:admin:read"], titleKey: "routes.tenantAccounts" } },
  {
    path: "/workspace",
    name: "workspace",
    component: WorkspacePage,
    meta: { requiresAuth: true, requiredScopes: ["topic1:read"], titleKey: "routes.workspace" },
  },
  { path: "/knowledge", name: "knowledge", component: KnowledgePage, meta: { requiresAuth: true, requiredScopes: ["topic1:read"], titleKey: "routes.knowledge" } },
  { path: "/learning", name: "learning", component: LearningPage, meta: { requiresAuth: true, requiredScopes: ["topic2:read"], titleKey: "routes.learning" } },
  { path: "/agents", name: "agents", component: AgentsPage, meta: { requiresAuth: true, requiredScopes: ["topic3:read"], titleKey: "routes.agents" } },
  { path: "/verification", name: "verification", component: VerificationPage, meta: { requiresAuth: true, requiredScopes: ["topic4:read"], titleKey: "routes.verification" } },
  { path: "/verification/revision", name: "verification-revision", component: VerificationPage, meta: { requiresAuth: true, requiredScopes: ["topic4:read"], titleKey: "routes.revision" } },
  { path: "/reviews", name: "reviews", component: ReviewsPage, meta: { requiresAuth: true, requiredScopes: ["topic4:review:read"], titleKey: "routes.reviews" } },
  { path: "/publications", name: "publications", component: PublicationsPage, meta: { requiresAuth: true, requiredScopes: ["topic4:release:read"], titleKey: "routes.publications" } },
  {
    path: "/forbidden",
    name: "forbidden",
    component: ForbiddenPage,
    meta: { shell: false, titleKey: "routes.forbidden" },
  },
  {
    path: "/error",
    name: "error",
    component: ErrorPage,
    meta: { shell: false, titleKey: "routes.error" },
  },
  { path: "/:pathMatch(.*)*", redirect: "/error" },
]

export function createWorkbenchRouter(pinia: Pinia) {
  const router = createRouter({ history: createWebHistory(), routes })
  router.beforeEach(async (to) => {
    const auth = useAuthStore(pinia)
    await auth.restore()
    document.title = to.meta.titleKey ? `${translate(to.meta.titleKey)} | CyberControl` : "CyberControl"

    if ((to.name === "login" || to.name === "register") && auth.authenticated) return { name: "workspace" }
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

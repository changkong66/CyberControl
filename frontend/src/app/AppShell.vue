<script setup lang="ts">
import {
  Activity,
  Bot,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  FileCheck2,
  LayoutDashboard,
  LogOut,
  Menu,
  Network,
  Route,
  ShieldCheck,
  X,
} from "@lucide/vue"
import { computed, ref, watch } from "vue"
import { RouterLink, RouterView, useRoute } from "vue-router"

import { useAuthStore } from "../stores/auth"

const route = useRoute()
const auth = useAuthStore()
const mobileOpen = ref(false)
const collapsed = ref(false)
const shellEnabled = computed(() => route.meta.shell !== false)

const navigation = [
  { to: "/workspace", label: "工作台", icon: LayoutDashboard, scope: "topic1:read" },
  { to: "/knowledge", label: "知识拓扑", icon: Network, scope: "topic1:read" },
  { to: "/learning", label: "学习路径", icon: Route, scope: "topic2:read" },
  { to: "/agents", label: "智能体协同", icon: Bot, scope: "topic3:read" },
  { to: "/verification", label: "可信核验", icon: ShieldCheck, scope: "topic4:read" },
  { to: "/reviews", label: "人工审核", icon: ClipboardCheck, scope: "topic4:review:read" },
  { to: "/publications", label: "发布归档", icon: FileCheck2, scope: "topic4:release:read" },
]

const visibleNavigation = computed(() => navigation.filter((item) => auth.hasScope(item.scope)))
const roleLabel = computed(() => auth.user?.roles[0] ?? "member")

watch(
  () => route.fullPath,
  () => {
    mobileOpen.value = false
  },
)

async function logout(): Promise<void> {
  await auth.logout()
}
</script>

<template>
  <div v-if="!shellEnabled" class="public-layout">
    <RouterView />
  </div>

  <div v-else class="workbench-shell" :class="{ 'sidebar-collapsed': collapsed }">
    <button
      v-if="mobileOpen"
      class="mobile-scrim"
      type="button"
      aria-label="关闭导航"
      @click="mobileOpen = false"
    />
    <aside class="sidebar" :class="{ 'mobile-open': mobileOpen }">
      <div class="brand-row">
        <span class="brand-mark" aria-hidden="true"><Activity :size="19" /></span>
        <div v-if="!collapsed" class="brand-copy">
          <strong>CyberControl</strong>
          <span>可信教育工作台</span>
        </div>
        <button class="mobile-close" type="button" title="关闭导航" @click="mobileOpen = false">
          <X :size="19" />
        </button>
      </div>

      <nav class="primary-nav" aria-label="主导航">
        <RouterLink
          v-for="item in visibleNavigation"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          :title="collapsed ? item.label : undefined"
        >
          <component :is="item.icon" :size="19" aria-hidden="true" />
          <span v-if="!collapsed">{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar-footer">
        <div v-if="!collapsed" class="tenant-block">
          <span>当前租户</span>
          <strong>{{ auth.user?.tenantId }}</strong>
        </div>
        <button
          class="collapse-button"
          type="button"
          :title="collapsed ? '展开导航' : '收起导航'"
          @click="collapsed = !collapsed"
        >
          <ChevronRight v-if="collapsed" :size="18" />
          <ChevronLeft v-else :size="18" />
        </button>
      </div>
    </aside>

    <div class="workspace-frame">
      <header class="topbar">
        <button class="mobile-menu" type="button" title="打开导航" @click="mobileOpen = true">
          <Menu :size="20" />
        </button>
        <div class="topbar-title">
          <BookOpen :size="18" aria-hidden="true" />
          <span>{{ route.meta.title }}</span>
        </div>
        <div class="account-block">
          <div class="account-copy">
            <strong>{{ auth.user?.displayName }}</strong>
            <span>{{ roleLabel }}</span>
          </div>
          <button class="icon-button" type="button" title="退出登录" aria-label="退出登录" @click="logout">
            <LogOut :size="18" />
          </button>
        </div>
      </header>
      <main class="workspace-main">
        <RouterView />
      </main>
    </div>
  </div>
</template>

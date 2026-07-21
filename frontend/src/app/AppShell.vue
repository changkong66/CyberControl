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
  UserRound,
  Users,
  X,
} from "@lucide/vue"
import type { AccountProfileV1 } from "@liyans/contracts"
import { computed, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { RouterLink, RouterView, useRoute } from "vue-router"

import { useAuthStore } from "../stores/auth"
import { useAppServices } from "./services"
import { isIdentityConflict } from "../identity/errors"
import { setAppLocale, type AppLocale } from "../i18n"
import LocaleSwitcher from "../shared/components/LocaleSwitcher.vue"

const route = useRoute()
const auth = useAuthStore()
const { t } = useI18n()
const { workbench } = useAppServices()
const mobileOpen = ref(false)
const collapsed = ref(false)
const profile = ref<AccountProfileV1 | null>(null)
const localeSyncing = ref(false)
const shellEnabled = computed(() => route.meta.shell !== false)

const navigation = [
  { to: "/workspace", labelKey: "navigation.workspace", icon: LayoutDashboard, scope: "topic1:read" },
  { to: "/knowledge", labelKey: "navigation.knowledge", icon: Network, scope: "topic1:read" },
  { to: "/learning", labelKey: "navigation.learning", icon: Route, scope: "topic2:read" },
  { to: "/agents", labelKey: "navigation.agents", icon: Bot, scope: "topic3:read" },
  { to: "/verification", labelKey: "navigation.verification", icon: ShieldCheck, scope: "topic4:read" },
  { to: "/reviews", labelKey: "navigation.reviews", icon: ClipboardCheck, scope: "topic4:review:read" },
  { to: "/publications", labelKey: "navigation.publications", icon: FileCheck2, scope: "topic4:release:read" },
  { to: "/account/profile", labelKey: "navigation.profile", icon: UserRound, scope: "account:profile:read" },
  { to: "/tenant/accounts", labelKey: "navigation.tenantAccounts", icon: Users, scope: "account:admin:read" },
]

const visibleNavigation = computed(() => navigation.filter((item) => auth.hasScope(item.scope)))
const roleLabel = computed(() => auth.user?.roles[0] ?? "member")
const routeTitle = computed(() => t(route.meta.titleKey ?? "app.name"))

watch(
  () => route.fullPath,
  () => {
    mobileOpen.value = false
  },
)

async function logout(): Promise<void> {
  await auth.logout()
}

async function loadProfilePreference(): Promise<void> {
  if (!auth.authenticated || !auth.hasScope("account:profile:read")) return
  try {
    const result = await workbench.getAccountProfile()
    if (result.data.tenant_id !== auth.user?.tenantId) return
    profile.value = result.data
    setAppLocale(result.data.preferred_locale)
  } catch {
    profile.value = null
  }
}

async function persistLocale(locale: AppLocale): Promise<void> {
  if (!auth.hasScope("account:profile:write") || localeSyncing.value) return
  localeSyncing.value = true
  try {
    let current = profile.value ?? (await workbench.getAccountProfile()).data
    if (current.preferred_locale === locale) return
    try {
      current = (
        await workbench.updateAccountProfile({
          display_name: current.display_name,
          preferred_locale: locale,
          expected_version: current.profile_version,
        })
      ).data
    } catch (error) {
      if (!isIdentityConflict(error)) throw error
      const authoritative = (await workbench.getAccountProfile()).data
      current = (
        await workbench.updateAccountProfile({
          display_name: authoritative.display_name,
          preferred_locale: locale,
          expected_version: authoritative.profile_version,
        })
      ).data
    }
    profile.value = current
  } catch {
    profile.value = null
  } finally {
    localeSyncing.value = false
  }
}

watch(
  () => auth.user?.subject,
  () => {
    profile.value = null
    void loadProfilePreference()
  },
  { immediate: true },
)
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
      :aria-label="t('navigation.close')"
      @click="mobileOpen = false"
    />
    <aside class="sidebar" :class="{ 'mobile-open': mobileOpen }">
      <div class="brand-row">
        <span class="brand-mark" aria-hidden="true"><Activity :size="19" /></span>
        <div v-if="!collapsed" class="brand-copy">
          <strong>CyberControl</strong>
          <span>{{ t("app.tagline") }}</span>
        </div>
        <button class="mobile-close" type="button" :title="t('navigation.close')" @click="mobileOpen = false">
          <X :size="19" />
        </button>
      </div>

      <nav class="primary-nav" :aria-label="t('navigation.main')">
        <RouterLink
          v-for="item in visibleNavigation"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          :title="collapsed ? t(item.labelKey) : undefined"
        >
          <component :is="item.icon" :size="19" aria-hidden="true" />
          <span v-if="!collapsed">{{ t(item.labelKey) }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar-footer">
        <div v-if="!collapsed" class="tenant-block">
          <span>{{ t("app.currentTenant") }}</span>
          <strong>{{ auth.user?.tenantId }}</strong>
        </div>
        <button
          class="collapse-button"
          type="button"
          :title="t(collapsed ? 'navigation.expand' : 'navigation.collapse')"
          @click="collapsed = !collapsed"
        >
          <ChevronRight v-if="collapsed" :size="18" />
          <ChevronLeft v-else :size="18" />
        </button>
      </div>
    </aside>

    <div class="workspace-frame">
      <header class="topbar">
        <button class="mobile-menu" type="button" :title="t('navigation.open')" @click="mobileOpen = true">
          <Menu :size="20" />
        </button>
        <div class="topbar-title">
          <BookOpen :size="18" aria-hidden="true" />
          <span>{{ routeTitle }}</span>
        </div>
        <div class="account-block">
          <LocaleSwitcher compact @change="persistLocale" />
          <div class="account-copy">
            <strong>{{ auth.user?.displayName }}</strong>
            <span>{{ roleLabel }}</span>
          </div>
          <RouterLink class="icon-button" to="/account/profile" :title="t('navigation.profile')" :aria-label="t('navigation.profile')"><UserRound :size="18" /></RouterLink>
          <button class="icon-button" type="button" :title="t('auth.signOut')" :aria-label="t('auth.signOut')" @click="logout">
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

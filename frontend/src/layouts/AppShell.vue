<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { Bot, ClipboardCheck, FolderKanban, LogOut, PlayCircle, ScanSearch, TestTube2 } from "lucide-vue-next";
import { NButton, NDropdown } from "naive-ui";

import { useAuthStore } from "@/stores/auth";

const router = useRouter();
const authStore = useAuthStore();
const userLabel = computed(() => authStore.user?.display_name ?? authStore.user?.username ?? "当前用户");
const userActions = [{ label: "退出登录", key: "sign-out" }];

function handleUserAction(key: string): void {
  if (key !== "sign-out") {
    return;
  }
  authStore.signOut();
  void router.replace({ name: "login" });
}
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar" aria-label="主导航">
      <div class="brand">
        <span class="brand-mark"><TestTube2 :size="20" aria-hidden="true" /></span>
        <span class="brand-name">Test Agent</span>
      </div>
      <nav class="navigation">
        <RouterLink class="navigation-item" :to="{ name: 'projects' }">
          <span class="navigation-rail" aria-hidden="true"></span>
          <FolderKanban :size="20" aria-hidden="true" />
          <span class="navigation-label">项目管理</span>
        </RouterLink>
        <RouterLink class="navigation-item" :to="{ name: 'api-definitions' }">
          <span class="navigation-rail" aria-hidden="true"></span>
          <ScanSearch :size="20" aria-hidden="true" />
          <span class="navigation-label">接口发现</span>
        </RouterLink>
        <RouterLink class="navigation-item" :to="{ name: 'analysis' }">
          <span class="navigation-rail" aria-hidden="true"></span>
          <Bot :size="20" aria-hidden="true" />
          <span class="navigation-label">AI 分析</span>
        </RouterLink>
        <RouterLink class="navigation-item" :to="{ name: 'testcases' }">
          <span class="navigation-rail" aria-hidden="true"></span>
          <ClipboardCheck :size="20" aria-hidden="true" />
          <span class="navigation-label">用例管理</span>
        </RouterLink>
        <RouterLink class="navigation-item" :to="{ name: 'executions' }">
          <span class="navigation-rail" aria-hidden="true"></span>
          <PlayCircle :size="20" aria-hidden="true" />
          <span class="navigation-label">测试执行</span>
        </RouterLink>
      </nav>
      <div class="sidebar-footer">
        <span class="sidebar-status-dot" aria-hidden="true"></span>
        <span class="sidebar-status-text">平台基础服务</span>
      </div>
    </aside>

    <main class="workspace">
      <header class="topbar">
        <div class="breadcrumb">项目 / <span>未选择项目</span></div>
        <NDropdown :options="userActions" @select="handleUserAction">
          <NButton class="user-menu" quaternary>
            <span class="user-avatar">{{ userLabel.slice(0, 1) }}</span>
            <span class="user-name">{{ userLabel }}</span>
            <LogOut :size="16" aria-label="打开用户菜单" />
          </NButton>
        </NDropdown>
      </header>
      <section class="content-area"><RouterView /></section>
    </main>
  </div>
</template>

<style scoped>
.app-shell { display: grid; grid-template-columns: var(--sidebar-width) minmax(0, 1fr); min-height: 100vh; background: var(--color-page); }
.sidebar { display: flex; flex-direction: column; min-height: 100vh; padding: 20px 14px; background: var(--color-surface); border-right: 1px solid var(--color-border); }
.brand { display: flex; align-items: center; gap: 10px; height: 44px; padding: 0 10px; color: var(--color-text); font-weight: 650; letter-spacing: -0.02em; }
.brand-mark { display: grid; width: 32px; height: 32px; color: var(--color-primary); place-items: center; background: var(--color-primary-softer); border-radius: var(--radius-sm); }
.navigation { margin-top: 36px; }
.navigation-item { position: relative; display: flex; align-items: center; gap: 12px; height: 48px; padding: 0 12px; color: var(--color-text-secondary); text-decoration: none; border-radius: var(--radius-sm); }
.navigation-item.router-link-active { color: var(--color-primary); font-weight: 600; background: var(--color-primary-softer); }
.navigation-rail { position: absolute; left: -14px; width: 3px; height: 24px; background: transparent; border-radius: 0 3px 3px 0; }
.navigation-item.router-link-active .navigation-rail { background: var(--color-primary); }
.sidebar-footer { display: flex; align-items: center; gap: 8px; margin-top: auto; padding: 12px 10px; color: var(--color-text-muted); font-size: 12px; }
.sidebar-status-dot { width: 7px; height: 7px; background: var(--color-success); border-radius: 50%; }
.workspace { min-width: 0; }
.topbar { display: flex; align-items: center; justify-content: space-between; height: var(--topbar-height); padding: 0 var(--page-padding); background: var(--color-surface); border-bottom: 1px solid var(--color-border); }
.breadcrumb { color: var(--color-text-secondary); font-size: 13px; }
.breadcrumb span { color: var(--color-text-muted); }
.user-menu { display: inline-flex; align-items: center; gap: 8px; color: var(--color-text-secondary); }
.user-avatar { display: grid; width: 26px; height: 26px; color: var(--color-primary); font-size: 12px; font-weight: 650; place-items: center; background: var(--color-primary-soft); border-radius: 50%; }
.content-area { min-height: calc(100vh - var(--topbar-height)); padding: var(--page-padding); }
@media (max-width: 1279px) { .app-shell { grid-template-columns: var(--sidebar-collapsed-width) minmax(0, 1fr); } .sidebar { align-items: center; padding-right: 10px; padding-left: 10px; } .brand-name, .navigation-label, .sidebar-status-text, .user-name { display: none; } .navigation-item { justify-content: center; width: 48px; padding: 0; } .navigation-rail { left: -10px; } }
</style>

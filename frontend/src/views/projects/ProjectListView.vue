<script setup lang="ts">
import { FolderPlus, FolderSearch } from "lucide-vue-next";
import { NButton, NCard, NEmpty, NTag } from "naive-ui";
</script>

<template>
  <section class="project-page">
    <header class="page-header">
      <div class="page-heading"><span class="page-rail" aria-hidden="true"></span><div><p class="page-kicker">工作区</p><h1>项目管理</h1><p>集中管理被测项目、源码来源和接口测试资产。</p></div></div>
      <NButton type="primary" disabled><template #icon><FolderPlus :size="17" /></template>创建项目</NButton>
    </header>
    <NCard class="project-card" :bordered="false">
      <NEmpty size="large" description="尚未创建测试项目">
        <template #icon><FolderSearch :size="40" stroke-width="1.5" /></template>
        <template #extra><div class="empty-extra"><p>项目创建将在 M1 阶段开放。当前可先确认源码目录、OpenAPI 来源和测试环境。</p><NTag size="small" type="info" :bordered="false">下一阶段：项目配置</NTag></div></template>
      </NEmpty>
    </NCard>
  </section>
</template>

<style scoped>
.project-page { display: grid; gap: 24px; }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.page-heading { display: flex; gap: 16px; }
.page-rail { width: 3px; min-height: 72px; background: var(--color-primary); border-radius: 3px; }
.page-kicker { margin: 0 0 6px; color: var(--color-primary); font-size: 12px; font-weight: 650; }
h1 { margin: 0; color: var(--color-text); font-size: 24px; font-weight: 650; letter-spacing: -0.025em; }
.page-heading > div > p:last-child { margin: 8px 0 0; color: var(--color-text-secondary); font-size: 14px; }
.project-card { display: grid; min-height: 420px; border: 1px solid var(--color-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-card); place-items: center; }
.empty-extra { max-width: 360px; margin-top: 8px; text-align: center; }
.empty-extra p { margin: 0 0 12px; color: var(--color-text-secondary); font-size: 13px; line-height: 1.7; }
@media (max-width: 640px) { .page-header { flex-direction: column; } }
</style>

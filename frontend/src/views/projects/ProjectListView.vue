<script setup lang="ts">
import { onMounted, ref } from "vue";
import { FolderPlus } from "lucide-vue-next";
import { NButton, NCard, NCheckbox, NForm, NFormItem, NInput, NModal, NTag } from "naive-ui";
import { createEnvironment, createProject, listLlmConfigs, listProjects, setEnvironmentVariable, setLocalSource, setOpenApiUrl, testLlmConfig, type LlmConfig, type Project } from "@/api/projects";

const projects = ref<Project[]>([]); const configs = ref<LlmConfig[]>([]); const showCreate = ref(false); const name = ref(""); const description = ref(""); const message = ref("");
const selected = ref(""); const sourcePath = ref(""); const openapiUrl = ref(""); const environmentName = ref(""); const baseUrl = ref(""); const variableKey = ref(""); const variableValue = ref(""); const variableSecret = ref(false); const environmentId = ref("");
async function load(): Promise<void> { projects.value = (await listProjects()).data; configs.value = (await listLlmConfigs()).data; }
async function submit(): Promise<void> { await createProject({ name: name.value, description: description.value }); showCreate.value = false; name.value = ""; description.value = ""; await load(); }
async function test(id: string): Promise<void> { message.value = (await testLlmConfig(id)).data.success ? "连接成功" : "连接失败"; }
onMounted(() => { void load(); });
async function saveSource(): Promise<void> { await setLocalSource(selected.value, sourcePath.value); message.value = "源码目录已保存"; }
async function saveOpenapi(): Promise<void> { await setOpenApiUrl(selected.value, openapiUrl.value); message.value = "OpenAPI 已保存"; }
async function saveEnvironment(): Promise<void> { await createEnvironment(selected.value, { name: environmentName.value, base_url: baseUrl.value, environment_type: "test", allow_write_requests: false }); message.value = "测试环境已创建"; }
async function saveVariable(): Promise<void> { await setEnvironmentVariable(selected.value, environmentId.value, { key: variableKey.value, value: variableValue.value, is_secret: variableSecret.value }); variableValue.value = ""; message.value = "变量已保存"; }
</script>

<template>
  <section class="project-page">
    <header class="page-header">
      <div class="page-heading"><span class="page-rail" aria-hidden="true"></span><div><p class="page-kicker">工作区</p><h1>项目管理</h1><p>集中管理被测项目、源码来源和接口测试资产。</p></div></div>
      <NButton type="primary" @click="showCreate = true"><template #icon><FolderPlus :size="17" /></template>创建项目</NButton>
    </header>
    <NCard class="project-card" :bordered="false"><div v-if="projects.length" class="project-list"><article v-for="project in projects" :key="project.id"><strong>{{ project.name }}</strong><p>{{ project.description || "暂无描述" }}</p><NTag size="small">Java / Spring Boot</NTag></article></div><p v-else class="empty-extra">尚未创建测试项目。</p></NCard>
    <NCard :bordered="false" title="LLM 配置"><p v-if="message">{{ message }}</p><div v-for="config in configs" :key="config.id" class="llm-row"><span>{{ config.name }} · {{ config.model }}</span><NTag :type="config.apiKeyConfigured ? 'success' : 'warning'">{{ config.apiKeyConfigured ? "Key 已配置" : "未配置" }}</NTag><NButton size="small" @click="test(config.id)">测试连接</NButton></div><p v-if="!configs.length">尚未配置 LLM。</p></NCard>
    <NCard :bordered="false" title="项目配置"><NForm><NFormItem label="项目 ID"><NInput v-model:value="selected" placeholder="从上方项目列表复制 ID" /></NFormItem><NFormItem label="源码目录"><NInput v-model:value="sourcePath" /><NButton @click="saveSource">保存源码</NButton></NFormItem><NFormItem label="OpenAPI URL"><NInput v-model:value="openapiUrl" /><NButton @click="saveOpenapi">保存 OpenAPI</NButton></NFormItem><NFormItem label="环境名称 / Base URL"><NInput v-model:value="environmentName" /><NInput v-model:value="baseUrl" /><NButton @click="saveEnvironment">创建环境</NButton></NFormItem><NFormItem label="环境 ID / 变量"><NInput v-model:value="environmentId" placeholder="环境 ID" /><NInput v-model:value="variableKey" placeholder="变量名" /><NInput v-model:value="variableValue" type="password" placeholder="变量值" /><NCheckbox v-model:checked="variableSecret">加密变量</NCheckbox><NButton @click="saveVariable">保存变量</NButton></NFormItem></NForm></NCard>
    <NModal v-model:show="showCreate" preset="card" title="创建项目" style="width: 480px"><NForm @submit.prevent="submit"><NFormItem label="项目名称"><NInput v-model:value="name" /></NFormItem><NFormItem label="描述"><NInput v-model:value="description" type="textarea" /></NFormItem><NButton type="primary" attr-type="submit">保存</NButton></NForm></NModal>
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
.project-card { border: 1px solid var(--color-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-card); }
.project-list { display: grid; gap: 12px; }.project-list article { padding: 16px; border: 1px solid var(--color-border); border-radius: var(--radius-md); }.project-list p { color: var(--color-text-secondary); }.llm-row { display: flex; gap: 12px; align-items: center; margin: 10px 0; }
.empty-extra { max-width: 360px; margin-top: 8px; text-align: center; }
.empty-extra p { margin: 0 0 12px; color: var(--color-text-secondary); font-size: 13px; line-height: 1.7; }
@media (max-width: 640px) { .page-header { flex-direction: column; } }
</style>

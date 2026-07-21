<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { FolderOpen, FolderPlus } from "lucide-vue-next";
import { NButton, NCard, NCheckbox, NForm, NFormItem, NInput, NModal, NSelect, NSpin, NTag } from "naive-ui";

import { ApiRequestError } from "@/api/client";
import {
  createEnvironment,
  createProject,
  getOpenApiSource,
  getProjectSource,
  listEnvironments,
  listProjects,
  setEnvironmentVariable,
  setLocalSource,
  setOpenApiUrl,
  updateEnvironment,
  updateProject,
  type EnvironmentPayload,
  type Project,
  type TestEnvironment
} from "@/api/projects";

const route = useRoute();
const router = useRouter();
const projects = ref<Project[]>([]);
const selectedProject = ref<Project | null>(null);
const environments = ref<TestEnvironment[]>([]);
const showCreate = ref(false);
const loading = ref(false);
const saving = ref(false);
const message = ref("");
const errorMessage = ref("");

const createName = ref("");
const createDescription = ref("");
const projectName = ref("");
const projectDescription = ref("");
const sourcePath = ref("");
const openapiUrl = ref("");
const environmentId = ref("");
const environmentName = ref("");
const baseUrl = ref("");
const environmentType = ref<EnvironmentPayload["environment_type"]>("test");
const hostAllowlist = ref("");
const allowWriteRequests = ref(false);
const variableKey = ref("");
const variableValue = ref("");

const environmentOptions = computed(() => [
  { label: "新建测试环境", value: "" },
  ...environments.value.map((item) => ({ label: item.name, value: item.id }))
]);
const environmentTypeOptions = [
  { label: "测试环境", value: "test" },
  { label: "预发布环境", value: "staging" },
  { label: "生产环境", value: "production" }
];

function errorText(error: unknown): string {
  return error instanceof ApiRequestError ? error.message : "操作失败，请稍后重试";
}

async function loadProjects(): Promise<void> {
  projects.value = (await listProjects()).data;
}

async function submitProject(): Promise<void> {
  errorMessage.value = "";
  try {
    await createProject({ name: createName.value.trim(), description: createDescription.value.trim() });
    showCreate.value = false;
    createName.value = "";
    createDescription.value = "";
    await loadProjects();
  } catch (error: unknown) {
    errorMessage.value = errorText(error);
  }
}

function applyEnvironment(id: string): void {
  environmentId.value = id;
  const environment = environments.value.find((item) => item.id === id);
  environmentName.value = environment?.name ?? "";
  baseUrl.value = environment?.baseUrl ?? "";
  environmentType.value = environment?.environmentType ?? "test";
  hostAllowlist.value = environment?.hostAllowlist.join("\n") ?? "";
  allowWriteRequests.value = environment?.allowWriteRequests ?? false;
  variableKey.value = "";
  variableValue.value = "";
}

async function loadProjectConfiguration(project: Project): Promise<void> {
  selectedProject.value = project;
  projectName.value = project.name;
  projectDescription.value = project.description;
  sourcePath.value = "";
  openapiUrl.value = "";
  message.value = "";
  errorMessage.value = "";
  loading.value = true;
  try {
    const [sourceResponse, openapiResponse, environmentResponse] = await Promise.all([
      getProjectSource(project.id),
      getOpenApiSource(project.id),
      listEnvironments(project.id)
    ]);
    sourcePath.value = sourceResponse.data?.local_path ?? "";
    openapiUrl.value = openapiResponse.data.url ?? "";
    environments.value = environmentResponse.data;
    applyEnvironment(environments.value[0]?.id ?? "");
  } catch (error: unknown) {
    errorMessage.value = errorText(error);
  } finally {
    loading.value = false;
  }
}

function resetProjectSelection(): void {
  selectedProject.value = null;
  environments.value = [];
  message.value = "";
  errorMessage.value = "";
}

function openProject(project: Project): void {
  void router.push({ name: "project-detail", params: { projectId: project.id }, query: { name: project.name } });
}

function environmentPayload(): EnvironmentPayload {
  return {
    name: environmentName.value.trim(),
    base_url: baseUrl.value.trim(),
    environment_type: environmentType.value,
    host_allowlist: hostAllowlist.value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean),
    allow_write_requests: allowWriteRequests.value
  };
}

async function saveConfiguration(): Promise<void> {
  const project = selectedProject.value;
  if (project === null) {
    return;
  }
  saving.value = true;
  message.value = "";
  errorMessage.value = "";
  try {
    const updated = (await updateProject(project.id, { name: projectName.value.trim(), description: projectDescription.value.trim() })).data;
    if (sourcePath.value.trim() !== "") {
      await setLocalSource(project.id, sourcePath.value.trim());
    }
    if (openapiUrl.value.trim() !== "") {
      await setOpenApiUrl(project.id, openapiUrl.value.trim());
    }
    let savedEnvironmentId = environmentId.value;
    if (environmentName.value.trim() !== "" || baseUrl.value.trim() !== "") {
      const payload = environmentPayload();
      if (savedEnvironmentId === "") {
        savedEnvironmentId = (await createEnvironment(project.id, payload)).data.id;
      } else {
        await updateEnvironment(project.id, savedEnvironmentId, payload);
      }
    }
    if (variableKey.value.trim() !== "" && variableValue.value !== "") {
      if (savedEnvironmentId === "") {
        throw new Error("请先填写测试环境信息");
      }
      await setEnvironmentVariable(project.id, savedEnvironmentId, { key: variableKey.value.trim(), value: variableValue.value, is_secret: false });
    }
    selectedProject.value = updated;
    variableValue.value = "";
    await loadProjects();
    await router.replace({ name: "project-detail", params: { projectId: updated.id }, query: { name: updated.name } });
    await loadProjectConfiguration(updated);
    message.value = "项目配置已保存";
  } catch (error: unknown) {
    errorMessage.value = error instanceof Error ? error.message : errorText(error);
  } finally {
    saving.value = false;
  }
}

watch(
  () => route.params.projectId,
  async (projectId) => {
    if (projects.value.length === 0) {
      await loadProjects();
    }
    if (typeof projectId !== "string") {
      resetProjectSelection();
      return;
    }
    const project = projects.value.find((item) => item.id === projectId);
    if (project === undefined) {
      errorMessage.value = "项目不存在或当前用户无权访问";
      return;
    }
    if (route.query.name !== project.name) {
      await router.replace({ name: "project-detail", params: { projectId }, query: { name: project.name } });
    }
    await loadProjectConfiguration(project);
  },
  { immediate: true }
);
</script>

<template>
  <section class="project-page">
    <header v-if="selectedProject === null" class="page-header">
      <div class="page-heading">
        <span class="page-rail" aria-hidden="true"></span>
        <div class="list-heading">
          <h1>项目管理</h1>
        </div>
      </div>
      <NButton type="primary" @click="showCreate = true">
        <template #icon><FolderPlus :size="17" /></template>创建项目
      </NButton>
    </header>

    <template v-if="selectedProject === null">
      <div v-if="projects.length" class="project-list">
        <button v-for="project in projects" :key="project.id" type="button" class="project-item" @click="openProject(project)">
          <div class="project-copy">
            <strong>{{ project.name }}</strong>
            <p>{{ project.description || "暂无项目描述" }}</p>
          </div>
          <NTag class="project-language" size="small">Java / Spring Boot</NTag>
        </button>
      </div>
      <NCard v-else class="empty-card" :bordered="false">
        <FolderOpen :size="34" aria-hidden="true" />
        <strong>还没有测试项目</strong>
        <p>创建项目后再配置源码、OpenAPI 和测试环境。</p>
        <NButton type="primary" @click="showCreate = true">创建第一个项目</NButton>
      </NCard>
    </template>

    <NSpin v-else :show="loading">
      <NCard class="config-card" :bordered="false">
        <section class="config-section">
          <h2>基础信息</h2>
          <div class="form-grid">
            <NFormItem label="项目名称"><NInput v-model:value="projectName" /></NFormItem>
            <NFormItem label="技术栈"><NInput value="Java / Spring Boot" disabled /></NFormItem>
            <NFormItem class="full-field" label="项目描述"><NInput v-model:value="projectDescription" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" /></NFormItem>
          </div>
        </section>

        <section class="config-section">
          <h2>源码与接口定义</h2>
          <div class="form-grid">
            <NFormItem class="full-field" label="源码位置">
              <NInput v-model:value="sourcePath" placeholder="请输入或粘贴绝对路径，例如：D:\test\Ai_meeting" />
            </NFormItem>
            <NFormItem class="full-field" label="OpenAPI URL"><NInput v-model:value="openapiUrl" placeholder="https://example.test/v3/api-docs" /></NFormItem>
          </div>
        </section>

        <section class="config-section">
          <h2>测试环境</h2>
          <div class="form-grid">
            <NFormItem class="full-field" label="配置对象"><NSelect :value="environmentId" :options="environmentOptions" @update:value="applyEnvironment" /></NFormItem>
            <NFormItem label="环境名称"><NInput v-model:value="environmentName" placeholder="例如：集成测试环境" /></NFormItem>
            <NFormItem label="环境类型"><NSelect v-model:value="environmentType" :options="environmentTypeOptions" /></NFormItem>
            <NFormItem class="full-field" label="Base URL"><NInput v-model:value="baseUrl" placeholder="https://api.example.test" /></NFormItem>
            <NFormItem class="full-field" label="Host 白名单"><NInput v-model:value="hostAllowlist" type="textarea" placeholder="每行填写一个 Host" :autosize="{ minRows: 2, maxRows: 5 }" /></NFormItem>
            <NFormItem label="环境变量名"><NInput v-model:value="variableKey" placeholder="例如：tenant_id" /></NFormItem>
            <NFormItem label="环境变量值"><NInput v-model:value="variableValue" placeholder="填写普通环境变量" /></NFormItem>
            <NFormItem class="full-field"><NCheckbox v-model:checked="allowWriteRequests">允许向该环境发送写请求</NCheckbox></NFormItem>
          </div>
        </section>

        <div class="save-bar">
          <div><p v-if="message" class="success-message">{{ message }}</p><p v-if="errorMessage" class="error-message">{{ errorMessage }}</p></div>
          <NButton type="primary" :loading="saving" @click="saveConfiguration">保存项目配置</NButton>
        </div>
      </NCard>
    </NSpin>

    <NModal v-model:show="showCreate" preset="card" title="创建项目" style="width: min(480px, calc(100vw - 32px))">
      <NForm @submit.prevent="submitProject">
        <NFormItem label="项目名称"><NInput v-model:value="createName" /></NFormItem>
        <NFormItem label="项目描述"><NInput v-model:value="createDescription" type="textarea" /></NFormItem>
        <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>
        <NButton type="primary" attr-type="submit">创建项目</NButton>
      </NForm>
    </NModal>

  </section>
</template>

<style scoped>
.project-page { display: grid; gap: 24px; }
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 24px; margin: calc(var(--page-padding) * -1) calc(var(--page-padding) * -1) 0; padding: 12px var(--page-padding); background: var(--color-surface); border-bottom: 1px solid var(--color-border); }
.page-heading { display: flex; gap: 16px; }
.page-rail { width: 3px; min-height: 40px; background: var(--color-primary); border-radius: var(--radius-sm); }
h1 { margin: 0; color: var(--color-text); font-size: 24px; font-weight: 650; letter-spacing: -0.025em; }
.list-heading { display: flex; align-items: center; min-height: 40px; }
.project-list { display: grid; gap: 12px; }
.project-item { display: flex; align-items: center; gap: 24px; width: 100%; min-height: 92px; padding: 20px 24px; color: var(--color-text-secondary); text-align: left; cursor: pointer; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-card); transition: border-color 160ms ease, box-shadow 160ms ease; }
.project-item:hover { border-color: var(--color-primary); box-shadow: 0 8px 24px rgba(85, 72, 232, 0.08); }
.project-copy { min-width: 0; }
.project-copy strong { color: var(--color-text); font-size: 16px; }
.project-copy p { margin: 7px 0 0; overflow: hidden; color: var(--color-text-secondary); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.project-language { flex: 0 0 auto; margin-left: auto; }
.empty-card { display: grid; justify-items: center; gap: 12px; padding: 64px 24px; color: var(--color-text-muted); text-align: center; border: 1px solid var(--color-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-card); }
.empty-card strong { color: var(--color-text); font-size: 16px; }.empty-card p { margin: 0 0 6px; color: var(--color-text-secondary); }
.config-card { border: 1px solid var(--color-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-card); }
.config-section { padding-bottom: 20px; }.config-section + .config-section { padding-top: 24px; }.config-section h2 { display: flex; align-items: center; gap: 10px; margin: 0 0 20px; color: var(--color-text); font-size: 16px; }.config-section h2::before { width: 3px; height: 22px; content: ""; background: var(--color-primary); border-radius: var(--radius-sm); }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 18px; }
.full-field { grid-column: 1 / -1; }
.save-bar { display: flex; align-items: center; flex-direction: column; gap: 12px; padding-top: 20px; text-align: center; }
.save-bar p { margin: 0; font-size: 13px; }.success-message { color: var(--color-success); }.error-message { color: var(--color-danger); font-size: 13px; }
@media (max-width: 700px) { .page-header { flex-direction: column; }.project-item { align-items: flex-start; flex-direction: column; gap: 12px; }.project-language { margin-left: 0; }.form-grid { grid-template-columns: 1fr; }.full-field { grid-column: auto; } }
</style>

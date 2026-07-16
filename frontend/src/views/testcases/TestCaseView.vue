<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { ClipboardCheck, Pencil, Save } from "lucide-vue-next";
import { NButton, NCard, NDrawer, NDrawerContent, NEmpty, NInput, NSelect, NSpin, NTag } from "naive-ui";

import { listProjects, type Project } from "@/api/projects";
import { listTestCases, updateTestCase, type AssertionInput, type TestCase } from "@/api/testcases";

const projects = ref<Project[]>([]);
const selectedProjectId = ref<string | null>(null);
const cases = ref<TestCase[]>([]);
const selectedCase = ref<TestCase | null>(null);
const loading = ref(false);
const saving = ref(false);
const errorMessage = ref("");
const requestTemplateText = ref("{}");
const assertionsText = ref("[]");
const preconditionsText = ref("");

const projectOptions = computed(() => projects.value.map((project) => ({ label: project.name, value: project.id })));
const drawerVisible = computed({ get: () => selectedCase.value !== null, set: (value: boolean) => { if (!value) selectedCase.value = null; } });

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function statusType(status: TestCase["status"]): "default" | "success" | "warning" | "error" | "info" {
  if (status === "approved") return "success";
  if (status === "pending_review" || status === "draft") return "warning";
  if (status === "disabled") return "error";
  return "default";
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

async function loadCases(): Promise<void> {
  if (selectedProjectId.value === null) { cases.value = []; return; }
  loading.value = true;
  errorMessage.value = "";
  try { cases.value = (await listTestCases(selectedProjectId.value)).data; } catch (error: unknown) { errorMessage.value = error instanceof Error ? error.message : "用例加载失败"; } finally { loading.value = false; }
}

function openCase(item: TestCase): void {
  selectedCase.value = item;
  requestTemplateText.value = formatJson(item.request_template);
  assertionsText.value = formatJson(item.assertions.map(({ assertion_type, config, description }) => ({ assertion_type, config, description })));
  preconditionsText.value = item.preconditions.join("\n");
}

function parseRequestTemplate(): Record<string, unknown> {
  const value: unknown = JSON.parse(requestTemplateText.value);
  if (!isRecord(value)) throw new Error("请求模板必须是 JSON 对象");
  return value;
}

function parseAssertions(): AssertionInput[] {
  const value: unknown = JSON.parse(assertionsText.value);
  if (!Array.isArray(value)) throw new Error("断言必须是 JSON 数组");
  return value.map((item): AssertionInput => {
    if (!isRecord(item) || typeof item.assertion_type !== "string" || !isRecord(item.config) || typeof item.description !== "string") {
      throw new Error("断言格式无效");
    }
    if (!["status_code_equals", "business_code_equals", "json_path_equals", "json_path_exists", "json_path_not_exists", "json_path_type", "body_contains", "body_not_contains", "number_range", "response_time_less_than", "status_code", "business_code", "text_contains"].includes(item.assertion_type)) {
      throw new Error("断言类型不受支持");
    }
    return { assertion_type: item.assertion_type as AssertionInput["assertion_type"], config: item.config, description: item.description };
  });
}

async function saveCase(): Promise<void> {
  if (selectedProjectId.value === null || selectedCase.value === null) return;
  saving.value = true;
  errorMessage.value = "";
  try {
    const updated = (await updateTestCase(selectedProjectId.value, selectedCase.value.id, { request_template: parseRequestTemplate(), assertions: parseAssertions(), preconditions: preconditionsText.value.split("\n").map((value) => value.trim()).filter(Boolean) })).data;
    cases.value = cases.value.map((item) => item.id === updated.id ? updated : item);
    openCase(updated);
  } catch (error: unknown) { errorMessage.value = error instanceof Error ? error.message : "保存用例失败"; } finally { saving.value = false; }
}

watch(selectedProjectId, () => { selectedCase.value = null; void loadCases(); });
onMounted(async () => { projects.value = (await listProjects()).data; });
</script>

<template>
  <section class="case-page"><header class="page-header"><div class="page-heading"><span class="page-rail"></span><div><p class="page-kicker">审核前草稿</p><h1>用例管理</h1><p>编辑 Agent 生成的请求模板与断言，再回到 AI 分析页面批量审核。</p></div></div></header><NCard class="control-card" :bordered="false"><label>项目<NSelect v-model:value="selectedProjectId" :options="projectOptions" placeholder="选择项目" /></label><p v-if="errorMessage" class="error-message">{{ errorMessage }}</p></NCard><NSpin :show="loading"><NCard v-if="cases.length" class="case-card" :bordered="false"><div class="case-list"><button v-for="item in cases" :key="item.id" type="button" class="case-row" @click="openCase(item)"><NTag size="small" type="info">{{ item.category }}</NTag><div><strong>{{ item.name }}</strong><p>{{ item.description }}</p></div><NTag size="small" :type="statusType(item.status)">{{ item.status }}</NTag><span class="confidence">{{ Math.round(item.confidence * 100) }}%</span><Pencil :size="16" /></button></div></NCard><NEmpty v-else description="当前项目尚未生成测试用例"><template #icon><ClipboardCheck :size="38" /></template></NEmpty></NSpin><NDrawer v-model:show="drawerVisible" :width="680" placement="right"><NDrawerContent v-if="selectedCase !== null" :title="selectedCase.name" closable><div class="detail-meta"><NTag size="small" type="info">{{ selectedCase.category }}</NTag><NTag size="small" :type="statusType(selectedCase.status)">{{ selectedCase.status }}</NTag><span v-if="selectedCase.is_inferred">包含 AI 推断规则</span></div><label>前置条件（每行一条）<NInput v-model:value="preconditionsText" type="textarea" :autosize="{ minRows: 3, maxRows: 7 }" :disabled="selectedCase.status === 'approved' || selectedCase.status === 'disabled'" /></label><label>请求模板（JSON）<NInput v-model:value="requestTemplateText" type="textarea" :autosize="{ minRows: 10, maxRows: 18 }" :disabled="selectedCase.status === 'approved' || selectedCase.status === 'disabled'" /></label><label>断言草稿（JSON）<NInput v-model:value="assertionsText" type="textarea" :autosize="{ minRows: 10, maxRows: 18 }" :disabled="selectedCase.status === 'approved' || selectedCase.status === 'disabled'" /></label><p v-if="errorMessage" class="error-message">{{ errorMessage }}</p><NButton v-if="selectedCase.status === 'draft' || selectedCase.status === 'pending_review'" type="primary" :loading="saving" @click="saveCase"><template #icon><Save :size="16" /></template>保存草稿</NButton></NDrawerContent></NDrawer></section>
</template>

<style scoped>
.case-page { display: grid; gap: 20px; }.page-heading { display: flex; gap: 16px; }.page-rail { width: 3px; min-height: 74px; background: var(--color-primary); border-radius: var(--radius-sm); }.page-kicker { margin: 0 0 6px; color: var(--color-primary); font-size: 12px; font-weight: 650; }h1 { margin: 0; color: var(--color-text); font-size: 24px; }.page-heading p:last-child { margin: 8px 0 0; color: var(--color-text-secondary); font-size: 14px; }.control-card,.case-card { border: 1px solid var(--color-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-card); }.control-card label { display: grid; max-width: 360px; gap: 8px; color: var(--color-text-secondary); font-size: 12px; }.case-list { display: grid; }.case-row { display: grid; grid-template-columns: auto minmax(0,1fr) auto auto auto; gap: 12px; align-items: center; width: 100%; padding: 14px 4px; color: var(--color-text); text-align: left; cursor: pointer; background: transparent; border: 0; border-bottom: 1px solid var(--color-border); }.case-row:hover { color: var(--color-primary); }.case-row strong { font-size: 14px; }.case-row p { max-width: 600px; margin: 5px 0 0; overflow: hidden; color: var(--color-text-secondary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.confidence { color: var(--color-text-muted); font-size: 12px; }.detail-meta { display: flex; gap: 8px; align-items: center; margin-bottom: 18px; color: var(--color-warning); font-size: 12px; }.detail-meta span { margin-left: auto; }.n-drawer-content label { display: grid; gap: 8px; margin: 16px 0; color: var(--color-text-secondary); font-size: 13px; }.error-message { color: var(--color-danger); font-size: 13px; }@media (max-width: 700px) { .case-row { grid-template-columns: auto minmax(0,1fr) auto; }.case-row .confidence { display: none; } }
</style>

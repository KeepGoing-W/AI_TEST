<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Play, RefreshCw, Square } from "lucide-vue-next";
import { NButton, NCard, NCheckbox, NCheckboxGroup, NCode, NCollapse, NCollapseItem, NEmpty, NModal, NSelect, NSpin, NSwitch, NTag } from "naive-ui";

import { getExecution, listExecutions, retryExecution, startExecution, stopExecution, type ExecutionRun } from "@/api/executions";
import { listEnvironments, listProjects, type Project, type TestEnvironment } from "@/api/projects";
import { listTestCases, type TestCase } from "@/api/testcases";

const projects = ref<Project[]>([]);
const environments = ref<TestEnvironment[]>([]);
const cases = ref<TestCase[]>([]);
const runs = ref<ExecutionRun[]>([]);
const selectedProjectId = ref<string | null>(null);
const selectedEnvironmentId = ref<string | null>(null);
const selectedCaseIds = ref<string[]>([]);
const selectedRun = ref<ExecutionRun | null>(null);
const stopOnFailure = ref(false);
const confirmVisible = ref(false);
const writeConfirmed = ref(false);
const retryRunId = ref<string | null>(null);
const loading = ref(false);
const submitting = ref(false);
const errorMessage = ref("");
let progressTimer: ReturnType<typeof setInterval> | null = null;

const projectOptions = computed(() => projects.value.map((item) => ({ label: item.name, value: item.id })));
const environmentOptions = computed(() => environments.value.map((item) => ({ label: `${item.name} · ${item.baseUrl}`, value: item.id })));
const approvedCases = computed(() => cases.value.filter((item) => item.status === "approved"));
const selectedEnvironment = computed(() => environments.value.find((item) => item.id === selectedEnvironmentId.value) ?? null);
const selectedCases = computed(() => approvedCases.value.filter((item) => selectedCaseIds.value.includes(item.id)));
const hasWriteRequest = computed(() => selectedCases.value.some((item) => ["POST", "PUT", "PATCH", "DELETE"].includes(item.api_method)));
const confirmationHasWrite = computed(() => retryRunId.value === null ? hasWriteRequest.value : selectedRun.value?.steps.some((item) => ["POST", "PUT", "PATCH", "DELETE"].includes(item.method ?? "")) ?? false);
const confirmedHost = computed(() => selectedEnvironment.value === null ? "" : new URL(selectedEnvironment.value.baseUrl).origin);

function statusType(status: string): "default" | "success" | "warning" | "error" | "info" {
  if (status === "passed" || status === "completed") return "success";
  if (status === "failed" || status === "error") return "error";
  if (status === "running" || status === "pending") return "warning";
  return "default";
}

function formatJson(value: unknown): string { return JSON.stringify(value, null, 2); }

async function loadProjectData(): Promise<void> {
  if (selectedProjectId.value === null) return;
  loading.value = true;
  errorMessage.value = "";
  try {
    const [environmentResponse, caseResponse, runResponse] = await Promise.all([listEnvironments(selectedProjectId.value), listTestCases(selectedProjectId.value), listExecutions(selectedProjectId.value)]);
    environments.value = environmentResponse.data;
    cases.value = caseResponse.data;
    runs.value = runResponse.data;
    selectedEnvironmentId.value = environments.value[0]?.id ?? null;
    selectedCaseIds.value = [];
    selectedRun.value = null;
  } catch (error: unknown) { errorMessage.value = error instanceof Error ? error.message : "执行数据加载失败"; } finally { loading.value = false; }
}

function openConfirm(): void {
  if (selectedEnvironment.value === null || selectedCaseIds.value.length === 0) { errorMessage.value = "请选择环境和至少一个已审核用例"; return; }
  writeConfirmed.value = false;
  retryRunId.value = null;
  confirmVisible.value = true;
}

async function submitExecution(): Promise<void> {
  if (selectedProjectId.value === null || selectedEnvironmentId.value === null) return;
  if (confirmationHasWrite.value && !writeConfirmed.value) { errorMessage.value = "请确认写请求的目标 Host"; return; }
  submitting.value = true;
  errorMessage.value = "";
  try {
    const response = retryRunId.value === null
      ? await startExecution(selectedProjectId.value, { environment_id: selectedEnvironmentId.value, test_case_ids: selectedCaseIds.value, stop_on_failure: stopOnFailure.value, write_confirmed: writeConfirmed.value, confirmed_host: confirmationHasWrite.value ? confirmedHost.value : undefined })
      : await retryExecution(selectedProjectId.value, retryRunId.value, { write_confirmed: writeConfirmed.value, confirmed_host: confirmationHasWrite.value ? confirmedHost.value : undefined });
    selectedRun.value = response.data;
    runs.value = [response.data, ...runs.value];
    confirmVisible.value = false;
    startProgressPolling(response.data.id);
  } catch (error: unknown) { errorMessage.value = error instanceof Error ? error.message : "创建执行任务失败"; } finally { submitting.value = false; }
}

async function loadRun(runId: string): Promise<void> {
  if (selectedProjectId.value === null) return;
  try { selectedRun.value = (await getExecution(selectedProjectId.value, runId)).data; } catch (error: unknown) { errorMessage.value = error instanceof Error ? error.message : "执行详情加载失败"; }
}

function startProgressPolling(runId: string): void {
  if (progressTimer !== null) clearInterval(progressTimer);
  progressTimer = setInterval(() => { void refreshProgress(runId); }, 1000);
  void refreshProgress(runId);
}

async function refreshProgress(runId: string): Promise<void> {
  await loadRun(runId);
  if (selectedRun.value !== null && !["pending", "running"].includes(selectedRun.value.status) && progressTimer !== null) { clearInterval(progressTimer); progressTimer = null; }
}

async function stopRun(): Promise<void> {
  if (selectedProjectId.value === null || selectedRun.value === null) return;
  try { selectedRun.value = (await stopExecution(selectedProjectId.value, selectedRun.value.id)).data; } catch (error: unknown) { errorMessage.value = error instanceof Error ? error.message : "停止任务失败"; }
}

async function retryRun(): Promise<void> {
  if (selectedProjectId.value === null || selectedRun.value === null) return;
  selectedEnvironmentId.value = selectedRun.value.environment_id;
  retryRunId.value = selectedRun.value.id;
  writeConfirmed.value = false;
  confirmVisible.value = true;
}

watch(selectedProjectId, () => { void loadProjectData(); });
onMounted(async () => { projects.value = (await listProjects()).data; });
onBeforeUnmount(() => { if (progressTimer !== null) clearInterval(progressTimer); });
</script>

<template>
  <section class="execution-page">
    <header class="page-header"><div><p class="page-kicker">确定性执行</p><h1>测试执行</h1><p>仅执行已审核用例；请求、响应和断言结果会以脱敏快照留存。</p></div></header>
    <NCard class="control-card" :bordered="false"><div class="controls"><label>项目<NSelect v-model:value="selectedProjectId" :options="projectOptions" placeholder="选择项目" /></label><label>测试环境<NSelect v-model:value="selectedEnvironmentId" :options="environmentOptions" placeholder="选择环境" /></label><label class="policy"><span>失败后停止</span><NSwitch v-model:value="stopOnFailure" /></label></div><p v-if="errorMessage" class="error-message">{{ errorMessage }}</p></NCard>
    <NSpin :show="loading"><NCard v-if="approvedCases.length" class="case-card" :bordered="false"><template #header>选择已审核用例</template><NCheckboxGroup v-model:value="selectedCaseIds" class="case-options"><NCheckbox v-for="item in approvedCases" :key="item.id" :value="item.id"><span class="method">{{ item.api_method }}</span><strong>{{ item.name }}</strong><small>{{ selectedEnvironment?.baseUrl ?? "" }}{{ item.api_path }}</small></NCheckbox></NCheckboxGroup><NButton type="primary" :disabled="selectedCaseIds.length === 0 || selectedEnvironment === null" @click="openConfirm"><template #icon><Play :size="16" /></template>执行所选用例</NButton></NCard><NEmpty v-else description="当前项目没有已审核用例" /></NSpin>
    <NCard v-if="runs.length" class="run-card" :bordered="false"><template #header>执行记录</template><div class="run-list"><button v-for="run in runs" :key="run.id" type="button" class="run-row" @click="loadRun(run.id)"><NTag size="small" :type="statusType(run.status)">{{ run.status }}</NTag><span>{{ run.passed_count }}/{{ run.total_count }} 通过</span><span>{{ run.failed_count }} 失败</span><time>{{ new Date(run.created_at).toLocaleString() }}</time></button></div></NCard>
    <NCard v-if="selectedRun !== null" class="detail-card" :bordered="false"><template #header>执行详情 · {{ selectedRun.status }}</template><template #header-extra><NButton v-if="['pending', 'running'].includes(selectedRun.status)" size="small" @click="stopRun"><template #icon><Square :size="14" /></template>停止任务</NButton><NButton v-else-if="selectedRun.failed_count > 0" size="small" @click="retryRun"><template #icon><RefreshCw :size="14" /></template>重试失败用例</NButton></template><NCollapse><NCollapseItem v-for="step in selectedRun.steps" :key="step.id" :title="`${step.position}. ${step.method ?? '待构造'} ${step.target_url ?? ''}`"><template #header-extra><NTag size="small" :type="statusType(step.status)">{{ step.status }}</NTag></template><p v-if="step.error_message" class="error-message">{{ step.error_code }}：{{ step.error_message }}</p><p v-if="step.skip_reason" class="muted">{{ step.skip_reason }}</p><div class="snapshot-grid"><div><h3>请求快照</h3><NCode :code="formatJson(step.request_snapshot)" language="json" word-wrap /></div><div><h3>响应快照</h3><NCode :code="formatJson(step.response_snapshot)" language="json" word-wrap /></div></div><NCode v-if="step.redacted_curl" :code="step.redacted_curl" language="bash" word-wrap /><div v-if="step.assertions.length" class="assertions"><p v-for="result in step.assertions" :key="result.id"><NTag size="small" :type="result.passed ? 'success' : 'error'">{{ result.passed ? '通过' : '失败' }}</NTag>{{ result.assertion_type }}：{{ result.message }}</p></div></NCollapseItem></NCollapse></NCard>
    <NModal v-model:show="confirmVisible" preset="dialog" title="确认执行"><p>环境：{{ selectedEnvironment?.name }}</p><p>目标 Host：<strong>{{ confirmedHost }}</strong></p><p>将{{ retryRunId === null ? `执行 ${selectedCases.length} 个用例` : '重新执行失败用例' }}，其中 {{ confirmationHasWrite ? '包含写请求' : '均为只读请求' }}。</p><NCheckbox v-if="confirmationHasWrite" v-model:checked="writeConfirmed">我已确认当前环境和完整目标 Host</NCheckbox><template #action><NButton @click="confirmVisible = false">取消</NButton><NButton type="primary" :loading="submitting" :disabled="confirmationHasWrite && !writeConfirmed" @click="submitExecution">确认并执行</NButton></template></NModal>
  </section>
</template>

<style scoped>
.execution-page { display: grid; gap: 20px; }.page-kicker { margin: 0 0 6px; color: var(--color-primary); font-size: 12px; font-weight: 650; }h1 { margin: 0; color: var(--color-text); font-size: 24px; }.page-header p:last-child,.muted { color: var(--color-text-secondary); font-size: 14px; }.control-card,.case-card,.run-card,.detail-card { border: 1px solid var(--color-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-card); }.controls { display: grid; grid-template-columns: minmax(220px, 1fr) minmax(260px, 1fr) auto; gap: 16px; }.controls label { display: grid; gap: 8px; color: var(--color-text-secondary); font-size: 12px; }.controls .policy { display: flex; align-items: end; gap: 10px; padding-bottom: 8px; }.case-options { display: grid; gap: 12px; margin-bottom: 18px; }.case-options :deep(.n-checkbox) { display: grid; grid-template-columns: 60px auto minmax(0,1fr); gap: 10px; align-items: center; }.method { color: var(--color-primary); font-family: var(--font-mono); font-size: 12px; }.case-options strong { color: var(--color-text); }.case-options small { overflow: hidden; color: var(--color-text-secondary); text-overflow: ellipsis; white-space: nowrap; }.run-list { display: grid; }.run-row { display: grid; grid-template-columns: auto 1fr 1fr auto; gap: 12px; align-items: center; padding: 12px 0; color: var(--color-text-secondary); text-align: left; cursor: pointer; background: none; border: 0; border-bottom: 1px solid var(--color-border); }.snapshot-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }.snapshot-grid h3 { margin: 14px 0 8px; color: var(--color-text-secondary); font-size: 12px; }.assertions p { display: flex; gap: 8px; align-items: center; color: var(--color-text-secondary); font-size: 13px; }.error-message { color: var(--color-danger); font-size: 13px; }@media (max-width: 800px) { .controls,.snapshot-grid { grid-template-columns: 1fr; }.run-row { grid-template-columns: auto 1fr; }.run-row time { display: none; } }
</style>

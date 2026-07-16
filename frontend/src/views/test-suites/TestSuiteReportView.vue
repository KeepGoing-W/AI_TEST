<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { ArrowDown, ArrowUp, FileSearch, Play, Plus, RefreshCw, Save, Trash2 } from "lucide-vue-next";
import { NButton, NCard, NCheckbox, NCode, NCollapse, NCollapseItem, NEmpty, NInput, NModal, NSelect, NSpin, NSwitch, NTag } from "naive-ui";

import { listProjects, listEnvironments, type Project, type TestEnvironment } from "@/api/projects";
import { listTestCases, type TestCase } from "@/api/testcases";
import { diagnoseReport, getReport, listReports, retryReport, type Diagnosis, type ExecutionReport, type ReportItem } from "@/api/reports";
import { createTestSuite, listTestSuites, runTestSuite, updateTestSuite, type TestSuite, type TestSuiteStep, type VariableExtractionSource } from "@/api/test-suites";

interface EditableStep extends TestSuiteStep { overrideText: string; extractionText: string; }

const projects = ref<Project[]>([]);
const environments = ref<TestEnvironment[]>([]);
const cases = ref<TestCase[]>([]);
const suites = ref<TestSuite[]>([]);
const reports = ref<ReportItem[]>([]);
const selectedProjectId = ref<string | null>(null);
const selectedSuiteId = ref<string | null>(null);
const selectedEnvironmentId = ref<string | null>(null);
const selectedReport = ref<ExecutionReport | null>(null);
const diagnoses = ref<Diagnosis[]>([]);
const suiteName = ref("");
const suiteDescription = ref("");
const stopOnFailure = ref(true);
const editingSteps = ref<EditableStep[]>([]);
const confirmVisible = ref(false);
const pendingAction = ref<"run" | "retry" | null>(null);
const writeConfirmed = ref(false);
const loading = ref(false);
const saving = ref(false);
const errorMessage = ref("");

const projectOptions = computed(() => projects.value.map((item) => ({ label: item.name, value: item.id })));
const environmentOptions = computed(() => environments.value.map((item) => ({ label: `${item.name} · ${item.baseUrl}`, value: item.id })));
const caseOptions = computed(() => cases.value.filter((item) => item.status === "approved").map((item) => ({ label: `${item.api_method} ${item.api_path} · ${item.name}`, value: item.id })));
const selectedEnvironment = computed(() => environments.value.find((item) => item.id === selectedEnvironmentId.value) ?? null);
const selectedSuite = computed(() => suites.value.find((item) => item.id === selectedSuiteId.value) ?? null);
const currentReportHasWrite = computed(() => selectedReport.value?.execution.steps.some((step) => ["POST", "PUT", "PATCH", "DELETE"].includes(step.method ?? "")) ?? false);
const suiteHasWrite = computed(() => editingSteps.value.some((step) => ["POST", "PUT", "PATCH", "DELETE"].includes(cases.value.find((item) => item.id === step.test_case_id)?.api_method ?? "")));
const confirmationHasWrite = computed(() => pendingAction.value === "retry" ? currentReportHasWrite.value : suiteHasWrite.value);
const confirmedHost = computed(() => selectedEnvironment.value === null ? "" : new URL(selectedEnvironment.value.baseUrl).origin);
const variableHint = computed(() => {
  const produced = new Set<string>();
  return editingSteps.value.map((step, index) => {
    const consumed = runtimeVariables(`${step.overrideText}\n${step.extractionText}`);
    const unavailable = [...consumed].filter((key) => !produced.has(key));
    extractionRules(step.extractionText).forEach((item) => produced.add(item.variable_key));
    return unavailable.length ? `第 ${index + 1} 步等待上游变量：${unavailable.join("、")}` : "变量依赖已满足";
  });
});

function runtimeVariables(value: string): Set<string> { return new Set([...value.matchAll(/\{\{runtime\.([A-Za-z_][A-Za-z0-9_]*)\}\}/g)].map((item) => item[1])); }
function safeParseObject(value: string): Record<string, unknown> { const parsed: unknown = JSON.parse(value || "{}"); if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("请求覆盖必须是 JSON 对象"); return parsed as Record<string, unknown>; }
function extractionRules(value: string): Array<{ variable_key: string; source: VariableExtractionSource; expression: string | null }> { const parsed: unknown = JSON.parse(value || "[]"); if (!Array.isArray(parsed)) throw new Error("变量提取必须是 JSON 数组"); return parsed.map((item): { variable_key: string; source: VariableExtractionSource; expression: string | null } => { if (item === null || typeof item !== "object") throw new Error("变量提取项无效"); const entry = item as Record<string, unknown>; if (typeof entry.variable_key !== "string" || !["json_path", "response_header", "text", "status_code"].includes(String(entry.source))) throw new Error("变量提取项缺少 variable_key 或 source"); return { variable_key: entry.variable_key, source: entry.source as VariableExtractionSource, expression: typeof entry.expression === "string" ? entry.expression : null }; }); }
function asEditable(step: TestSuiteStep): EditableStep { return { ...step, overrideText: JSON.stringify(step.request_override, null, 2), extractionText: JSON.stringify(step.variable_extractions.map(({ variable_key, source, expression }) => ({ variable_key, source, expression })), null, 2) }; }
function newStep(): EditableStep { return { test_case_id: caseOptions.value[0]?.value ?? "", request_override: {}, variable_extractions: [], overrideText: "{}", extractionText: "[]" }; }
function moveStep(index: number, offset: number): void { const target = index + offset; if (target < 0 || target >= editingSteps.value.length) return; const [step] = editingSteps.value.splice(index, 1); editingSteps.value.splice(target, 0, step); }

async function loadProjectData(): Promise<void> {
  if (selectedProjectId.value === null) return;
  loading.value = true; errorMessage.value = "";
  try {
    const [environmentResponse, caseResponse, suiteResponse, reportResponse] = await Promise.all([listEnvironments(selectedProjectId.value), listTestCases(selectedProjectId.value), listTestSuites(selectedProjectId.value), listReports(selectedProjectId.value)]);
    environments.value = environmentResponse.data; cases.value = caseResponse.data; suites.value = suiteResponse.data; reports.value = reportResponse.data; selectedEnvironmentId.value = environments.value[0]?.id ?? null; resetEditor(); selectedReport.value = null; diagnoses.value = [];
  } catch (error: unknown) { errorMessage.value = error instanceof Error ? error.message : "流程和报告数据加载失败"; } finally { loading.value = false; }
}

function resetEditor(): void { selectedSuiteId.value = null; suiteName.value = ""; suiteDescription.value = ""; stopOnFailure.value = true; editingSteps.value = []; }
function selectSuite(id: string): void { const suite = suites.value.find((item) => item.id === id); if (suite === undefined) return; selectedSuiteId.value = suite.id; suiteName.value = suite.name; suiteDescription.value = suite.description ?? ""; stopOnFailure.value = suite.stop_on_failure; editingSteps.value = suite.steps.map(asEditable); }

async function saveSuite(): Promise<void> {
  if (selectedProjectId.value === null || !suiteName.value.trim() || editingSteps.value.some((item) => !item.test_case_id)) { errorMessage.value = "请填写流程名称并为每个步骤选择已审核用例"; return; }
  saving.value = true; errorMessage.value = "";
  try {
    const steps = editingSteps.value.map((step) => ({ test_case_id: step.test_case_id, request_override: safeParseObject(step.overrideText), variable_extractions: extractionRules(step.extractionText) }));
    const payload = { name: suiteName.value.trim(), description: suiteDescription.value.trim() || null, stop_on_failure: stopOnFailure.value, steps };
    const response = selectedSuiteId.value === null ? await createTestSuite(selectedProjectId.value, payload) : await updateTestSuite(selectedProjectId.value, selectedSuiteId.value, payload);
    suites.value = selectedSuiteId.value === null ? [response.data, ...suites.value] : suites.value.map((item) => item.id === response.data.id ? response.data : item); selectSuite(response.data.id);
  } catch (error: unknown) { errorMessage.value = error instanceof Error ? error.message : "保存流程失败"; } finally { saving.value = false; }
}

function openRun(): void { if (selectedSuite.value === null || selectedEnvironment.value === null) { errorMessage.value = "请选择流程和测试环境"; return; } pendingAction.value = "run"; writeConfirmed.value = false; confirmVisible.value = true; }
function openRetry(): void { if (selectedReport.value === null) return; selectedEnvironmentId.value = selectedReport.value.execution.environment_id; pendingAction.value = "retry"; writeConfirmed.value = false; confirmVisible.value = true; }
async function submitAction(): Promise<void> {
  if (selectedProjectId.value === null || selectedEnvironmentId.value === null || pendingAction.value === null) return;
  if (confirmationHasWrite.value && !writeConfirmed.value) { errorMessage.value = "请确认当前目标 Host"; return; }
  saving.value = true;
  try {
    if (pendingAction.value === "run" && selectedSuite.value !== null) await runTestSuite(selectedProjectId.value, selectedSuite.value.id, { environment_id: selectedEnvironmentId.value, write_confirmed: writeConfirmed.value, confirmed_host: confirmationHasWrite.value ? confirmedHost.value : undefined });
    if (pendingAction.value === "retry" && selectedReport.value !== null) await retryReport(selectedProjectId.value, selectedReport.value.run_id, { write_confirmed: writeConfirmed.value, confirmed_host: confirmationHasWrite.value ? confirmedHost.value : undefined });
    reports.value = (await listReports(selectedProjectId.value)).data; confirmVisible.value = false;
  } catch (error: unknown) { errorMessage.value = error instanceof Error ? error.message : "创建执行任务失败"; } finally { saving.value = false; }
}
async function openReport(runId: string): Promise<void> { if (selectedProjectId.value === null) return; try { selectedReport.value = (await getReport(selectedProjectId.value, runId)).data; diagnoses.value = []; } catch (error: unknown) { errorMessage.value = error instanceof Error ? error.message : "报告加载失败"; } }
async function diagnose(): Promise<void> { if (selectedProjectId.value === null || selectedReport.value === null) return; try { diagnoses.value = (await diagnoseReport(selectedProjectId.value, selectedReport.value.run_id)).data; } catch (error: unknown) { errorMessage.value = error instanceof Error ? error.message : "失败诊断生成失败"; } }
function formatJson(value: unknown): string { return JSON.stringify(value, null, 2); }
function tagType(status: string): "default" | "success" | "error" | "warning" { return status === "completed" || status === "passed" ? "success" : status === "failed" || status === "error" ? "error" : "warning"; }

watch(selectedProjectId, () => { void loadProjectData(); });
onMounted(async () => { projects.value = (await listProjects()).data; });
</script>

<template>
  <section class="suite-page">
    <header class="page-header"><div><p class="page-kicker">顺序回归</p><h1>测试流程与报告</h1><p>按固定步骤建立变量链路；报告只展示脱敏证据与确定性结果。</p></div></header>
    <NCard class="control-card" :bordered="false"><label>项目<NSelect v-model:value="selectedProjectId" :options="projectOptions" placeholder="选择项目" /></label><label>执行环境<NSelect v-model:value="selectedEnvironmentId" :options="environmentOptions" placeholder="选择环境" /></label><p v-if="errorMessage" class="error-message">{{ errorMessage }}</p></NCard>
    <NSpin :show="loading"><div class="workspace-grid"><NCard class="suite-card" :bordered="false"><template #header>流程定义</template><template #header-extra><NButton quaternary size="small" @click="resetEditor">新建流程</NButton></template><div class="suite-list"><button v-for="suite in suites" :key="suite.id" class="suite-row" type="button" @click="selectSuite(suite.id)"><strong>{{ suite.name }}</strong><span>{{ suite.steps.length }} 步 · {{ suite.stop_on_failure ? "失败停止" : "失败继续" }}</span></button></div><NEmpty v-if="!suites.length" description="尚未创建测试流程" /></NCard><NCard class="editor-card" :bordered="false"><template #header>{{ selectedSuiteId === null ? "新建流程" : "编辑流程" }}</template><div class="editor-top"><label>流程名称<NInput v-model:value="suiteName" placeholder="例如：登录到删除回归" /></label><label>失败停止<NCheckbox v-model:checked="stopOnFailure">前置步骤失败时跳过剩余步骤</NCheckbox></label></div><label>说明<NInput v-model:value="suiteDescription" type="textarea" placeholder="说明该流程验证的关联链路" /></label><div class="step-list"><article v-for="(step, index) in editingSteps" :key="`${index}-${step.test_case_id}`" class="flow-step"><div class="step-index">{{ String(index + 1).padStart(2, "0") }}</div><div class="step-main"><NSelect v-model:value="step.test_case_id" :options="caseOptions" placeholder="选择已审核用例" /><small :class="{ 'hint-warning': variableHint[index]?.includes('等待') }">{{ variableHint[index] }}</small><details><summary>请求覆盖（JSON）</summary><NInput v-model:value="step.overrideText" type="textarea" :autosize="{ minRows: 2, maxRows: 8 }" /></details><details><summary>变量提取（JSON 数组）</summary><NInput v-model:value="step.extractionText" type="textarea" :autosize="{ minRows: 2, maxRows: 8 }" placeholder='[{"variable_key":"token","source":"json_path","expression":"$.data.token"}]' /></details></div><div class="step-actions"><NButton size="small" quaternary :disabled="index === 0" @click="moveStep(index, -1)"><ArrowUp :size="15" /></NButton><NButton size="small" quaternary :disabled="index === editingSteps.length - 1" @click="moveStep(index, 1)"><ArrowDown :size="15" /></NButton><NButton size="small" quaternary @click="editingSteps.splice(index, 1)"><Trash2 :size="15" /></NButton></div></article></div><div class="editor-actions"><NButton @click="editingSteps.push(newStep())"><template #icon><Plus :size="16" /></template>添加步骤</NButton><NButton type="primary" :loading="saving" @click="saveSuite"><template #icon><Save :size="16" /></template>保存流程</NButton><NButton v-if="selectedSuite !== null" type="primary" secondary @click="openRun"><template #icon><Play :size="16" /></template>执行流程</NButton></div></NCard></div></NSpin>
    <NCard class="report-card" :bordered="false"><template #header>执行报告</template><div class="report-list"><button v-for="item in reports" :key="item.run_id" type="button" class="report-row" @click="openReport(item.run_id)"><NTag size="small" :type="tagType(item.status)">{{ item.status }}</NTag><strong>{{ Math.round(item.pass_rate * 100) }}% 通过</strong><span>{{ item.summary.passed }}/{{ item.summary.total }} 通过，{{ item.summary.failed }} 失败</span><time>{{ new Date(item.created_at).toLocaleString() }}</time></button></div><NEmpty v-if="!reports.length" description="暂无执行报告" /></NCard>
    <NCard v-if="selectedReport !== null" class="detail-card" :bordered="false"><template #header>报告详情 · {{ Math.round(selectedReport.pass_rate * 100) }}% 通过</template><template #header-extra><NButton v-if="selectedReport.summary.failed" size="small" @click="openRetry"><template #icon><RefreshCw :size="14" /></template>{{ selectedReport.test_suite_id ? "重试完整流程" : "重试失败用例" }}</NButton><NButton v-if="selectedReport.summary.failed" size="small" @click="diagnose"><template #icon><FileSearch :size="14" /></template>诊断失败</NButton></template><div class="stat-grid"><div><small>总计</small><strong>{{ selectedReport.summary.total }}</strong></div><div><small>通过</small><strong>{{ selectedReport.summary.passed }}</strong></div><div><small>失败</small><strong>{{ selectedReport.summary.failed }}</strong></div><div><small>跳过</small><strong>{{ selectedReport.summary.skipped }}</strong></div></div><div class="report-grid"><section><h2>分类统计</h2><p v-for="item in selectedReport.categories" :key="item.key">{{ item.label }}：{{ item.counter.passed }}/{{ item.counter.total }} 通过</p></section><section><h2>接口统计</h2><p v-for="item in selectedReport.apis" :key="item.key">{{ item.label }}：{{ item.counter.passed }}/{{ item.counter.total }} 通过</p></section><section><h2>失败原因</h2><p v-for="item in selectedReport.failure_reasons" :key="`${item.category}-${item.code}`">{{ item.category }} / {{ item.code }} · {{ item.count }}</p></section></div><NCollapse><NCollapseItem v-for="step in selectedReport.execution.steps" :key="step.id" :title="`${step.position}. ${step.method ?? '待构造'} ${step.target_url ?? ''}`"><template #header-extra><NTag size="small" :type="tagType(step.status)">{{ step.status }}</NTag></template><p v-if="step.error_message" class="error-message">{{ step.error_code }}：{{ step.error_message }}</p><p v-if="step.skip_reason" class="muted">{{ step.skip_reason }}</p><p v-if="Object.keys(step.extracted_variables).length" class="muted">已提取变量：{{ Object.keys(step.extracted_variables).join("、") }}</p><NCode v-if="step.redacted_curl" :code="step.redacted_curl" language="bash" word-wrap /><div class="snapshot-grid"><NCode :code="formatJson(step.request_snapshot)" language="json" word-wrap /><NCode :code="formatJson(step.response_snapshot)" language="json" word-wrap /></div><details class="traceability"><summary>可追溯证据</summary><NCode :code="formatJson(step.traceability_snapshot)" language="json" word-wrap /></details></NCollapseItem></NCollapse><div v-if="diagnoses.length" class="diagnoses"><h2>失败诊断（假设）</h2><article v-for="item in diagnoses" :key="item.id"><NTag size="small" type="warning">{{ item.failure_category }}</NTag><p v-for="hypothesis in item.hypotheses" :key="hypothesis.summary">{{ hypothesis.summary }}（置信度 {{ hypothesis.confidence }}）</p><small>{{ item.note }}</small></article></div></NCard>
    <NModal v-model:show="confirmVisible" preset="dialog" title="确认执行"><p>环境：{{ selectedEnvironment?.name }}</p><p>目标 Host：<strong>{{ confirmedHost }}</strong></p><p>{{ pendingAction === "retry" && selectedReport?.test_suite_id ? "将从流程第一步重新执行，以恢复下游变量。" : "将按顺序执行已审核流程步骤。" }}</p><NCheckbox v-if="confirmationHasWrite" v-model:checked="writeConfirmed">我已确认当前环境和完整目标 Host</NCheckbox><template #action><NButton @click="confirmVisible = false">取消</NButton><NButton type="primary" :loading="saving" :disabled="confirmationHasWrite && !writeConfirmed" @click="submitAction">确认执行</NButton></template></NModal>
  </section>
</template>

<style scoped>
.suite-page { display: grid; gap: 20px; }.page-kicker { margin: 0 0 6px; color: var(--color-primary); font-size: 12px; font-weight: 650; }h1 { margin: 0; color: var(--color-text); font-size: 24px; }.page-header p:last-child,.muted { color: var(--color-text-secondary); font-size: 14px; }.control-card,.suite-card,.editor-card,.report-card,.detail-card { border: 1px solid var(--color-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-card); }.control-card { display: grid; grid-template-columns: minmax(220px, .7fr) minmax(260px, 1fr); gap: 16px; }.control-card label,.editor-card label,.editor-top label { display: grid; gap: 8px; color: var(--color-text-secondary); font-size: 12px; }.workspace-grid { display: grid; grid-template-columns: minmax(220px, .7fr) minmax(0, 1.8fr); gap: 18px; }.suite-list,.step-list,.report-list { display: grid; }.suite-row,.report-row { display: grid; gap: 5px; width: 100%; padding: 12px 4px; color: var(--color-text-secondary); text-align: left; cursor: pointer; background: transparent; border: 0; border-bottom: 1px solid var(--color-border); }.suite-row:hover,.report-row:hover { color: var(--color-primary); }.suite-row strong { color: var(--color-text); }.suite-row span,.suite-row small { font-size: 12px; }.editor-card { display: grid; gap: 16px; }.editor-top { display: grid; grid-template-columns: minmax(200px, 1fr) auto; gap: 16px; }.flow-step { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; gap: 12px; padding: 14px 0; border-bottom: 1px solid var(--color-border); }.step-index { color: var(--color-primary); font: 600 12px var(--font-mono); }.step-main { display: grid; gap: 9px; }.step-main small { color: var(--color-text-muted); }.step-main .hint-warning { color: var(--color-warning); }.step-main details { color: var(--color-text-secondary); font-size: 12px; }.step-main summary { margin: 4px 0; cursor: pointer; }.step-actions { display: flex; gap: 4px; align-items: start; }.editor-actions { display: flex; flex-wrap: wrap; gap: 10px; }.report-row { grid-template-columns: auto auto 1fr auto; align-items: center; gap: 12px; }.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 18px; }.stat-grid div { padding: 12px; background: var(--color-surface-muted); border-radius: var(--radius-md); }.stat-grid small { display: block; color: var(--color-text-muted); font-size: 12px; }.stat-grid strong { color: var(--color-text); font-size: 20px; }.report-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }.report-grid h2,.diagnoses h2 { margin: 0 0 9px; color: var(--color-text); font-size: 14px; }.report-grid p { margin: 6px 0; color: var(--color-text-secondary); font-size: 13px; }.snapshot-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 12px; }.traceability { margin-top: 12px; color: var(--color-text-secondary); font-size: 13px; }.traceability summary { cursor: pointer; }.diagnoses { margin-top: 18px; }.diagnoses article { padding: 12px 0; border-top: 1px solid var(--color-border); }.diagnoses p { color: var(--color-text-secondary); font-size: 13px; }.diagnoses small,.error-message { color: var(--color-danger); font-size: 12px; }@media (max-width: 900px) { .workspace-grid,.report-grid,.snapshot-grid { grid-template-columns: 1fr; }.control-card,.editor-top { grid-template-columns: 1fr; }.report-row { grid-template-columns: auto 1fr; }.report-row time { display: none; } }
</style>

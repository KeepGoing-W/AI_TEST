<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { Bot, Check, FileCode2, Play, ShieldCheck, Sparkles } from "lucide-vue-next";
import { NButton, NCard, NCheckbox, NCheckboxGroup, NEmpty, NSelect, NSpin, NTag } from "naive-ui";

import { reviewAgentRun, startTestcaseGeneration, streamAgentRunProgress, type AgentRun } from "@/api/agents";
import { listProjects, type Project } from "@/api/projects";
import { listApiDefinitions, listSourceScans, type ApiDefinition, type SourceScan } from "@/api/source-scans";
import { listTestCases, type TestCase } from "@/api/testcases";

interface RuleView {
  content: string;
  sourceType: "source_confirmed" | "inferred";
  confidence: number;
  references: SourceReferenceView[];
}

interface SourceReferenceView {
  sourceFilePath: string;
  startLine: number;
  endLine: number;
}

interface ScenarioView {
  name: string;
  category: string;
  confidence: number;
}

const projects = ref<Project[]>([]);
const scans = ref<SourceScan[]>([]);
const definitions = ref<ApiDefinition[]>([]);
const selectedProjectId = ref<string | null>(null);
const selectedScanId = ref<string | null>(null);
const selectedApiIds = ref<string[]>([]);
const currentRun = ref<AgentRun | null>(null);
const currentCases = ref<TestCase[]>([]);
const loading = ref(false);
const submitting = ref(false);
const reviewing = ref(false);
const errorMessage = ref("");

const projectOptions = computed(() => projects.value.map((project) => ({ label: project.name, value: project.id })));
const scanOptions = computed(() => scans.value.map((scan) => ({ label: `版本 ${scan.scan_version} · ${scan.status}`, value: scan.id })));
const apiOptions = computed(() => definitions.value.map((api) => ({ label: `${api.method} ${api.normalized_path}`, value: api.id })));
const graphNodes = ["validate_input", "load_api_definition", "retrieve_code_context", "analyze_business_rules", "generate_test_scenarios", "generate_structured_cases", "validate_generated_cases", "persist_drafts", "human_review_interrupt"];
const graphLabels: Record<string, string> = { validate_input: "输入校验", load_api_definition: "加载接口", retrieve_code_context: "检索源码", analyze_business_rules: "分析规则", generate_test_scenarios: "生成场景", generate_structured_cases: "生成用例", validate_generated_cases: "校验用例", persist_drafts: "保存草稿", human_review_interrupt: "人工审核" };
const rules = computed(() => readRules(currentRun.value?.state_summary));
const scenarios = computed(() => readScenarios(currentRun.value?.state_summary));
const activeNodeIndex = computed(() => currentRun.value === null ? -1 : graphNodes.indexOf(currentRun.value.current_node));

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readRules(summary: Record<string, unknown> | undefined): RuleView[] {
  const values = summary?.businessRules;
  if (!Array.isArray(values)) return [];
  return values.flatMap((value) => {
    if (!isRecord(value) || typeof value.content !== "string" || typeof value.source_type !== "string" || typeof value.confidence !== "number") return [];
    const rawReferences = Array.isArray(value.evidence) ? value.evidence : [];
    const references = rawReferences.flatMap((reference): SourceReferenceView[] => {
      if (!isRecord(reference) || typeof reference.source_file_path !== "string" || typeof reference.start_line !== "number" || typeof reference.end_line !== "number") return [];
      return [{ sourceFilePath: reference.source_file_path, startLine: reference.start_line, endLine: reference.end_line }];
    });
    const sourceType = value.source_type === "source_confirmed" ? "source_confirmed" : "inferred";
    return [{ content: value.content, sourceType, confidence: value.confidence, references }];
  });
}

function readScenarios(summary: Record<string, unknown> | undefined): ScenarioView[] {
  const values = summary?.scenarios;
  if (!Array.isArray(values)) return [];
  return values.flatMap((value): ScenarioView[] => {
    if (!isRecord(value) || typeof value.name !== "string" || typeof value.category !== "string" || typeof value.confidence !== "number") return [];
    return [{ name: value.name, category: value.category, confidence: value.confidence }];
  });
}

function tagType(status: string): "default" | "success" | "warning" | "error" | "info" {
  if (status === "approved") return "success";
  if (status === "pending_review" || status === "running") return "warning";
  if (status === "failed" || status === "disabled") return "error";
  return "info";
}

async function loadScans(): Promise<void> {
  if (selectedProjectId.value === null) return;
  scans.value = (await listSourceScans(selectedProjectId.value)).data;
  selectedScanId.value = scans.value.find((scan) => scan.status === "succeeded")?.id ?? null;
}

async function loadDefinitions(): Promise<void> {
  if (selectedProjectId.value === null || selectedScanId.value === null) return;
  definitions.value = (await listApiDefinitions(selectedProjectId.value, selectedScanId.value)).data;
  selectedApiIds.value = [];
}

async function startAnalysis(): Promise<void> {
  if (selectedProjectId.value === null || selectedScanId.value === null || selectedApiIds.value.length === 0) return;
  submitting.value = true;
  errorMessage.value = "";
  try {
    currentRun.value = (await startTestcaseGeneration(selectedProjectId.value, { source_scan_id: selectedScanId.value, api_definition_ids: selectedApiIds.value })).data;
    await loadRunCases();
    if (currentRun.value.status === "running") {
      void streamAgentRunProgress(selectedProjectId.value, currentRun.value.id, (event) => {
        if (currentRun.value !== null) currentRun.value = { ...currentRun.value, status: event.status, current_node: event.current_node, error_code: event.error_code };
      });
    }
  } catch (error: unknown) {
    errorMessage.value = error instanceof Error ? error.message : "Agent 分析失败";
  } finally {
    submitting.value = false;
  }
}

async function loadRunCases(): Promise<void> {
  if (selectedProjectId.value === null || currentRun.value === null) return;
  currentCases.value = (await listTestCases(selectedProjectId.value, currentRun.value.id)).data;
}

async function review(status: "approved" | "disabled"): Promise<void> {
  if (selectedProjectId.value === null || currentRun.value === null) return;
  reviewing.value = true;
  errorMessage.value = "";
  try {
    currentRun.value = (await reviewAgentRun(selectedProjectId.value, currentRun.value.id, status)).data;
    await loadRunCases();
  } catch (error: unknown) {
    errorMessage.value = error instanceof Error ? error.message : "审核失败";
  } finally {
    reviewing.value = false;
  }
}

watch(selectedProjectId, () => { scans.value = []; definitions.value = []; currentRun.value = null; currentCases.value = []; void loadScans(); });
watch(selectedScanId, () => { definitions.value = []; currentRun.value = null; currentCases.value = []; void loadDefinitions(); });
onMounted(async () => { loading.value = true; try { projects.value = (await listProjects()).data; } finally { loading.value = false; } });
</script>

<template>
  <section class="analysis-page">
    <header class="page-header"><div class="page-heading"><span class="page-rail"></span><div><p class="page-kicker">受控 LangGraph</p><h1>AI 分析与用例生成</h1><p>只依据已扫描接口和源码上下文生成可追溯草稿，审核前不会执行请求。</p></div></div></header>
    <NCard class="control-card" :bordered="false"><NSpin :show="loading"><div class="controls"><label>项目<NSelect v-model:value="selectedProjectId" :options="projectOptions" placeholder="选择项目" /></label><label>扫描版本<NSelect v-model:value="selectedScanId" :options="scanOptions" :disabled="selectedProjectId === null" placeholder="选择成功扫描版本" /></label></div><div class="api-picker"><span>选择接口</span><NCheckboxGroup v-model:value="selectedApiIds" class="api-options"><NCheckbox v-for="api in apiOptions" :key="api.value" :value="api.value">{{ api.label }}</NCheckbox></NCheckboxGroup></div><p v-if="errorMessage" class="error-message">{{ errorMessage }}</p><NButton type="primary" :disabled="selectedApiIds.length === 0" :loading="submitting" @click="startAnalysis"><template #icon><Play :size="16" /></template>开始分析并生成草稿</NButton></NSpin></NCard>
    <NEmpty v-if="currentRun === null" description="选择已扫描接口后即可启动 Agent 分析"><template #icon><Bot :size="40" /></template></NEmpty>
    <template v-else><div class="run-summary"><div><span>运行状态</span><NTag :type="tagType(currentRun.status)">{{ currentRun.status }}</NTag></div><div><span>Prompt</span><code>{{ currentRun.prompt_version }}</code></div><div><span>草稿用例</span><strong>{{ currentCases.length }}</strong></div></div><div class="analysis-grid"><NCard class="graph-card" :bordered="false" title="Agent 节点轨道"><ol class="node-track"><li v-for="(node, index) in graphNodes" :key="node" :class="{ active: index === activeNodeIndex, completed: index < activeNodeIndex || currentRun.status === 'pending_review' || currentRun.status === 'approved' || currentRun.status === 'disabled' }"><span class="node-dot"><Check v-if="index < activeNodeIndex || currentRun.status !== 'running'" :size="13" /><span v-else>{{ index + 1 }}</span></span><span>{{ graphLabels[node] }}</span></li></ol></NCard><div class="result-stack"><NCard class="rules-card" :bordered="false"><template #header><div class="card-title"><Sparkles :size="17" />业务规则 <NTag size="small">{{ rules.length }}</NTag></div></template><div v-if="rules.length" class="rule-list"><article v-for="(rule, index) in rules" :key="`${rule.content}-${index}`" class="rule-item"><div><NTag size="small" :type="rule.sourceType === 'source_confirmed' ? 'success' : 'warning'">{{ rule.sourceType === 'source_confirmed' ? '源码确认' : 'AI 推断' }}</NTag><span class="confidence">置信度 {{ Math.round(rule.confidence * 100) }}%</span></div><p>{{ rule.content }}</p><small v-for="reference in rule.references" :key="`${reference.sourceFilePath}-${reference.startLine}`"><FileCode2 :size="13" />{{ reference.sourceFilePath }}:{{ reference.startLine }}-{{ reference.endLine }}</small></article></div><NEmpty v-else size="small" description="尚无规则结果" /></NCard><NCard :bordered="false" class="scenario-card"><template #header><div class="card-title"><ShieldCheck :size="17" />测试场景 <NTag size="small">{{ scenarios.length }}</NTag></div></template><div class="scenario-list"><span v-for="scenario in scenarios" :key="scenario.name"><NTag size="small" type="info">{{ scenario.category }}</NTag>{{ scenario.name }} <em>{{ Math.round(scenario.confidence * 100) }}%</em></span></div></NCard></div></div><NCard class="review-card" :bordered="false"><div><h2>人工审核</h2><p>所有草稿当前为 {{ currentRun.status === 'pending_review' ? '待审核' : '已处理' }}；本阶段的审核操作不会执行测试请求。</p></div><div class="review-actions"><RouterLink :to="{ name: 'testcases' }"><NButton secondary>编辑用例与断言</NButton></RouterLink><NButton v-if="currentRun.status === 'pending_review'" type="primary" :loading="reviewing" @click="review('approved')">批量审核通过</NButton><NButton v-if="currentRun.status === 'pending_review'" :loading="reviewing" @click="review('disabled')">批量禁用</NButton></div></NCard></template>
  </section>
</template>

<style scoped>
.analysis-page { display: grid; gap: 20px; }.page-header,.review-card,.run-summary,.controls { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }.page-heading { display: flex; gap: 16px; }.page-rail { width: 3px; min-height: 74px; background: var(--color-primary); border-radius: var(--radius-sm); }.page-kicker { margin: 0 0 6px; color: var(--color-primary); font-size: 12px; font-weight: 650; }h1,h2 { margin: 0; color: var(--color-text); }h1 { font-size: 24px; }.page-heading p:last-child,.review-card p { margin: 8px 0 0; color: var(--color-text-secondary); font-size: 14px; }.control-card,.graph-card,.rules-card,.scenario-card,.review-card { border: 1px solid var(--color-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-card); }.controls { justify-content: flex-start; }.controls label { display: grid; min-width: 260px; gap: 8px; color: var(--color-text-secondary); font-size: 12px; }.api-picker { display: grid; gap: 10px; margin: 18px 0; color: var(--color-text-secondary); font-size: 13px; }.api-options { display: flex; flex-wrap: wrap; gap: 12px 24px; }.error-message { color: var(--color-danger); font-size: 13px; }.run-summary { align-items: center; padding: 14px 18px; background: var(--color-surface-muted); border-radius: var(--radius-md); }.run-summary div { display: flex; gap: 10px; align-items: center; color: var(--color-text-secondary); font-size: 13px; }.run-summary code { color: var(--color-primary); }.analysis-grid { display: grid; grid-template-columns: minmax(220px,.65fr) minmax(0,1.8fr); gap: 18px; }.node-track { display: grid; gap: 0; margin: 0; padding: 4px 0; list-style: none; }.node-track li { position: relative; display: flex; gap: 12px; align-items: center; min-height: 42px; color: var(--color-text-muted); font-size: 13px; }.node-track li:not(:last-child)::before { position: absolute; top: 28px; left: 10px; width: 1px; height: 28px; content: ""; background: var(--color-border); }.node-track .active { color: var(--color-primary); font-weight: 650; }.node-track .completed { color: var(--color-text-secondary); }.node-dot { z-index: 1; display: grid; width: 21px; height: 21px; color: var(--color-text-muted); font-size: 11px; place-items: center; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 50%; }.active .node-dot,.completed .node-dot { color: var(--color-primary); background: var(--color-primary-softer); border-color: var(--color-primary); }.result-stack { display: grid; gap: 18px; }.card-title { display: flex; gap: 8px; align-items: center; }.rule-list { display: grid; gap: 12px; }.rule-item { padding: 13px; background: var(--color-surface-muted); border: 1px solid var(--color-border); border-radius: var(--radius-sm); }.rule-item div,.rule-item small { display: flex; gap: 7px; align-items: center; }.rule-item p { margin: 9px 0; color: var(--color-text); font-size: 14px; }.rule-item small { color: var(--color-text-muted); font-family: var(--font-mono); font-size: 11px; }.confidence { color: var(--color-text-muted); font-size: 12px; }.scenario-list { display: grid; gap: 10px; }.scenario-list span { display: flex; gap: 8px; align-items: center; color: var(--color-text-secondary); font-size: 13px; }.scenario-list em { margin-left: auto; color: var(--color-text-muted); font-size: 12px; font-style: normal; }.review-card { align-items: center; }.review-card h2 { font-size: 16px; }.review-actions { display: flex; flex-wrap: wrap; gap: 10px; }.review-actions a { text-decoration: none; }@media (max-width: 900px) { .analysis-grid { grid-template-columns: 1fr; }.controls,.run-summary,.review-card { flex-direction: column; }.controls label { min-width: 0; width: 100%; } }
</style>

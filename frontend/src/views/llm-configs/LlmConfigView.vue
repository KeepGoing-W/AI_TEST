<script setup lang="ts">
import { onMounted, ref } from "vue";
import { BrainCircuit, Pencil, Plus, Radio, ShieldCheck } from "lucide-vue-next";
import { NButton, NCard, NCheckbox, NForm, NFormItem, NInput, NInputNumber, NModal, NSpin, NTag } from "naive-ui";

import { ApiRequestError } from "@/api/client";
import { createLlmConfig, listLlmConfigs, testLlmConfig, updateLlmConfig, type LlmConfig, type LlmConfigPayload } from "@/api/llm-configs";

const configs = ref<LlmConfig[]>([]);
const loading = ref(false);
const saving = ref(false);
const testingId = ref<string | null>(null);
const showForm = ref(false);
const editingId = ref<string | null>(null);
const message = ref("");
const errorMessage = ref("");

const name = ref("");
const provider = ref("openai");
const baseUrl = ref("https://api.openai.com/v1");
const model = ref("");
const apiKey = ref("");
const contextWindow = ref(128000);
const temperature = ref(0.2);
const maxOutputTokens = ref(4096);
const isDefault = ref(false);
const enabled = ref(true);

function errorText(error: unknown): string {
  return error instanceof ApiRequestError ? error.message : "操作失败，请稍后重试";
}

function resetForm(): void {
  name.value = "";
  provider.value = "openai";
  baseUrl.value = "https://api.openai.com/v1";
  model.value = "";
  apiKey.value = "";
  contextWindow.value = 128000;
  temperature.value = 0.2;
  maxOutputTokens.value = 4096;
  isDefault.value = false;
  enabled.value = true;
}

function openCreate(): void {
  editingId.value = null;
  resetForm();
  errorMessage.value = "";
  showForm.value = true;
}

function openEdit(config: LlmConfig): void {
  editingId.value = config.id;
  name.value = config.name;
  provider.value = config.provider;
  baseUrl.value = config.baseUrl;
  model.value = config.model;
  apiKey.value = "";
  contextWindow.value = config.contextWindow;
  temperature.value = config.temperature;
  maxOutputTokens.value = config.maxOutputTokens;
  isDefault.value = config.isDefault;
  enabled.value = config.enabled;
  errorMessage.value = "";
  showForm.value = true;
}

async function load(): Promise<void> {
  loading.value = true;
  errorMessage.value = "";
  try {
    configs.value = (await listLlmConfigs()).data;
  } catch (error: unknown) {
    errorMessage.value = errorText(error);
  } finally {
    loading.value = false;
  }
}

async function submit(): Promise<void> {
  saving.value = true;
  errorMessage.value = "";
  try {
    const payload: LlmConfigPayload = {
      name: name.value.trim(),
      provider: provider.value.trim(),
      base_url: baseUrl.value.trim(),
      model: model.value.trim(),
      context_window: contextWindow.value,
      temperature: temperature.value,
      max_output_tokens: maxOutputTokens.value,
      is_default: isDefault.value,
      enabled: enabled.value
    };
    if (editingId.value) {
      await updateLlmConfig(editingId.value, { ...payload, ...(apiKey.value ? { api_key: apiKey.value } : {}) });
      message.value = "LLM 配置已更新";
    } else {
      await createLlmConfig({ ...payload, api_key: apiKey.value });
      message.value = "LLM 配置已创建";
    }
    showForm.value = false;
    resetForm();
    await load();
  } catch (error: unknown) {
    errorMessage.value = errorText(error);
  } finally {
    saving.value = false;
  }
}

async function testConnection(id: string): Promise<void> {
  testingId.value = id;
  message.value = "";
  errorMessage.value = "";
  try {
    message.value = (await testLlmConfig(id)).data.success ? "连接测试成功" : "连接测试失败，请检查地址、模型和 API Key";
  } catch (error: unknown) {
    errorMessage.value = errorText(error);
  } finally {
    testingId.value = null;
  }
}

onMounted(() => {
  void load();
});
</script>

<template>
  <section class="llm-page">
    <header class="page-header">
      <div class="page-heading">
        <span class="page-rail" aria-hidden="true"></span>
        <div><p class="page-kicker">模型接入</p><h1>LLM 配置</h1><p>集中管理 Agent 使用的大模型连接、上下文和输出参数。</p></div>
      </div>
      <NButton type="primary" @click="openCreate"><template #icon><Plus :size="17" /></template>新建配置</NButton>
    </header>

    <div class="security-note"><ShieldCheck :size="17" /><span>API Key 加密保存，列表和接口响应均不会回显明文。</span></div>
    <p v-if="message" class="success-message">{{ message }}</p>
    <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>

    <NSpin :show="loading">
      <div v-if="configs.length" class="config-grid">
        <NCard v-for="config in configs" :key="config.id" class="config-card" :bordered="false">
          <template #header><div class="config-title"><span class="model-icon"><BrainCircuit :size="19" /></span><div><strong>{{ config.name }}</strong><small>{{ config.provider }}</small></div></div></template>
          <template #header-extra><NTag v-if="config.isDefault" size="small" type="info">默认</NTag></template>
          <dl><dt>模型</dt><dd>{{ config.model }}</dd><dt>服务地址</dt><dd>{{ config.baseUrl }}</dd><dt>上下文</dt><dd>{{ config.contextWindow.toLocaleString() }}</dd><dt>最大输出</dt><dd>{{ config.maxOutputTokens.toLocaleString() }}</dd></dl>
          <div class="config-footer"><div><NTag size="small" :type="config.enabled ? 'success' : 'default'">{{ config.enabled ? "已启用" : "已停用" }}</NTag><NTag size="small" :type="config.apiKeyConfigured ? 'success' : 'warning'">{{ config.apiKeyConfigured ? "Key 已配置" : "Key 未配置" }}</NTag></div><div class="card-actions"><NButton size="small" @click="openEdit(config)"><template #icon><Pencil :size="14" /></template>编辑</NButton><NButton size="small" :loading="testingId === config.id" @click="testConnection(config.id)"><template #icon><Radio :size="14" /></template>测试连接</NButton></div></div>
        </NCard>
      </div>
      <NCard v-else class="empty-card" :bordered="false"><BrainCircuit :size="36" /><strong>尚未配置大模型</strong><p>创建一个连接配置后，Agent 才能执行分析和用例生成。</p><NButton type="primary" @click="openCreate">新建 LLM 配置</NButton></NCard>
    </NSpin>

    <NModal v-model:show="showForm" preset="card" :title="editingId ? '编辑 LLM 配置' : '新建 LLM 配置'" style="width: min(680px, calc(100vw - 32px))">
      <NForm class="config-form" @submit.prevent="submit">
        <NFormItem label="配置名称"><NInput v-model:value="name" placeholder="例如：默认分析模型" /></NFormItem>
        <NFormItem label="Provider"><NInput v-model:value="provider" placeholder="openai" /></NFormItem>
        <NFormItem class="full-field" label="Base URL"><NInput v-model:value="baseUrl" /></NFormItem>
        <NFormItem label="模型"><NInput v-model:value="model" placeholder="模型名称" /></NFormItem>
        <NFormItem label="API Key"><NInput v-model:value="apiKey" type="password" show-password-on="click" :placeholder="editingId ? '留空则保持当前 Key 不变' : '请输入 API Key'" /></NFormItem>
        <NFormItem label="上下文窗口"><NInputNumber v-model:value="contextWindow" :min="1" /></NFormItem>
        <NFormItem label="最大输出 Token"><NInputNumber v-model:value="maxOutputTokens" :min="1" /></NFormItem>
        <NFormItem label="Temperature"><NInputNumber v-model:value="temperature" :min="0" :max="2" :step="0.1" /></NFormItem>
        <div class="checks"><NCheckbox v-model:checked="isDefault">设为默认配置</NCheckbox><NCheckbox v-model:checked="enabled">启用配置</NCheckbox></div>
        <p v-if="errorMessage" class="error-message full-field">{{ errorMessage }}</p>
        <div class="modal-actions full-field"><NButton @click="showForm = false">取消</NButton><NButton type="primary" attr-type="submit" :loading="saving">{{ editingId ? "保存修改" : "创建配置" }}</NButton></div>
      </NForm>
    </NModal>
  </section>
</template>

<style scoped>
.llm-page { display: grid; gap: 20px; }.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }.page-heading { display: flex; gap: 16px; }.page-rail { width: 3px; min-height: 72px; background: var(--color-primary); border-radius: var(--radius-sm); }.page-kicker { margin: 0 0 6px; color: var(--color-primary); font-size: 12px; font-weight: 650; }h1 { margin: 0; color: var(--color-text); font-size: 24px; }.page-heading p:last-child { margin: 8px 0 0; color: var(--color-text-secondary); font-size: 14px; }.security-note { display: flex; gap: 9px; align-items: center; padding: 12px 14px; color: var(--color-text-secondary); font-size: 13px; background: var(--color-primary-softer); border: 1px solid var(--color-primary-soft); border-radius: var(--radius-md); }.config-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; }.config-card,.empty-card { border: 1px solid var(--color-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-card); }.config-title { display: flex; gap: 11px; align-items: center; }.config-title > div { display: grid; gap: 3px; }.config-title small { color: var(--color-text-muted); font-size: 11px; text-transform: uppercase; }.model-icon { display: grid; width: 38px; height: 38px; color: var(--color-primary); place-items: center; background: var(--color-primary-softer); border-radius: var(--radius-md); }.config-card dl { display: grid; grid-template-columns: 80px minmax(0, 1fr); gap: 10px; margin: 0; font-size: 13px; }.config-card dt { color: var(--color-text-muted); }.config-card dd { min-width: 0; margin: 0; overflow: hidden; color: var(--color-text-secondary); text-overflow: ellipsis; white-space: nowrap; }.config-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 20px; padding-top: 14px; border-top: 1px solid var(--color-border); }.config-footer > div,.card-actions { display: flex; gap: 6px; }.empty-card { display: grid; justify-items: center; gap: 12px; padding: 64px 24px; color: var(--color-text-muted); text-align: center; }.empty-card strong { color: var(--color-text); font-size: 16px; }.empty-card p { margin: 0 0 6px; color: var(--color-text-secondary); }.config-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }.full-field { grid-column: 1 / -1; }.checks { display: flex; gap: 18px; align-items: center; }.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 8px; }.success-message,.error-message { margin: 0; font-size: 13px; }.success-message { color: var(--color-success); }.error-message { color: var(--color-danger); }@media (max-width: 700px) { .page-header { flex-direction: column; }.config-grid,.config-form { grid-template-columns: 1fr; }.full-field { grid-column: auto; }.config-footer { align-items: flex-start; flex-direction: column; } }
</style>

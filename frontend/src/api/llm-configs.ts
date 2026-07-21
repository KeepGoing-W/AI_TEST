import { apiClient } from "@/api/client";
import type { ApiResponse } from "@/types/domain";

export interface LlmConfig {
  id: string;
  name: string;
  provider: string;
  baseUrl: string;
  model: string;
  contextWindow: number;
  temperature: number;
  maxOutputTokens: number;
  isDefault: boolean;
  enabled: boolean;
  apiKeyConfigured: boolean;
}

export interface LlmConfigPayload {
  name: string;
  provider: string;
  base_url: string;
  model: string;
  context_window: number;
  temperature: number;
  max_output_tokens: number;
  is_default: boolean;
  enabled: boolean;
}

export interface CreateLlmConfigPayload extends LlmConfigPayload {
  api_key: string;
}

export interface UpdateLlmConfigPayload extends LlmConfigPayload {
  api_key?: string;
}

export function listLlmConfigs(): Promise<ApiResponse<LlmConfig[]>> {
  return apiClient<ApiResponse<LlmConfig[]>>("/llm-configs");
}

export function createLlmConfig(payload: CreateLlmConfigPayload): Promise<ApiResponse<LlmConfig>> {
  return apiClient<ApiResponse<LlmConfig>>("/llm-configs", { method: "POST", body: payload });
}

export function updateLlmConfig(id: string, payload: UpdateLlmConfigPayload): Promise<ApiResponse<LlmConfig>> {
  return apiClient<ApiResponse<LlmConfig>>(`/llm-configs/${id}`, { method: "PATCH", body: payload });
}

export function testLlmConfig(id: string): Promise<ApiResponse<{ success: boolean }>> {
  return apiClient<ApiResponse<{ success: boolean }>>(`/llm-configs/${id}/test`, { method: "POST" });
}

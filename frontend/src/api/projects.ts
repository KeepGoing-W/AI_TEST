import { apiClient } from "@/api/client";
import type { ApiResponse } from "@/types/domain";

export interface Project { id: string; name: string; description: string; }
export interface LlmConfig { id: string; name: string; provider: string; model: string; enabled: boolean; apiKeyConfigured: boolean; }

export function listProjects(): Promise<ApiResponse<Project[]>> { return apiClient<ApiResponse<Project[]>>("/projects"); }
export function createProject(payload: { name: string; description: string }): Promise<ApiResponse<Project>> { return apiClient<ApiResponse<Project>>("/projects", { method: "POST", body: payload }); }
export function listLlmConfigs(): Promise<ApiResponse<LlmConfig[]>> { return apiClient<ApiResponse<LlmConfig[]>>("/llm-configs"); }
export function testLlmConfig(id: string): Promise<ApiResponse<{ success: boolean }>> { return apiClient<ApiResponse<{ success: boolean }>>(`/llm-configs/${id}/test`, { method: "POST" }); }
export function setLocalSource(id: string, path: string): Promise<ApiResponse<unknown>> { return apiClient(`/projects/${id}/source/local`, { method: "PUT", body: { path } }); }
export function setOpenApiUrl(id: string, url: string): Promise<ApiResponse<unknown>> { return apiClient(`/projects/${id}/openapi/url`, { method: "PUT", body: { url } }); }
export function createEnvironment(projectId: string, body: { name: string; base_url: string; environment_type: "test" | "staging" | "production"; allow_write_requests: boolean }): Promise<ApiResponse<unknown>> { return apiClient(`/projects/${projectId}/environments`, { method: "POST", body }); }
export function setEnvironmentVariable(projectId: string, environmentId: string, body: { key: string; value: string; is_secret: boolean }): Promise<ApiResponse<unknown>> { return apiClient(`/projects/${projectId}/environments/${environmentId}/variables`, { method: "PUT", body }); }

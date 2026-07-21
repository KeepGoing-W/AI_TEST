import { apiClient } from "@/api/client";
import type { ApiResponse } from "@/types/domain";

export interface Project {
  id: string;
  name: string;
  description: string;
  language: string;
  framework: string;
}

export interface SourceArtifact {
  id: string;
  source_type: "local_path" | "zip_upload";
  original_name: string | null;
  local_path: string | null;
}

export interface OpenApiSource {
  source_type: "url" | "file" | null;
  configured: boolean;
  url: string | null;
}

export interface TestEnvironment {
  id: string;
  name: string;
  baseUrl: string;
  environmentType: "test" | "staging" | "production";
  allowWriteRequests: boolean;
  hostAllowlist: string[];
}

export interface EnvironmentPayload {
  name: string;
  base_url: string;
  environment_type: "test" | "staging" | "production";
  host_allowlist: string[];
  allow_write_requests: boolean;
}

export function listProjects(): Promise<ApiResponse<Project[]>> {
  return apiClient<ApiResponse<Project[]>>("/projects");
}

export function createProject(payload: { name: string; description: string }): Promise<ApiResponse<Project>> {
  return apiClient<ApiResponse<Project>>("/projects", { method: "POST", body: payload });
}

export function updateProject(id: string, payload: { name: string; description: string }): Promise<ApiResponse<Project>> {
  return apiClient<ApiResponse<Project>>(`/projects/${id}`, { method: "PATCH", body: payload });
}

export function getProjectSource(id: string): Promise<ApiResponse<SourceArtifact | null>> {
  return apiClient<ApiResponse<SourceArtifact | null>>(`/projects/${id}/source`);
}

export function getOpenApiSource(id: string): Promise<ApiResponse<OpenApiSource>> {
  return apiClient<ApiResponse<OpenApiSource>>(`/projects/${id}/openapi`);
}

export function setLocalSource(id: string, path: string): Promise<ApiResponse<SourceArtifact>> {
  return apiClient<ApiResponse<SourceArtifact>>(`/projects/${id}/source/local`, { method: "PUT", body: { path } });
}

export function setOpenApiUrl(id: string, url: string): Promise<ApiResponse<OpenApiSource>> {
  return apiClient<ApiResponse<OpenApiSource>>(`/projects/${id}/openapi/url`, { method: "PUT", body: { url } });
}

export function createEnvironment(projectId: string, body: EnvironmentPayload): Promise<ApiResponse<{ id: string; name: string }>> {
  return apiClient<ApiResponse<{ id: string; name: string }>>(`/projects/${projectId}/environments`, { method: "POST", body });
}

export function updateEnvironment(projectId: string, environmentId: string, body: EnvironmentPayload): Promise<ApiResponse<TestEnvironment>> {
  return apiClient<ApiResponse<TestEnvironment>>(`/projects/${projectId}/environments/${environmentId}`, { method: "PATCH", body });
}

export function listEnvironments(projectId: string): Promise<ApiResponse<TestEnvironment[]>> {
  return apiClient<ApiResponse<TestEnvironment[]>>(`/projects/${projectId}/environments`);
}

export function setEnvironmentVariable(projectId: string, environmentId: string, body: { key: string; value: string; is_secret: false }): Promise<ApiResponse<unknown>> {
  return apiClient(`/projects/${projectId}/environments/${environmentId}/variables`, { method: "PUT", body });
}

import { apiBaseUrl, apiClient, getAccessToken } from "@/api/client";
import type { ApiResponse } from "@/types/domain";

export interface SourceScan {
  id: string;
  background_task_id: string;
  scan_version: number;
  status: "pending" | "running" | "succeeded" | "failed" | "cancelled";
  summary: Record<string, unknown>;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface ApiDefinition {
  id: string;
  source_scan_id: string;
  method: string;
  normalized_path: string;
  operation_id: string | null;
  source_file_path: string | null;
  controller_qualified_name: string | null;
  method_qualified_name: string | null;
  request_definition: Record<string, unknown>;
  response_definition: Record<string, unknown>;
  security_definition: Record<string, unknown>;
  source_definition: Record<string, unknown>;
  openapi_definition: Record<string, unknown>;
  conflicts: unknown[];
  is_conflicted: boolean;
}

export interface ScanProgressEvent {
  scan_id: string;
  scan_version: number;
  task_status: string;
  scan_status: SourceScan["status"];
  progress: number;
  phase: string;
  error_code: string | null;
}

export function startSourceScan(projectId: string): Promise<ApiResponse<SourceScan>> {
  return apiClient<ApiResponse<SourceScan>>(`/projects/${projectId}/source-scans`, { method: "POST" });
}

export function listSourceScans(projectId: string): Promise<ApiResponse<SourceScan[]>> {
  return apiClient<ApiResponse<SourceScan[]>>(`/projects/${projectId}/source-scans`);
}

export function listApiDefinitions(projectId: string, scanId: string): Promise<ApiResponse<ApiDefinition[]>> {
  return apiClient<ApiResponse<ApiDefinition[]>>(`/projects/${projectId}/source-scans/${scanId}/api-definitions`);
}

export function getApiDefinition(projectId: string, scanId: string, apiDefinitionId: string): Promise<ApiResponse<ApiDefinition>> {
  return apiClient<ApiResponse<ApiDefinition>>(`/projects/${projectId}/source-scans/${scanId}/api-definitions/${apiDefinitionId}`);
}

function isScanProgressEvent(value: unknown): value is ScanProgressEvent {
  return typeof value === "object" && value !== null && "scan_id" in value && "progress" in value && "phase" in value;
}

export async function streamSourceScanProgress(
  projectId: string,
  scanId: string,
  onProgress: (event: ScanProgressEvent) => void
): Promise<void> {
  const accessToken = getAccessToken();
  const response = await fetch(`${apiBaseUrl}/projects/${projectId}/source-scans/${scanId}/events`, {
    headers: accessToken === null ? {} : { Authorization: `Bearer ${accessToken}` }
  });
  if (!response.ok || response.body === null) {
    throw new Error("扫描进度订阅失败");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) {
      return;
    }
    buffer += decoder.decode(chunk.value, { stream: true });
    const messages = buffer.split("\n\n");
    buffer = messages.pop() ?? "";
    for (const message of messages) {
      const data = message.split("\n").find((line) => line.startsWith("data: "));
      if (data === undefined) {
        continue;
      }
      const payload: unknown = JSON.parse(data.slice(6));
      if (isScanProgressEvent(payload)) {
        onProgress(payload);
      }
    }
  }
}

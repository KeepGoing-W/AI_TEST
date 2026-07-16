import { apiBaseUrl, apiClient, getAccessToken } from "@/api/client";
import type { ApiResponse } from "@/types/domain";

export type AgentRunStatus = "pending" | "running" | "pending_review" | "approved" | "disabled" | "failed";

export interface AgentRun {
  id: string;
  project_id: string;
  source_scan_id: string;
  api_definition_ids: string[];
  status: AgentRunStatus;
  current_node: string;
  prompt_version: string;
  model_snapshot: Record<string, unknown>;
  state_summary: Record<string, unknown>;
  error_category: string | null;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentRunProgressEvent {
  run_id: string;
  status: AgentRunStatus;
  current_node: string;
  error_code: string | null;
}

export interface TestcaseGenerationPayload {
  source_scan_id: string;
  api_definition_ids: string[];
  llm_config_id?: string;
}

export function startTestcaseGeneration(projectId: string, payload: TestcaseGenerationPayload): Promise<ApiResponse<AgentRun>> {
  return apiClient<ApiResponse<AgentRun>>(`/projects/${projectId}/agent-runs/testcase-generation`, {
    method: "POST",
    body: payload
  });
}

export function getAgentRun(projectId: string, runId: string): Promise<ApiResponse<AgentRun>> {
  return apiClient<ApiResponse<AgentRun>>(`/projects/${projectId}/agent-runs/${runId}`);
}

export function reviewAgentRun(projectId: string, runId: string, status: "approved" | "disabled"): Promise<ApiResponse<AgentRun>> {
  return apiClient<ApiResponse<AgentRun>>(`/projects/${projectId}/agent-runs/${runId}/approve`, {
    method: "POST",
    body: { status }
  });
}

function isAgentRunProgressEvent(value: unknown): value is AgentRunProgressEvent {
  return typeof value === "object" && value !== null && "run_id" in value && "status" in value && "current_node" in value;
}

export async function streamAgentRunProgress(
  projectId: string,
  runId: string,
  onProgress: (event: AgentRunProgressEvent) => void
): Promise<void> {
  const accessToken = getAccessToken();
  const response = await fetch(`${apiBaseUrl}/projects/${projectId}/agent-runs/${runId}/events`, {
    headers: accessToken === null ? {} : { Authorization: `Bearer ${accessToken}` }
  });
  if (!response.ok || response.body === null) {
    throw new Error("Agent 进度订阅失败");
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
      if (isAgentRunProgressEvent(payload)) {
        onProgress(payload);
      }
    }
  }
}

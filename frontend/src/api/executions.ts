import { apiClient } from "@/api/client";
import type { ApiResponse } from "@/types/domain";

export type ExecutionRunStatus = "pending" | "running" | "completed" | "failed" | "stopped";
export type ExecutionStepStatus = "pending" | "running" | "passed" | "failed" | "error" | "skipped" | "stopped";

export interface AssertionResult { id: string; position: number; assertion_type: string; path: string | null; expected: unknown; actual: unknown; passed: boolean; message: string; }
export interface ExecutionStep { id: string; test_case_id: string; position: number; status: ExecutionStepStatus; method: string | null; target_url: string | null; request_snapshot: Record<string, unknown>; response_snapshot: Record<string, unknown>; redacted_curl: string | null; duration_ms: number | null; error_category: string | null; error_code: string | null; error_message: string | null; skip_reason: string | null; assertions: AssertionResult[]; }
export interface ExecutionRun { id: string; project_id: string; environment_id: string; background_task_id: string; status: ExecutionRunStatus; stop_on_failure: boolean; total_count: number; passed_count: number; failed_count: number; skipped_count: number; error_code: string | null; error_message: string | null; started_at: string | null; completed_at: string | null; created_at: string; updated_at: string; steps: ExecutionStep[]; }

export interface StartExecutionPayload { environment_id: string; test_case_ids: string[]; stop_on_failure: boolean; write_confirmed: boolean; confirmed_host?: string; }

export function startExecution(projectId: string, payload: StartExecutionPayload): Promise<ApiResponse<ExecutionRun>> { return apiClient<ApiResponse<ExecutionRun>>(`/projects/${projectId}/executions`, { method: "POST", body: payload }); }
export function listExecutions(projectId: string): Promise<ApiResponse<ExecutionRun[]>> { return apiClient<ApiResponse<ExecutionRun[]>>(`/projects/${projectId}/executions`); }
export function getExecution(projectId: string, runId: string): Promise<ApiResponse<ExecutionRun>> { return apiClient<ApiResponse<ExecutionRun>>(`/projects/${projectId}/executions/${runId}`); }
export function stopExecution(projectId: string, runId: string): Promise<ApiResponse<ExecutionRun>> { return apiClient<ApiResponse<ExecutionRun>>(`/projects/${projectId}/executions/${runId}/stop`, { method: "POST" }); }
export function retryExecution(projectId: string, runId: string, payload: Pick<StartExecutionPayload, "write_confirmed" | "confirmed_host">): Promise<ApiResponse<ExecutionRun>> { return apiClient<ApiResponse<ExecutionRun>>(`/projects/${projectId}/executions/${runId}/retry`, { method: "POST", body: payload }); }

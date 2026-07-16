import { apiClient } from "@/api/client";
import type { ExecutionRun, StartExecutionPayload } from "@/api/executions";
import type { ApiResponse } from "@/types/domain";

export interface ReportCounter { total: number; passed: number; failed: number; skipped: number; }
export interface ReportDimension { key: string; label: string; counter: ReportCounter; }
export interface FailureReason { category: string; code: string; count: number; }
export interface ReportItem { run_id: string; test_suite_id: string | null; status: string; pass_rate: number; summary: ReportCounter; created_at: string; }
export interface ExecutionReport extends ReportItem { categories: ReportDimension[]; apis: ReportDimension[]; failure_reasons: FailureReason[]; execution: ExecutionRun; }
export interface Diagnosis { id: string; execution_run_id: string; execution_step_id: string | null; failure_category: string; evidence_summary: Record<string, unknown>; source_references: unknown[]; hypotheses: Array<{ summary: string; confidence: number; kind: string }>; note: string | null; created_at: string; }

export function listReports(projectId: string): Promise<ApiResponse<ReportItem[]>> { return apiClient<ApiResponse<ReportItem[]>>(`/projects/${projectId}/reports`); }
export function getReport(projectId: string, runId: string): Promise<ApiResponse<ExecutionReport>> { return apiClient<ApiResponse<ExecutionReport>>(`/projects/${projectId}/reports/${runId}`); }
export function retryReport(projectId: string, runId: string, payload: Pick<StartExecutionPayload, "write_confirmed" | "confirmed_host">): Promise<ApiResponse<ExecutionRun>> { return apiClient<ApiResponse<ExecutionRun>>(`/projects/${projectId}/reports/${runId}/retry`, { method: "POST", body: payload }); }
export function diagnoseReport(projectId: string, runId: string): Promise<ApiResponse<Diagnosis[]>> { return apiClient<ApiResponse<Diagnosis[]>>(`/projects/${projectId}/reports/${runId}/diagnoses`, { method: "POST" }); }

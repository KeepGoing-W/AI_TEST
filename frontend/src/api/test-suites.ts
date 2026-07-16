import { apiClient } from "@/api/client";
import type { ApiResponse } from "@/types/domain";
import type { ExecutionRun } from "@/api/executions";

export type VariableExtractionSource = "json_path" | "response_header" | "text" | "status_code";
export interface VariableExtraction { id?: string; variable_key: string; source: VariableExtractionSource; expression: string | null; }
export interface TestSuiteStep { id?: string; test_case_id: string; position?: number; request_override: Record<string, unknown>; variable_extractions: VariableExtraction[]; }
export interface TestSuite { id: string; project_id: string; name: string; description: string | null; stop_on_failure: boolean; created_at: string; updated_at: string; steps: TestSuiteStep[]; }
export interface TestSuitePayload { name: string; description: string | null; stop_on_failure: boolean; steps: TestSuiteStep[]; }
export interface SuiteRunPayload { environment_id: string; write_confirmed: boolean; confirmed_host?: string; }

export function listTestSuites(projectId: string): Promise<ApiResponse<TestSuite[]>> { return apiClient<ApiResponse<TestSuite[]>>(`/projects/${projectId}/test-suites`); }
export function createTestSuite(projectId: string, payload: TestSuitePayload): Promise<ApiResponse<TestSuite>> { return apiClient<ApiResponse<TestSuite>>(`/projects/${projectId}/test-suites`, { method: "POST", body: payload }); }
export function updateTestSuite(projectId: string, suiteId: string, payload: TestSuitePayload): Promise<ApiResponse<TestSuite>> { return apiClient<ApiResponse<TestSuite>>(`/projects/${projectId}/test-suites/${suiteId}`, { method: "PUT", body: payload }); }
export function runTestSuite(projectId: string, suiteId: string, payload: SuiteRunPayload): Promise<ApiResponse<ExecutionRun>> { return apiClient<ApiResponse<ExecutionRun>>(`/projects/${projectId}/test-suites/${suiteId}/runs`, { method: "POST", body: payload }); }

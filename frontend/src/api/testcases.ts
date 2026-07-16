import { apiClient } from "@/api/client";
import type { ApiResponse } from "@/types/domain";

export type TestCaseCategory = "functional" | "boundary" | "exception" | "permission";
export type TestCaseStatus = "draft" | "pending_review" | "approved" | "disabled";

export interface TestAssertion {
  id: string;
  position: number;
  assertion_type: string;
  config: Record<string, unknown>;
  description: string;
}

export interface TestCase {
  id: string;
  project_id: string;
  source_scan_id: string;
  api_definition_id: string;
  api_method: string;
  api_path: string;
  agent_run_id: string | null;
  name: string;
  description: string;
  category: TestCaseCategory;
  priority: string;
  status: TestCaseStatus;
  preconditions: string[];
  request_template: Record<string, unknown>;
  source_rule_ids: string[];
  source_symbol_ids: string[];
  confidence: number;
  is_inferred: boolean;
  assertions: TestAssertion[];
  created_at: string;
  updated_at: string;
}

export interface AssertionInput {
  assertion_type: "status_code_equals" | "business_code_equals" | "json_path_equals" | "json_path_exists" | "json_path_not_exists" | "json_path_type" | "body_contains" | "body_not_contains" | "number_range" | "response_time_less_than" | "status_code" | "business_code" | "text_contains";
  config: Record<string, unknown>;
  description: string;
}

export interface TestCaseUpdatePayload {
  name?: string;
  description?: string;
  priority?: "P0" | "P1" | "P2" | "P3";
  preconditions?: string[];
  request_template?: Record<string, unknown>;
  assertions?: AssertionInput[];
}

export function listTestCases(projectId: string, agentRunId?: string): Promise<ApiResponse<TestCase[]>> {
  const query = agentRunId === undefined ? "" : `?agent_run_id=${encodeURIComponent(agentRunId)}`;
  return apiClient<ApiResponse<TestCase[]>>(`/projects/${projectId}/testcases${query}`);
}

export function updateTestCase(
  projectId: string,
  caseId: string,
  payload: TestCaseUpdatePayload
): Promise<ApiResponse<TestCase>> {
  return apiClient<ApiResponse<TestCase>>(`/projects/${projectId}/testcases/${caseId}`, { method: "PATCH", body: payload });
}

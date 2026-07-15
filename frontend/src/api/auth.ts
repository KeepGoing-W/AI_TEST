import { apiClient } from "@/api/client";
import type { ApiResponse, LoginPayload, TokenPayload, UserProfile } from "@/types/domain";

export function login(payload: LoginPayload): Promise<ApiResponse<TokenPayload>> {
  return apiClient<ApiResponse<TokenPayload>>("/auth/login", { method: "POST", body: payload });
}

export function getCurrentUser(): Promise<ApiResponse<UserProfile>> {
  return apiClient<ApiResponse<UserProfile>>("/auth/me");
}

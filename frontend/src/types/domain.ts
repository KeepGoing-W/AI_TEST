export type UserRole = "admin" | "test_member";

export interface ApiResponse<T> {
  data: T;
  message: string;
  requestId: string;
}

export interface ApiErrorResponse {
  code: string;
  message: string;
  details: Record<string, unknown>;
  requestId: string;
}

export interface LoginPayload {
  username: string;
  password: string;
}

export interface TokenPayload {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
}

export interface UserProfile {
  id: string;
  username: string;
  display_name: string;
  role: UserRole;
  is_active: boolean;
}

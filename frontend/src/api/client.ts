import { ofetch } from "ofetch";

import type { ApiErrorResponse } from "@/types/domain";

const accessTokenKey = "ai-test-platform.access-token";
let redirectingToLogin = false;
export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export class ApiRequestError extends Error {
  readonly code: string;

  constructor(message: string, code = "REQUEST_FAILED") {
    super(message);
    this.code = code;
  }
}

function isApiErrorResponse(value: unknown): value is ApiErrorResponse {
  return typeof value === "object" && value !== null && "message" in value && "code" in value;
}

function redirectToLogin(): void {
  clearAccessToken();
  if (window.location.pathname === "/login" || redirectingToLogin) {
    return;
  }
  redirectingToLogin = true;
  const redirect = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  const query = new URLSearchParams({ redirect });
  window.location.replace(`/login?${query.toString()}`);
}

export const apiClient = ofetch.create({
  baseURL: apiBaseUrl,
  onRequest({ options }) {
    const accessToken = window.localStorage.getItem(accessTokenKey);
    if (accessToken === null) {
      return;
    }

    const headers = new Headers(options.headers);
    headers.set("Authorization", `Bearer ${accessToken}`);
    options.headers = headers;
  },
  onResponseError({ response }) {
    if (response.status === 401) {
      redirectToLogin();
    }
    const payload = response._data;
    if (isApiErrorResponse(payload)) {
      throw new ApiRequestError(payload.message, payload.code);
    }
    throw new ApiRequestError("请求失败，请稍后重试");
  }
});

export function saveAccessToken(accessToken: string): void {
  window.localStorage.setItem(accessTokenKey, accessToken);
}

export function getAccessToken(): string | null {
  return window.localStorage.getItem(accessTokenKey);
}

export function clearAccessToken(): void {
  window.localStorage.removeItem(accessTokenKey);
}

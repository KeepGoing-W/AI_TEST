import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { clearAccessToken, getAccessToken, saveAccessToken } from "@/api/client";
import { getCurrentUser, login } from "@/api/auth";
import type { LoginPayload, UserProfile } from "@/types/domain";

export const useAuthStore = defineStore("auth", () => {
  const accessToken = ref<string | null>(getAccessToken());
  const user = ref<UserProfile | null>(null);
  const isAuthenticated = computed(() => accessToken.value !== null);

  async function signIn(payload: LoginPayload): Promise<void> {
    const response = await login(payload);
    accessToken.value = response.data.access_token;
    saveAccessToken(response.data.access_token);
    await loadCurrentUser();
  }

  async function loadCurrentUser(): Promise<void> {
    const response = await getCurrentUser();
    user.value = response.data;
  }

  function signOut(): void {
    clearAccessToken();
    accessToken.value = null;
    user.value = null;
  }

  return { accessToken, user, isAuthenticated, signIn, loadCurrentUser, signOut };
});

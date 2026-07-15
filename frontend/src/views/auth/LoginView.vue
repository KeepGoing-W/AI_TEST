<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { LockKeyhole, UserRound } from "lucide-vue-next";
import { NButton, NCard, NForm, NFormItem, NInput, useMessage } from "naive-ui";

import { ApiRequestError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";

const router = useRouter();
const route = useRoute();
const message = useMessage();
const authStore = useAuthStore();
const isSubmitting = ref(false);
const form = reactive({ username: "", password: "" });

async function handleLogin(): Promise<void> {
  if (form.username.trim() === "" || form.password === "") {
    message.warning("请输入用户名和密码");
    return;
  }
  isSubmitting.value = true;
  try {
    await authStore.signIn({ username: form.username.trim(), password: form.password });
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/projects";
    await router.replace(redirect);
  } catch (error: unknown) {
    message.error(error instanceof ApiRequestError ? error.message : "登录失败，请稍后重试");
  } finally {
    isSubmitting.value = false;
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-intro" aria-label="平台说明">
      <div class="intro-brand"><span class="intro-mark"><LockKeyhole :size="20" aria-hidden="true" /></span><span>Test Agent</span></div>
      <div class="intro-copy">
        <p class="eyebrow">API QUALITY WORKSPACE</p>
        <h1>让接口测试<br />保持可追溯。</h1>
        <p>从源码规则到执行证据，测试资产始终保持在同一条受控轨道上。</p>
      </div>
      <ol class="access-track">
        <li class="access-track-item is-active"><span>01</span> 验证账号</li>
        <li class="access-track-item"><span>02</span> 进入项目</li>
        <li class="access-track-item"><span>03</span> 管理测试资产</li>
      </ol>
    </section>
    <section class="login-panel">
      <NCard class="login-card" :bordered="false">
        <div class="login-heading"><p class="eyebrow">平台登录</p><h2>欢迎回来</h2><p>使用管理员或已授权测试成员账号登录。</p></div>
        <NForm :model="form" @submit.prevent="handleLogin">
          <NFormItem label="用户名"><NInput v-model:value="form.username" placeholder="输入用户名" size="large"><template #prefix><UserRound :size="17" aria-hidden="true" /></template></NInput></NFormItem>
          <NFormItem label="密码"><NInput v-model:value="form.password" type="password" show-password-on="click" placeholder="输入密码" size="large"><template #prefix><LockKeyhole :size="17" aria-hidden="true" /></template></NInput></NFormItem>
          <NButton type="primary" size="large" block attr-type="submit" :loading="isSubmitting">登录平台</NButton>
        </NForm>
      </NCard>
    </section>
  </main>
</template>

<style scoped>
.login-page { display: grid; grid-template-columns: minmax(420px, 1.05fr) minmax(480px, 0.95fr); min-height: 100vh; background: var(--color-page); }
.login-intro { display: flex; flex-direction: column; padding: 48px 64px; color: var(--color-text); background: var(--color-surface); border-right: 1px solid var(--color-border); }
.intro-brand { display: flex; align-items: center; gap: 10px; font-size: 16px; font-weight: 650; }
.intro-mark { display: grid; width: 34px; height: 34px; color: var(--color-primary); place-items: center; background: var(--color-primary-softer); border-radius: var(--radius-sm); }
.intro-copy { max-width: 470px; margin: auto 0; }
.eyebrow { margin: 0 0 12px; color: var(--color-primary); font-size: 12px; font-weight: 650; letter-spacing: 0.08em; }
.intro-copy h1, .login-heading h2 { margin: 0; letter-spacing: -0.04em; }
.intro-copy h1 { font-size: clamp(42px, 5vw, 68px); line-height: 1.08; font-weight: 650; }
.intro-copy > p:last-child { max-width: 370px; margin: 24px 0 0; color: var(--color-text-secondary); line-height: 1.75; }
.access-track { display: grid; gap: 14px; padding: 0; margin: 0; list-style: none; }
.access-track-item { display: flex; align-items: center; gap: 12px; color: var(--color-text-muted); font-size: 13px; }
.access-track-item span { display: inline-grid; width: 26px; height: 26px; font-family: var(--font-mono); font-size: 11px; place-items: center; border: 1px solid var(--color-border); border-radius: 50%; }
.access-track-item.is-active { color: var(--color-primary); font-weight: 600; }
.access-track-item.is-active span { color: white; background: var(--color-primary); border-color: var(--color-primary); }
.login-panel { display: grid; padding: 32px; place-items: center; }
.login-card { width: min(100%, 420px); padding: 12px; border: 1px solid var(--color-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-card); }
.login-heading { margin-bottom: 30px; }
.login-heading h2 { font-size: 28px; font-weight: 650; }
.login-heading > p:last-child { margin: 10px 0 0; color: var(--color-text-secondary); font-size: 14px; }
@media (max-width: 900px) { .login-page { grid-template-columns: 1fr; } .login-intro { min-height: 260px; padding: 32px; } .intro-copy { margin: 42px 0 0; } .intro-copy h1 { font-size: 42px; } .access-track { display: none; } }
</style>

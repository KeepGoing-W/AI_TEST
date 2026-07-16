import { createRouter, createWebHistory } from "vue-router";

import AppShell from "@/layouts/AppShell.vue";
import LoginView from "@/views/auth/LoginView.vue";
import ProjectListView from "@/views/projects/ProjectListView.vue";
import ApiDefinitionView from "@/views/api-definitions/ApiDefinitionView.vue";
import AnalysisView from "@/views/analysis/AnalysisView.vue";
import TestCaseView from "@/views/testcases/TestCaseView.vue";
import ExecutionView from "@/views/executions/ExecutionView.vue";
import { useAuthStore } from "@/stores/auth";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", name: "login", component: LoginView, meta: { guestOnly: true } },
    {
      path: "/",
      component: AppShell,
      meta: { requiresAuth: true },
      children: [
        { path: "", redirect: { name: "projects" } },
        { path: "projects", name: "projects", component: ProjectListView },
        { path: "api-definitions", name: "api-definitions", component: ApiDefinitionView },
        { path: "analysis", name: "analysis", component: AnalysisView },
        { path: "testcases", name: "testcases", component: TestCaseView },
        { path: "executions", name: "executions", component: ExecutionView }
      ]
    }
  ]
});

router.beforeEach((to) => {
  const authStore = useAuthStore();
  if (to.meta.requiresAuth === true && !authStore.isAuthenticated) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.meta.guestOnly === true && authStore.isAuthenticated) {
    return { name: "projects" };
  }
  return true;
});

export default router;

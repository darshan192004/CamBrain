/**
 * Application router factory: the eight paths of design §3. `/login` is
 * public and renders bare; every other path nests inside the AppShell
 * layout (top bar, sidebar, status bar) — task 4.9. `/settings/*` requires
 * admin; content screens are placeholders until tasks 4.10–4.17 replace
 * them. Tests build their own instance so navigations never leak between
 * specs.
 * @module router
 */

import { createRouter, createWebHistory } from "vue-router";

import { authGuard } from "./auth/AuthGuard.js";
import { useAuthStore } from "./stores/auth.js";

/**
 * Create a router with the full route table and the auth guard installed.
 * @returns {import("vue-router").Router} a fresh router instance
 */
export function createAppRouter() {
  /** @type {import("vue-router").RouteRecordRaw[]} */
  const routes = [
    {
      path: "/login",
      name: "login",
      component: () => import("./auth/LoginForm.vue"),
      meta: { public: true, title: "Sign in" },
    },
    {
      path: "/",
      component: () => import("./layout/AppShell.vue"),
      children: [
        { path: "", redirect: { name: "cameras" } },
        {
          path: "cameras",
          name: "cameras",
          component: () => import("./camera/CameraGrid.vue"),
          meta: { title: "Cameras" },
        },
        {
          path: "cameras/:id",
          name: "camera-detail",
          component: () => import("./views/PlaceholderView.vue"),
          props: true,
          meta: { title: "Camera" },
        },
        {
          path: "events",
          name: "events",
          component: () => import("./views/PlaceholderView.vue"),
          meta: { title: "Events" },
        },
        {
          path: "events/:id",
          name: "event-detail",
          component: () => import("./views/PlaceholderView.vue"),
          props: true,
          meta: { title: "Event" },
        },
        {
          path: "settings/users",
          name: "users",
          component: () => import("./views/PlaceholderView.vue"),
          meta: { title: "Users", roles: ["admin"] },
        },
        {
          path: "settings/system",
          name: "system",
          component: () => import("./views/PlaceholderView.vue"),
          meta: { title: "System", roles: ["admin"] },
        },
      ],
    },
    { path: "/:pathMatch(.*)*", redirect: { name: "cameras" } },
  ];

  const router = createRouter({
    history: createWebHistory(),
    routes,
  });
  router.beforeEach((to) => authGuard(to, useAuthStore()));
  return router;
}

/** The app's router instance (main.js). */
export const router = createAppRouter();

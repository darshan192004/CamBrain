<script setup>
// Design §7: single centred card, no marketing chrome, and error copy that
// never reveals which of the two fields was wrong — the status decides the
// message, not the payload.
import { ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError } from "../api/client.js";
import { useAuthStore } from "../stores/auth.js";

const router = useRouter();
const auth = useAuthStore();

const username = ref("");
const password = ref("");
const error = ref("");
const busy = ref(false);

const COPY = {
  401: "Check your username and password.",
  423: "Too many failed attempts. Try again in 5 minutes.",
  429: "Too many attempts. Please wait a moment and try again.",
};

/**
 * Submit the credentials: on success store the session and route to the
 * grid; on failure pick fixed copy by HTTP status (never by field).
 * @returns {Promise<void>} settles when navigation or error state is done
 */
async function submit() {
  busy.value = true;
  error.value = "";
  try {
    await auth.login(username.value, password.value);
    await router.push({ name: "cameras" });
  } catch (err) {
    const status = err instanceof ApiError ? err.status : 0;
    error.value = COPY[status] ?? "Something went wrong. Please try again.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="flex min-h-screen items-center justify-center bg-bg-base p-4">
    <form
      class="w-full max-w-sm rounded-[var(--radius-card)] border border-border bg-bg-surface p-8"
      novalidate
      @submit.prevent="submit"
    >
      <h1 class="text-lg font-semibold text-text-primary">CamBrain</h1>
      <p class="mt-1 text-xs text-text-secondary">Sign in to the dashboard</p>

      <label
        class="mt-6 block text-xs font-medium text-text-secondary"
        for="username"
      >
        Username
      </label>
      <input
        id="username"
        v-model="username"
        class="mt-1 w-full rounded-[var(--radius-control)] border border-border bg-bg-raised px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
        name="username"
        autocomplete="username"
        required
      />

      <label
        class="mt-4 block text-xs font-medium text-text-secondary"
        for="password"
      >
        Password
      </label>
      <input
        id="password"
        v-model="password"
        class="mt-1 w-full rounded-[var(--radius-control)] border border-border bg-bg-raised px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
        name="password"
        type="password"
        autocomplete="current-password"
        required
      />

      <p
        v-if="error"
        class="mt-4 text-sm text-alert-critical"
        role="alert"
        data-testid="login-error"
      >
        {{ error }}
      </p>

      <button
        class="mt-6 w-full rounded-[var(--radius-control)] bg-accent px-4 py-2 text-sm font-medium text-white transition-colors duration-[var(--dur-base)] hover:bg-accent-hover disabled:opacity-50"
        type="submit"
        :disabled="busy"
      >
        {{ busy ? "Signing in…" : "Sign in" }}
      </button>
    </form>
  </main>
</template>

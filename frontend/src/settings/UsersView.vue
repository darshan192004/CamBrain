<script setup>
// Admin user management (design §3 /settings/users): list, create, and
// delete, with the API's last-admin 409 surfaced inline — the protection
// exists so an operator never locks themselves out of their own box.
// Deletion is a two-step inline confirm, not window.confirm, so the flow
// is testable and styled like the rest of the dashboard.
import { onMounted, ref } from "vue";

import { del, get, post } from "../api/client.js";

const users = ref([]);
const error = ref("");
const username = ref("");
const password = ref("");
const role = ref("viewer");
const pendingDelete = ref(null);

/**
 * Load every user in the site (GET /users — a plain list, not paginated).
 * @returns {Promise<void>} resolves when the list is in place
 */
async function load() {
  users.value = await get("/users");
}

/**
 * Create a user from the form; failures land in the inline error slot.
 * @returns {Promise<void>} resolves after the attempt
 */
async function create() {
  error.value = "";
  try {
    const created = await post("/users", {
      username: username.value.trim(),
      password: password.value,
      role: role.value,
    });
    users.value = [...users.value, created];
    username.value = "";
    password.value = "";
    role.value = "viewer";
  } catch (err) {
    error.value = err?.message ?? "Could not create the user.";
  }
}

/**
 * Delete a confirmed user; a 409 (last admin) keeps the row and explains.
 * @param {number} id user id
 * @returns {Promise<void>} resolves after the attempt
 */
async function remove(id) {
  error.value = "";
  try {
    await del(`/users/${id}`);
    users.value = users.value.filter((user) => user.id !== id);
    pendingDelete.value = null;
  } catch (err) {
    error.value = err?.message ?? "Could not delete the user.";
  }
}

/**
 * Date part of an ISO timestamp, locale-independent for stable rendering.
 * @param {string|null} iso ISO timestamp or null
 * @returns {string} YYYY-MM-DD, or a dash when absent
 */
function day(iso) {
  return iso ? String(iso).slice(0, 10) : "—";
}

onMounted(async () => {
  try {
    await load();
  } catch (err) {
    error.value = err?.message ?? "Could not load users.";
  }
});
</script>

<template>
  <section class="p-8" data-testid="users-view">
    <h1 class="text-xl font-semibold text-text-primary">Users</h1>
    <p
      v-if="error"
      data-testid="users-error"
      role="alert"
      class="mt-2 text-sm text-alert-critical"
    >
      {{ error }}
    </p>

    <form
      class="mt-4 flex flex-wrap items-end gap-3"
      aria-label="Create user"
      @submit.prevent="create"
    >
      <label class="flex flex-col gap-1 text-sm text-text-secondary">
        Username
        <input
          v-model="username"
          data-testid="user-username"
          type="text"
          autocomplete="off"
          maxlength="64"
          class="rounded-md border border-border bg-bg-surface px-2 py-1 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-accent"
        />
      </label>
      <label class="flex flex-col gap-1 text-sm text-text-secondary">
        Password
        <input
          v-model="password"
          data-testid="user-password"
          type="password"
          autocomplete="new-password"
          minlength="8"
          maxlength="128"
          class="rounded-md border border-border bg-bg-surface px-2 py-1 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-accent"
        />
      </label>
      <label class="flex flex-col gap-1 text-sm text-text-secondary">
        Role
        <select
          v-model="role"
          data-testid="user-role"
          class="rounded-md border border-border bg-bg-surface px-2 py-1 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-accent"
        >
          <option value="admin">admin</option>
          <option value="viewer">viewer</option>
        </select>
      </label>
      <button
        type="button"
        data-testid="create-user"
        :disabled="!username.trim() || password.length < 8"
        class="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
        @click="create"
      >
        Create user
      </button>
    </form>

    <ul
      aria-label="Users"
      class="mt-6 divide-y divide-border rounded-md border border-border"
    >
      <li
        v-for="user in users"
        :key="user.id"
        :data-testid="`user-row-${user.id}`"
        class="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
      >
        <div class="min-w-0">
          <p class="truncate text-sm font-medium text-text-primary">
            {{ user.username }}
          </p>
          <p class="mt-0.5 text-xs text-text-secondary">
            <span class="capitalize">{{ user.role }}</span>
            · added {{ day(user.created_at) }}
            <template v-if="user.last_login_at">
              · last login {{ day(user.last_login_at) }}
            </template>
            <template v-else> · never signed in</template>
          </p>
          <p v-if="!user.is_active" class="text-xs text-alert-warning">
            inactive
          </p>
        </div>
        <div class="flex items-center gap-2">
          <template v-if="pendingDelete === user.id">
            <button
              type="button"
              :data-testid="`confirm-delete-user-${user.id}`"
              class="rounded-md bg-alert-critical px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
              @click="remove(user.id)"
            >
              Confirm delete
            </button>
            <button
              type="button"
              :data-testid="`cancel-delete-user-${user.id}`"
              class="rounded-md border border-border px-3 py-1.5 text-sm text-text-secondary hover:bg-bg-raised"
              @click="pendingDelete = null"
            >
              Cancel
            </button>
          </template>
          <button
            v-else
            type="button"
            :data-testid="`delete-user-${user.id}`"
            class="rounded-md border border-border px-3 py-1.5 text-sm text-text-secondary hover:bg-bg-raised"
            @click="pendingDelete = user.id"
          >
            Delete
          </button>
        </div>
      </li>
    </ul>
  </section>
</template>

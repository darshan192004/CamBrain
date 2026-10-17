<script setup>
// Telegram notifier wiring (API §settings/notifiers, spec A7.4): the bot
// token is write-only — entered once, surfaced thereafter only through
// has_token, and echoed by no endpoint (the panel renders an allow-list of
// config fields, never the raw object). Structure follows UsersView: local
// refs, load on mount, inline form, errors in an alert slot. SystemView
// only mounts this for admins; the API's 403s remain the real guard.
import { onMounted, ref } from "vue";

import { del, get, patch, post } from "../api/client.js";

const notifiers = ref([]);
const error = ref("");
const chatId = ref("");
const botToken = ref("");
const testResult = ref("");
const testOk = ref(true);
const testing = ref(false);
const saving = ref(false);

/**
 * Load GET /notifiers (a plain list — ids are notifier_config indexes).
 * @returns {Promise<void>} resolves when the list is in place
 */
async function load() {
  notifiers.value = await get("/notifiers");
}

/**
 * Add the telegram notifier from the form; the 201 carries has_token, so
 * the entered secret never re-enters client state.
 * @returns {Promise<void>} resolves after the attempt
 */
async function save() {
  error.value = "";
  saving.value = true;
  try {
    const created = await post("/notifiers", {
      kind: "telegram",
      enabled: true,
      config: { chat_id: chatId.value.trim(), bot_token: botToken.value },
    });
    notifiers.value = [...notifiers.value, created];
    chatId.value = "";
    botToken.value = "";
  } catch (err) {
    error.value = err?.message ?? "Could not save the notifier.";
  } finally {
    saving.value = false;
  }
}

/**
 * Flip `enabled` through PATCH; the response replaces the row in place.
 * @param {object} notifier current NotifierOut row
 * @param {boolean} enabled new enabled state
 * @returns {Promise<void>} resolves after the attempt
 */
async function toggle(notifier, enabled) {
  error.value = "";
  try {
    const updated = await patch(`/notifiers/${notifier.id}`, { enabled });
    notifiers.value = notifiers.value.map((n) =>
      n.id === updated.id ? updated : n,
    );
  } catch (err) {
    error.value = err?.message ?? "Could not update the notifier.";
  }
}

/**
 * Delete a notifier, then re-read the list: ids are indexes, and popping
 * one shifts every later id — a stale index would patch the wrong entry.
 * @param {number} id notifier index
 * @returns {Promise<void>} resolves after the attempt
 */
async function remove(id) {
  error.value = "";
  try {
    await del(`/notifiers/${id}`);
    await load();
  } catch (err) {
    error.value = err?.message ?? "Could not delete the notifier.";
  }
}

/**
 * POST /notifiers/test; the outcome lands verbatim in the aria-live slot.
 * @returns {Promise<void>} resolves after the attempt
 */
async function runTest() {
  error.value = "";
  testing.value = true;
  try {
    const out = await post("/notifiers/test", {});
    testOk.value = Boolean(out?.ok);
    testResult.value = out?.ok
      ? "Test message sent."
      : `Test failed: ${out?.error ?? "unknown error"}`;
  } catch (err) {
    testOk.value = false;
    testResult.value = `Test failed: ${err?.message ?? "unknown error"}`;
  } finally {
    testing.value = false;
  }
}

onMounted(async () => {
  try {
    await load();
  } catch (err) {
    error.value = err?.message ?? "Could not load notifiers.";
  }
});
</script>

<template>
  <section
    data-testid="notifiers-panel"
    aria-labelledby="notifiers-heading"
    class="mt-8 border-t border-border pt-6"
  >
    <h2 id="notifiers-heading" class="text-sm font-semibold text-text-primary">
      Notifiers
    </h2>
    <p class="mt-1 text-xs text-text-secondary">
      Telegram delivery for alerts. The bot token is write-only — it is never
      shown again after saving.
    </p>
    <p
      v-if="error"
      data-testid="notifiers-error"
      role="alert"
      class="mt-2 text-sm text-alert-critical"
    >
      {{ error }}
    </p>

    <form
      data-testid="notifier-add"
      aria-label="Add notifier"
      class="mt-4 flex flex-wrap items-end gap-3"
      @submit.prevent="save"
    >
      <label class="flex flex-col gap-1 text-sm text-text-secondary">
        Chat ID
        <input
          v-model="chatId"
          data-testid="field-chat_id"
          type="text"
          autocomplete="off"
          maxlength="64"
          class="rounded-md border border-border bg-bg-surface px-2 py-1 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-accent"
        />
      </label>
      <label class="flex flex-col gap-1 text-sm text-text-secondary">
        Bot token
        <input
          v-model="botToken"
          data-testid="field-bot_token"
          type="password"
          autocomplete="new-password"
          maxlength="128"
          class="rounded-md border border-border bg-bg-surface px-2 py-1 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-accent"
        />
      </label>
      <button
        type="submit"
        data-testid="notifier-save"
        :disabled="!chatId.trim() || !botToken || saving"
        class="rounded-md bg-accent-fill px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-fill-hover disabled:cursor-not-allowed disabled:opacity-50"
      >
        Save notifier
      </button>
      <button
        type="button"
        data-testid="notifier-test"
        :disabled="testing"
        class="rounded-md border border-border px-3 py-1.5 text-sm text-text-secondary hover:bg-bg-raised disabled:cursor-not-allowed disabled:opacity-50"
        @click="runTest"
      >
        Send test
      </button>
    </form>

    <p
      data-testid="notifier-test-result"
      aria-live="polite"
      class="mt-2 min-h-5 text-sm"
      :class="testOk ? 'text-alert-success' : 'text-alert-critical'"
    >
      {{ testResult }}
    </p>

    <ul
      aria-label="Notifiers"
      class="mt-4 divide-y divide-border rounded-md border border-border"
    >
      <li
        v-for="n in notifiers"
        :key="n.id"
        :data-testid="`notifier-row-${n.id}`"
        class="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
      >
        <div class="min-w-0">
          <p class="truncate text-sm font-medium text-text-primary">
            <span class="capitalize">{{ n.kind }}</span>
            · {{ n.config?.chat_id ?? "—" }}
          </p>
          <p class="mt-0.5 text-xs text-text-secondary">
            {{ n.has_token ? "Token set" : "No token" }}
            <template v-if="!n.enabled"> · disabled</template>
          </p>
        </div>
        <div class="flex items-center gap-3">
          <label class="flex items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              :data-testid="`notifier-enabled-${n.id}`"
              :checked="n.enabled"
              @change="toggle(n, $event.target.checked)"
            />
            Enabled
          </label>
          <button
            type="button"
            :data-testid="`notifier-delete-${n.id}`"
            class="rounded-md border border-border px-3 py-1.5 text-sm text-text-secondary hover:bg-bg-raised"
            @click="remove(n.id)"
          >
            Delete
          </button>
        </div>
      </li>
    </ul>
    <p v-if="!notifiers.length" class="mt-3 text-xs text-text-secondary">
      No notifiers configured — alerts will only appear in the dashboard.
    </p>
  </section>
</template>

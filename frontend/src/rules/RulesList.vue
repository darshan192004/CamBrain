<script setup>
// Per-camera rules with severity badges (friend's detail look) and the
// create/patch/delete happy paths straight against the API contract.
// DELETE is soft server-side, so the confirm copy says what actually
// happens: the rule is kept for history — events reference the rule that
// fired them (API.md §Rules).
import { ref } from "vue";

import { del, patch, post } from "../api/client.js";
import RoleGate from "../auth/RoleGate.vue";
import { useAuthStore } from "../stores/auth.js";
import RuleDiagnostics from "./RuleDiagnostics.vue";
import RuleForm from "./RuleForm.vue";

const props = defineProps({
  cameraId: {
    type: [Number, String],
    required: true,
  },
  rules: {
    type: Array,
    required: true,
  },
  rois: {
    type: Array,
    default: () => [],
  },
});
const emit = defineEmits(["changed"]);

useAuthStore();
const editing = ref(null);
const confirming = ref(null);
const testing = ref(null);
const error = ref("");
const busy = ref(false);

/**
 * Persist the form payload — POST for create, PATCH for edit.
 * @param {object} payload RuleCreate-shaped body from RuleForm
 * @returns {Promise<void>} resolves when the API has accepted it
 */
async function save(payload) {
  busy.value = true;
  error.value = "";
  try {
    if (editing.value?.mode === "edit") {
      await patch(`/rules/${editing.value.rule.id}`, payload);
    } else {
      await post(`/cameras/${props.cameraId}/rules`, payload);
    }
    editing.value = null;
    emit("changed");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Saving failed.";
  } finally {
    busy.value = false;
  }
}

/**
 * Soft-delete a rule (events keep their attribution).
 * @param {object} rule RuleOut row
 * @returns {Promise<void>} resolves when the API has accepted it
 */
async function remove(rule) {
  busy.value = true;
  error.value = "";
  try {
    await del(`/rules/${rule.id}`);
    confirming.value = null;
    emit("changed");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Deleting failed.";
  } finally {
    busy.value = false;
  }
}

const SEVERITY_STYLE = {
  info: "border-border text-text-secondary",
  warning: "border-amber-500/60 text-amber-400",
  critical: "border-red-500/60 text-red-400",
};
</script>

<template>
  <section aria-label="Rules" class="grid gap-3">
    <header class="flex items-center justify-between gap-3">
      <h2 class="text-lg font-semibold text-text-primary">Rules</h2>
      <RoleGate :roles="['admin']">
        <button
          type="button"
          data-testid="new-rule"
          class="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover"
          @click="editing = { mode: 'create' }"
        >
          New rule
        </button>
      </RoleGate>
    </header>

    <p v-if="error" data-testid="rules-error" class="text-sm text-red-400">
      {{ error }}
    </p>

    <RuleForm
      v-if="editing"
      :rois="rois"
      :initial="editing.mode === 'edit' ? editing.rule : null"
      @save="save"
      @cancel="editing = null"
    />

    <ul class="grid gap-2">
      <li
        v-for="rule in props.rules"
        :key="rule.id"
        class="grid gap-2 rounded-[10px] border border-border bg-bg-surface p-3"
      >
        <div class="flex flex-wrap items-center gap-2">
          <strong class="text-sm text-text-primary">{{ rule.name }}</strong>
          <span
            data-testid="rule-severity"
            class="rounded-full border px-2 py-0.5 text-[10px] tracking-wide uppercase"
            :class="SEVERITY_STYLE[rule.severity] ?? SEVERITY_STYLE.info"
          >
            {{ rule.severity }}
          </span>
          <span
            v-if="!rule.enabled"
            class="rounded-full border border-border px-2 py-0.5 text-[10px] tracking-wide text-text-secondary uppercase"
          >
            disabled
          </span>
        </div>
        <p class="font-mono text-xs text-text-secondary">
          {{ rule.classes.join(", ") }} ≥ {{ rule.confidence_threshold }} ·
          cooldown {{ rule.cooldown_seconds }}s
          <template v-if="rule.active_hours?.windows?.length">
            ·
            {{
              rule.active_hours.windows
                .map((w) => `${w.start}–${w.end}`)
                .join(", ")
            }}
            ({{ rule.active_hours.timezone }})
          </template>
          <template v-else> · all day </template>
        </p>
        <RoleGate :roles="['admin']">
          <div class="flex flex-wrap items-center gap-2">
            <button
              type="button"
              :data-testid="`rule-test-${rule.id}`"
              class="rounded-md border border-border px-3 py-1 text-xs text-text-primary hover:bg-bg-raised"
              @click="testing = testing === rule.id ? null : rule.id"
            >
              Test
            </button>
            <button
              type="button"
              :data-testid="`rule-edit-${rule.id}`"
              class="rounded-md border border-border px-3 py-1 text-xs text-text-primary hover:bg-bg-raised"
              @click="editing = { mode: 'edit', rule }"
            >
              Edit
            </button>
            <button
              type="button"
              :data-testid="`rule-delete-${rule.id}`"
              class="rounded-md border border-border px-3 py-1 text-xs text-text-primary hover:bg-bg-raised"
              @click="confirming = rule"
            >
              Delete
            </button>
          </div>
          <RuleDiagnostics
            v-if="testing === rule.id"
            :rule-id="rule.id"
            :camera-id="props.cameraId"
          />
          <p
            v-if="confirming?.id === rule.id"
            class="mt-2 rounded-md border border-border p-2 text-xs text-text-secondary"
          >
            Delete "{{ rule.name }}"? Soft delete — the rule is kept for history
            so past events keep their attribution.
            <span class="mt-2 flex gap-2">
              <button
                type="button"
                data-testid="confirm-yes"
                class="rounded-md border border-red-500/60 px-3 py-1 text-xs text-red-400"
                :disabled="busy"
                @click="remove(rule)"
              >
                Delete rule
              </button>
              <button
                type="button"
                data-testid="confirm-no"
                class="rounded-md border border-border px-3 py-1 text-xs text-text-primary"
                @click="confirming = null"
              >
                Keep it
              </button>
            </span>
          </p>
        </RoleGate>
      </li>
      <li
        v-if="!props.rules.length"
        class="rounded-[10px] border border-dashed border-border p-4 text-sm text-text-secondary"
      >
        No rules yet — every detection is ignored until one exists.
      </li>
    </ul>
  </section>
</template>

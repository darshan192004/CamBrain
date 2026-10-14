<script setup>
// Per-condition rule replay (API.md POST /rules/{id}/test) — the debug
// view the rules engine is designed to have. Empty body replays the
// camera's most recent event; the optional picker targets a specific one.
// Every check renders an icon AND text (never colour alone, design §11),
// and `detail` is shown verbatim so the operator can act on it.
import { onMounted, ref } from "vue";

import { get, post } from "../api/client.js";

const props = defineProps({
  ruleId: {
    type: [Number, String],
    required: true,
  },
  cameraId: {
    type: [Number, String],
    required: true,
  },
});

const events = ref([]);
const selectedEvent = ref("");
const result = ref(null);
const error = ref("");
const empty = ref(false);
const busy = ref(false);

onMounted(async () => {
  try {
    const page = await get(`/events?camera_id=${props.cameraId}&limit=20`);
    events.value = Array.isArray(page?.items) ? page.items : [];
  } catch {
    events.value = [];
  }
});

/**
 * Replay the selected event (or the most recent one) through the engine.
 * @returns {Promise<void>} resolves after the response is rendered
 */
async function run() {
  busy.value = true;
  error.value = "";
  empty.value = false;
  result.value = null;
  try {
    const body = selectedEvent.value
      ? { event_id: Number(selectedEvent.value) }
      : {};
    result.value = await post(`/rules/${props.ruleId}/test`, body);
  } catch (err) {
    if (err && typeof err === "object" && err.status === 404) {
      empty.value = true;
    } else {
      error.value = err instanceof Error ? err.message : "Replay failed.";
    }
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section
    aria-label="Rule diagnostics"
    class="grid gap-3 rounded-[10px] border border-border bg-bg-base p-3"
  >
    <div class="flex flex-wrap items-end gap-3">
      <label class="grid gap-1 text-xs text-text-secondary">
        Event (optional)
        <select
          v-model="selectedEvent"
          data-testid="event-select"
          class="rounded-md border border-border bg-bg-surface px-2 py-1 text-sm text-text-primary"
        >
          <option value="">Most recent event</option>
          <option v-for="ev in events" :key="ev.id" :value="String(ev.id)">
            #{{ ev.id }} · {{ ev.started_at }}
          </option>
        </select>
      </label>
      <button
        type="button"
        data-testid="run-test"
        :disabled="busy"
        class="rounded-md bg-accent-fill px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-fill-hover disabled:opacity-50"
        @click="run"
      >
        {{ busy ? "Replaying…" : "Run test" }}
      </button>
    </div>

    <p
      v-if="empty"
      data-testid="empty-state"
      class="rounded-md border border-dashed border-border p-3 text-sm text-text-secondary"
    >
      No detections recorded yet — run the camera and try again.
    </p>

    <p v-if="error" data-testid="diag-error" class="text-sm text-red-400">
      {{ error }}
    </p>

    <template v-if="result">
      <p
        data-testid="fired-banner"
        class="rounded-md border px-3 py-2 text-sm font-medium"
        :class="
          result.fired
            ? 'border-red-500/60 text-red-400'
            : 'border-border text-text-secondary'
        "
      >
        {{ result.fired ? "Rule fired" : "Rule did not fire" }}
      </p>
      <ul class="grid gap-1">
        <li
          v-for="check in result.checks"
          :key="check.condition"
          data-testid="check-row"
          class="grid gap-0.5 rounded-md border border-border bg-bg-surface px-3 py-2 text-sm"
        >
          <span class="flex items-center gap-2 text-text-primary">
            <span aria-hidden="true">{{ check.passed ? "✓" : "✗" }}</span>
            <code class="font-mono text-xs">{{ check.condition }}</code>
            <span class="text-xs text-text-secondary">
              {{ check.passed ? "pass" : "fail" }}
            </span>
          </span>
          <span class="font-mono text-xs break-all text-text-secondary">
            {{ check.detail }}
          </span>
        </li>
      </ul>
    </template>
  </section>
</template>

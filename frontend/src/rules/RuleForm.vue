<script setup>
// Create/edit one rule (API.md §Rules). Validation mirrors the backend so
// the operator never pays a round-trip for an obvious mistake: classes
// non-empty COCO names, confidence 0–1, cooldown 5–86400, at most four
// active-hours windows (start < end, or end < start for a midnight wrap —
// the naive check would reject the one rule a shop owner actually needs),
// and roi_id drawn from this camera's ROIs. Emits the RuleCreate payload.
import { computed, ref, watch } from "vue";

import { COCO_CLASSES } from "../data/coco.js";

const props = defineProps({
  rois: {
    type: Array,
    default: () => [],
  },
  initial: {
    type: Object,
    default: null,
  },
});
const emit = defineEmits(["save", "cancel"]);

const localTz =
  typeof Intl !== "undefined" && Intl.DateTimeFormat
    ? Intl.DateTimeFormat().resolvedOptions().timeZone
    : "UTC";

const name = ref(props.initial?.name ?? "");
const selected = ref([...(props.initial?.classes ?? ["person"])]);
const confidence = ref(props.initial?.confidence_threshold ?? 0.5);
const cooldown = ref(props.initial?.cooldown_seconds ?? 60);
const severity = ref(props.initial?.severity ?? "warning");
const notify = ref(props.initial?.notify ?? true);
const enabled = ref(props.initial?.enabled ?? true);
const roiId = ref(
  props.initial?.roi_id == null ? "" : String(props.initial.roi_id),
);
const timezone = ref(props.initial?.active_hours?.timezone ?? localTz);
const windows = ref(
  props.initial?.active_hours?.windows?.length
    ? props.initial.active_hours.windows.map((w) => ({ ...w }))
    : [{ start: "09:00", end: "17:00" }],
);
const errors = ref({});
const windowsEl = ref(null);

watch(
  () => props.initial,
  (next) => {
    if (!next) return;
    name.value = next.name ?? "";
    selected.value = [...(next.classes ?? ["person"])];
    confidence.value = next.confidence_threshold ?? 0.5;
    cooldown.value = next.cooldown_seconds ?? 60;
    severity.value = next.severity ?? "warning";
    notify.value = next.notify ?? true;
    enabled.value = next.enabled ?? true;
    roiId.value = next.roi_id == null ? "" : String(next.roi_id);
    timezone.value = next.active_hours?.timezone ?? localTz;
    windows.value = next.active_hours?.windows?.length
      ? next.active_hours.windows.map((w) => ({ ...w }))
      : [{ start: "09:00", end: "17:00" }];
    errors.value = {};
  },
  { deep: true },
);

const roiOptions = computed(() => props.rois);

/**
 * Toggle one COCO class in the allow-list.
 * @param {string} cls class name
 * @param {boolean} on checked state
 * @returns {void}
 */
function toggleClass(cls, on) {
  if (on && !selected.value.includes(cls)) {
    selected.value = [...selected.value, cls];
  } else if (!on) {
    selected.value = selected.value.filter((c) => c !== cls);
  }
}

/**
 * Add an active-hours row (max four — API.md validation).
 * @returns {void}
 */
function addWindow() {
  if (windows.value.length < 4) {
    windows.value = [...windows.value, { start: "09:00", end: "17:00" }];
  }
}

/**
 * Remove an active-hours row by index.
 * @param {number} index row index
 * @returns {void}
 */
function removeWindow(index) {
  windows.value = windows.value.filter((_, i) => i !== index);
}

/**
 * Re-read every window row from the DOM after any change event, so the
 * state always reflects what the operator actually typed.
 * @returns {void}
 */
function readWindows() {
  const root = windowsEl.value;
  if (!root) return;
  windows.value = [...root.querySelectorAll('[data-testid="window-row"]')].map(
    (row) => ({
      start: row.querySelector('[data-testid="window-start"]').value,
      end: row.querySelector('[data-testid="window-end"]').value,
    }),
  );
}

/**
 * Validate every field against API.md's rules table.
 * @returns {boolean} true when the payload is safe to emit
 */
function validate() {
  const next = {};
  if (!name.value.trim()) {
    next.name = "Give the rule a name.";
  }
  if (!selected.value.length) {
    next.classes = "Pick at least one class.";
  }
  const conf = Number(confidence.value);
  if (!(conf >= 0 && conf <= 1)) {
    next.confidence = "Confidence must be between 0 and 1.";
  }
  const cd = Number(cooldown.value);
  if (!(cd >= 5 && cd <= 86400)) {
    next.cooldown = "Cooldown must be between 5 and 86400 seconds.";
  }
  const hhmm = /^\d{2}:\d{2}$/;
  for (const w of windows.value) {
    if (!hhmm.test(w.start) || !hhmm.test(w.end)) {
      next.windows = "Times must look like HH:MM.";
      break;
    }
    if (w.start === w.end) {
      next.windows = "A window cannot start and end at the same time.";
      break;
    }
  }
  if (
    roiId.value !== "" &&
    !props.rois.some((r) => r.id === Number(roiId.value))
  ) {
    next.roi = "That ROI is not one of this camera's zones.";
  }
  errors.value = next;
  return Object.keys(next).length === 0;
}

/**
 * Build the RuleCreate payload and emit it when valid.
 * @returns {void}
 */
function submit() {
  if (!validate()) return;
  emit("save", {
    name: name.value.trim(),
    roi_id: roiId.value === "" ? null : Number(roiId.value),
    enabled: enabled.value,
    classes: [...selected.value],
    confidence_threshold: Number(confidence.value),
    cooldown_seconds: Number(cooldown.value),
    active_hours: windows.value.length
      ? {
          timezone: timezone.value,
          windows: windows.value.map((w) => ({ start: w.start, end: w.end })),
        }
      : null,
    severity: severity.value,
    notify: notify.value,
  });
}
</script>

<template>
  <form
    data-testid="rule-form"
    class="grid gap-4 rounded-[10px] border border-border bg-bg-surface p-4"
    novalidate
    @submit.prevent="submit"
  >
    <div class="grid gap-1">
      <label for="rule-name" class="text-sm text-text-secondary">Name</label>
      <input
        id="rule-name"
        v-model="name"
        data-testid="rule-name"
        type="text"
        class="rounded-md border border-border bg-bg-base px-3 py-2 text-sm text-text-primary"
      />
      <p
        v-if="errors.name"
        data-testid="field-error-name"
        class="text-xs text-red-400"
      >
        {{ errors.name }}
      </p>
    </div>

    <fieldset class="grid gap-2">
      <legend class="text-sm text-text-secondary">Classes (COCO names)</legend>
      <div class="max-h-40 overflow-auto rounded-md border border-border p-2">
        <label
          v-for="cls in COCO_CLASSES"
          :key="cls"
          class="mr-3 inline-flex items-center gap-1 text-xs text-text-primary"
        >
          <input
            type="checkbox"
            :data-testid="`class-option-${cls}`"
            :checked="selected.includes(cls)"
            @change="toggleClass(cls, $event.target.checked)"
          />
          {{ cls }}
        </label>
      </div>
      <p
        v-if="errors.classes"
        data-testid="field-error-classes"
        class="text-xs text-red-400"
      >
        {{ errors.classes }}
      </p>
    </fieldset>

    <div class="grid grid-cols-2 gap-4">
      <div class="grid gap-1">
        <label for="rule-confidence" class="text-sm text-text-secondary">
          Confidence (0–1)
        </label>
        <input
          id="rule-confidence"
          v-model.number="confidence"
          data-testid="confidence"
          type="number"
          min="0"
          max="1"
          step="0.05"
          class="rounded-md border border-border bg-bg-base px-3 py-2 text-sm text-text-primary"
        />
        <p
          v-if="errors.confidence"
          data-testid="field-error-confidence"
          class="text-xs text-red-400"
        >
          {{ errors.confidence }}
        </p>
      </div>
      <div class="grid gap-1">
        <label for="rule-cooldown" class="text-sm text-text-secondary">
          Cooldown (seconds)
        </label>
        <input
          id="rule-cooldown"
          v-model.number="cooldown"
          data-testid="cooldown"
          type="number"
          min="5"
          max="86400"
          class="rounded-md border border-border bg-bg-base px-3 py-2 text-sm text-text-primary"
        />
        <p
          v-if="errors.cooldown"
          data-testid="field-error-cooldown"
          class="text-xs text-red-400"
        >
          {{ errors.cooldown }}
        </p>
      </div>
    </div>

    <div class="grid grid-cols-2 gap-4">
      <div class="grid gap-1">
        <label for="rule-severity" class="text-sm text-text-secondary">
          Severity
        </label>
        <select
          id="rule-severity"
          v-model="severity"
          data-testid="severity"
          class="rounded-md border border-border bg-bg-base px-3 py-2 text-sm text-text-primary"
        >
          <option value="info">info</option>
          <option value="warning">warning</option>
          <option value="critical">critical</option>
        </select>
      </div>
      <div class="grid gap-1">
        <label for="rule-roi" class="text-sm text-text-secondary">ROI</label>
        <select
          id="rule-roi"
          v-model="roiId"
          data-testid="roi-select"
          class="rounded-md border border-border bg-bg-base px-3 py-2 text-sm text-text-primary"
        >
          <option value="">Whole frame (no ROI)</option>
          <option
            v-for="roi in roiOptions"
            :key="roi.id"
            :value="String(roi.id)"
          >
            {{ roi.name }}
          </option>
        </select>
        <p
          v-if="errors.roi"
          data-testid="field-error-roi"
          class="text-xs text-red-400"
        >
          {{ errors.roi }}
        </p>
      </div>
    </div>

    <fieldset class="grid gap-2">
      <legend class="text-sm text-text-secondary">
        Active hours (empty = all day)
      </legend>
      <div ref="windowsEl" class="grid gap-2">
        <div
          v-for="(_w, i) in windows"
          :key="i"
          data-testid="window-row"
          class="flex flex-wrap items-end gap-2"
        >
          <label class="grid gap-1 text-xs text-text-secondary">
            Start
            <input
              type="time"
              data-testid="window-start"
              :value="windows[i].start"
              class="rounded-md border border-border bg-bg-base px-2 py-1 text-sm text-text-primary"
              @change="readWindows"
            />
          </label>
          <label class="grid gap-1 text-xs text-text-secondary">
            End
            <input
              type="time"
              data-testid="window-end"
              :value="windows[i].end"
              class="rounded-md border border-border bg-bg-base px-2 py-1 text-sm text-text-primary"
              @change="readWindows"
            />
          </label>
          <button
            type="button"
            data-testid="remove-window"
            class="rounded-md border border-border px-2 py-1 text-xs text-text-primary hover:bg-bg-raised"
            @click="removeWindow(i)"
          >
            Remove
          </button>
        </div>
      </div>
      <p
        v-if="errors.windows"
        data-testid="field-error-windows"
        class="text-xs text-red-400"
      >
        {{ errors.windows }}
      </p>
      <div class="flex items-end gap-3">
        <button
          type="button"
          data-testid="add-window"
          :disabled="windows.length >= 4"
          class="rounded-md border border-border px-3 py-1 text-xs text-text-primary hover:bg-bg-raised disabled:opacity-40"
          @click="addWindow"
        >
          Add window
        </button>
        <label class="grid gap-1 text-xs text-text-secondary">
          Timezone
          <input
            v-model="timezone"
            data-testid="timezone"
            type="text"
            class="rounded-md border border-border bg-bg-base px-2 py-1 text-sm text-text-primary"
          />
        </label>
      </div>
    </fieldset>

    <div class="flex flex-wrap items-center gap-4 text-sm text-text-primary">
      <label class="inline-flex items-center gap-2">
        <input v-model="notify" data-testid="notify" type="checkbox" />
        Notify (Telegram)
      </label>
      <label class="inline-flex items-center gap-2">
        <input v-model="enabled" data-testid="enabled" type="checkbox" />
        Enabled
      </label>
    </div>

    <div class="flex gap-2">
      <button
        type="submit"
        data-testid="rule-submit"
        class="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover"
      >
        Save rule
      </button>
      <button
        type="button"
        data-testid="rule-cancel"
        class="rounded-md border border-border px-4 py-2 text-sm text-text-primary hover:bg-bg-raised"
        @click="emit('cancel')"
      >
        Cancel
      </button>
    </div>
  </form>
</template>

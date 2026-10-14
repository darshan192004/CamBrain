<script setup>
// Filter bar for the event log. A local draft commits on Apply or Reset
// only — every keystroke must not refetch the page. Emits `apply` with
// the full filter set; the parent owns fetching.
import { ref } from "vue";

const props = defineProps({
  modelValue: {
    type: Object,
    default: () => ({}),
  },
});

const emit = defineEmits(["apply"]);

/**
 * A blank filter set (every query param absent).
 * @returns {object} empty filters
 */
function empty() {
  return {
    camera_id: "",
    severity: "",
    from: "",
    to: "",
    acknowledged: "",
    q: "",
  };
}

const draft = ref({ ...empty(), ...props.modelValue });

/**
 * Commit the draft — the parent resets to page one and reloads.
 * @returns {void}
 */
function apply() {
  emit("apply", { ...draft.value });
}

/**
 * Clear every field, then commit the blank set.
 * @returns {void}
 */
function reset() {
  draft.value = empty();
  emit("apply", { ...draft.value });
}
</script>

<template>
  <form
    data-testid="event-filters"
    class="flex flex-wrap items-center gap-2"
    aria-label="Event filters"
    @submit.prevent="apply"
  >
    <input
      v-model="draft.camera_id"
      data-testid="filter-camera"
      type="number"
      min="1"
      placeholder="Camera id"
      aria-label="Camera id"
      class="w-28 rounded-md border border-border bg-bg-base px-2 py-1.5 text-sm text-text-primary"
    />
    <select
      v-model="draft.severity"
      data-testid="filter-severity"
      aria-label="Severity"
      class="rounded-md border border-border bg-bg-base px-2 py-1.5 text-sm text-text-primary"
    >
      <option value="">All severities</option>
      <option value="critical">critical</option>
      <option value="warning">warning</option>
      <option value="info">info</option>
    </select>
    <input
      v-model="draft.from"
      data-testid="filter-from"
      type="datetime-local"
      aria-label="From"
      class="rounded-md border border-border bg-bg-base px-2 py-1.5 text-sm text-text-primary"
    />
    <input
      v-model="draft.to"
      data-testid="filter-to"
      type="datetime-local"
      aria-label="To"
      class="rounded-md border border-border bg-bg-base px-2 py-1.5 text-sm text-text-primary"
    />
    <select
      v-model="draft.acknowledged"
      data-testid="filter-acknowledged"
      aria-label="Acknowledgement"
      class="rounded-md border border-border bg-bg-base px-2 py-1.5 text-sm text-text-primary"
    >
      <option value="">Any status</option>
      <option value="true">Acknowledged</option>
      <option value="false">Unacknowledged</option>
    </select>
    <input
      v-model="draft.q"
      data-testid="filter-q"
      type="search"
      placeholder="Search summaries"
      aria-label="Search summaries"
      class="w-44 rounded-md border border-border bg-bg-base px-2 py-1.5 text-sm text-text-primary"
    />
    <button
      type="button"
      data-testid="filter-apply"
      class="rounded-md bg-accent-fill px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-fill-hover"
      @click="apply"
    >
      Apply
    </button>
    <button
      type="button"
      data-testid="filter-reset"
      class="rounded-md border border-border px-3 py-1.5 text-sm text-text-primary hover:bg-bg-raised"
      @click="reset"
    >
      Reset
    </button>
  </form>
</template>

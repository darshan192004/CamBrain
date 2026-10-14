<script setup>
// The event log (design §6): filter → fetch → table, bulk acknowledge,
// offset pagination. Filters commit only on Apply/Reset and the parent
// owns every request, so a keystroke never refetches.
import { computed, onMounted, ref } from "vue";

import { get, post } from "../api/client.js";
import EventFilters from "../events/EventFilters.vue";
import EventTable from "../events/EventTable.vue";

/** Rows per page — the query's fixed `limit`. */
const PAGE_SIZE = 20;

const filters = ref({
  camera_id: "",
  severity: "",
  from: "",
  to: "",
  acknowledged: "",
  q: "",
});
const items = ref([]);
const total = ref(0);
const offset = ref(0);
const selected = ref([]);
const error = ref("");

/**
 * The documented `GET /events` query for the current filters + offset.
 * @returns {string} `/events?...` path (client prepends /api/v1)
 */
function buildQuery() {
  const f = filters.value;
  const params = new URLSearchParams();
  if (f.camera_id) params.set("camera_id", String(f.camera_id));
  if (f.severity) params.set("severity", f.severity);
  if (f.from) params.set("from", f.from);
  if (f.to) params.set("to", f.to);
  if (f.acknowledged) params.set("acknowledged", f.acknowledged);
  if (f.q) params.set("q", f.q);
  params.set("limit", String(PAGE_SIZE));
  params.set("offset", String(offset.value));
  params.set("sort", "-started_at");
  return `/events?${params.toString()}`;
}

/**
 * Fetch the current page. A failed load keeps the previous rows and
 * surfaces the API message inline.
 * @returns {Promise<void>} settles after the request
 */
async function load() {
  error.value = "";
  try {
    const page = await get(buildQuery());
    items.value = Array.isArray(page?.items) ? page.items : [];
    total.value = page?.total ?? 0;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Loading events failed.";
  }
}

/**
 * Apply filters from the bar, restarting at page one with a clean
 * selection.
 * @param {object} next full filter set from EventFilters
 * @returns {void}
 */
function applyFilters(next) {
  filters.value = next;
  offset.value = 0;
  selected.value = [];
  load();
}

/**
 * Toggle one row's selection.
 * @param {number} id event id
 * @returns {void}
 */
function toggleRow(id) {
  selected.value = selected.value.includes(id)
    ? selected.value.filter((x) => x !== id)
    : [...selected.value, id];
}

/**
 * Acknowledge every selected row in one POST, then reflect it locally.
 * @returns {Promise<void>} settles after the request
 */
async function bulkAck() {
  if (!selected.value.length) return;
  const ids = [...selected.value];
  try {
    await post("/events/acknowledge-bulk", { event_ids: ids });
    items.value = items.value.map((event) =>
      ids.includes(event.id) ? { ...event, acknowledged: true } : event,
    );
    selected.value = [];
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Acknowledging failed.";
  }
}

/**
 * Move one page forward (+1) or back (-1); the buttons themselves are
 * disabled at the bounds.
 * @param {number} direction page step
 * @returns {void}
 */
function step(direction) {
  offset.value = Math.max(offset.value + direction * PAGE_SIZE, 0);
  selected.value = [];
  load();
}

const pageInfo = computed(() => {
  const first = offset.value + 1;
  const last = Math.min(offset.value + items.value.length, total.value);
  return `Showing ${first}–${last} of ${total.value}`;
});

onMounted(load);
</script>

<template>
  <section class="grid gap-3 p-6">
    <h1 class="text-xl font-semibold text-text-primary">Events</h1>

    <EventFilters :model-value="filters" @apply="applyFilters" />

    <p
      v-if="error"
      data-testid="events-error"
      class="text-sm text-alert-critical"
    >
      {{ error }}
    </p>

    <template v-if="items.length">
      <EventTable
        :items="items"
        :selected="selected"
        @toggle="toggleRow"
        @bulk-ack="bulkAck"
      />
      <div class="flex flex-wrap items-center justify-end gap-2">
        <span data-testid="page-info" class="text-sm text-text-secondary">
          {{ pageInfo }}
        </span>
        <button
          type="button"
          data-testid="page-prev"
          :disabled="offset === 0"
          class="rounded-md border border-border px-3 py-1.5 text-sm text-text-primary hover:bg-bg-raised disabled:opacity-50"
          @click="step(-1)"
        >
          Previous
        </button>
        <button
          type="button"
          data-testid="page-next"
          :disabled="offset + PAGE_SIZE >= total"
          class="rounded-md border border-border px-3 py-1.5 text-sm text-text-primary hover:bg-bg-raised disabled:opacity-50"
          @click="step(1)"
        >
          Next
        </button>
      </div>
    </template>

    <p
      v-else-if="!error"
      data-testid="events-empty"
      class="rounded-lg border border-dashed border-border p-6 text-sm text-text-secondary"
    >
      No events yet — events appear once a rule fires. Clips and stills are
      recorded in Phase 5.
    </p>
  </section>
</template>

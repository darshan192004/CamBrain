<script setup>
// The log table itself: rows plus a bulk-acknowledge action. Selection
// state lives in the parent (it drives the POST); this component only
// reports toggles and the bulk click.
import EventRow from "./EventRow.vue";

defineProps({
  items: {
    type: Array,
    default: () => [],
  },
  selected: {
    type: Array,
    default: () => [],
  },
});

const emit = defineEmits(["toggle", "bulk-ack"]);
</script>

<template>
  <div class="overflow-x-auto rounded-lg border border-border bg-bg-surface">
    <table data-testid="event-table" class="w-full border-collapse">
      <thead>
        <tr
          class="border-b border-border text-left text-xs tracking-wide text-text-secondary uppercase"
        >
          <th class="px-3 py-2">
            <span class="sr-only">Select</span>
          </th>
          <th class="px-3 py-2">Severity</th>
          <th class="px-3 py-2">Time</th>
          <th class="px-3 py-2">Camera</th>
          <th class="px-3 py-2">
            <span class="sr-only">Still</span>
          </th>
          <th class="px-3 py-2">Summary</th>
          <th class="px-3 py-2">Status</th>
        </tr>
      </thead>
      <tbody>
        <EventRow
          v-for="event in items"
          :key="event.id"
          :event="event"
          :selected="selected.includes(event.id)"
          @toggle="emit('toggle', $event)"
        />
      </tbody>
    </table>
    <div class="border-t border-border px-3 py-2">
      <button
        type="button"
        data-testid="bulk-ack"
        :disabled="selected.length === 0"
        class="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
        @click="emit('bulk-ack')"
      >
        Acknowledge {{ selected.length }} selected
      </button>
    </div>
  </div>
</template>

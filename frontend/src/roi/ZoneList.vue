<script setup>
// Zone list (design §5.6) — always visible, never behind an edit mode.
// Coverage is recomputed from the points via shoelace rather than trusting
// the server field, so a stale `coverage_pct` can never lie to the operator;
// >80% is the nearly-the-whole-frame mistake API.md calls out.
import { coveragePct } from "./geometry.js";

defineProps({
  zones: {
    type: Array,
    required: true,
  },
  selectedId: {
    type: [Number, String],
    default: null,
  },
  canEdit: {
    type: Boolean,
    default: false,
  },
});

defineEmits(["select", "duplicate", "delete"]);
</script>

<template>
  <aside aria-label="Zones" class="grid content-start gap-2">
    <h3 class="text-sm font-semibold text-text-primary">Zones</h3>
    <ul
      v-if="zones.length"
      data-testid="zone-list"
      class="grid list-none gap-1 p-0"
    >
      <li
        v-for="zone in zones"
        :key="zone.id"
        class="grid gap-1 rounded-md border p-2"
        :class="
          zone.id === selectedId
            ? 'border-accent bg-bg-raised'
            : 'border-border bg-bg-surface'
        "
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <button
            type="button"
            :data-testid="`zone-row-${zone.id}`"
            class="text-left text-sm text-text-primary hover:underline"
            @click="$emit('select', zone.id)"
          >
            {{ zone.name }}
          </button>
          <span
            :data-testid="`zone-coverage-${zone.id}`"
            class="font-mono text-xs text-text-secondary"
          >
            {{ coveragePct(zone.points) }}%
          </span>
        </div>
        <p
          v-if="coveragePct(zone.points) > 80"
          :data-testid="`zone-warning-${zone.id}`"
          class="text-xs text-alert-warning"
          role="alert"
        >
          Covers most of the frame — narrow it to what actually matters.
        </p>
        <div v-if="canEdit" class="flex flex-wrap gap-2">
          <button
            type="button"
            :data-testid="`zone-duplicate-${zone.id}`"
            class="rounded-md border border-border px-2 py-0.5 text-xs text-text-primary hover:bg-bg-raised"
            @click="$emit('duplicate', zone.id)"
          >
            Duplicate
          </button>
          <button
            type="button"
            :data-testid="`zone-delete-${zone.id}`"
            class="rounded-md border border-border px-2 py-0.5 text-xs text-text-primary hover:bg-bg-raised"
            @click="$emit('delete', zone.id)"
          >
            Delete
          </button>
        </div>
      </li>
    </ul>
    <p v-else data-testid="zones-empty" class="text-sm text-text-secondary">
      No zones yet — draw one on the snapshot.
    </p>
  </aside>
</template>

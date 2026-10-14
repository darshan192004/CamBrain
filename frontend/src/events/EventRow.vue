<script setup>
// One event-log row: selection box, severity badge, time, camera, still
// thumbnail, link to the detail page, acknowledgement state. The still is
// fetched through the authenticated client (an `<img src>` cannot send the
// Bearer token); a 404 — Phase 5 writes stills — shows a placeholder
// instead of a broken image.
import { onBeforeUnmount, onMounted, ref } from "vue";

import { fetchThumbnail } from "./thumbnail.js";
import { severityClass } from "./severity.js";

const props = defineProps({
  event: {
    type: Object,
    required: true,
  },
  selected: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(["toggle"]);

const thumbUrl = ref("");
const thumbFailed = ref(false);

onMounted(async () => {
  try {
    thumbUrl.value = await fetchThumbnail(props.event.thumbnail_url);
  } catch {
    thumbFailed.value = true;
  }
});

onBeforeUnmount(() => {
  if (thumbUrl.value) {
    URL.revokeObjectURL(thumbUrl.value);
  }
});
</script>

<template>
  <tr
    :data-testid="`event-row-${event.id}`"
    class="border-b border-border text-sm"
  >
    <td class="px-3 py-2">
      <input
        type="checkbox"
        :data-testid="`row-select-${event.id}`"
        :checked="selected"
        :aria-label="`Select event ${event.id}`"
        @change="emit('toggle', event.id)"
      />
    </td>
    <td class="px-3 py-2">
      <span
        :data-testid="`severity-${event.id}`"
        class="inline-flex rounded-full border border-current px-2 py-0.5 text-xs font-medium uppercase"
        :class="severityClass(event.severity)"
      >
        {{ event.severity }}
      </span>
    </td>
    <td class="px-3 py-2 text-xs text-text-secondary">
      <time :datetime="event.started_at">{{ event.started_at }}</time>
    </td>
    <td class="px-3 py-2 text-text-primary">{{ event.camera?.name }}</td>
    <td class="px-3 py-2">
      <img
        v-if="thumbUrl && !thumbFailed"
        :data-testid="`row-thumb-${event.id}`"
        :src="thumbUrl"
        :alt="`Still for event ${event.id}`"
        class="h-10 w-auto rounded border border-border"
      />
      <span
        v-else
        :data-testid="`row-thumb-placeholder-${event.id}`"
        class="inline-flex h-10 w-14 items-center justify-center rounded border border-dashed border-border text-text-muted"
      >
        <svg
          aria-hidden="true"
          class="h-5 w-5"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          viewBox="0 0 24 24"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909M3.75 19.5h16.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 0-1.5-1.5H3.75A1.5 1.5 0 0 0 2.25 6v12a1.5 1.5 0 0 0 1.5 1.5Z"
          />
        </svg>
        <span class="sr-only">No still yet</span>
      </span>
    </td>
    <td class="px-3 py-2">
      <RouterLink
        :to="`/events/${event.id}`"
        class="text-accent hover:underline"
      >
        {{ event.summary || `#${event.id}` }}
      </RouterLink>
    </td>
    <td class="px-3 py-2">
      <span
        :data-testid="`ack-state-${event.id}`"
        class="text-xs"
        :class="event.acknowledged ? 'text-alert-success' : 'text-text-muted'"
      >
        {{ event.acknowledged ? "Acknowledged" : "Pending" }}
      </span>
    </td>
  </tr>
</template>

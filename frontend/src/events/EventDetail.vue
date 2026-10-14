<script setup>
// Event detail body (plan 4.16): the still with detection boxes drawn in
// frame-percent space, the per-detection list, acknowledge, and the clip —
// hidden behind the Phase 5 note until `has_clip` is ever true (plan D6).
import { onBeforeUnmount, onMounted, ref } from "vue";

import DetectionOverlay from "./DetectionOverlay.vue";
import { severityClass } from "./severity.js";
import { fetchThumbnail } from "./thumbnail.js";

const props = defineProps({
  event: {
    type: Object,
    required: true,
  },
  frameWidth: {
    type: Number,
    default: 640,
  },
  frameHeight: {
    type: Number,
    default: 360,
  },
});

const emit = defineEmits(["ack"]);

const stillUrl = ref("");
const stillFailed = ref(false);

onMounted(async () => {
  try {
    stillUrl.value = await fetchThumbnail(props.event.thumbnail_url);
  } catch {
    stillFailed.value = true;
  }
});

onBeforeUnmount(() => {
  if (stillUrl.value) {
    URL.revokeObjectURL(stillUrl.value);
  }
});

/**
 * Confidence as a whole-percent label (0.71 → "71%").
 * @param {number} confidence model confidence 0..1
 * @returns {string} whole percent
 */
function pct(confidence) {
  return `${Math.round(confidence * 100)}%`;
}
</script>

<template>
  <div class="grid gap-3">
    <div class="flex flex-wrap items-center gap-2">
      <span
        data-testid="event-severity"
        class="inline-flex rounded-full border border-current px-2 py-0.5 text-xs font-medium uppercase"
        :class="severityClass(event.severity)"
      >
        {{ event.severity }}
      </span>
      <h2 class="text-base font-semibold text-text-primary">
        {{ event.summary || `Event #${event.id}` }}
      </h2>
    </div>

    <div class="flex flex-wrap items-center gap-2 text-sm text-text-secondary">
      <span data-testid="event-camera">{{ event.camera?.name }}</span>
      <time :datetime="event.started_at">{{ event.started_at }}</time>
      <span v-if="event.rule" data-testid="event-rule">
        {{ event.rule.name }}
      </span>
      <span
        data-testid="ack-state"
        class="text-xs"
        :class="event.acknowledged ? 'text-alert-success' : 'text-text-muted'"
      >
        {{ event.acknowledged ? "Acknowledged" : "Pending" }}
      </span>
      <button
        v-if="!event.acknowledged"
        type="button"
        data-testid="event-ack"
        class="rounded-md border border-border px-3 py-1 text-sm text-text-primary hover:bg-bg-raised"
        @click="emit('ack')"
      >
        Acknowledge
      </button>
    </div>

    <div
      class="relative overflow-hidden rounded-lg border border-border bg-bg-base"
    >
      <img
        v-if="stillUrl && !stillFailed"
        data-testid="detail-still"
        :src="stillUrl"
        :alt="`Still for event ${event.id}`"
        class="block w-full"
      />
      <div
        v-else
        data-testid="detail-still-placeholder"
        class="flex aspect-video items-center justify-center text-sm text-text-muted"
      >
        No still yet (Phase 5 records frames)
      </div>
      <DetectionOverlay
        :detections="event.detections ?? []"
        :frame-width="frameWidth"
        :frame-height="frameHeight"
        class="absolute inset-0"
      />
    </div>

    <ul class="grid gap-1" data-testid="detections">
      <li
        v-for="(detection, index) in event.detections ?? []"
        :key="index"
        :data-testid="`detection-row-${index}`"
        class="flex flex-wrap gap-2 rounded-md border border-border bg-bg-raised px-2 py-1 text-sm text-text-primary"
      >
        <span>{{ detection.class_name }}</span>
        <span class="text-text-secondary">{{ pct(detection.confidence) }}</span>
        <span v-if="detection.zone_name" class="text-text-secondary">
          {{ detection.zone_name }}
        </span>
      </li>
    </ul>

    <div class="grid gap-2">
      <h3 class="text-sm font-semibold text-text-primary">Clip</h3>
      <video
        v-if="event.has_clip"
        data-testid="event-clip"
        :src="event.clip_url"
        controls
        class="w-full rounded-lg border border-border"
      ></video>
      <p v-else data-testid="clip-note" class="text-sm text-text-secondary">
        Clip available after recording (Phase 5)
      </p>
    </div>
  </div>
</template>

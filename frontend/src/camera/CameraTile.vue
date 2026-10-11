<script setup>
// One live view (design §4 tile states): `starting` until the first
// frame, `live` while MJPEG plays, `error` with the actual reason and a
// Retry button, `offline` dimmed for a disabled or failing camera. The
// status pill always carries text — colour is never the sole signal
// (design §11).
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { openMjpeg, streamUrl } from "../api/mjpeg.js";

const props = defineProps({
  camera: {
    type: Object,
    required: true,
  },
});

const STATUS_TEXT = {
  starting: "Starting…",
  live: "Live",
  offline: "Offline",
  error: "Error",
};

const REASON_COPY = {
  capacity: "Server at live-stream capacity. Try again in a moment.",
  network: "Lost the connection to the server.",
  http: "The stream request failed.",
  ended: "The stream ended.",
};

const offline = computed(
  () => !props.camera.enabled || Boolean(props.camera.last_error),
);
const state = ref(offline.value ? "offline" : "starting");
const reason = ref("");
const frameUrl = ref(null);

let controller = null;

/**
 * Open the MJPEG stream for this tile.
 * @returns {void}
 */
function open() {
  controller = new AbortController();
  openMjpeg(streamUrl(props.camera.id), {
    signal: controller.signal,
    onFrame: (url) => {
      frameUrl.value = url;
      state.value = "live";
    },
    onError: (code) => {
      reason.value = REASON_COPY[code] ?? "Stream failed.";
      state.value = "error";
    },
  });
}

/**
 * Tear down the current stream and try again from `starting`.
 * @returns {void}
 */
function retry() {
  controller?.abort();
  frameUrl.value = null;
  reason.value = "";
  state.value = "starting";
  open();
}

watch(offline, (now) => {
  if (now) {
    controller?.abort();
    controller = null;
    state.value = "offline";
    reason.value = "";
  } else if (state.value === "offline") {
    state.value = "starting";
    open();
  }
});

onMounted(() => {
  if (!offline.value) {
    open();
  }
});

onBeforeUnmount(() => {
  controller?.abort();
});
</script>

<template>
  <figure
    data-testid="camera-tile"
    :data-state="state"
    class="overflow-hidden rounded-[10px] border border-border bg-bg-surface"
    :class="offline ? 'opacity-60' : ''"
  >
    <div class="relative aspect-video bg-black">
      <img
        v-if="frameUrl"
        :src="frameUrl"
        :alt="`${props.camera.name} live view`"
        class="h-full w-full object-contain"
      />
      <p
        v-if="state === 'starting'"
        class="absolute inset-0 grid place-items-center text-xs text-text-secondary"
      >
        Connecting to stream…
      </p>
      <div
        v-else-if="state === 'error'"
        class="absolute inset-0 grid place-items-center content-center gap-2 p-4 text-center"
      >
        <p class="text-xs text-text-primary">{{ reason }}</p>
        <button
          type="button"
          data-testid="tile-retry"
          class="rounded-md border border-border px-3 py-1 text-xs text-text-primary hover:bg-bg-raised"
          @click="retry"
        >
          Retry
        </button>
      </div>
      <p
        v-else-if="state === 'offline'"
        class="absolute inset-0 grid place-items-center p-4 text-center text-xs text-text-secondary"
      >
        {{ props.camera.last_error ?? "Camera disabled" }}
      </p>
    </div>
    <figcaption
      class="flex items-center justify-between gap-2 px-3 py-2 text-sm"
    >
      <span class="truncate text-text-primary">{{ props.camera.name }}</span>
      <span
        data-testid="tile-status"
        class="shrink-0 rounded-full border border-border px-2 py-0.5 text-[10px] tracking-wide text-text-secondary uppercase"
      >
        {{ STATUS_TEXT[state] }}
      </span>
    </figcaption>
  </figure>
</template>

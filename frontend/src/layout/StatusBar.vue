<script setup>
// Status bar (design §4): polls GET /system/status every 10s for live
// camera counts and the mean FPS of live streams; the interval is cleared
// on unmount so a route change never leaks a poller. Poll failures keep the
// last good numbers — the bar degrades, it does not throw.
import { onBeforeUnmount, onMounted, ref } from "vue";

import { get } from "../api/client.js";

const POLL_MS = 10_000;

const online = ref(0);
const offline = ref(0);
const avgFps = ref("0.0");

let timer = null;

/**
 * Fetch one /system/status sample and derive the headline numbers.
 * @returns {Promise<void>} resolves when the sample has been applied
 */
async function poll() {
  try {
    const status = await get("/system/status");
    const cameras = Array.isArray(status.cameras) ? status.cameras : [];
    online.value = cameras.filter((c) => c.status === "live").length;
    offline.value = cameras.length - online.value;
    const fps = cameras
      .filter((c) => typeof c.fps === "number")
      .map((c) => c.fps);
    avgFps.value = fps.length
      ? (fps.reduce((sum, f) => sum + f, 0) / fps.length).toFixed(1)
      : "0.0";
  } catch {
    // Keep the last known numbers; the next tick retries.
  }
}

onMounted(() => {
  poll();
  timer = setInterval(poll, POLL_MS);
});

onBeforeUnmount(() => {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
});
</script>

<template>
  <footer
    data-testid="status-bar"
    class="flex h-9 shrink-0 items-center gap-4 border-t border-border bg-bg-surface px-4 text-xs text-text-secondary"
  >
    <span>{{ online }} online · {{ offline }} offline</span>
    <span>{{ avgFps }} FPS avg</span>
  </footer>
</template>

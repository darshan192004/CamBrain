<script setup>
// Event ticker (design §4, plan D6 — no websocket): polls the five
// newest events every 10s and renders them into the shell's aria-live
// region; a click opens the event detail. The interval is cleared on
// unmount so leaving the screen never leaks a poller.
import { onBeforeUnmount, onMounted } from "vue";

import { useEventsStore } from "../stores/events.js";

const POLL_MS = 10_000;

const store = useEventsStore();

let timer = null;

onMounted(() => {
  store.load();
  timer = setInterval(() => store.load(), POLL_MS);
});

onBeforeUnmount(() => {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
});
</script>

<template>
  <nav
    data-testid="event-ticker"
    aria-label="Recent events"
    class="border-t border-border bg-bg-surface px-4 py-1"
  >
    <ul v-if="store.events.length" class="flex flex-wrap gap-4">
      <li v-for="event in store.events" :key="event.id">
        <RouterLink
          :to="`/events/${event.id}`"
          class="flex items-center gap-2 text-xs hover:bg-bg-raised"
        >
          <time class="text-text-secondary">{{
            event.started_at.slice(11, 19)
          }}</time>
          <span class="text-text-primary">{{ event.summary }}</span>
          <span class="text-text-secondary">{{ event.camera?.name }}</span>
        </RouterLink>
      </li>
    </ul>
    <p v-else class="text-xs text-text-secondary">No recent events.</p>
  </nav>
</template>

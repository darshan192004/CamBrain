<script setup>
// Event ticker (design §4): opens the /ws/alerts socket for immediate
// updates (API A3) while keeping the 10s poll as the degradation path —
// a dead socket falls back to Phase-4 polling instead of silence. Both
// timers are torn down on unmount so leaving the screen never leaks a
// poller or a reconnect loop.
import { onBeforeUnmount, onMounted } from "vue";

import { connectAlerts } from "../api/alertsSocket.js";
import { useEventsStore } from "../stores/events.js";

const POLL_MS = 10_000;

const store = useEventsStore();

let timer = null;
let socketHandle = null;

onMounted(() => {
  store.load();
  timer = setInterval(() => store.load(), POLL_MS);
  socketHandle = connectAlerts({
    onEvent: (event) => store.upsert(event),
    onOpen: () => store.load(), // resync after every (re)connect
  });
});

onBeforeUnmount(() => {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
  socketHandle?.close();
  socketHandle = null;
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

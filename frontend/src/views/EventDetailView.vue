<script setup>
// Route screen for /events/:id: loads the event, then its camera's frame
// size so the overlay scales in real pixel space (fallback 640x360).
// Acknowledge round-trips through POST /events/{id}/acknowledge
// (idempotent) and replaces the loaded event.
import { onMounted, ref } from "vue";

import { get, post } from "../api/client.js";
import EventDetail from "../events/EventDetail.vue";

const props = defineProps({
  id: {
    type: [String, Number],
    required: true,
  },
});

const event = ref(null);
const frameWidth = ref(640);
const frameHeight = ref(360);
const error = ref("");

/**
 * Load the event, then its camera's frame size for the overlay. A frame
 * size failure keeps the default — the still still renders.
 * @returns {Promise<void>} settles after both requests
 */
async function load() {
  error.value = "";
  try {
    event.value = await get(`/events/${props.id}`);
    try {
      const camera = await get(`/cameras/${event.value.camera.id}`);
      frameWidth.value = camera.frame_width ?? 640;
      frameHeight.value = camera.frame_height ?? 360;
    } catch {
      // Keep the default frame size — the still still renders.
    }
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "Loading the event failed.";
  }
}

/**
 * Acknowledge this event; the response replaces the local row.
 * @returns {Promise<void>} settles after the request
 */
async function ack() {
  try {
    event.value = await post(`/events/${props.id}/acknowledge`);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Acknowledging failed.";
  }
}

onMounted(load);
</script>

<template>
  <section class="grid gap-3 p-6">
    <h1 class="text-xl font-semibold text-text-primary">Event #{{ id }}</h1>

    <p
      v-if="error"
      data-testid="event-error"
      class="text-sm text-alert-critical"
    >
      {{ error }}
    </p>

    <EventDetail
      v-if="event"
      :event="event"
      :frame-width="frameWidth"
      :frame-height="frameHeight"
      @ack="ack"
    />
    <p v-else-if="!error" class="text-sm text-text-secondary">Loading…</p>
  </section>
</template>

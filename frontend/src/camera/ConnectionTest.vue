<script setup>
// ConnectionTest (plan 4.11, design §4): the add-dialog's diagnostic probe.
// It POSTs the unsaved draft to /cameras/test (API Cameras /test), where
// ok:false is data, not an HTTP failure — the six typed error_codes carry
// installer-facing copy, and only a real envelope (422/403/network) lands
// in the HTTP-error slot.
import { ref } from "vue";

import { ApiError, post } from "../api/client.js";

const props = defineProps({
  /** CameraCreate-shaped draft body (name + rtsp_url + optional creds). */
  payload: { type: Object, required: true },
});

const ERROR_COPY = {
  AUTH_FAILED: "Check the username and password.",
  CONNECT_TIMEOUT:
    "The camera did not respond in time. Check the address and network.",
  HOST_UNREACHABLE:
    "Could not reach the camera. Check the IP address and that it is on.",
  NO_SUCH_STREAM:
    "That stream path does not exist on the camera. Check the channel.",
  DECODE_FAILED:
    "Connected, but the video could not be decoded. It may use an unsupported codec.",
  CANCELLED: "The connection was cancelled before a frame arrived.",
};

const testing = ref(false);
const result = ref(null);
const httpError = ref("");

/**
 * Probe the draft credentials. A 200 body with ok:false renders through the
 * copy table; only a thrown ApiError (envelope or network) fills httpError.
 * @returns {Promise<void>} settles when the probe result is rendered
 */
async function run() {
  testing.value = true;
  result.value = null;
  httpError.value = "";
  try {
    result.value = await post("/cameras/test", props.payload);
  } catch (err) {
    httpError.value =
      err instanceof ApiError
        ? err.message
        : "Something went wrong. Please try again.";
  } finally {
    testing.value = false;
  }
}
</script>

<template>
  <div class="mt-4">
    <button
      type="button"
      data-testid="test-connection"
      class="rounded-[var(--radius-control)] border border-border px-4 py-2 text-sm font-medium text-text-primary transition-colors duration-[var(--dur-base)] hover:bg-bg-raised disabled:cursor-not-allowed disabled:opacity-50"
      :disabled="testing || !payload.rtsp_url"
      @click="run"
    >
      Test connection
    </button>

    <p
      v-if="testing"
      data-testid="test-spinner"
      class="mt-3 text-sm text-text-secondary"
      role="status"
    >
      Testing connection…
    </p>

    <p
      v-if="result && result.ok"
      data-testid="test-success"
      class="mt-3 text-sm text-alert-success"
      role="status"
    >
      {{ result.message }}
      <span v-if="result.latency_ms != null">({{ result.latency_ms }} ms)</span>
    </p>

    <p
      v-if="result && !result.ok"
      data-testid="test-error"
      class="mt-3 text-sm text-alert-critical"
      role="alert"
    >
      {{ ERROR_COPY[result.error_code] ?? result.message }}
    </p>

    <p
      v-if="httpError"
      data-testid="test-http-error"
      class="mt-3 text-sm text-alert-critical"
      role="alert"
    >
      {{ httpError }}
    </p>
  </div>
</template>

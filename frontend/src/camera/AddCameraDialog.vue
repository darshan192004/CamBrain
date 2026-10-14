<script setup>
// AddCameraDialog (plan 4.11): the CameraCreate form plus the ConnectionTest
// probe. 422 renders inline on the envelope's `field`; other envelopes land
// at the dialog level; a successful create appends to the store (the tile
// appears) and closes the dialog.
import { computed, reactive, ref } from "vue";

import { ApiError } from "../api/client.js";
import { useCamerasStore } from "../stores/cameras.js";
import ConnectionTest from "./ConnectionTest.vue";

const emit = defineEmits(["close"]);
const store = useCamerasStore();

const form = reactive({
  name: "",
  rtsp_url: "",
  username: "",
  password: "",
  enabled: true,
  sample_fps: 2,
  motion_threshold: 0.02,
});

/** @type {Record<string, string>} inline 422 messages keyed by field */
const fieldErrors = reactive({});
const dialogError = ref("");
const busy = ref(false);

/**
 * Build a CameraCreate body. Blank credentials are omitted — an empty
 * password is a 422 (API Cameras), and an absent username is null.
 * @returns {object} CameraCreate payload
 */
function payload() {
  const body = {
    name: form.name,
    rtsp_url: form.rtsp_url,
    enabled: form.enabled,
    sample_fps: Number(form.sample_fps),
    motion_threshold: Number(form.motion_threshold),
  };
  if (form.username) body.username = form.username;
  if (form.password) body.password = form.password;
  return body;
}

/** Draft body for the connection probe (reactive wrapper for the child). */
const draft = computed(() => payload());

/**
 * Save the camera: append to the store and close on success; map a 422
 * envelope's field to its inline slot, everything else to the dialog level.
 * @returns {Promise<void>} settles when the create attempt is rendered
 */
async function save() {
  busy.value = true;
  dialogError.value = "";
  for (const key of Object.keys(fieldErrors)) delete fieldErrors[key];
  try {
    await store.create(payload());
    emit("close");
  } catch (err) {
    if (err instanceof ApiError && err.field) {
      fieldErrors[err.field] = err.message;
    } else {
      dialogError.value =
        err instanceof ApiError
          ? err.message
          : "Something went wrong. Please try again.";
    }
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    data-testid="add-camera-dialog"
    role="dialog"
    aria-modal="true"
    aria-labelledby="add-camera-title"
    tabindex="-1"
    @keydown.esc="emit('close')"
  >
    <form
      class="max-h-full w-full max-w-md overflow-y-auto rounded-[var(--radius-card)] border border-border bg-bg-surface p-6"
      novalidate
      @submit.prevent="save"
    >
      <h2 id="add-camera-title" class="text-lg font-semibold text-text-primary">
        Add camera
      </h2>
      <p class="mt-1 text-xs text-text-secondary">
        RTSP cameras only. Test the connection before saving.
      </p>

      <label
        class="mt-4 block text-xs font-medium text-text-secondary"
        for="camera-name"
      >
        Name
      </label>
      <input
        id="camera-name"
        v-model="form.name"
        data-testid="field-name"
        class="mt-1 w-full rounded-[var(--radius-control)] border border-border bg-bg-raised px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
        name="name"
        required
      />
      <p
        v-if="fieldErrors.name"
        data-testid="field-error-name"
        class="mt-1 text-xs text-alert-critical"
        role="alert"
      >
        {{ fieldErrors.name }}
      </p>

      <label
        class="mt-4 block text-xs font-medium text-text-secondary"
        for="camera-rtsp"
      >
        RTSP URL
      </label>
      <input
        id="camera-rtsp"
        v-model="form.rtsp_url"
        data-testid="field-rtsp_url"
        class="mt-1 w-full rounded-[var(--radius-control)] border border-border bg-bg-raised px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
        name="rtsp_url"
        placeholder="rtsp://192.168.1.10:554/stream1"
        required
      />
      <p
        v-if="fieldErrors.rtsp_url"
        data-testid="field-error-rtsp_url"
        class="mt-1 text-xs text-alert-critical"
        role="alert"
      >
        {{ fieldErrors.rtsp_url }}
      </p>

      <div class="mt-4 grid grid-cols-2 gap-3">
        <div>
          <label
            class="block text-xs font-medium text-text-secondary"
            for="camera-username"
          >
            Username
          </label>
          <input
            id="camera-username"
            v-model="form.username"
            data-testid="field-username"
            class="mt-1 w-full rounded-[var(--radius-control)] border border-border bg-bg-raised px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
            name="username"
            autocomplete="off"
          />
        </div>
        <div>
          <label
            class="block text-xs font-medium text-text-secondary"
            for="camera-password"
          >
            Password
          </label>
          <input
            id="camera-password"
            v-model="form.password"
            data-testid="field-password"
            class="mt-1 w-full rounded-[var(--radius-control)] border border-border bg-bg-raised px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
            name="password"
            type="password"
            autocomplete="new-password"
          />
        </div>
      </div>

      <div class="mt-4 grid grid-cols-2 gap-3">
        <div>
          <label
            class="block text-xs font-medium text-text-secondary"
            for="camera-fps"
          >
            Sample FPS (2–5)
          </label>
          <input
            id="camera-fps"
            v-model.number="form.sample_fps"
            data-testid="field-sample_fps"
            class="mt-1 w-full rounded-[var(--radius-control)] border border-border bg-bg-raised px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
            name="sample_fps"
            type="number"
            min="2"
            max="5"
            step="1"
          />
        </div>
        <div>
          <label
            class="block text-xs font-medium text-text-secondary"
            for="camera-threshold"
          >
            Motion threshold
          </label>
          <input
            id="camera-threshold"
            v-model.number="form.motion_threshold"
            data-testid="field-motion_threshold"
            class="mt-1 w-full rounded-[var(--radius-control)] border border-border bg-bg-raised px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
            name="motion_threshold"
            type="number"
            min="0"
            max="1"
            step="0.01"
          />
        </div>
      </div>

      <label class="mt-4 flex items-center gap-2 text-sm text-text-primary">
        <input
          v-model="form.enabled"
          data-testid="field-enabled"
          name="enabled"
          type="checkbox"
          class="size-4 accent-[var(--accent)]"
        />
        Enabled
      </label>

      <ConnectionTest :payload="draft" />

      <p
        v-if="dialogError"
        data-testid="dialog-error"
        class="mt-4 text-sm text-alert-critical"
        role="alert"
      >
        {{ dialogError }}
      </p>

      <div class="mt-6 flex justify-end gap-3">
        <button
          type="button"
          data-testid="dialog-cancel"
          class="rounded-[var(--radius-control)] border border-border px-4 py-2 text-sm font-medium text-text-primary transition-colors duration-[var(--dur-base)] hover:bg-bg-raised"
          @click="emit('close')"
        >
          Cancel
        </button>
        <button
          type="submit"
          data-testid="dialog-submit"
          class="rounded-[var(--radius-control)] bg-accent-fill px-4 py-2 text-sm font-medium text-white transition-colors duration-[var(--dur-base)] hover:bg-accent-fill-hover disabled:opacity-50"
          :disabled="busy"
        >
          {{ busy ? "Saving…" : "Add camera" }}
        </button>
      </div>
    </form>
  </div>
</template>

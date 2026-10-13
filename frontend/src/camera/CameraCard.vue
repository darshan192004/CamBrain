<script setup>
// Camera settings card (friend's detail look): enabled switch patches
// immediately, name/sample_fps save as a pair, delete asks once and then
// navigates back via the parent. Viewers never see mutating controls —
// defence in depth with the API's AdminDep.
import { ref, watch } from "vue";

import { del, patch } from "../api/client.js";
import RoleGate from "../auth/RoleGate.vue";
import { useAuthStore } from "../stores/auth.js";

const props = defineProps({
  camera: {
    type: Object,
    required: true,
  },
});
const emit = defineEmits(["saved", "deleted"]);

useAuthStore();
const name = ref(props.camera.name);
const fps = ref(props.camera.sample_fps);
const confirming = ref(false);
const busy = ref(false);
const error = ref("");

watch(
  () => props.camera,
  (cam) => {
    name.value = cam.name;
    fps.value = cam.sample_fps;
  },
  { deep: true },
);

/**
 * Flip the enabled switch straight into a PATCH (design: one control,
 * one request).
 * @param {Event} ev change event from the switch
 * @returns {Promise<void>} resolves after the PATCH settles
 */
async function toggleEnabled(ev) {
  busy.value = true;
  error.value = "";
  try {
    const updated = await patch(`/cameras/${props.camera.id}`, {
      enabled: /** @type {HTMLInputElement} */ (ev.target).checked,
    });
    emit("saved", updated);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Saving failed.";
  } finally {
    busy.value = false;
  }
}

/**
 * Save the name and sample_fps pair.
 * @returns {Promise<void>} resolves after the PATCH settles
 */
async function save() {
  busy.value = true;
  error.value = "";
  try {
    const updated = await patch(`/cameras/${props.camera.id}`, {
      name: name.value,
      sample_fps: Number(fps.value),
    });
    emit("saved", updated);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Saving failed.";
  } finally {
    busy.value = false;
  }
}

/**
 * Hard-delete the camera after the confirm step (204 → no body).
 * @returns {Promise<void>} resolves after the DELETE settles
 */
async function destroy() {
  busy.value = true;
  error.value = "";
  try {
    await del(`/cameras/${props.camera.id}`);
    emit("deleted");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Deleting failed.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section
    aria-label="Camera settings"
    class="grid gap-3 rounded-[10px] border border-border bg-bg-surface p-4"
  >
    <header class="flex items-center justify-between gap-3">
      <h2 class="text-lg font-semibold text-text-primary">Settings</h2>
      <RoleGate :roles="['admin']">
        <label class="inline-flex items-center gap-2 text-sm text-text-primary">
          <input
            :checked="props.camera.enabled"
            data-testid="card-enabled"
            type="checkbox"
            :disabled="busy"
            @change="toggleEnabled"
          />
          Enabled
        </label>
      </RoleGate>
    </header>

    <p class="font-mono text-xs break-all text-text-secondary">
      {{ props.camera.rtsp_url }}
      <template v-if="props.camera.has_password"> (password stored) </template>
    </p>

    <p v-if="error" data-testid="card-error" class="text-sm text-red-400">
      {{ error }}
    </p>

    <RoleGate :roles="['admin']">
      <div class="grid gap-3">
        <div class="grid gap-1">
          <label for="card-name" class="text-sm text-text-secondary">
            Name
          </label>
          <input
            id="card-name"
            v-model="name"
            data-testid="card-name"
            type="text"
            class="rounded-md border border-border bg-bg-base px-3 py-2 text-sm text-text-primary"
          />
        </div>
        <div class="grid gap-1">
          <label for="card-fps" class="text-sm text-text-secondary">
            Sample rate (fps, 2–5)
          </label>
          <input
            id="card-fps"
            v-model.number="fps"
            data-testid="card-fps"
            type="number"
            min="2"
            max="5"
            class="rounded-md border border-border bg-bg-base px-3 py-2 text-sm text-text-primary"
          />
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <button
            type="button"
            data-testid="card-save"
            :disabled="busy"
            class="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
            @click="save"
          >
            Save
          </button>
          <button
            type="button"
            data-testid="card-delete"
            :disabled="busy"
            class="rounded-md border border-border px-4 py-2 text-sm text-text-primary hover:bg-bg-raised"
            @click="confirming = true"
          >
            Delete camera
          </button>
        </div>
        <p
          v-if="confirming"
          class="rounded-md border border-border p-3 text-sm text-text-secondary"
        >
          Delete this camera? Its ROIs and rules go with it; event history is
          kept.
          <span class="mt-2 flex gap-2">
            <button
              type="button"
              data-testid="card-confirm"
              :disabled="busy"
              class="rounded-md border border-red-500/60 px-3 py-1 text-xs text-red-400"
              @click="destroy"
            >
              Yes, delete
            </button>
            <button
              type="button"
              data-testid="card-cancel"
              class="rounded-md border border-border px-3 py-1 text-xs text-text-primary"
              @click="confirming = false"
            >
              Cancel
            </button>
          </span>
        </p>
      </div>
    </RoleGate>
  </section>
</template>

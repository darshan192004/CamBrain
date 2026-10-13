<script setup>
// ROI editor (design §5): the zone list stays visible — coverage and the
// class filter are properties of a zone, not something you enter an edit
// mode to see. Nothing commits until Save (§5.9): name, polygon and class
// filter live in a draft that Cancel restores to the last-saved state and
// that blur never touches.
import { computed, ref, watch } from "vue";

import { del, patch, post } from "../api/client.js";
import { useAuthStore } from "../stores/auth.js";
import ClassFilter from "./ClassFilter.vue";
import RoiCanvas from "./RoiCanvas.vue";
import ZoneList from "./ZoneList.vue";

const props = defineProps({
  cameraId: {
    type: [Number, String],
    required: true,
  },
  rois: {
    type: Array,
    default: () => [],
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

const emit = defineEmits(["changed"]);

const auth = useAuthStore();
const canEdit = computed(() => auth.role === "admin");

const zones = ref([...props.rois]);
watch(
  () => props.rois,
  (next) => {
    zones.value = [...next];
  },
);

const selectedId = ref(null);
const draftName = ref("");
const draftPoints = ref([]);
const draftClasses = ref(["person"]);
const lastSaved = ref({ name: "", points: [], classes: ["person"] });
const error = ref("");
const saving = ref(false);

const dirty = computed(
  () =>
    draftName.value !== lastSaved.value.name ||
    JSON.stringify(draftPoints.value) !==
      JSON.stringify(lastSaved.value.points) ||
    JSON.stringify(draftClasses.value) !==
      JSON.stringify(lastSaved.value.classes),
);

/**
 * Replace the draft with a saved state (deep copies).
 * @param {{name: string, points: number[][], classes: string[]}} state state to load
 * @returns {void}
 */
function loadState(state) {
  draftName.value = state.name;
  draftPoints.value = state.points.map((pt) => [...pt]);
  draftClasses.value = [...state.classes];
}

/**
 * Select a zone: its name, polygon and classes become the draft, which is
 * by definition clean until the operator changes something.
 * @param {number} id zone id
 * @returns {void}
 */
function selectZone(id) {
  const zone = zones.value.find((z) => z.id === id);
  if (!zone) return;
  selectedId.value = id;
  const classes = [...(zone.class_filter ?? ["person"])];
  const points = zone.points.map((pt) => [...pt]);
  draftName.value = zone.name;
  draftPoints.value = points;
  draftClasses.value = classes;
  lastSaved.value = { name: zone.name, points, classes };
  error.value = "";
}

/**
 * Duplicate a zone into an unsaved copy: dirty immediately, POSTed only
 * when the operator saves it as a new zone.
 * @param {number} id zone id to copy
 * @returns {void}
 */
function duplicateZone(id) {
  const zone = zones.value.find((z) => z.id === id);
  if (!zone) return;
  selectedId.value = null;
  draftName.value = `Copy of ${zone.name}`;
  draftPoints.value = zone.points.map((pt) => [...pt]);
  draftClasses.value = [...(zone.class_filter ?? ["person"])];
  error.value = "";
}

/**
 * Delete a zone immediately (row disappears only after the API accepts).
 * @param {number} id zone id
 * @returns {Promise<void>} settles when the request completes
 */
async function removeZone(id) {
  if (!canEdit.value) return;
  error.value = "";
  try {
    await del(`/rois/${id}`);
    zones.value = zones.value.filter((z) => z.id !== id);
    if (selectedId.value === id) {
      selectedId.value = null;
      loadState({ name: "", points: [], classes: ["person"] });
    }
    emit("changed");
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "Deleting the zone failed.";
  }
}

/**
 * Persist the draft: POST for a new zone, PATCH for the selected one. Both
 * carry the full point list (API.md destructive-edit rule). On success the
 * local zone row and the clean baseline update together.
 * @returns {Promise<void>} settles when the request completes
 */
async function save() {
  if (!dirty.value || saving.value) return;
  const name = draftName.value.trim();
  if (!name) {
    error.value = "Give the zone a name.";
    return;
  }
  if (draftPoints.value.length < 3) {
    error.value = "A zone needs at least three vertices.";
    return;
  }
  const sent = { name, points: draftPoints.value.map((pt) => [...pt]) };
  const classes = [...draftClasses.value];
  const payload = { ...sent, class_filter: classes };
  saving.value = true;
  error.value = "";
  try {
    const isNew = selectedId.value === null;
    const saved = isNew
      ? await post(`/cameras/${props.cameraId}/rois`, payload)
      : await patch(`/rois/${selectedId.value}`, payload);
    const row = { ...saved, ...payload };
    if (isNew) {
      zones.value = [...zones.value, row];
      selectedId.value = saved.id;
    } else {
      zones.value = zones.value.map((z) =>
        z.id === selectedId.value ? row : z,
      );
    }
    draftName.value = sent.name;
    lastSaved.value = { name: sent.name, points: sent.points, classes };
    emit("changed");
  } catch (err) {
    error.value =
      err instanceof Error ? err.message : "Saving the zone failed.";
  } finally {
    saving.value = false;
  }
}

/**
 * Restore the draft to the last-saved state — commits nothing.
 * @returns {void}
 */
function cancel() {
  loadState(lastSaved.value);
  error.value = "";
}
</script>

<template>
  <div class="grid gap-3 lg:grid-cols-[minmax(220px,260px)_1fr]">
    <ZoneList
      :zones="zones"
      :selected-id="selectedId"
      :can-edit="canEdit"
      @select="selectZone"
      @duplicate="duplicateZone"
      @delete="removeZone"
    />

    <div class="grid content-start gap-3">
      <div class="flex flex-wrap items-center gap-2">
        <label for="zone-name" class="text-sm text-text-secondary">
          Zone name
        </label>
        <input
          id="zone-name"
          v-model="draftName"
          data-testid="zone-name"
          type="text"
          maxlength="128"
          :disabled="!canEdit"
          class="min-w-40 flex-1 rounded-md border border-border bg-bg-base px-2 py-1.5 text-sm text-text-primary disabled:opacity-50"
        />
        <span
          v-if="dirty"
          data-testid="dirty-marker"
          class="rounded-full border border-alert-warning px-2 py-0.5 text-[10px] tracking-wide text-alert-warning uppercase"
        >
          Unsaved
        </span>
      </div>

      <RoiCanvas
        :camera-id="cameraId"
        :frame-width="frameWidth"
        :frame-height="frameHeight"
        :initial-points="draftPoints"
        @update="draftPoints = $event"
        @closed="draftPoints = $event"
        @cancelled="cancel"
      />

      <ClassFilter v-model="draftClasses" :disabled="!canEdit" />

      <div v-if="canEdit" class="flex flex-wrap gap-2">
        <button
          type="button"
          data-testid="roi-save"
          :disabled="!dirty || saving"
          class="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
          @click="save"
        >
          Save zone
        </button>
        <button
          type="button"
          data-testid="roi-cancel"
          :disabled="!dirty"
          class="rounded-md border border-border px-4 py-2 text-sm text-text-primary hover:bg-bg-raised disabled:opacity-50"
          @click="cancel"
        >
          Cancel
        </button>
      </div>

      <p v-if="error" data-testid="roi-error" class="text-sm text-red-400">
        {{ error }}
      </p>
    </div>
  </div>
</template>

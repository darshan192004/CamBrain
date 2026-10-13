<script setup>
// Frozen-snapshot ROI drawer (design §5.4, §11). Draft vertices live in
// normalised 0..1 space; display pixels are derived through a letterbox
// transform so only normalised coordinates ever leave via `closed`.
// A draft under 500px² at source resolution is blocked with an explanation
// (design §5.5) — that floor is the accidental-double-click guard.
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { request } from "../api/client.js";
import { fromPixels, minAreaPx, toPixels } from "./geometry.js";
import VertexHandle from "./VertexHandle.vue";

const props = defineProps({
  cameraId: {
    type: [Number, String],
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

const emit = defineEmits(["closed", "cancelled"]);

const MIN_VERTICES = 3;
const MIN_AREA_PX = 500;
const CLOSE_RADIUS_PX = 8;

const surface = ref(null);
const snapshotUrl = ref("");
const snapshotError = ref("");
const draft = ref([]);
const selectedIndex = ref(-1);
const dragging = ref(-1);
const minAreaError = ref("");

let objectUrl = null;

/**
 * Letterbox transform: fit frameWidth×frameHeight inside the surface rect.
 * @param {DOMRect} rect surface bounding box
 * @returns {{scale: number, offX: number, offY: number}} display mapping
 */
function letterbox(rect) {
  const scale = Math.min(
    rect.width / props.frameWidth,
    rect.height / props.frameHeight,
  );
  const offX = (rect.width - props.frameWidth * scale) / 2;
  const offY = (rect.height - props.frameHeight * scale) / 2;
  return { scale, offX, offY };
}

/**
 * Normalised point → surface display pixels (through the letterbox).
 * @param {number[]} pt [x, y] in 0..1
 * @returns {number[]} [dx, dy] in surface pixels
 */
function toDisplay(pt) {
  const rect = surface.value.getBoundingClientRect();
  const { scale, offX, offY } = letterbox(rect);
  const [px, py] = toPixels(pt, props.frameWidth, props.frameHeight);
  return [offX + px * scale, offY + py * scale];
}

/**
 * Surface display pixels → normalised point (clamped to the frame).
 * @param {number} dx display x
 * @param {number} dy display y
 * @returns {number[]} [x, y] in 0..1
 */
function fromDisplay(dx, dy) {
  const rect = surface.value.getBoundingClientRect();
  const { scale, offX, offY } = letterbox(rect);
  const fx = (dx - offX) / scale;
  const fy = (dy - offY) / scale;
  return fromPixels([fx, fy], props.frameWidth, props.frameHeight);
}

const displayPoints = computed(() => draft.value.map((pt) => toDisplay(pt)));

const polygonPoints = computed(() =>
  displayPoints.value.map(([x, y]) => `${x},${y}`).join(" "),
);

/**
 * Try to finish the draft; blocked below the min-area floor.
 * @returns {void}
 */
function tryClose() {
  if (draft.value.length < MIN_VERTICES) return;
  const area = minAreaPx(draft.value, props.frameWidth, props.frameHeight);
  if (area < MIN_AREA_PX) {
    minAreaError.value = `Polygon too small (${Math.round(area)}px² < ${MIN_AREA_PX}px²) — enlarge it before closing.`;
    return;
  }
  minAreaError.value = "";
  emit(
    "closed",
    draft.value.map(([x, y]) => [x, y]),
  );
  draft.value = [];
  selectedIndex.value = -1;
}

/**
 * Cancel the whole draft (Esc).
 * @returns {void}
 */
function cancelDraft() {
  draft.value = [];
  selectedIndex.value = -1;
  minAreaError.value = "";
  emit("cancelled");
}

/**
 * Surface click: add a vertex, or close when clicking the first vertex.
 * @param {MouseEvent} ev click event
 * @returns {void}
 */
function onSurfaceClick(ev) {
  if (!surface.value) return;
  const rect = surface.value.getBoundingClientRect();
  const dx = ev.clientX - rect.left;
  const dy = ev.clientY - rect.top;
  if (draft.value.length >= MIN_VERTICES) {
    const [fx, fy] = toDisplay(draft.value[0]);
    if (Math.hypot(dx - fx, dy - fy) <= CLOSE_RADIUS_PX) {
      tryClose();
      return;
    }
  }
  draft.value = [...draft.value, fromDisplay(dx, dy)];
  selectedIndex.value = draft.value.length - 1;
  minAreaError.value = "";
}

/**
 * Surface keyboard: Enter closes, Escape cancels.
 * @param {KeyboardEvent} ev key event
 * @returns {void}
 */
function onSurfaceKey(ev) {
  if (ev.key === "Enter") tryClose();
  else if (ev.key === "Escape") cancelDraft();
}

/**
 * Vertex keyboard (design §11): arrows nudge 1px, Shift 10px, Enter closes,
 * Escape cancels.
 * @param {number} index vertex index
 * @param {KeyboardEvent} ev key event
 * @returns {void}
 */
function onVertexKey(index, ev) {
  selectedIndex.value = index;
  if (ev.key === "Enter") {
    tryClose();
    return;
  }
  if (ev.key === "Escape") {
    cancelDraft();
    return;
  }
  const step = ev.shiftKey ? 10 : 1;
  const dx =
    ev.key === "ArrowRight" ? step : ev.key === "ArrowLeft" ? -step : 0;
  const dy = ev.key === "ArrowDown" ? step : ev.key === "ArrowUp" ? -step : 0;
  if (!dx && !dy) return;
  const [cx, cy] = toDisplay(draft.value[index]);
  draft.value = draft.value.map((pt, i) =>
    i === index ? fromDisplay(cx + dx, cy + dy) : pt,
  );
}

/**
 * Begin dragging a vertex.
 * @param {number} index vertex index
 * @returns {void}
 */
function onVertexPointerdown(index) {
  dragging.value = index;
  selectedIndex.value = index;
}

/**
 * Surface pointermove: update the dragged vertex.
 * @param {MouseEvent} ev pointer event
 * @returns {void}
 */
function onSurfacePointermove(ev) {
  if (dragging.value < 0 || !surface.value) return;
  const rect = surface.value.getBoundingClientRect();
  const next = fromDisplay(ev.clientX - rect.left, ev.clientY - rect.top);
  draft.value = draft.value.map((pt, i) => (i === dragging.value ? next : pt));
}

/**
 * End any drag.
 * @returns {void}
 */
function onSurfacePointerup() {
  dragging.value = -1;
}

onMounted(async () => {
  try {
    const bytes = await request(`/cameras/${props.cameraId}/snapshot`, {
      method: "POST",
      raw: true,
    });
    objectUrl = URL.createObjectURL(new Blob([bytes], { type: "image/jpeg" }));
    snapshotUrl.value = objectUrl;
  } catch (err) {
    snapshotError.value =
      err instanceof Error ? err.message : "Could not capture a snapshot.";
  }
});

onBeforeUnmount(() => {
  if (objectUrl) URL.revokeObjectURL(objectUrl);
});
</script>

<template>
  <div
    ref="surface"
    data-testid="roi-surface"
    class="relative select-none rounded-[10px] border border-border bg-bg-base"
    role="application"
    aria-label="ROI drawing surface. Click to add vertices, Enter closes, Escape cancels."
    tabindex="0"
    @click="onSurfaceClick"
    @keydown="onSurfaceKey"
    @pointermove="onSurfacePointermove"
    @pointerup="onSurfacePointerup"
  >
    <img
      v-if="snapshotUrl"
      data-testid="roi-snapshot"
      :src="snapshotUrl"
      alt="Frozen camera snapshot for ROI drawing"
      class="block h-full w-full object-contain"
      draggable="false"
    />
    <p
      v-else-if="snapshotError"
      data-testid="snapshot-error"
      class="p-4 text-sm text-red-400"
    >
      {{ snapshotError }}
    </p>
    <p
      v-else
      data-testid="snapshot-loading"
      class="p-4 text-sm text-text-secondary"
    >
      Capturing snapshot…
    </p>

    <svg
      class="pointer-events-none absolute inset-0 h-full w-full"
      aria-hidden="true"
    >
      <polygon
        v-if="draft.length >= MIN_VERTICES"
        :points="polygonPoints"
        fill="var(--roi-fill)"
        stroke="var(--roi-stroke)"
        stroke-width="2"
      />
      <polyline
        v-else-if="draft.length === 2"
        :points="polygonPoints"
        fill="none"
        stroke="var(--roi-stroke)"
        stroke-width="2"
      />
      <VertexHandle
        v-for="(pt, i) in displayPoints"
        :key="i"
        class="pointer-events-auto"
        :index="i"
        :x="pt[0]"
        :y="pt[1]"
        :selected="i === selectedIndex"
        @select="selectedIndex = $event"
        @pointerdown="onVertexPointerdown"
        @keydown="onVertexKey"
      />
    </svg>

    <p
      v-if="minAreaError"
      data-testid="min-area-error"
      class="absolute bottom-2 left-2 rounded-md border border-red-500/60 bg-bg-base px-2 py-1 text-xs text-red-400"
      role="alert"
    >
      {{ minAreaError }}
    </p>
  </div>
</template>

<style scoped>
[data-testid="roi-surface"] {
  aspect-ratio: 16 / 9;
  cursor: crosshair;
}
</style>

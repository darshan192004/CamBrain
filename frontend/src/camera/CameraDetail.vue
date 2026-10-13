<script setup>
// /cameras/:id — the camera detail screen (design §3). Loads the camera,
// its ROIs and its rules once on mount; the rules list mutates through
// the API client and asks this view to refetch. The ROI canvas itself
// lands in task 4.14 — this view reserves the slot so the layout is
// stable. 404 (stale link, deleted camera) renders as an inline message,
// not a crash.
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { get } from "../api/client.js";
import CameraCard from "./CameraCard.vue";
import RulesList from "../rules/RulesList.vue";

const props = defineProps({
  id: {
    type: String,
    required: true,
  },
});
const router = useRouter();

const camera = ref(null);
const rois = ref([]);
const rules = ref([]);
const error = ref("");
const loading = ref(true);

/**
 * Load the camera, its ROIs and its rules in parallel.
 * @returns {Promise<void>} resolves when every request has settled
 */
async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [cam, roiRows, ruleRows] = await Promise.all([
      get(`/cameras/${props.id}`),
      get(`/cameras/${props.id}/rois`),
      get(`/cameras/${props.id}/rules`),
    ]);
    camera.value = cam;
    rois.value = Array.isArray(roiRows) ? roiRows : [];
    rules.value = Array.isArray(ruleRows) ? ruleRows : [];
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Loading failed.";
  } finally {
    loading.value = false;
  }
}

/**
 * After a delete, go back to the grid (the camera no longer exists).
 * @returns {void}
 */
function goBack() {
  router.push({ name: "cameras" });
}

onMounted(load);
</script>

<template>
  <section class="grid gap-4 p-4">
    <p
      v-if="loading"
      data-testid="detail-loading"
      class="text-sm text-text-secondary"
    >
      Loading camera…
    </p>
    <p
      v-else-if="error"
      data-testid="detail-error"
      class="text-sm text-red-400"
    >
      {{ error }}
    </p>
    <template v-else-if="camera">
      <header class="flex flex-wrap items-baseline justify-between gap-2">
        <h1 class="text-xl font-semibold text-text-primary">
          {{ camera.name }}
        </h1>
        <p class="font-mono text-xs text-text-secondary">
          {{ camera.frame_width ?? "—" }}×{{ camera.frame_height ?? "—" }} ·
          {{ camera.sample_fps }} fps sample
        </p>
      </header>

      <CameraCard :camera="camera" @saved="load" @deleted="goBack" />

      <section
        aria-label="Regions of interest"
        class="rounded-[10px] border border-dashed border-border p-4 text-sm text-text-secondary"
      >
        Regions of interest ({{ rois.length }}) — the drawing canvas arrives in
        task 4.14.
      </section>

      <RulesList
        :camera-id="camera.id"
        :rules="rules"
        :rois="rois"
        @changed="load"
      />
    </template>
  </section>
</template>

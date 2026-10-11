<script setup>
// Live grid (design §4): one tile per camera plus the admin-only add
// tile; the auto-fill columns and 16:9 tiles keep the layout stable from
// a 1366px shop PC to a 4K monitor without breakpoints. The add tile
// opens AddCameraDialog — viewer role never renders the tile, so the
// dialog is unreachable (defence in depth with the API's AdminDep).
import { onMounted, ref } from "vue";

import RoleGate from "../auth/RoleGate.vue";
import { useCamerasStore } from "../stores/cameras.js";
import AddCameraDialog from "./AddCameraDialog.vue";
import CameraTile from "./CameraTile.vue";

const store = useCamerasStore();
const showAdd = ref(false);

onMounted(() => {
  store.load();
});
</script>

<template>
  <section class="flex flex-col gap-4 p-4">
    <h1 class="text-xl font-semibold text-text-primary">Cameras</h1>
    <div
      data-testid="camera-grid"
      class="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4"
    >
      <CameraTile
        v-for="camera in store.cameras"
        :key="camera.id"
        :camera="camera"
      />
      <RoleGate :roles="['admin']">
        <button
          type="button"
          data-testid="add-camera-tile"
          class="flex aspect-video items-center justify-center rounded-[10px] border border-dashed border-border bg-bg-surface text-sm text-text-secondary hover:border-text-secondary hover:text-text-primary"
          @click="showAdd = true"
        >
          + Add camera
        </button>
      </RoleGate>
    </div>
    <AddCameraDialog v-if="showAdd" @close="showAdd = false" />
  </section>
</template>

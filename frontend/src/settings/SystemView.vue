<script setup>
// System status page (design §3 /settings/system): hardware tier, model,
// storage, and live per-camera stats from /system/status, plus the
// unauthenticated /system/health ping shown as service status. The live
// backend may report empty hardware/model objects (detection not run yet),
// which render as em dashes — an absent value reads as "unknown", never
// as a broken page. Notifier wiring arrives in Phase 5.
import { computed, onMounted, ref } from "vue";

import { get } from "../api/client.js";

const status = ref(null);
const health = ref(null);
const error = ref("");

/**
 * One hardware figure, tolerant of the stub's empty hardware object.
 * @param {string} key field of `status.hardware`
 * @param {string} [suffix] unit appended when the value exists
 * @returns {string} display text
 */
function hw(key, suffix = "") {
  const value = status.value?.hardware?.[key];
  if (value === undefined || value === null) {
    return "—";
  }
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
  }
  return `${value}${suffix}`;
}

/** Disk usage percentage with unit, or an em dash when unknown. */
const diskPct = computed(() => {
  const value = status.value?.hardware?.disk_used_pct;
  return value === undefined || value === null ? "—" : `${value}%`;
});

/** Model file name, or an em dash when unknown. */
const modelName = computed(() => status.value?.model?.name ?? "—");

/** Camera rows for the stats table, with display-ready stat strings. */
const cameras = computed(() =>
  (status.value?.cameras ?? []).map((camera) => ({
    ...camera,
    fpsText: camera.fps !== undefined ? `${camera.fps} fps` : "",
    framesText:
      camera.frames_processed !== undefined
        ? `${camera.frames_processed} frames`
        : "",
  })),
);

/** Ping colour: green once the liveness probe answers ok. */
const serviceClass = computed(() =>
  health.value?.status === "ok" ? "text-alert-success" : "text-alert-warning",
);

/** One-line service summary: ping, uptime, and both versions. */
const serviceText = computed(() => {
  if (!health.value) {
    return "checking…";
  }
  const ping = `${health.value.status} · up ${health.value.uptime_s}s · v${health.value.version}`;
  return status.value ? `${ping} · dashboard v${status.value.version}` : ping;
});

/**
 * Fetch both endpoints; either failure lands in the inline error slot.
 * @returns {Promise<void>} resolves after the attempt
 */
async function load() {
  try {
    const [live, ping] = await Promise.all([
      get("/system/status"),
      get("/system/health", { auth: false }),
    ]);
    status.value = live;
    health.value = ping;
  } catch (err) {
    error.value = err?.message ?? "Could not read system status.";
  }
}

onMounted(load);
</script>

<template>
  <section class="p-8" data-testid="system-view">
    <h1 class="text-xl font-semibold text-text-primary">System</h1>
    <p
      v-if="error"
      data-testid="system-error"
      role="alert"
      class="mt-2 text-sm text-alert-critical"
    >
      {{ error }}
    </p>

    <p class="mt-2 text-sm text-text-secondary">
      Service:
      <span
        data-testid="service-status"
        :class="serviceClass"
        class="font-medium"
      >
        {{ serviceText }}
      </span>
    </p>

    <dl class="mt-4 flex flex-wrap gap-x-8 gap-y-2 text-sm">
      <div>
        <dt class="text-text-secondary">Hardware tier</dt>
        <dd data-testid="hw-tier" class="font-medium text-text-primary">
          {{ status?.hardware_tier ?? "—" }}
        </dd>
      </div>
      <div>
        <dt class="text-text-secondary">Model</dt>
        <dd data-testid="model-name" class="font-medium text-text-primary">
          {{ modelName }}
        </dd>
      </div>
      <div>
        <dt class="text-text-secondary">Storage used</dt>
        <dd data-testid="disk-pct" class="font-medium text-text-primary">
          {{ diskPct }}
        </dd>
      </div>
    </dl>

    <h2 class="mt-6 text-sm font-semibold text-text-primary">Hardware</h2>
    <dl
      data-testid="hardware-rows"
      class="mt-1 grid grid-cols-2 gap-x-8 gap-y-1 text-sm sm:grid-cols-3 lg:grid-cols-4"
    >
      <div class="flex justify-between gap-3">
        <dt class="text-text-secondary">CPU cores</dt>
        <dd data-testid="hw-cpu-cores" class="text-text-primary">
          {{ hw("cpu_cores") }}
        </dd>
      </div>
      <div class="flex justify-between gap-3">
        <dt class="text-text-secondary">AVX2</dt>
        <dd class="text-text-primary">{{ hw("avx2") }}</dd>
      </div>
      <div class="flex justify-between gap-3">
        <dt class="text-text-secondary">VNNI</dt>
        <dd class="text-text-primary">{{ hw("vnni") }}</dd>
      </div>
      <div class="flex justify-between gap-3">
        <dt class="text-text-secondary">RAM total</dt>
        <dd class="text-text-primary">{{ hw("ram_total_mb", " MB") }}</dd>
      </div>
      <div class="flex justify-between gap-3">
        <dt class="text-text-secondary">RAM used</dt>
        <dd class="text-text-primary">{{ hw("ram_used_mb", " MB") }}</dd>
      </div>
      <div class="flex justify-between gap-3">
        <dt class="text-text-secondary">Disk total</dt>
        <dd class="text-text-primary">{{ hw("disk_total_gb", " GB") }}</dd>
      </div>
    </dl>

    <h2 class="mt-6 text-sm font-semibold text-text-primary">Cameras</h2>
    <ul
      aria-label="Camera stats"
      class="mt-1 divide-y divide-border rounded-md border border-border"
    >
      <li
        v-for="camera in cameras"
        :key="camera.id"
        :data-testid="`camera-row-${camera.id}`"
        class="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm"
      >
        <div class="min-w-0">
          <p class="truncate font-medium text-text-primary">
            {{ camera.name }}
          </p>
          <p
            v-if="camera.last_error"
            class="mt-0.5 text-xs text-alert-critical"
          >
            {{ camera.last_error }}
          </p>
        </div>
        <div class="flex items-center gap-4 text-text-secondary">
          <span class="capitalize">{{ camera.status }}</span>
          <span v-if="camera.fpsText">{{ camera.fpsText }}</span>
          <span v-if="camera.framesText">{{ camera.framesText }}</span>
        </div>
      </li>
    </ul>
  </section>
</template>

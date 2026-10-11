<script setup>
// The authenticated frame (design §4): top bar, role-aware sidebar, the
// routed screen, a persistent aria-live region for the event ticker
// (task 4.10 mounts it here so announcements survive navigation), and the
// status bar. /login renders outside this shell (route meta.public).
import { RouterView } from "vue-router";

import Sidebar from "./Sidebar.vue";
import StatusBar from "./StatusBar.vue";
import TopBar from "./TopBar.vue";
</script>

<template>
  <div class="flex h-screen flex-col bg-bg-base text-text-primary">
    <TopBar />
    <div class="flex min-h-0 flex-1">
      <Sidebar />
      <div class="flex min-w-0 flex-1 flex-col">
        <main class="min-h-0 flex-1 overflow-y-auto">
          <RouterView />
        </main>
        <div
          data-testid="live-region"
          aria-live="polite"
          class="shrink-0"
        ></div>
      </div>
    </div>
    <StatusBar />
  </div>
</template>

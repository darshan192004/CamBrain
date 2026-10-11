<script setup>
// Top bar (design §4): brand plus the operator's site name, which /auth/me
// now returns so the header renders without a second request.
import { useAuthStore } from "../stores/auth.js";

const auth = useAuthStore();
</script>

<template>
  <header
    class="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-bg-surface px-4"
  >
    <span class="text-sm font-semibold tracking-wide text-text-primary">
      CamBrain
    </span>
    <span data-testid="site-name" class="text-sm text-text-secondary">
      {{ auth.user?.site_name }}
    </span>
  </header>
</template>

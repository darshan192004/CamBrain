<script setup>
// Nav rail (design §3): four destinations, icons + labels, admin-only
// entries hidden through RoleGate (defence in depth with the route guard),
// collapsed to icons below 1024px. jsdom has no matchMedia — the guard
// keeps tests and older engines on the expanded rail.
import { onBeforeUnmount, onMounted, ref } from "vue";

import RoleGate from "../auth/RoleGate.vue";

const collapsed = ref(false);
let media = null;

/**
 * Track viewport width changes from the (max-width: 1023px) query.
 * @param {{matches: boolean}} event change event carrying matches
 * @returns {void}
 */
function onViewportChange(event) {
  collapsed.value = event.matches;
}

onMounted(() => {
  if (typeof window.matchMedia !== "function") {
    return;
  }
  media = window.matchMedia("(max-width: 1023px)");
  collapsed.value = media.matches;
  media.addEventListener("change", onViewportChange);
});

onBeforeUnmount(() => {
  if (media) {
    media.removeEventListener("change", onViewportChange);
  }
});
</script>

<template>
  <nav
    data-testid="sidebar"
    :class="[
      'flex shrink-0 flex-col gap-1 border-r border-border bg-bg-surface p-2 transition-[width] duration-150 ease-snappy',
      collapsed ? 'sidebar--collapsed w-[72px]' : 'w-[232px]',
    ]"
    aria-label="Primary"
  >
    <RouterLink
      to="/cameras"
      class="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-text-secondary hover:bg-bg-raised hover:text-text-primary [&.router-link-active]:bg-bg-raised [&.router-link-active]:text-text-primary"
    >
      <svg
        class="h-4 w-4 shrink-0"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="m22 8-6 4 6 4V8Z" />
        <rect width="14" height="12" x="2" y="6" rx="2" />
      </svg>
      <span :class="collapsed ? 'sr-only' : ''">Cameras</span>
    </RouterLink>
    <RouterLink
      to="/events"
      class="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-text-secondary hover:bg-bg-raised hover:text-text-primary [&.router-link-active]:bg-bg-raised [&.router-link-active]:text-text-primary"
    >
      <svg
        class="h-4 w-4 shrink-0"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
        <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
      </svg>
      <span :class="collapsed ? 'sr-only' : ''">Events</span>
    </RouterLink>
    <RoleGate :roles="['admin']">
      <RouterLink
        to="/settings/users"
        class="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-text-secondary hover:bg-bg-raised hover:text-text-primary [&.router-link-active]:bg-bg-raised [&.router-link-active]:text-text-primary"
      >
        <svg
          class="h-4 w-4 shrink-0"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
          <path d="M16 3.13a4 4 0 0 1 0 7.75" />
        </svg>
        <span :class="collapsed ? 'sr-only' : ''">Users</span>
      </RouterLink>
      <RouterLink
        to="/settings/system"
        class="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-text-secondary hover:bg-bg-raised hover:text-text-primary [&.router-link-active]:bg-bg-raised [&.router-link-active]:text-text-primary"
      >
        <svg
          class="h-4 w-4 shrink-0"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path
            d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"
          />
          <circle cx="12" cy="12" r="3" />
        </svg>
        <span :class="collapsed ? 'sr-only' : ''">System</span>
      </RouterLink>
    </RoleGate>
  </nav>
</template>

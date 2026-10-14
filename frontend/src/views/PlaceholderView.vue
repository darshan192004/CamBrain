<script setup>
// Stand-in screen for routes whose real view lands in tasks 4.10–4.17;
// the guard, layout, and titles are already exercised through it.
</script>

<template>
  <section class="p-8">
    <h1 class="text-xl font-semibold text-text-primary">
      {{ $route.meta.title ?? "CamBrain" }}
    </h1>
    <p class="mt-2 text-sm text-text-secondary">
      This screen arrives in a later task.
    </p>
  </section>
</template>

<script setup>
// Root: `/login` renders bare, every other route renders inside the
// AppShell layout (task 4.9) because the router nests them as its children.
import { RouterView } from "vue-router";
</script>

<template>
  <RouterView />
</template>

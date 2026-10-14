<script setup>
// Defence in depth (design §7, API §5): the sidebar omits admin-only
// entries for viewers, and the route guard rejects them independently —
// this component is the "omit" half, used wherever visibility differs by
// role.
import { computed } from "vue";

import { useAuthStore } from "../stores/auth.js";

const props = defineProps({
  roles: {
    type: Array,
    required: true,
  },
});

const auth = useAuthStore();
const allowed = computed(() => props.roles.includes(auth.role));
</script>

<template>
  <slot v-if="allowed" />
</template>

<script setup>
// One draggable, keyboard-focusable ROI vertex (design §11). Position is
// display pixels; the parent converts through fromPixels so only normalised
// coordinates ever leave the canvas.
defineProps({
  index: {
    type: Number,
    required: true,
  },
  x: {
    type: Number,
    required: true,
  },
  y: {
    type: Number,
    required: true,
  },
  selected: {
    type: Boolean,
    default: false,
  },
});

defineEmits(["select", "pointerdown", "keydown"]);
</script>

<template>
  <circle
    :data-testid="`vertex-${index}`"
    :cx="x"
    :cy="y"
    r="6"
    class="vertex-handle"
    :class="{ selected }"
    tabindex="0"
    role="button"
    :aria-label="`Vertex ${index + 1}. Arrow keys nudge, Enter closes, Escape cancels.`"
    @click.stop="$emit('select', index)"
    @pointerdown.stop.prevent="$emit('pointerdown', index, $event)"
    @keydown.stop.prevent="$emit('keydown', index, $event)"
  />
</template>

<style scoped>
.vertex-handle {
  fill: var(--accent);
  cursor: grab;
}
.vertex-handle.selected {
  stroke: var(--text-primary);
  stroke-width: 2;
}
.vertex-handle:focus-visible {
  outline: 2px solid var(--text-primary);
  outline-offset: 1px;
}
</style>

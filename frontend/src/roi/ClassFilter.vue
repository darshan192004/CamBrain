<script setup>
// COCO class filter for a zone (design §5.7). Defaults to person only —
// noise control by default; the operator opts into more classes.
import { COCO_CLASSES } from "../data/coco.js";

const props = defineProps({
  modelValue: {
    type: Array,
    default: () => ["person"],
  },
  disabled: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(["update:modelValue"]);

/**
 * Toggle one class in the filter.
 * @param {string} cls COCO class name
 * @param {boolean} on checked state
 * @returns {void}
 */
function toggle(cls, on) {
  const next = new Set(props.modelValue);
  if (on) next.add(cls);
  else next.delete(cls);
  emit(
    "update:modelValue",
    COCO_CLASSES.filter((c) => next.has(c)),
  );
}
</script>

<template>
  <fieldset class="grid gap-1" aria-label="Classes this zone watches">
    <legend class="text-sm font-semibold text-text-primary">Classes</legend>
    <div class="grid max-h-40 grid-cols-2 gap-x-3 gap-y-0.5 overflow-y-auto">
      <label
        v-for="cls in COCO_CLASSES"
        :key="cls"
        class="flex items-center gap-1.5 text-xs text-text-secondary"
      >
        <input
          type="checkbox"
          :data-testid="`filter-class-${cls}`"
          :checked="modelValue.includes(cls)"
          :disabled="disabled"
          class="accent-[var(--accent)]"
          @change="toggle(cls, $event.target.checked)"
        />
        {{ cls }}
      </label>
    </div>
  </fieldset>
</template>

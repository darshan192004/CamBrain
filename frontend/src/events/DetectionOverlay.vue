<script setup>
// Detection boxes drawn over the event still. Boxes are stored in frame
// pixels at detection time (DATABASE.md `event_detections.bbox`) and
// positioned as percentages of the camera's frame size, so one style set
// scales correctly at any rendered resolution or frame size.
const props = defineProps({
  detections: {
    type: Array,
    default: () => [],
  },
  frameWidth: {
    type: Number,
    default: 640,
  },
  frameHeight: {
    type: Number,
    default: 360,
  },
});

/**
 * Absolute box style for one detection, in frame-percent space.
 * @param {{bbox: number[]}} detection detection row with an [x1,y1,x2,y2] box
 * @returns {object} CSS style object
 */
function boxStyle(detection) {
  const [x1, y1, x2, y2] = detection.bbox ?? [];
  return {
    left: `${(x1 / props.frameWidth) * 100}%`,
    top: `${(y1 / props.frameHeight) * 100}%`,
    width: `${((x2 - x1) / props.frameWidth) * 100}%`,
    height: `${((y2 - y1) / props.frameHeight) * 100}%`,
  };
}
</script>

<template>
  <div
    v-for="(detection, index) in detections"
    :key="index"
    :data-testid="`detect-box-${index}`"
    :style="boxStyle(detection)"
    class="absolute rounded-sm border-2 border-detect-box"
  >
    <span
      class="absolute -top-5 left-0 rounded-sm bg-bg-base px-1 text-[10px] text-detect-box"
    >
      {{ detection.class_name }}
    </span>
  </div>
</template>

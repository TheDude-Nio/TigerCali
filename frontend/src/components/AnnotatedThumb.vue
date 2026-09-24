<script setup lang="ts">
import { computed } from 'vue'
import type { Ann, ClassDef } from '../types'
import { classColor } from '../utils'

const props = defineProps<{
  id: number
  width: number
  height: number
  annotations: Ann[]
  classes: ClassDef[]
}>()

const wide = computed(() => props.width / props.height >= 4 / 3)
const polys = computed(() =>
  props.annotations.map((a) => ({
    points: a.pts.map((p) => `${p[0]},${p[1]}`).join(' '),
    color: classColor(props.classes, a.cls),
    first: a.pts[0],
  })),
)
const r = computed(() => Math.max(props.width, props.height) / 160)
</script>

<template>
  <div class="thumb-box">
    <div class="thumb-inner" :class="wide ? 'wide' : 'tall'" :style="{ aspectRatio: `${width} / ${height}` }">
      <img :src="`/api/images/${id}/thumb`" loading="lazy" decoding="async" draggable="false" alt="" />
      <svg :viewBox="`0 0 ${width} ${height}`" preserveAspectRatio="none">
        <g v-for="(p, i) in polys" :key="i">
          <polygon
            :points="p.points"
            :stroke="p.color"
            :fill="p.color"
            fill-opacity="0.18"
            stroke-width="1.6"
            vector-effect="non-scaling-stroke"
          />
          <circle :cx="p.first[0]" :cy="p.first[1]" :r="r" fill="#fff" :stroke="p.color" vector-effect="non-scaling-stroke" />
        </g>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.thumb-box {
  display: flex;
  align-items: center;
  justify-content: center;
  aspect-ratio: 4 / 3;
  background: #111827;
  overflow: hidden;
}
.thumb-inner {
  position: relative;
}
.thumb-inner.wide {
  width: 100%;
}
.thumb-inner.tall {
  height: 100%;
}
.thumb-inner img,
.thumb-inner svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
}
.thumb-inner img {
  object-fit: fill;
}
.thumb-inner svg {
  pointer-events: none;
}
</style>

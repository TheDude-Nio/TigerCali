<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ value: number; total: number; green?: boolean; label?: boolean }>()
const pct = computed(() => (props.total > 0 ? Math.min(100, (props.value / props.total) * 100) : 0))
</script>

<template>
  <div class="pb">
    <div class="progress" :class="{ green }"><span :style="{ width: pct + '%' }" /></div>
    <span v-if="label" class="pb-label">{{ value }} / {{ total }}</span>
  </div>
</template>

<style scoped>
.pb {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 120px;
}
.pb .progress {
  flex: 1;
}
.pb-label {
  font-size: 12px;
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
</style>

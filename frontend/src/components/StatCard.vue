<script setup lang="ts">
// 图标路径取自 Lucide（ISC），只收录用到的几个，避免引入整个图标库
const ICONS = {
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
  check: '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
  inbox:
    '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  target: '<circle cx="12" cy="12" r="10"/><path d="M22 12h-4M6 12H2M12 6V2M12 22v-4"/>',
  user: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  redo: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
  flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22v-7"/>',
  chart: '<path d="M12 20V10M18 20V4M6 20v-4"/>',
} as const

defineProps<{
  icon: keyof typeof ICONS
  label: string
  value?: string | number
  tone?: 'brand' | 'blue' | 'green' | 'red' | 'purple' | 'gray'
}>()
</script>

<template>
  <div class="stat" :class="`tone-${tone ?? 'gray'}`">
    <span class="stat-ico">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" v-html="ICONS[icon]" />
    </span>
    <div class="stat-body">
      <slot>
        <div class="num">{{ value }}</div>
      </slot>
      <div class="lbl">{{ label }}</div>
    </div>
  </div>
</template>

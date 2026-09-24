<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ page: number; pageSize: number; total: number }>()
const emit = defineEmits<{ (e: 'update:page', v: number): void }>()
const pages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))

function go(p: number) {
  const n = Math.min(pages.value, Math.max(1, p))
  if (n !== props.page) emit('update:page', n)
}
</script>

<template>
  <div v-if="pages > 1" class="pager">
    <button class="btn btn-sm" :disabled="page <= 1" @click="go(1)">«</button>
    <button class="btn btn-sm" :disabled="page <= 1" @click="go(page - 1)">上一页</button>
    <span class="muted">
      第
      <input
        class="input input-sm pager-input"
        :value="page"
        @change="go(Number(($event.target as HTMLInputElement).value) || 1)"
      />
      / {{ pages }} 页 · 共 {{ total }} 张
    </span>
    <button class="btn btn-sm" :disabled="page >= pages" @click="go(page + 1)">下一页</button>
    <button class="btn btn-sm" :disabled="page >= pages" @click="go(pages)">»</button>
  </div>
  <div v-else class="pager faint">共 {{ total }} 张</div>
</template>

<style scoped>
.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 16px;
}
.pager-input {
  width: 56px;
  text-align: center;
  display: inline-block;
}
</style>

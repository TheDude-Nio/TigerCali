<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { dialog } from '../store'

const inputEl = ref<HTMLInputElement | HTMLTextAreaElement | null>(null)
const okBtn = ref<HTMLButtonElement | null>(null)

watch(
  () => dialog.open,
  async (open) => {
    if (!open) return
    await nextTick()
    if (dialog.input) inputEl.value?.focus()
    else okBtn.value?.focus()
  },
)

function close(ok: boolean) {
  const r = dialog.resolve
  dialog.open = false
  dialog.resolve = null
  r?.(ok ? (dialog.input ? dialog.inputValue : '') : null)
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') close(false)
  else if (e.key === 'Enter' && (!dialog.multiline || e.ctrlKey || e.metaKey)) {
    e.preventDefault()
    close(true)
  }
}
</script>

<template>
  <div v-if="dialog.open" class="modal-mask" @mousedown.self="close(false)" @keydown="onKey">
    <div class="modal" role="dialog">
      <div class="modal-head">{{ dialog.title }}</div>
      <div class="modal-body">
        <div v-if="dialog.message">{{ dialog.message }}</div>
        <template v-if="dialog.input">
          <textarea
            v-if="dialog.multiline"
            ref="inputEl"
            v-model="dialog.inputValue"
            class="textarea mt-8"
            rows="4"
            :placeholder="dialog.placeholder"
          />
          <input v-else ref="inputEl" v-model="dialog.inputValue" class="input mt-8" :placeholder="dialog.placeholder" />
        </template>
      </div>
      <div class="modal-foot">
        <button class="btn" @click="close(false)">取消</button>
        <button
          ref="okBtn"
          class="btn"
          :class="dialog.danger ? 'btn-danger solid' : 'btn-primary'"
          @click="close(true)"
        >
          {{ dialog.okText }}
        </button>
      </div>
    </div>
  </div>
</template>

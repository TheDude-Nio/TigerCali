<script setup lang="ts">
import { ref } from 'vue'
import { errMsg, uploadForm } from '../api'
import { toast } from '../store'
import MarkdownView from './MarkdownView.vue'

const props = defineProps<{ modelValue: string; taskId?: number; rows?: number }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const tab = ref<'edit' | 'preview'>('edit')
const ta = ref<HTMLTextAreaElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)

function insert(text: string) {
  const el = ta.value
  const v = props.modelValue
  if (!el) {
    emit('update:modelValue', v + text)
    return
  }
  const s = el.selectionStart
  const e = el.selectionEnd
  emit('update:modelValue', v.slice(0, s) + text + v.slice(e))
  requestAnimationFrame(() => {
    el.focus()
    el.selectionStart = el.selectionEnd = s + text.length
  })
}

async function uploadImage(file: File) {
  if (!props.taskId) return
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', file, file.name || 'paste.png')
    const r = await uploadForm<{ url: string }>(`/api/tasks/${props.taskId}/attachments`, fd)
    insert(`\n![示例图](${r.url})\n`)
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    uploading.value = false
  }
}

function onPaste(e: ClipboardEvent) {
  if (!props.taskId) return
  const file = Array.from(e.clipboardData?.files ?? []).find((f) => f.type.startsWith('image/'))
  if (file) {
    e.preventDefault()
    uploadImage(file)
  }
}

function onPick(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (f) uploadImage(f)
  ;(e.target as HTMLInputElement).value = ''
}
</script>

<template>
  <div class="mde">
    <div class="mde-bar">
      <div class="seg">
        <button type="button" :class="{ on: tab === 'edit' }" @click="tab = 'edit'">编辑</button>
        <button type="button" :class="{ on: tab === 'preview' }" @click="tab = 'preview'">预览</button>
      </div>
      <span class="faint">支持 Markdown</span>
      <div class="spacer" />
      <template v-if="taskId">
        <span class="faint">可直接粘贴截图</span>
        <button type="button" class="btn btn-sm" :disabled="uploading" @click="fileInput?.click()">
          {{ uploading ? '上传中…' : '插入示例图' }}
        </button>
        <input ref="fileInput" type="file" accept="image/*" hidden @change="onPick" />
      </template>
    </div>
    <textarea
      v-show="tab === 'edit'"
      ref="ta"
      class="textarea"
      :rows="rows ?? 12"
      :value="modelValue"
      @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
      @paste="onPaste"
    />
    <div v-show="tab === 'preview'" class="mde-preview">
      <MarkdownView v-if="modelValue.trim()" :source="modelValue" />
      <div v-else class="faint">（空）</div>
    </div>
  </div>
</template>

<style scoped>
.mde-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.mde-preview {
  min-height: 200px;
  padding: 12px 14px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: #fff;
}
</style>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, errMsg, uploadForm } from '../api'
import AnnotatedThumb from '../components/AnnotatedThumb.vue'
import Pager from '../components/Pager.vue'
import { confirmDialog, metaStore, toast } from '../store'
import type { ImageDetail, Page, Task, TaskStats } from '../types'
import { IMAGE_STATUS, basename, debounce } from '../utils'

const props = defineProps<{ task: Task; stats: TaskStats | null }>()
const emit = defineEmits<{ (e: 'refresh'): void }>()
const router = useRouter()

// ---------------------------------------------------------------- 上传

const IMAGE_RE = /\.(jpe?g|png|bmp|webp)$/i
const MAX_BATCH_FILES = 24
const MAX_BATCH_BYTES = 48 * 1024 * 1024
const CONCURRENCY = 3

interface UploadResult {
  added: number
  duplicates: number
  errors: string[]
  error_count: number
  labels: LabelResult | null
}
interface LabelResult {
  matched: number
  unmatched: number
  kept: number
  bad_lines: number
}

const up = reactive({
  running: false,
  total: 0,
  loaded: 0,
  files: 0,
  added: 0,
  duplicates: 0,
  errors: [] as string[],
  labels: null as LabelResult | null,
  finished: false,
})
const dragging = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const dirInput = ref<HTMLInputElement | null>(null)

function relPath(f: File): string {
  return (f as File & { _rel?: string })._rel || f.webkitRelativePath || f.name
}

async function readEntry(entry: FileSystemEntry, prefix: string, out: File[]): Promise<void> {
  if (entry.isFile) {
    const file = await new Promise<File>((res, rej) => (entry as FileSystemFileEntry).file(res, rej))
    ;(file as File & { _rel?: string })._rel = prefix + file.name
    out.push(file)
  } else if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader()
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej))
      if (!batch.length) break
      for (const e of batch) await readEntry(e, `${prefix}${entry.name}/`, out)
    }
  }
}

async function onDrop(e: DragEvent) {
  dragging.value = false
  const items = Array.from(e.dataTransfer?.items ?? [])
  const files: File[] = []
  const entries = items.map((it) => it.webkitGetAsEntry?.()).filter(Boolean) as FileSystemEntry[]
  if (entries.length) {
    for (const en of entries) await readEntry(en, '', files)
  } else {
    files.push(...Array.from(e.dataTransfer?.files ?? []))
  }
  startUpload(files)
}

function onPick(e: Event) {
  const input = e.target as HTMLInputElement
  startUpload(Array.from(input.files ?? []))
  input.value = ''
}

async function startUpload(files: File[]) {
  if (up.running) {
    toast('正在上传，请稍候', 'warn')
    return
  }
  const images = files.filter((f) => IMAGE_RE.test(f.name))
  const zips = files.filter((f) => /\.zip$/i.test(f.name))
  const txts = files.filter((f) => /\.txt$/i.test(f.name) && f.name.toLowerCase() !== 'classes.txt')
  if (!images.length && !zips.length && !txts.length) {
    toast('没有找到可上传的图片 / zip / txt 文件', 'warn')
    return
  }
  const batches: File[][] = zips.map((z) => [z])
  let cur: File[] = []
  let curBytes = 0
  for (const f of images) {
    if (cur.length && (cur.length >= MAX_BATCH_FILES || curBytes + f.size > MAX_BATCH_BYTES)) {
      batches.push(cur)
      cur = []
      curBytes = 0
    }
    cur.push(f)
    curBytes += f.size
  }
  if (cur.length) batches.push(cur)

  Object.assign(up, {
    running: true,
    finished: false,
    total: [...images, ...zips, ...txts].reduce((s, f) => s + f.size, 0),
    loaded: 0,
    files: images.length + zips.length,
    added: 0,
    duplicates: 0,
    errors: [],
    labels: null,
  })
  const loadedPer = new Map<number, number>()
  const report = () => (up.loaded = Array.from(loadedPer.values()).reduce((a, b) => a + b, 0))

  let next = 0
  async function worker() {
    while (next < batches.length) {
      const idx = next++
      const fd = new FormData()
      for (const f of batches[idx]) fd.append('files', f, relPath(f))
      try {
        const r = await uploadForm<UploadResult>(`/api/tasks/${props.task.id}/images`, fd, (l) => {
          loadedPer.set(idx, l)
          report()
        })
        up.added += r.added
        up.duplicates += r.duplicates
        up.errors.push(...r.errors)
        if (r.labels) mergeLabels(r.labels)
      } catch (e) {
        up.errors.push(`第 ${idx + 1} 批上传失败：${errMsg(e)}`)
      }
      loadedPer.set(idx, batches[idx].reduce((s, f) => s + f.size, 0))
      report()
    }
  }
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, batches.length) }, worker))

  // 图片都传完后再导入同时拖进来的 txt 标签（预标注）
  for (let i = 0; i < txts.length; i += 500) {
    const fd = new FormData()
    for (const f of txts.slice(i, i + 500)) fd.append('files', f, relPath(f))
    try {
      mergeLabels(await uploadForm<LabelResult>(`/api/tasks/${props.task.id}/labels`, fd))
    } catch (e) {
      up.errors.push(`标签导入失败：${errMsg(e)}`)
    }
  }
  up.loaded = up.total
  up.running = false
  up.finished = true
  toast(`上传完成：新增 ${up.added} 张${up.duplicates ? `，跳过重复 ${up.duplicates} 张` : ''}`, 'success')
  emit('refresh')
  load()
}

function mergeLabels(r: LabelResult) {
  const cur = up.labels ?? { matched: 0, unmatched: 0, kept: 0, bad_lines: 0 }
  up.labels = {
    matched: cur.matched + r.matched,
    unmatched: cur.unmatched + r.unmatched,
    kept: cur.kept + r.kept,
    bad_lines: cur.bad_lines + r.bad_lines,
  }
}

const upPct = computed(() => (up.total ? Math.round((up.loaded / up.total) * 100) : 0))

// ---------------------------------------------------------------- 导入预标注

const importOpen = ref(false)
const imp = reactive({ fmt: 'auto', point_order: 'tl_bl_br_tr', overwrite: false, busy: false })
const labelInput = ref<HTMLInputElement | null>(null)

async function importLabels(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (!files.length) return
  imp.busy = true
  try {
    let total: LabelResult = { matched: 0, unmatched: 0, kept: 0, bad_lines: 0 }
    for (let i = 0; i < files.length; i += 500) {
      const fd = new FormData()
      for (const f of files.slice(i, i + 500)) fd.append('files', f, relPath(f))
      fd.append('fmt', imp.fmt)
      fd.append('point_order', imp.point_order)
      fd.append('overwrite', String(imp.overwrite))
      const r = await uploadForm<LabelResult>(`/api/tasks/${props.task.id}/labels`, fd)
      total = {
        matched: total.matched + r.matched,
        unmatched: total.unmatched + r.unmatched,
        kept: total.kept + r.kept,
        bad_lines: total.bad_lines + r.bad_lines,
      }
    }
    toast(
      `导入完成：匹配 ${total.matched} 张，未匹配 ${total.unmatched}，保留已有标注 ${total.kept}，无效行 ${total.bad_lines}`,
      'success',
      5000,
    )
    load()
    emit('refresh')
  } catch (err) {
    toast(errMsg(err), 'error')
  } finally {
    imp.busy = false
  }
}

// ---------------------------------------------------------------- 列表

const filters = reactive({ assignee: 'all', status: '', flagged: '', q: '' })
const page = ref(1)
const PAGE_SIZE = 60
const data = ref<Page<ImageDetail> | null>(null)
const loading = ref(false)
const selected = ref(new Set<number>())

const memberName = computed(() => {
  const m = new Map<number, string>()
  for (const x of props.stats?.members ?? []) m.set(x.user_id, x.username)
  return m
})

async function load() {
  loading.value = true
  try {
    data.value = await api.get<Page<ImageDetail>>(`/api/tasks/${props.task.id}/images`, {
      page: page.value,
      page_size: PAGE_SIZE,
      assignee: filters.assignee,
      status: filters.status,
      flagged: filters.flagged,
      q: filters.q,
    })
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    loading.value = false
  }
}

const reloadDebounced = debounce(() => {
  page.value = 1
  load()
}, 300)
watch(() => [filters.assignee, filters.status, filters.flagged], () => {
  page.value = 1
  selected.value = new Set()
  load()
})
watch(() => filters.q, () => reloadDebounced())
watch(page, load)
onMounted(load)

function toggleSel(id: number) {
  const s = new Set(selected.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selected.value = s
}

function selectPage() {
  const s = new Set(selected.value)
  for (const it of data.value?.items ?? []) s.add(it.id)
  selected.value = s
}

async function deleteSelected() {
  const ids = Array.from(selected.value)
  if (!ids.length) return
  if (!(await confirmDialog(`删除 ${ids.length} 张图片`, '图片和它们的标注会被永久删除，无法恢复。', { danger: true, okText: '删除' })))
    return
  try {
    const r = await api.post<{ deleted: number }>(`/api/tasks/${props.task.id}/images/delete`, { ids })
    toast(`已删除 ${r.deleted} 张`, 'success')
    selected.value = new Set()
    load()
    emit('refresh')
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

function open(img: ImageDetail) {
  router.push({
    path: `/tasks/${props.task.id}/label`,
    query: { mode: 'inspect', assignee: filters.assignee || 'all', image: img.id },
  })
}
</script>

<template>
  <div>
    <div class="card">
      <div class="card-title">
        上传图片
        <span class="faint">支持 jpg / png / bmp / webp、整个文件夹、zip 压缩包；相同图片自动去重</span>
      </div>
      <div
        class="drop"
        :class="{ over: dragging }"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <div class="drop-icon">⬆</div>
        <div><b>拖拽图片、文件夹或 zip 到这里</b></div>
        <div class="faint mt-8">zip / 文件夹里如果带有同名 .txt 标签（YOLO Pose / RM 四点格式），会自动导入为预标注</div>
        <div class="row mt-16" style="justify-content: center">
          <button class="btn" :disabled="up.running" @click="fileInput?.click()">选择图片 / zip</button>
          <button class="btn" :disabled="up.running" @click="dirInput?.click()">选择文件夹</button>
          <button class="btn btn-ghost" @click="importOpen = !importOpen">导入预标注…</button>
        </div>
        <input ref="fileInput" type="file" multiple accept="image/*,.zip,.txt" hidden @change="onPick" />
        <input ref="dirInput" type="file" webkitdirectory multiple hidden @change="onPick" />
      </div>

      <div v-if="up.running || up.finished" class="up-status mt-16">
        <div class="row">
          <b>{{ up.running ? '上传中…' : '上传完成' }}</b>
          <span class="muted">{{ upPct }}% · {{ (up.loaded / 1048576).toFixed(1) }} / {{ (up.total / 1048576).toFixed(1) }} MB</span>
          <div class="spacer" />
          <span>新增 <b>{{ up.added }}</b> 张</span>
          <span v-if="up.duplicates" class="muted">重复跳过 {{ up.duplicates }}</span>
          <span v-if="up.labels" class="muted">预标注匹配 {{ up.labels.matched }} 张</span>
        </div>
        <div class="progress mt-8"><span :style="{ width: upPct + '%' }" /></div>
        <details v-if="up.errors.length" class="mt-8">
          <summary class="error-text">{{ up.errors.length }} 个文件失败</summary>
          <div class="errs">
            <div v-for="(er, i) in up.errors" :key="i">{{ er }}</div>
          </div>
        </details>
      </div>

      <div v-if="importOpen" class="import mt-16">
        <div class="card-title" style="font-size: 14px">导入预标注（用已有模型的推理结果，标注员只需修正）</div>
        <div class="row">
          <label class="label">格式</label>
          <select v-model="imp.fmt" class="select" style="width: 240px">
            <option value="auto">自动识别（按每行数字个数）</option>
            <option value="rm4">RM 四点：cls x1 y1 … x4 y4</option>
            <option value="yolo_pose">YOLO Pose：cls cx cy w h x1 y1 …</option>
            <option value="sjtu">双标签：color tag x1 y1 …</option>
          </select>
          <label class="label">点序</label>
          <select v-model="imp.point_order" class="select" style="width: 300px">
            <option v-for="o in metaStore.meta?.point_orders ?? []" :key="o.key" :value="o.key">{{ o.name }}</option>
          </select>
        </div>
        <div class="row mt-8">
          <label class="check"><input v-model="imp.overwrite" type="checkbox" />覆盖已有标注（默认只填充还没有标注的图片）</label>
          <div class="spacer" />
          <button class="btn btn-primary" :disabled="imp.busy" @click="labelInput?.click()">
            {{ imp.busy ? '导入中…' : '选择 .txt 或 zip' }}
          </button>
          <input ref="labelInput" type="file" multiple accept=".txt,.zip" hidden @change="importLabels" />
        </div>
        <div class="faint mt-8">按文件名匹配图片（a.txt ↔ a.jpg）。坐标可以是归一化或像素坐标，会自动判断。</div>
      </div>
    </div>

    <div class="card mt-16">
      <div class="card-title">
        全部图片
        <span class="faint">{{ data?.total ?? 0 }} 张</span>
        <div class="spacer" />
        <template v-if="selected.size">
          <span class="muted">已选 {{ selected.size }}</span>
          <button class="btn btn-sm" @click="selected = new Set()">取消选择</button>
          <button class="btn btn-sm btn-danger" @click="deleteSelected">删除所选</button>
        </template>
        <button class="btn btn-sm" @click="selectPage">选择本页</button>
      </div>
      <div class="row mb-16">
        <select v-model="filters.assignee" class="select" style="width: 160px">
          <option value="all">全部成员</option>
          <option value="none">未分配</option>
          <option v-for="m in stats?.members ?? []" :key="m.user_id" :value="String(m.user_id)">{{ m.username }}</option>
        </select>
        <select v-model="filters.status" class="select" style="width: 120px">
          <option value="">全部状态</option>
          <option value="todo">未完成</option>
          <option value="done">已完成</option>
          <option value="rework">需返工</option>
        </select>
        <select v-model="filters.flagged" class="select" style="width: 120px">
          <option value="">全部</option>
          <option value="true">有问题标记</option>
        </select>
        <input v-model="filters.q" class="input" style="width: 220px" placeholder="搜索文件名" />
      </div>

      <div v-if="data && !data.items.length" class="empty">{{ loading ? '加载中…' : '没有图片' }}</div>
      <div v-else-if="data" class="thumb-grid" :style="{ opacity: loading ? 0.6 : 1 }">
        <div
          v-for="img in data.items"
          :key="img.id"
          class="thumb-card"
          :class="{ selected: selected.has(img.id), flagged: img.flagged }"
        >
          <label class="sel" @click.stop>
            <input type="checkbox" :checked="selected.has(img.id)" @change="toggleSel(img.id)" />
          </label>
          <div style="cursor: pointer" @click="open(img)">
            <AnnotatedThumb :id="img.id" :width="img.width" :height="img.height" :annotations="img.annotations" :classes="task.classes" />
          </div>
          <div class="thumb-meta">
            <span class="ellipsis" style="flex: 1" :title="img.filename">{{ basename(img.filename) }}</span>
            <span class="faint">{{ img.ann_count }}框</span>
          </div>
          <div class="thumb-meta" style="border-top: none; padding-top: 0">
            <span class="badge" :class="IMAGE_STATUS[img.status].cls">{{ IMAGE_STATUS[img.status].text }}</span>
            <span class="faint ellipsis">{{ img.assignee_id ? memberName.get(img.assignee_id) ?? '?' : '未分配' }}</span>
          </div>
        </div>
      </div>
      <Pager v-if="data" v-model:page="page" :page-size="PAGE_SIZE" :total="data.total" />
    </div>
  </div>
</template>

<style scoped>
.drop {
  padding: 28px 16px;
  border: 2px dashed var(--border-strong);
  border-radius: 12px;
  background: #fafbfc;
  text-align: center;
  transition: all 0.12s;
}
.drop.over {
  border-color: var(--brand);
  background: var(--brand-50);
}
.drop-icon {
  font-size: 28px;
  color: var(--brand);
}
.up-status {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.errs {
  max-height: 160px;
  overflow: auto;
  font-size: 12px;
  color: var(--text-2);
}
.import {
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fafbfc;
}
.sel {
  position: absolute;
  top: 6px;
  left: 6px;
  z-index: 2;
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.9);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.1s;
}
.thumb-card:hover .sel,
.thumb-card.selected .sel {
  opacity: 1;
}
.sel input {
  accent-color: var(--brand);
  width: 15px;
  height: 15px;
  margin: 0;
}
</style>

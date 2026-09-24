<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { cloneAnns } from '../annotator/geometry'
import { Editor } from '../annotator/editor'
import { BitmapCache } from '../annotator/imageCache'
import { ApiError, api, errMsg } from '../api'
import MarkdownView from '../components/MarkdownView.vue'
import { confirmDialog, dialog, metaStore, toast } from '../store'
import type { Ann, ImageDetail, ImageItem, ImageStatus, Task } from '../types'
import { IMAGE_STATUS, basename, classColor, classLabel, debounce } from '../utils'

// ---------------------------------------------------------------- 路由参数

const route = useRoute()
const router = useRouter()
const taskId = Number(route.params.id)
const mode: 'mine' | 'inspect' = route.query.mode === 'inspect' ? 'inspect' : 'mine'
const assignee = mode === 'mine' ? 'me' : String(route.query.assignee ?? 'all')
const title = typeof route.query.title === 'string' ? route.query.title : ''
const backTo = typeof route.query.back === 'string' && route.query.back.startsWith('/') ? route.query.back : `/tasks/${taskId}`

// ---------------------------------------------------------------- 状态

type Filter = 'all' | 'todo' | 'done' | 'rework' | 'flagged' | 'empty'
const FILTERS: [Filter, string][] = [
  ['all', '全部'],
  ['todo', '未完成'],
  ['done', '已完成'],
  ['rework', '返工'],
  ['flagged', '问题'],
  ['empty', '空图'],
]
const task = ref<Task | null>(null)
const items = ref<ImageItem[]>([])
const idx = ref(-1)
// 编辑器里实际显示的图片下标。切图时 idx 先变，图片加载完才更新 shownIdx，
// 所有保存/编辑操作都以 shownIdx 为准，避免把标注写到还没显示出来的图片上
const shownIdx = ref(-1)
const cur = ref<ImageDetail | null>(null)
const fatal = ref('')
const loading = ref(true)
const imgLoading = ref(false)
const listFilter = ref<Filter>((route.query.filter as Filter) || 'all')
const selectedAnn = ref(-1)
const annsView = ref<Ann[]>([])
const view = reactive({ zoom: 100, x: 0, y: 0, inside: false })
const ui = reactive({
  loupe: localStorage.getItem('tc.loupe') !== '0',
  labels: true,
  lockView: false,
  brightness: 100,
  contrast: 100,
  help: false,
  req: false,
})
const cls = reactive({ color: '', tag: '', custom: 0 })
const flagNote = ref('')

const canvasEl = ref<HTMLCanvasElement | null>(null)
let editor: Editor | null = null
let listRO: ResizeObserver | null = null
const bitmaps = new BitmapCache(24)

interface ImgState {
  d: ImageDetail
  seq: number
  saved: number
  chain: Promise<void>
}
const states = new Map<number, ImgState>()
const pendingDetail = new Map<number, Promise<ImageDetail>>()
const savingCount = ref(0)
const saveError = ref(false)
const dirtyCount = ref(0)

const readonly = computed(() => {
  const t = task.value
  if (!t) return true
  if (mode === 'inspect') return false
  return t.status !== 'active' || !['labeling', 'rejected'].includes(t.my_status)
})
const readonlyReason = computed(() => {
  const t = task.value
  if (!t || !readonly.value) return ''
  if (t.status !== 'active') return '任务已结束，只读'
  if (t.my_status === 'submitted') return '已提交审核，只读（撤回提交后可修改）'
  if (t.my_status === 'approved') return '已审核通过，只读'
  return '只读'
})

const isArmor = computed(() => task.value?.label_config.mode === 'armor')
const classes = computed(() => task.value?.classes ?? [])
const colorsEnabled = computed(() => {
  const cfg = task.value?.label_config
  if (!cfg || cfg.mode !== 'armor') return []
  return (metaStore.meta?.armor_colors ?? []).filter((c) => cfg.colors.includes(c.key))
})
const tagsEnabled = computed(() => {
  const cfg = task.value?.label_config
  if (!cfg || cfg.mode !== 'armor') return []
  return (metaStore.meta?.armor_tags ?? []).filter((t) => cfg.tags.includes(t.key))
})

function clsIndex(color: string, tag: string): number {
  return classes.value.findIndex((c) => c.color === color && c.tag === tag)
}
const currentCls = computed(() => (isArmor.value ? Math.max(0, clsIndex(cls.color, cls.tag)) : cls.custom))

const doneCount = computed(() => items.value.reduce((s, it) => s + (it.status === 'done' ? 1 : 0), 0))
const allDone = computed(() => items.value.length > 0 && doneCount.value === items.value.length)
const saveLabel = computed(() => {
  if (readonly.value) return ''
  if (saveError.value) return '保存失败，自动重试中'
  if (savingCount.value > 0) return '保存中…'
  if (dirtyCount.value > 0) return '未保存'
  return '已保存'
})

// ---------------------------------------------------------------- 列表过滤 + 虚拟滚动

const ROW = 30
const listEl = ref<HTMLElement | null>(null)
const listScroll = ref(0)
const listHeight = ref(600)

function matches(it: ImageItem, f: Filter): boolean {
  switch (f) {
    case 'todo':
      return it.status !== 'done'
    case 'done':
      return it.status === 'done'
    case 'rework':
      return it.status === 'rework'
    case 'flagged':
      return it.flagged
    case 'empty':
      return it.ann_count === 0
    default:
      return true
  }
}
const filtered = computed(() => {
  const out: number[] = []
  const f = listFilter.value
  items.value.forEach((it, i) => matches(it, f) && out.push(i))
  return out
})
const filterCounts = computed(() => {
  const c = { all: 0, todo: 0, done: 0, rework: 0, flagged: 0, empty: 0 }
  for (const it of items.value) {
    c.all++
    if (it.status === 'done') c.done++
    else c.todo++
    if (it.status === 'rework') c.rework++
    if (it.flagged) c.flagged++
    if (it.ann_count === 0) c.empty++
  }
  return c
})
const visibleRows = computed(() => {
  const f = filtered.value
  const start = Math.max(0, Math.floor(listScroll.value / ROW) - 8)
  const end = Math.min(f.length, Math.ceil((listScroll.value + listHeight.value) / ROW) + 8)
  const out = []
  for (let k = start; k < end; k++) out.push({ i: f[k], top: k * ROW })
  return out
})

function onListScroll() {
  if (!listEl.value) return
  listScroll.value = listEl.value.scrollTop
  listHeight.value = listEl.value.clientHeight
}

function scrollListTo(i: number) {
  const el = listEl.value
  if (!el) return
  const pos = filtered.value.indexOf(i)
  if (pos < 0) return
  const top = pos * ROW
  if (top < el.scrollTop + ROW) el.scrollTop = Math.max(0, top - ROW * 3)
  else if (top + ROW > el.scrollTop + el.clientHeight - ROW) el.scrollTop = top - el.clientHeight + ROW * 4
}

watch(listFilter, () => nextTick(() => scrollListTo(idx.value)))

// ---------------------------------------------------------------- 加载

async function fetchDetail(id: number): Promise<ImageDetail> {
  const p = api.get<ImageDetail>(`/api/images/${id}`)
  pendingDetail.set(id, p)
  try {
    return await p
  } finally {
    pendingDetail.delete(id)
  }
}

async function getState(id: number): Promise<ImgState> {
  const hit = states.get(id)
  if (hit) return hit
  let d: ImageDetail
  try {
    d = await (pendingDetail.get(id) ?? fetchDetail(id))
  } catch {
    d = await fetchDetail(id)
  }
  const again = states.get(id)
  if (again) return again
  const st: ImgState = { d: reactive(d) as ImageDetail, seq: 0, saved: 0, chain: Promise.resolve() }
  states.set(id, st)
  return st
}

async function prefetchDetails(ids: number[]) {
  const missing = ids.filter((id) => !states.has(id) && !pendingDetail.has(id))
  if (!missing.length) return
  const p = api.get<{ items: ImageDetail[] }>(`/api/tasks/${taskId}/images/batch`, { ids: missing.join(',') })
  for (const id of missing) {
    const one = p.then((r) => {
      const d = r.items.find((x) => x.id === id)
      if (!d) throw new Error('not found')
      return d
    })
    one.catch(() => undefined)
    pendingDetail.set(id, one)
  }
  try {
    const r = await p
    for (const d of r.items)
      if (!states.has(d.id)) states.set(d.id, { d: reactive(d) as ImageDetail, seq: 0, saved: 0, chain: Promise.resolve() })
  } catch {
    /* 预取失败无所谓，真正打开时会重新请求 */
  } finally {
    for (const id of missing) pendingDetail.delete(id)
  }
}

function prefetch(i: number) {
  const list = items.value
  const ahead = [1, 2, 3, 4].map((d) => list[i + d]?.id).filter((x): x is number => !!x)
  const behind = [1, 2].map((d) => list[i - d]?.id).filter((x): x is number => !!x)
  bitmaps.pin([list[i].id, ...ahead, behind[0]].filter((x): x is number => !!x))
  for (const id of [...ahead, behind[0]]) if (id) bitmaps.get(id).catch(() => undefined)
  prefetchDetails([...ahead, ...behind])
}

let navToken = 0
async function goto(i: number) {
  const list = items.value
  if (!list.length || !editor) return
  i = Math.max(0, Math.min(list.length - 1, i))
  flush()
  const token = ++navToken
  idx.value = i
  const item = list[i]
  const slow = setTimeout(() => token === navToken && (imgLoading.value = true), 150)
  try {
    const [st, bmp] = await Promise.all([getState(item.id), bitmaps.get(item.id)])
    if (token !== navToken) return
    cur.value = st.d
    flagNote.value = st.d.review_note
    editor.setImage(bmp, st.d.width, st.d.height, st.d.annotations, ui.lockView)
    shownIdx.value = i
    annsView.value = cloneAnns(st.d.annotations)
    router.replace({ query: { ...route.query, image: String(item.id) } })
  } catch (e) {
    if (token === navToken) toast(errMsg(e), 'error')
  } finally {
    clearTimeout(slow)
    if (token === navToken) imgLoading.value = false
  }
  if (token === navToken) {
    prefetch(i)
    scrollListTo(i)
  }
}

// ---------------------------------------------------------------- 保存

function currentState(): ImgState | undefined {
  const it = items.value[shownIdx.value]
  return it ? states.get(it.id) : undefined
}

function recountDirty() {
  let n = 0
  for (const s of states.values()) if (s.seq !== s.saved) n++
  dirtyCount.value = n
}

function updateItem(id: number, patch: Partial<ImageItem>) {
  const it = items.value.find((x) => x.id === id)
  if (it) Object.assign(it, patch)
}

function save(st: ImgState, done: boolean): Promise<void> {
  st.chain = st.chain.then(() => doSave(st, done))
  return st.chain
}

async function doSave(st: ImgState, done: boolean) {
  const needAnn = st.seq !== st.saved
  const needDone = done && st.d.status !== 'done'
  if ((!needAnn && !needDone) || readonly.value) return
  const sent = st.seq
  const id = st.d.id
  savingCount.value++
  try {
    const r = needAnn
      ? await api.put<{ version: number; status: ImageStatus; ann_count: number }>(`/api/images/${id}/annotations`, {
          annotations: st.d.annotations,
          version: st.d.version,
          done,
        })
      : await api.post<{ version: number; status: ImageStatus; ann_count: number }>(`/api/images/${id}/done`)
    st.d.version = r.version
    st.d.status = r.status
    if (needAnn) st.saved = sent
    updateItem(id, { status: r.status, ann_count: st.d.ann_count })
    saveError.value = false
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      // 版本冲突：以服务器为准
      const fresh = await api.get<ImageDetail>(`/api/images/${id}`).catch(() => null)
      if (fresh) {
        Object.assign(st.d, fresh)
        st.seq = st.saved = 0
        updateItem(id, { status: fresh.status, ann_count: fresh.ann_count, flagged: fresh.flagged })
        if (items.value[shownIdx.value]?.id === id) {
          editor?.replaceAnnotations(fresh.annotations)
          annsView.value = cloneAnns(fresh.annotations)
        }
      }
      // 冲突也可能是管理员改了类别（所有图片版本号都会变），重新加载任务拿最新类别
      await reloadTask()
      toast(e.message, 'warn', 4000)
    } else if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
      // 状态类错误（已提交、任务结束等），重试也没用
      st.saved = st.seq
      updateItem(id, { status: st.d.status })
      toast(e.message, 'error', 4000)
      if (e.status === 403) reloadTask()
    } else {
      saveError.value = true
      updateItem(id, { status: st.d.status })
    }
  } finally {
    savingCount.value--
    recountDirty()
  }
}

function saveDirty() {
  for (const st of states.values()) if (st.seq !== st.saved) save(st, false)
}

const autosave = debounce(saveDirty, 600)

function flush() {
  autosave.cancel()
  saveDirty()
}

async function flushAll() {
  autosave.cancel()
  for (const st of states.values()) if (st.seq !== st.saved) save(st, false)
  await Promise.all(Array.from(states.values()).map((s) => s.chain))
}

// 网络失败时定期重试
const retryTimer = setInterval(() => {
  if (!saveError.value) return
  for (const st of states.values()) if (st.seq !== st.saved) save(st, false)
}, 5000)

// ---------------------------------------------------------------- 编辑器回调

function onEditorChange(anns: Ann[]) {
  const st = currentState()
  annsView.value = anns
  if (!st || readonly.value) return
  st.d.annotations = anns
  st.d.ann_count = anns.length
  st.seq++
  updateItem(st.d.id, { ann_count: anns.length })
  recountDirty()
  autosave()
}

function onEditorSelect(i: number) {
  selectedAnn.value = i
  if (i < 0 || !editor) return
  const a = editor.anns[i]
  const c = classes.value[a.cls]
  if (!c) return
  if (isArmor.value) {
    cls.color = c.color ?? cls.color
    cls.tag = c.tag ?? cls.tag
  } else cls.custom = a.cls
}

// ---------------------------------------------------------------- 操作

function next() {
  const st = currentState()
  if (st && !readonly.value) {
    autosave.cancel()
    // 「保存并下一张」= 确认这张完成（没有装甲板也算完成）
    const markDone = mode === 'mine'
    if (markDone && st.d.status !== 'done') updateItem(st.d.id, { status: 'done' })
    save(st, markDone)
  }
  // 从当前显示的这张往后走：图片还没加载出来时连按 D 不会跳过、也不会误确认没看过的图
  if (shownIdx.value < items.value.length - 1) goto(shownIdx.value + 1)
  else if (mode === 'mine' && allDone.value) toast('全部完成了！可以点右上角「提交审核」', 'success', 4000)
  else toast('已经是最后一张了')
}

function prev() {
  if (shownIdx.value > 0) goto(shownIdx.value - 1)
}

function nextUndone() {
  const list = items.value
  for (let k = 1; k <= list.length; k++) {
    const j = (shownIdx.value + k) % list.length
    if (list[j].status !== 'done') {
      goto(j)
      return
    }
  }
  toast('没有未完成的图片了', 'success')
}

async function copyPrev() {
  if (readonly.value || !editor) return
  if (shownIdx.value <= 0) {
    toast('没有上一张')
    return
  }
  const st = await getState(items.value[shownIdx.value - 1].id)
  if (!st.d.annotations.length) {
    toast('上一张没有标注')
    return
  }
  editor.setAnnotations(st.d.annotations)
  toast(`已复制上一张的 ${st.d.annotations.length} 个标注（Ctrl+Z 撤销）`)
}

function selectAnn(i: number) {
  editor?.select(i)
}

function deleteAnn(i: number) {
  editor?.deleteAt(i)
}

async function clearAll() {
  if (readonly.value || !editor || !editor.anns.length) return
  editor.setAnnotations([])
  toast('已清空（Ctrl+Z 撤销）')
}

function pickColor(key: string) {
  cls.color = key
  const s = editor?.selected ?? -1
  if (s >= 0 && editor && !readonly.value) {
    const tag = classes.value[editor.anns[s].cls]?.tag
    const ni = tag ? clsIndex(key, tag) : -1
    if (ni >= 0) editor.setClassOf(s, ni)
  }
  editor?.requestRender()
}

function pickTag(key: string) {
  cls.tag = key
  const s = editor?.selected ?? -1
  if (s >= 0 && editor && !readonly.value) {
    const color = classes.value[editor.anns[s].cls]?.color
    const ni = color ? clsIndex(color, key) : -1
    if (ni >= 0) editor.setClassOf(s, ni)
  }
  editor?.requestRender()
}

function pickCustom(i: number) {
  if (i < 0 || i >= classes.value.length) return
  cls.custom = i
  const s = editor?.selected ?? -1
  if (s >= 0 && editor && !readonly.value) editor.setClassOf(s, i)
  editor?.requestRender()
}

async function setFlag(flagged: boolean) {
  const st = currentState()
  if (!st) return
  try {
    const r = await api.post<{ flagged: boolean; review_note: string }>(`/api/images/${st.d.id}/flag`, {
      flagged,
      note: flagged ? flagNote.value : '',
    })
    st.d.flagged = r.flagged
    st.d.review_note = r.review_note
    flagNote.value = r.review_note
    updateItem(st.d.id, { flagged: r.flagged })
    toast(r.flagged ? '已标记为有问题' : '已取消标记', 'success', 1500)
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function submitTask() {
  await flushAll()
  if (!allDone.value) {
    toast(`还有 ${items.value.length - doneCount.value} 张未完成`, 'warn')
    return
  }
  if (!(await confirmDialog('提交审核', '提交后等待管理员审核，审核期间不能修改（可以撤回）。'))) return
  try {
    await api.post(`/api/tasks/${taskId}/submit`)
    toast('已提交，等待审核', 'success')
    router.push(backTo)
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function reloadTask() {
  try {
    task.value = await api.get<Task>(`/api/tasks/${taskId}`)
    if (editor) {
      editor.autoSort = task.value.settings.auto_sort
      editor.requestRender()
    }
  } catch {
    /* ignore */
  }
}

function goBack() {
  router.push(backTo)
}

// ---------------------------------------------------------------- 键盘

function isTyping(e: KeyboardEvent) {
  const t = e.target as HTMLElement | null
  return !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)
}

function onKeyDown(e: KeyboardEvent) {
  if (!editor) return
  if (isTyping(e)) {
    if (e.key === 'Escape') (e.target as HTMLElement).blur()
    return
  }
  // 确认框 / 帮助 / 标注要求打开时，快捷键不作用到画布（比如确认提交时按 D 不能去标下一张）
  if (dialog.open) return
  if (ui.help || ui.req) {
    if (e.key === 'Escape' || (ui.help && (e.key === '?' || e.key === '/'))) {
      ui.help = false
      ui.req = false
    }
    return
  }
  const k = e.key
  const lower = k.length === 1 ? k.toLowerCase() : k
  const ctrl = e.ctrlKey || e.metaKey
  if (ctrl) {
    if (lower === 'z') {
      e.preventDefault()
      if (e.shiftKey) editor.redo()
      else editor.undo()
    } else if (lower === 'y') {
      e.preventDefault()
      editor.redo()
    } else if (lower === 's') {
      e.preventDefault()
      flush()
      toast('已保存', 'success', 1000)
    }
    return
  }
  if (e.altKey) return
  const step = e.shiftKey ? 0.2 : 1
  switch (lower) {
    case ' ':
      e.preventDefault()
      editor.setSpace(true)
      return
    case 'a':
    case 'PageUp':
      e.preventDefault()
      prev()
      return
    case 'd':
    case 'PageDown':
      e.preventDefault()
      if (e.shiftKey) nextUndone()
      else next()
      return
    case 'Escape':
      editor.cancel()
      return
    case 'Delete':
    case 'Backspace':
      e.preventDefault()
      editor.deleteSelected()
      return
    case 'ArrowLeft':
      e.preventDefault()
      editor.nudge(-step, 0)
      return
    case 'ArrowRight':
      e.preventDefault()
      editor.nudge(step, 0)
      return
    case 'ArrowUp':
      e.preventDefault()
      editor.nudge(0, -step)
      return
    case 'ArrowDown':
      e.preventDefault()
      editor.nudge(0, step)
      return
    case 'Tab':
      e.preventDefault()
      editor.selectNext(e.shiftKey ? -1 : 1)
      return
    case 'c':
      copyPrev()
      return
    case 'h':
      ui.labels = !ui.labels
      return
    case 'f':
      editor.fit()
      return
    case 'q':
      ui.loupe = !ui.loupe
      return
    case 'l':
      ui.lockView = !ui.lockView
      toast(ui.lockView ? '切换图片时保持缩放位置' : '切换图片时自动适应窗口', 'info', 1500)
      return
    case 'x':
      if (mode === 'inspect') setFlag(!cur.value?.flagged)
      return
    case '?':
    case '/':
      ui.help = !ui.help
      return
  }
  if (isArmor.value) {
    const color = colorsEnabled.value.find((c) => c.key.toLowerCase() === lower)
    if (color) {
      pickColor(color.key)
      return
    }
    const tag = tagsEnabled.value.find((t) => t.hotkey === k)
    if (tag) pickTag(tag.key)
  } else if (/^[0-9]$/.test(k)) {
    pickCustom(k === '0' ? 9 : Number(k) - 1)
  }
}

function onKeyUp(e: KeyboardEvent) {
  if (e.key === ' ') editor?.setSpace(false)
}

function onBlur() {
  editor?.setSpace(false)
}

function hasUnsaved(): boolean {
  for (const st of states.values()) if (st.seq !== st.saved) return true
  return false
}

function onBeforeUnload(e: BeforeUnloadEvent) {
  if (!readonly.value && (hasUnsaved() || savingCount.value > 0)) {
    flush()
    e.preventDefault()
    e.returnValue = ''
  }
}

function onPageHide() {
  // 页面真的要关了：用 keepalive 请求尽力把没保存的发出去（页面关闭后请求也会继续）
  if (readonly.value) return
  for (const st of states.values()) {
    if (st.seq === st.saved) continue
    api
      .put(`/api/images/${st.d.id}/annotations`, { annotations: st.d.annotations, version: st.d.version }, { keepalive: true })
      .catch(() => undefined)
  }
}

onBeforeRouteLeave(async () => {
  await flushAll()
  // 保存失败（比如断网）时不能悄悄丢掉修改
  if (!readonly.value && hasUnsaved()) {
    return await confirmDialog('有修改还没保存成功', '网络可能断开了，现在离开这些修改会丢失。确定离开吗？', {
      danger: true,
      okText: '仍然离开',
    })
  }
})

// ---------------------------------------------------------------- 生命周期

watch(
  () => ui.loupe,
  (v) => {
    if (editor) {
      editor.loupe = v
      editor.requestRender()
    }
    localStorage.setItem('tc.loupe', v ? '1' : '0')
  },
)
watch(
  () => ui.labels,
  (v) => {
    if (editor) {
      editor.showLabels = v
      editor.requestRender()
    }
  },
)
watch(
  () => [ui.brightness, ui.contrast],
  ([b, c]) => {
    if (editor) {
      editor.brightness = b / 100
      editor.contrast = c / 100
      editor.requestRender()
    }
  },
)
watch(readonly, (v) => {
  if (editor) editor.readonly = v
})

onMounted(async () => {
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('keyup', onKeyUp)
  window.addEventListener('blur', onBlur)
  window.addEventListener('beforeunload', onBeforeUnload)
  window.addEventListener('pagehide', onPageHide)
  try {
    const [t, list] = await Promise.all([
      api.get<Task>(`/api/tasks/${taskId}`),
      api.get<{ items: ImageItem[] }>(`/api/tasks/${taskId}/image-list`, { assignee }),
    ])
    task.value = t
    items.value = list.items
    document.title = `${t.name} · 标注`
  } catch (e) {
    fatal.value = errMsg(e)
    loading.value = false
    return
  }
  loading.value = false
  const t = task.value!
  if (t.label_config.mode === 'armor') {
    cls.color = t.label_config.colors[0]
    cls.tag = t.label_config.tags.includes('3') ? '3' : t.label_config.tags[0]
  }
  if (!items.value.length) return
  await nextTick()
  editor = new Editor(canvasEl.value!, {
    styleOf: (c) => ({ color: classColor(classes.value, c), label: classLabel(classes.value, c) }),
    newClass: () => currentCls.value,
    onChange: onEditorChange,
    onSelect: onEditorSelect,
    onView: () => {
      if (!editor) return
      view.zoom = Math.round(editor.scale * 100)
      view.x = editor.mouse.ix
      view.y = editor.mouse.iy
      view.inside = editor.mouse.inside
    },
  })
  editor.readonly = readonly.value
  editor.autoSort = t.settings.auto_sort
  editor.loupe = ui.loupe
  onListScroll()
  if (listEl.value) {
    listRO = new ResizeObserver(onListScroll)
    listRO.observe(listEl.value)
  }

  const wantId = Number(route.query.image)
  let start = items.value.findIndex((it) => it.id === wantId)
  if (start < 0 && listFilter.value !== 'all') start = items.value.findIndex((it) => matches(it, listFilter.value))
  if (start < 0 && mode === 'mine') start = items.value.findIndex((it) => it.status !== 'done')
  await goto(Math.max(0, start))
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('keyup', onKeyUp)
  window.removeEventListener('blur', onBlur)
  window.removeEventListener('beforeunload', onBeforeUnload)
  window.removeEventListener('pagehide', onPageHide)
  listRO?.disconnect()
  clearInterval(retryTimer)
  editor?.destroy()
  editor = null
  bitmaps.pin([])
  bitmaps.clear()
})

const helpKeys: [string, string][] = [
  ['左键单击 ×4', '依次点 4 个角点完成一个装甲板'],
  ['拖动点 / 框内拖动', '调整角点 / 整体移动'],
  ['Ctrl + 单击', '在已有框内强制开始画新框'],
  ['滚轮', '以鼠标为中心缩放'],
  ['右键 / 中键拖动、空格+拖动', '平移画面'],
  ['F', '适应窗口'],
  ['D / PageDown', '确认完成并下一张（空图也按 D）'],
  ['A / PageUp', '上一张'],
  ['Shift + D', '跳到下一张未完成'],
  ['C', '复制上一张的标注（视频序列神器）'],
  ['B R N P', '颜色：蓝 / 红 / 灰 / 紫（选中框时直接修改）'],
  ['0 ~ 8', '编号：0 哨兵 1~5 6 前哨站 7 基地小 8 基地大'],
  ['Tab / Shift+Tab', '切换选中的框'],
  ['方向键', '微调选中的点（Shift 精调 0.2 像素），未选点时平移整个框'],
  ['Delete / Backspace', '删除选中的框；画到一半时撤回上一个点'],
  ['Esc', '取消绘制 / 取消选择'],
  ['Ctrl+Z / Ctrl+Shift+Z', '撤销 / 重做'],
  ['H', '隐藏 / 显示标注'],
  ['Q', '开关放大镜'],
  ['L', '锁定视图（切图时保持缩放位置）'],
  ['X', '（审核模式）标记 / 取消标记有问题'],
  ['?', '显示本帮助'],
]
</script>

<template>
  <div class="ws">
    <!-- 顶栏 -->
    <header class="ws-top">
      <button class="wbtn" title="返回" @click="goBack">←</button>
      <div class="ws-title ellipsis">
        <b>{{ task?.name ?? '加载中…' }}</b>
        <span class="ws-mode" :class="mode">{{ mode === 'mine' ? '我的标注' : `审核${title ? '：' + title : ''}` }}</span>
      </div>
      <div v-if="cur" class="ws-file ellipsis">
        <span class="mono">{{ shownIdx + 1 }} / {{ items.length }}</span>
        <span class="ellipsis" :title="cur.filename">{{ basename(cur.filename) }}</span>
        <span class="wbadge" :class="items[shownIdx]?.status">{{ IMAGE_STATUS[items[shownIdx]?.status ?? 'todo'].text }}</span>
        <span v-if="items[shownIdx]?.flagged" class="wbadge rework">有问题</span>
      </div>
      <div class="spacer" />
      <div class="ws-prog" :title="`已完成 ${doneCount} / ${items.length}`">
        <div class="bar"><span :style="{ width: items.length ? (doneCount / items.length) * 100 + '%' : '0' }" /></div>
        <span class="mono">{{ doneCount }}/{{ items.length }}</span>
      </div>
      <span v-if="saveLabel" class="ws-save" :class="{ err: saveError, dirty: dirtyCount > 0 || savingCount > 0 }">● {{ saveLabel }}</span>
      <button class="wbtn" @click="ui.req = true">标注要求</button>
      <button class="wbtn" @click="ui.help = true">快捷键 ?</button>
      <button
        v-if="mode === 'mine' && !readonly"
        class="wbtn primary"
        :disabled="!allDone"
        :title="allDone ? '' : '全部完成后才能提交'"
        @click="submitTask"
      >
        提交审核
      </button>
    </header>

    <!-- 左侧列表 -->
    <aside class="ws-left">
      <div class="filters">
        <button
          v-for="f in FILTERS"
          v-show="f[0] === 'all' || f[0] === 'todo' || f[0] === 'done' || filterCounts[f[0]] > 0"
          :key="f[0]"
          :class="{ on: listFilter === f[0] }"
          @click="listFilter = f[0]"
        >
          {{ f[1] }} <span>{{ filterCounts[f[0]] }}</span>
        </button>
      </div>
      <div ref="listEl" class="list" @scroll="onListScroll">
        <div :style="{ height: filtered.length * ROW + 'px', position: 'relative' }">
          <div
            v-for="r in visibleRows"
            :key="items[r.i].id"
            class="li"
            :class="{ on: r.i === idx }"
            :style="{ top: r.top + 'px' }"
            @click="goto(r.i)"
          >
            <span class="dot" :class="items[r.i].status" />
            <span class="li-no mono">{{ r.i + 1 }}</span>
            <span class="li-name ellipsis" :title="items[r.i].filename">{{ basename(items[r.i].filename) }}</span>
            <span v-if="items[r.i].flagged" class="li-flag">⚑</span>
            <span class="li-n mono">{{ items[r.i].ann_count || '' }}</span>
          </div>
        </div>
        <div v-if="!filtered.length" class="list-empty">没有符合条件的图片</div>
      </div>
    </aside>

    <!-- 画布 -->
    <main class="ws-center">
      <canvas ref="canvasEl" tabindex="-1" />
      <div v-if="loading" class="overlay">加载中…</div>
      <div v-else-if="fatal" class="overlay">
        <div>{{ fatal }}</div>
        <button class="wbtn mt-16" @click="goBack">返回</button>
      </div>
      <div v-else-if="!items.length" class="overlay">
        <div>{{ mode === 'mine' ? '还没有分配给你的图片' : '没有图片' }}</div>
        <button class="wbtn mt-16" @click="goBack">返回</button>
      </div>
      <div v-if="imgLoading" class="spinner" />
      <div v-if="cur && cur.flagged && cur.review_note && mode === 'mine'" class="banner">⚑ 审核意见：{{ cur.review_note }}</div>
      <div v-if="readonlyReason" class="banner ro">{{ readonlyReason }}</div>
    </main>

    <!-- 右侧面板 -->
    <aside class="ws-right">
      <section class="panel">
        <div class="ph">类别 <span class="faint2">选中框时点击直接修改</span></div>
        <template v-if="isArmor">
          <div class="sub">颜色</div>
          <div class="btn-grid c4">
            <button
              v-for="c in colorsEnabled"
              :key="c.key"
              class="cbtn"
              :class="{ on: cls.color === c.key }"
              :style="{ '--c': c.hex }"
              @click="pickColor(c.key)"
            >
              <span class="sw" />{{ c.name }}<kbd>{{ c.key }}</kbd>
            </button>
          </div>
          <div class="sub">编号</div>
          <div class="btn-grid c3">
            <button v-for="t in tagsEnabled" :key="t.key" class="cbtn" :class="{ on: cls.tag === t.key }" @click="pickTag(t.key)">
              <b>{{ t.key }}</b><span class="tn">{{ t.name }}</span><kbd>{{ t.hotkey }}</kbd>
            </button>
          </div>
        </template>
        <div v-else class="btn-grid c2">
          <button v-for="(c, i) in classes" :key="c.name" class="cbtn" :class="{ on: cls.custom === i }" :style="{ '--c': classColor(classes, i) }" @click="pickCustom(i)">
            <span class="sw" />{{ c.name }}<kbd v-if="i < 10">{{ (i + 1) % 10 }}</kbd>
          </button>
        </div>
        <div class="cur-cls">
          当前：<span class="sw" :style="{ background: classColor(classes, currentCls) }" /><b class="mono">{{ classLabel(classes, currentCls) }}</b>
          <span class="faint2">#{{ currentCls }}</span>
        </div>
      </section>

      <section class="panel">
        <div class="ph">
          本图标注 <span class="faint2">{{ annsView.length }} 个</span>
          <div class="spacer" />
          <button class="lbtn" :disabled="readonly || shownIdx <= 0" title="C" @click="copyPrev">复制上一张</button>
          <button class="lbtn danger" :disabled="readonly || !annsView.length" @click="clearAll">清空</button>
        </div>
        <div class="ann-list">
          <div v-if="!annsView.length" class="faint2" style="padding: 6px 0">没有标注。没有装甲板就直接按 D 确认。</div>
          <div
            v-for="(a, i) in annsView"
            :key="i"
            class="ann"
            :class="{ on: i === selectedAnn }"
            @click="selectAnn(i)"
          >
            <span class="sw" :style="{ background: classColor(classes, a.cls) }" />
            <span class="mono">{{ i + 1 }}. {{ classLabel(classes, a.cls) }}</span>
            <div class="spacer" />
            <button v-if="!readonly" class="x" title="删除" @click.stop="deleteAnn(i)">×</button>
          </div>
        </div>
      </section>

      <section v-if="mode === 'inspect' && cur" class="panel review">
        <div class="ph">审核标记</div>
        <textarea v-model="flagNote" class="note" rows="2" placeholder="问题说明（标注员可见），如：左上点偏了" />
        <div class="row" style="gap: 6px; margin-top: 6px">
          <button v-if="!cur.flagged" class="wbtn danger" @click="setFlag(true)">⚑ 标记有问题 <kbd>X</kbd></button>
          <template v-else>
            <button class="wbtn" @click="setFlag(true)">更新说明</button>
            <button class="wbtn" @click="setFlag(false)">取消标记 <kbd>X</kbd></button>
          </template>
        </div>
        <div class="faint2" style="margin-top: 6px">也可以直接修改标注，修改会立即保存。</div>
      </section>

      <section class="panel">
        <div class="ph">显示</div>
        <label class="slider">亮度 <input v-model.number="ui.brightness" type="range" min="30" max="300" step="5" /><span class="mono">{{ ui.brightness }}%</span></label>
        <label class="slider">对比度 <input v-model.number="ui.contrast" type="range" min="30" max="300" step="5" /><span class="mono">{{ ui.contrast }}%</span></label>
        <div class="toggles">
          <label><input v-model="ui.loupe" type="checkbox" />放大镜 <kbd>Q</kbd></label>
          <label><input v-model="ui.labels" type="checkbox" />显示标注 <kbd>H</kbd></label>
          <label><input v-model="ui.lockView" type="checkbox" />锁定视图 <kbd>L</kbd></label>
        </div>
        <button class="lbtn" style="margin-top: 6px" @click="ui.brightness = 100; ui.contrast = 100">重置亮度对比度</button>
      </section>
    </aside>

    <!-- 状态栏 -->
    <footer class="ws-bottom">
      <span class="mono">{{ view.zoom }}%</span>
      <span v-if="cur" class="mono">{{ cur.width }}×{{ cur.height }}</span>
      <span v-if="view.inside" class="mono">x {{ view.x.toFixed(1) }} · y {{ view.y.toFixed(1) }}</span>
      <div class="spacer" />
      <span>点 4 下画一个框 · <kbd>D</kbd> 完成并下一张 · <kbd>A</kbd> 上一张 · 滚轮缩放 · 右键拖动 · <kbd>?</kbd> 全部快捷键</span>
    </footer>

    <!-- 帮助 -->
    <div v-if="ui.help" class="ws-modal" @mousedown.self="ui.help = false">
      <div class="ws-dialog">
        <div class="ph">快捷键 <div class="spacer" /><button class="lbtn" @click="ui.help = false">关闭</button></div>
        <table class="keys">
          <tr v-for="[k, v] in helpKeys" :key="k">
            <td><kbd>{{ k }}</kbd></td>
            <td>{{ v }}</td>
          </tr>
        </table>
        <div class="faint2" style="margin-top: 10px">
          白色实心的点是第 1 个点（左上）。{{ task?.settings.auto_sort ? '已开启自动规范点序，点击顺序可以随意。' : '请严格按 左上→左下→右下→右上 的顺序点击。' }}
        </div>
      </div>
    </div>

    <!-- 标注要求 -->
    <div v-if="ui.req && task" class="ws-modal" @mousedown.self="ui.req = false">
      <div class="ws-dialog light">
        <div class="ph">标注要求 <div class="spacer" /><button class="lbtn" @click="ui.req = false">关闭</button></div>
        <MarkdownView v-if="task.description.trim()" :source="task.description" />
        <div v-else class="faint2">管理员没有填写标注要求</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ws {
  --wbg: #0f141c;
  --wpanel: #151b25;
  --wborder: #252d3a;
  --wtext: #d7dde6;
  --wmuted: #8b95a5;
  position: fixed;
  inset: 0;
  display: grid;
  grid-template-rows: 46px minmax(0, 1fr) 26px;
  grid-template-columns: 230px minmax(0, 1fr) 280px;
  background: var(--wbg);
  color: var(--wtext);
  font-size: 13px;
  user-select: none;
}
.ws kbd {
  background: #1f2733;
  border-color: #3a4556;
  color: #c8d0dc;
  font-size: 11px;
  padding: 0 4px;
  min-width: 16px;
  line-height: 15px;
}
.ws-top {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  background: var(--wpanel);
  border-bottom: 1px solid var(--wborder);
  min-width: 0;
}
.ws-title {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 320px;
}
.ws-mode {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 12px;
  background: #1e3a5f;
  color: #93c5fd;
  white-space: nowrap;
}
.ws-mode.inspect {
  background: #4a2511;
  color: #fdba74;
}
.ws-file {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 10px;
  border-left: 1px solid var(--wborder);
  color: var(--wmuted);
  min-width: 0;
}
.wbadge {
  padding: 0 7px;
  border-radius: 999px;
  font-size: 11px;
  background: #273142;
  color: #cbd5e1;
  white-space: nowrap;
}
.wbadge.done {
  background: #133d27;
  color: #86efac;
}
.wbadge.rework {
  background: #4c1717;
  color: #fca5a5;
}
.ws-prog {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--wmuted);
}
.ws-prog .bar {
  position: relative;
  width: 110px;
  height: 6px;
  border-radius: 999px;
  background: #273142;
  overflow: hidden;
}
.ws-prog .bar span {
  position: absolute;
  inset: 0 auto 0 0;
  background: linear-gradient(90deg, #fb923c, #f97316);
  transition: width 0.2s;
}
.ws-save {
  color: #4ade80;
  font-size: 12px;
  white-space: nowrap;
}
.ws-save.dirty {
  color: #fbbf24;
}
.ws-save.err {
  color: #f87171;
}
.wbtn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 10px;
  border: 1px solid #334155;
  border-radius: 6px;
  background: #1c2430;
  color: var(--wtext);
  font: inherit;
  cursor: pointer;
  white-space: nowrap;
}
.wbtn:hover:not(:disabled) {
  background: #263041;
}
.wbtn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.wbtn.primary {
  background: #f97316;
  border-color: #f97316;
  color: #fff;
  font-weight: 600;
}
.wbtn.primary:hover:not(:disabled) {
  background: #ea580c;
}
.wbtn.danger {
  border-color: #7f1d1d;
  color: #fca5a5;
}

.ws-left {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--wpanel);
  border-right: 1px solid var(--wborder);
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 8px;
  border-bottom: 1px solid var(--wborder);
}
.filters button {
  padding: 2px 8px;
  border: 1px solid #2d3748;
  border-radius: 999px;
  background: transparent;
  color: var(--wmuted);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.filters button span {
  opacity: 0.7;
}
.filters button.on {
  border-color: #f97316;
  color: #fdba74;
  background: rgba(249, 115, 22, 0.12);
}
.list {
  flex: 1;
  overflow-y: auto;
  position: relative;
}
.li {
  position: absolute;
  left: 0;
  right: 0;
  height: 30px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  cursor: pointer;
  color: #aeb8c6;
}
.li:hover {
  background: #1c2430;
}
.li.on {
  background: rgba(249, 115, 22, 0.16);
  color: #fff;
  box-shadow: inset 3px 0 0 #f97316;
}
.dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #475569;
}
.dot.done {
  background: #22c55e;
}
.dot.rework {
  background: #ef4444;
}
.li-no {
  flex: none;
  width: 36px;
  color: #64748b;
  font-size: 11px;
}
.li-name {
  flex: 1;
  min-width: 0;
}
.li-flag {
  color: #f87171;
}
.li-n {
  flex: none;
  min-width: 14px;
  text-align: right;
  color: #fdba74;
  font-size: 11px;
}
.list-empty {
  padding: 20px;
  text-align: center;
  color: var(--wmuted);
}

.ws-center {
  position: relative;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.ws-center canvas {
  position: absolute;
  inset: 0;
  display: block;
  outline: none;
  touch-action: none;
}
.overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--wmuted);
  font-size: 15px;
}
.spinner {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 36px;
  height: 36px;
  margin: -18px 0 0 -18px;
  border: 3px solid rgba(255, 255, 255, 0.15);
  border-top-color: #f97316;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  pointer-events: none;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.banner {
  position: absolute;
  left: 50%;
  bottom: 12px;
  transform: translateX(-50%);
  max-width: 70%;
  padding: 6px 14px;
  border-radius: 8px;
  background: rgba(127, 29, 29, 0.92);
  color: #fee2e2;
  pointer-events: none;
}
.banner.ro {
  bottom: auto;
  top: 12px;
  background: rgba(30, 58, 95, 0.92);
  color: #dbeafe;
}

.ws-right {
  min-height: 0;
  overflow-y: auto;
  background: var(--wpanel);
  border-left: 1px solid var(--wborder);
}
.panel {
  padding: 10px 12px 12px;
  border-bottom: 1px solid var(--wborder);
}
.ph {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  font-weight: 600;
  color: #e5e9f0;
}
.faint2 {
  color: var(--wmuted);
  font-size: 12px;
  font-weight: 400;
}
.sub {
  margin: 4px 0 4px;
  color: var(--wmuted);
  font-size: 12px;
}
.btn-grid {
  display: grid;
  gap: 4px;
}
.btn-grid.c4 {
  grid-template-columns: repeat(4, 1fr);
}
.btn-grid.c3 {
  grid-template-columns: repeat(3, 1fr);
}
.btn-grid.c2 {
  grid-template-columns: repeat(2, 1fr);
}
.cbtn {
  position: relative;
  display: flex;
  align-items: center;
  gap: 4px;
  height: 30px;
  padding: 0 6px;
  border: 1px solid #2d3748;
  border-radius: 6px;
  background: #1a212c;
  color: var(--wtext);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  overflow: hidden;
  white-space: nowrap;
}
.cbtn:hover {
  border-color: #475569;
}
.cbtn.on {
  border-color: #f97316;
  background: rgba(249, 115, 22, 0.16);
  color: #fff;
}
.cbtn kbd {
  margin-left: auto;
}
.cbtn .tn {
  color: var(--wmuted);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cbtn .sw,
.cur-cls .sw,
.ann .sw {
  flex: none;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  background: var(--c);
}
.cur-cls {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  padding: 6px 8px;
  border-radius: 6px;
  background: #0f141c;
}
.ann-list {
  max-height: 240px;
  overflow-y: auto;
}
.ann {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 28px;
  padding: 0 6px;
  border-radius: 5px;
  cursor: pointer;
}
.ann:hover {
  background: #1c2430;
}
.ann.on {
  background: rgba(249, 115, 22, 0.16);
}
.ann .x {
  border: none;
  background: none;
  color: var(--wmuted);
  font-size: 16px;
  cursor: pointer;
  padding: 0 4px;
}
.ann .x:hover {
  color: #f87171;
}
.lbtn {
  border: none;
  background: none;
  color: #93c5fd;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  padding: 2px 4px;
}
.lbtn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.lbtn.danger {
  color: #fca5a5;
}
.review {
  background: rgba(127, 29, 29, 0.12);
}
.note {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid #334155;
  border-radius: 6px;
  background: #0f141c;
  color: var(--wtext);
  font: inherit;
  resize: vertical;
  user-select: text;
}
.slider {
  display: grid;
  grid-template-columns: 44px 1fr 40px;
  align-items: center;
  gap: 6px;
  margin: 2px 0;
  color: var(--wmuted);
}
.slider input {
  accent-color: #f97316;
}
.toggles {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 6px;
}
.toggles label {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}
.toggles input {
  accent-color: #f97316;
}

.ws-bottom {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 0 12px;
  background: var(--wpanel);
  border-top: 1px solid var(--wborder);
  color: var(--wmuted);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
}
.ws-modal {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.55);
}
.ws-dialog {
  width: 620px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 64px);
  overflow: auto;
  padding: 16px 18px;
  border: 1px solid var(--wborder);
  border-radius: 10px;
  background: var(--wpanel);
  user-select: text;
}
.ws-dialog.light {
  background: #fff;
  color: var(--text);
}
.ws-dialog.light .ph {
  color: var(--text);
}
.keys {
  width: 100%;
  border-collapse: collapse;
}
.keys td {
  padding: 5px 6px;
  border-bottom: 1px solid var(--wborder);
  vertical-align: top;
}
.keys td:first-child {
  width: 220px;
}
@media (max-width: 1100px) {
  .ws {
    grid-template-columns: 180px minmax(0, 1fr) 240px;
  }
  .ws-prog,
  .ws-title {
    display: none;
  }
}
</style>

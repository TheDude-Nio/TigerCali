<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errMsg } from '../api'
import AnnotatedThumb from '../components/AnnotatedThumb.vue'
import Pager from '../components/Pager.vue'
import ProgressBar from '../components/ProgressBar.vue'
import { confirmDialog, promptDialog, toast } from '../store'
import type { ImageDetail, MemberStat, Page, Task, TaskStats } from '../types'
import { IMAGE_STATUS, MEMBER_STATUS, basename, fmtTime } from '../utils'

const route = useRoute()
const router = useRouter()
const taskId = Number(route.params.id)
const uid = Number(route.params.uid)

const task = ref<Task | null>(null)
const member = ref<MemberStat | null>(null)
const data = ref<Page<ImageDetail> | null>(null)
const loading = ref(false)
const page = ref(Number(route.query.page) || 1)
const filters = reactive({
  status: '',
  flagged: '',
  has_ann: '',
  order: 'name' as 'name' | 'random',
  seed: Math.floor(Math.random() * 100000),
})
const size = ref<'s' | 'm' | 'l'>((localStorage.getItem('tc.thumb') as 's' | 'm' | 'l') || 'm')
const PAGE_SIZE = 48

async function loadMeta() {
  try {
    const [t, s] = await Promise.all([
      api.get<Task>(`/api/tasks/${taskId}`),
      api.get<TaskStats>(`/api/tasks/${taskId}/stats`),
    ])
    task.value = t
    member.value = s.members.find((m) => m.user_id === uid) ?? null
    document.title = `审核 ${member.value?.username ?? ''} · ${t.name}`
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function load() {
  loading.value = true
  try {
    data.value = await api.get<Page<ImageDetail>>(`/api/tasks/${taskId}/images`, {
      assignee: String(uid),
      page: page.value,
      page_size: PAGE_SIZE,
      status: filters.status,
      flagged: filters.flagged,
      has_ann: filters.has_ann,
      order: filters.order,
      seed: filters.seed,
    })
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    loading.value = false
  }
}

watch(
  () => [filters.status, filters.flagged, filters.has_ann, filters.order, filters.seed],
  () => {
    if (page.value !== 1) page.value = 1
    else load()
  },
)
watch(page, (p) => {
  router.replace({ query: { ...route.query, page: String(p) } })
  load()
})
watch(size, (s) => localStorage.setItem('tc.thumb', s))
onMounted(() => {
  loadMeta()
  load()
})

const gridMin = computed(() => ({ s: 150, m: 220, l: 340 })[size.value])

async function toggleFlag(img: ImageDetail) {
  let note = ''
  if (!img.flagged) {
    const r = await promptDialog('标记有问题', { placeholder: '问题说明（可选，标注员可见）', okText: '标记' })
    if (r === null) return
    note = r
  }
  try {
    const r = await api.post<{ flagged: boolean; review_note: string }>(`/api/images/${img.id}/flag`, {
      flagged: !img.flagged,
      note,
    })
    img.flagged = r.flagged
    img.review_note = r.review_note
    if (member.value) member.value.flagged += r.flagged ? 1 : -1
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

function open(img?: ImageDetail) {
  router.push({
    path: `/tasks/${taskId}/label`,
    query: {
      mode: 'inspect',
      assignee: String(uid),
      title: member.value?.username ?? '',
      back: route.fullPath,
      ...(img ? { image: String(img.id) } : {}),
    },
  })
}

async function approve() {
  if (!member.value) return
  if (member.value.flagged && !(await confirmDialog('还有被标记的问题图片', `有 ${member.value.flagged} 张图片被标记为有问题，确定直接通过吗？通过后标记会被清除。`))) return
  if (!member.value.flagged && !(await confirmDialog(`通过 ${member.value.username} 的标注`, '通过后该成员的标注结束。'))) return
  try {
    const r = await api.post<{ task_finished: boolean }>(`/api/tasks/${taskId}/members/${uid}/review`, { action: 'approve' })
    toast(r.task_finished ? '已通过。全部标注审核完成，任务已自动结束 🎉' : '已通过', 'success', 4000)
    router.push({ path: `/tasks/${taskId}`, query: { tab: 'review' } })
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function reject() {
  if (!member.value) return
  const comment = await promptDialog(`打回 ${member.value.username} 的标注`, {
    message: member.value.flagged
      ? `被标记的 ${member.value.flagged} 张图片会变成「需返工」。`
      : '当前没有标记问题图片，标注员需要根据审核意见自行检查。',
    placeholder: '审核意见（标注员可见）',
    multiline: true,
    okText: '打回',
    danger: true,
  })
  if (comment === null) return
  try {
    await api.post(`/api/tasks/${taskId}/members/${uid}/review`, { action: 'reject', comment })
    toast('已打回', 'success')
    router.push({ path: `/tasks/${taskId}`, query: { tab: 'review' } })
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}
</script>

<template>
  <div class="page review-page">
    <div class="page-head">
      <router-link :to="{ path: `/tasks/${taskId}`, query: { tab: 'review' } }" class="btn btn-sm">← 返回</router-link>
      <div v-if="member" class="col" style="gap: 2px">
        <div class="row">
          <h1>审核：{{ member.username }}</h1>
          <span class="badge" :class="MEMBER_STATUS[member.status].cls">{{ MEMBER_STATUS[member.status].text }}</span>
        </div>
        <div class="faint">{{ member.school }} · {{ task?.name }} · 提交于 {{ fmtTime(member.submitted_at) }}</div>
      </div>
      <div class="spacer" />
      <template v-if="member">
        <button class="btn" @click="open()">逐张审核（大图）</button>
        <template v-if="member.status === 'submitted'">
          <button class="btn btn-danger" @click="reject">打回</button>
          <button class="btn btn-success" @click="approve">通过</button>
        </template>
        <button v-else-if="member.status === 'approved'" class="btn btn-danger" @click="reject">撤销通过</button>
      </template>
    </div>

    <div v-if="member" class="grid-4 mb-16">
      <div class="stat">
        <ProgressBar :value="member.done" :total="member.assigned" :green="member.done === member.assigned" label />
        <div class="lbl mt-8">完成进度</div>
      </div>
      <div class="stat"><div class="num">{{ member.ann_count }}</div><div class="lbl">装甲板总数</div></div>
      <div class="stat">
        <div class="num" :style="{ color: member.flagged ? 'var(--red)' : '' }">{{ member.flagged }}</div>
        <div class="lbl">标记有问题</div>
      </div>
      <div class="stat">
        <div class="num">{{ member.assigned ? (member.ann_count / member.assigned).toFixed(2) : 0 }}</div>
        <div class="lbl">平均每张装甲板数</div>
      </div>
    </div>

    <div v-if="member?.review_comment" class="notice notice-warn mb-16">上次审核意见：{{ member.review_comment }}</div>

    <div class="card">
      <div class="row mb-16">
        <select v-model="filters.status" class="select" style="width: 120px">
          <option value="">全部状态</option>
          <option value="done">已完成</option>
          <option value="todo">未完成</option>
          <option value="rework">需返工</option>
        </select>
        <select v-model="filters.flagged" class="select" style="width: 130px">
          <option value="">全部</option>
          <option value="true">只看有问题</option>
          <option value="false">只看无问题</option>
        </select>
        <select v-model="filters.has_ann" class="select" style="width: 130px">
          <option value="">有无标注</option>
          <option value="true">有标注</option>
          <option value="false">空图</option>
        </select>
        <div class="seg">
          <button :class="{ on: filters.order === 'name' }" @click="filters.order = 'name'">按文件名</button>
          <button :class="{ on: filters.order === 'random' }" @click="filters.order = 'random'">随机抽查</button>
        </div>
        <button v-if="filters.order === 'random'" class="btn btn-sm" @click="filters.seed = Math.floor(Math.random() * 100000)">
          换一批
        </button>
        <div class="spacer" />
        <div class="seg">
          <button :class="{ on: size === 's' }" @click="size = 's'">小</button>
          <button :class="{ on: size === 'm' }" @click="size = 'm'">中</button>
          <button :class="{ on: size === 'l' }" @click="size = 'l'">大</button>
        </div>
      </div>

      <div v-if="data && !data.items.length" class="empty">{{ loading ? '加载中…' : '没有图片' }}</div>
      <div
        v-else-if="data && task"
        class="thumb-grid"
        :style="{ gridTemplateColumns: `repeat(auto-fill, minmax(${gridMin}px, 1fr))`, opacity: loading ? 0.6 : 1 }"
      >
        <div v-for="img in data.items" :key="img.id" class="thumb-card" :class="{ flagged: img.flagged }">
          <div style="cursor: zoom-in" @click="open(img)">
            <AnnotatedThumb :id="img.id" :width="img.width" :height="img.height" :annotations="img.annotations" :classes="task.classes" />
          </div>
          <div class="thumb-meta">
            <span class="ellipsis" style="flex: 1" :title="img.filename">{{ basename(img.filename) }}</span>
            <span class="badge" :class="IMAGE_STATUS[img.status].cls">{{ img.ann_count }} 框</span>
            <button class="flag-btn" :class="{ on: img.flagged }" :title="img.flagged ? '取消标记' : '标记有问题'" @click="toggleFlag(img)">
              ⚑
            </button>
          </div>
          <div v-if="img.flagged && img.review_note" class="note ellipsis" :title="img.review_note">{{ img.review_note }}</div>
        </div>
      </div>
      <Pager v-if="data" v-model:page="page" :page-size="PAGE_SIZE" :total="data.total" />
    </div>
  </div>
</template>

<style scoped>
.review-page {
  max-width: 1600px;
}
.flag-btn {
  border: 1px solid var(--border);
  border-radius: 4px;
  background: #fff;
  color: var(--text-3);
  cursor: pointer;
  padding: 0 6px;
  height: 22px;
}
.flag-btn:hover {
  color: var(--red);
  border-color: #fca5a5;
}
.flag-btn.on {
  background: var(--red);
  border-color: var(--red);
  color: #fff;
}
.note {
  padding: 4px 8px 6px;
  font-size: 12px;
  color: var(--red);
}
</style>

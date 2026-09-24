<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errMsg } from '../api'
import { auth, toast } from '../store'
import ExportTab from '../task/ExportTab.vue'
import ImagesTab from '../task/ImagesTab.vue'
import MembersTab from '../task/MembersTab.vue'
import MyWork from '../task/MyWork.vue'
import OverviewTab from '../task/OverviewTab.vue'
import ReviewTab from '../task/ReviewTab.vue'
import SettingsTab from '../task/SettingsTab.vue'
import type { Task, TaskStats } from '../types'
import { ROLE_TEXT } from '../utils'

const route = useRoute()
const router = useRouter()
const task = ref<Task | null>(null)
const stats = ref<TaskStats | null>(null)
const error = ref('')

const taskId = computed(() => Number(route.params.id))

async function loadTask() {
  try {
    task.value = await api.get<Task>(`/api/tasks/${taskId.value}`)
    error.value = ''
    document.title = `${task.value.name} · 华南虎一起标`
    if (task.value.is_manager) await loadStats()
  } catch (e) {
    error.value = errMsg(e)
  }
}

async function loadStats() {
  try {
    stats.value = await api.get<TaskStats>(`/api/tasks/${taskId.value}/stats`)
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function refresh() {
  await loadTask()
}

watch(taskId, loadTask, { immediate: true })

type TabKey = 'overview' | 'images' | 'members' | 'review' | 'export' | 'settings' | 'mywork'

const tabs = computed(() => {
  if (!task.value?.is_manager) return [] as { key: TabKey; text: string; count?: number }[]
  const submitted = stats.value?.members.filter((m) => m.status === 'submitted').length ?? 0
  const list: { key: TabKey; text: string; count?: number }[] = [
    { key: 'overview', text: '概览' },
    { key: 'images', text: '图片' },
    { key: 'members', text: '成员与分配' },
    { key: 'review', text: '审核', count: submitted || undefined },
    { key: 'export', text: '导出' },
    { key: 'settings', text: '设置' },
  ]
  // 管理员自己也被分配了图片时，多一个「我的标注」
  const mine = stats.value?.members.find((m) => m.user_id === auth.user?.id)
  if (mine && mine.assigned > 0) list.push({ key: 'mywork', text: '我的标注' })
  return list
})

const tab = computed<TabKey>(() => {
  const t = route.query.tab as TabKey | undefined
  return t && tabs.value.some((x) => x.key === t) ? t : 'overview'
})

function setTab(key: TabKey) {
  router.replace({ query: { ...route.query, tab: key } })
}

</script>

<template>
  <div class="page">
    <div v-if="error" class="card empty">
      <div class="big">🔒</div>
      {{ error }}
      <div class="mt-16"><router-link to="/" class="btn">返回首页</router-link></div>
    </div>
    <template v-else-if="task">
      <div class="page-head">
        <div class="col" style="gap: 4px; min-width: 0">
          <div class="row">
            <h1 class="ellipsis">{{ task.name }}</h1>
            <span class="badge" :class="task.status === 'finished' ? 'badge-green' : 'badge-blue'">
              {{ task.status === 'finished' ? '已结束' : '进行中' }}
            </span>
            <span class="badge badge-gray">{{ ROLE_TEXT[task.my_role] }}</span>
          </div>
          <div class="faint">
            发布者 {{ task.owner.username }}（{{ task.owner.school }}）· 四点模型 · {{ task.classes.length }} 个类别
          </div>
        </div>
      </div>

      <template v-if="task.is_manager">
        <div class="tabs">
          <button v-for="t in tabs" :key="t.key" :class="{ on: tab === t.key }" @click="setTab(t.key)">
            {{ t.text }}<span v-if="t.count" class="count">{{ t.count }}</span>
          </button>
        </div>
        <OverviewTab v-if="tab === 'overview'" :task="task" :stats="stats" @refresh="refresh" @tab="setTab" />
        <ImagesTab v-else-if="tab === 'images'" :task="task" :stats="stats" @refresh="loadStats" />
        <MembersTab v-else-if="tab === 'members'" :task="task" :stats="stats" @refresh="loadStats" />
        <ReviewTab v-else-if="tab === 'review'" :task="task" :stats="stats" @refresh="refresh" />
        <ExportTab v-else-if="tab === 'export'" :task="task" :stats="stats" />
        <SettingsTab v-else-if="tab === 'settings'" :task="task" @saved="(t: Task) => (task = t)" @refresh="refresh" />
        <MyWork v-else-if="tab === 'mywork'" :task="task" @refresh="refresh" />
      </template>
      <MyWork v-else :task="task" @refresh="refresh" />
    </template>
    <div v-else class="empty">加载中…</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errMsg } from '../api'
import ProgressBar from '../components/ProgressBar.vue'
import { auth, toast } from '../store'
import type { TaskSummary } from '../types'
import { MEMBER_STATUS, ROLE_TEXT, fmtTime, pct } from '../utils'

const tasks = ref<TaskSummary[]>([])
const loading = ref(true)

onMounted(async () => {
  try {
    tasks.value = await api.get<TaskSummary[]>('/api/tasks')
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    loading.value = false
  }
})

const labelTasks = computed(() => tasks.value.filter((t) => t.my_assigned > 0 || !t.is_manager))
const managedTasks = computed(() => tasks.value.filter((t) => t.is_manager))
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>你好，{{ auth.user?.username }}</h1>
        <div class="muted">{{ auth.user?.school }}</div>
      </div>
      <div class="spacer" />
      <router-link to="/tasks/new" class="btn btn-primary btn-lg">＋ 发布标注任务</router-link>
    </div>

    <div v-if="loading" class="empty">加载中…</div>
    <template v-else>
      <section class="sec">
        <h2 class="sec-title">我的标注 <span class="faint">{{ labelTasks.length }}</span></h2>
        <div v-if="!labelTasks.length" class="card empty">
          <div class="big">🐯</div>
          还没有分配给你的标注任务。管理员把你加入任务并分配图片后会出现在这里。
        </div>
        <div v-else class="cards">
          <router-link v-for="t in labelTasks" :key="t.id" :to="`/tasks/${t.id}`" class="tcard">
            <div class="tcard-head">
              <span class="tname ellipsis">{{ t.name }}</span>
              <span v-if="t.status === 'finished'" class="badge badge-gray">已结束</span>
              <span v-else class="badge" :class="MEMBER_STATUS[t.my_status].cls">{{ MEMBER_STATUS[t.my_status].text }}</span>
            </div>
            <div class="faint">发布者 {{ t.owner.username }} · {{ t.owner.school }}</div>
            <template v-if="t.my_assigned > 0">
              <ProgressBar class="mt-16" :value="t.my_done" :total="t.my_assigned" :green="t.my_done === t.my_assigned" label />
              <div class="tcard-foot">
                <span class="muted">完成 {{ pct(t.my_done, t.my_assigned) }}%</span>
                <span class="go">{{ t.my_done < t.my_assigned ? '继续标注 →' : '查看 →' }}</span>
              </div>
            </template>
            <div v-else class="tcard-foot">
              <span class="muted">等待管理员分配图片</span>
            </div>
          </router-link>
        </div>
      </section>

      <section class="sec">
        <h2 class="sec-title">我管理的任务 <span class="faint">{{ managedTasks.length }}</span></h2>
        <div v-if="!managedTasks.length" class="card empty">
          <div class="big">📦</div>
          你还没有发布过任务。<router-link to="/tasks/new">发布第一个标注任务</router-link>
        </div>
        <div v-else class="cards">
          <router-link v-for="t in managedTasks" :key="t.id" :to="`/tasks/${t.id}`" class="tcard">
            <div class="tcard-head">
              <span class="tname ellipsis">{{ t.name }}</span>
              <span class="badge" :class="t.status === 'finished' ? 'badge-green' : 'badge-blue'">
                {{ t.status === 'finished' ? '已结束' : '进行中' }}
              </span>
            </div>
            <div class="faint">{{ ROLE_TEXT[t.my_role] }} · {{ t.members }} 名成员 · {{ t.class_count }} 个类别 · {{ fmtTime(t.created_at) }}</div>
            <ProgressBar class="mt-16" :value="t.done" :total="t.total" :green="t.total > 0 && t.done === t.total" label />
            <div class="tcard-foot">
              <span class="muted">{{ t.total }} 张图片 · 完成 {{ pct(t.done, t.total) }}%</span>
              <span class="go">管理 →</span>
            </div>
          </router-link>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.sec + .sec {
  margin-top: 32px;
}
.sec-title {
  font-size: 16px;
  margin-bottom: 12px;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}
.tcard {
  display: block;
  padding: 16px 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: #fff;
  color: var(--text);
  box-shadow: var(--shadow);
  transition:
    transform 0.12s,
    box-shadow 0.12s,
    border-color 0.12s;
}
.tcard:hover {
  text-decoration: none;
  border-color: var(--brand);
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(16, 24, 40, 0.08);
}
.tcard-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.tname {
  flex: 1;
  font-size: 16px;
  font-weight: 600;
}
.tcard-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
  font-size: 13px;
}
.go {
  color: var(--brand-600);
  font-weight: 600;
}
</style>

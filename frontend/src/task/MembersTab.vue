<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api, errMsg } from '../api'
import ProgressBar from '../components/ProgressBar.vue'
import { auth, confirmDialog, toast } from '../store'
import type { MemberStat, Task, TaskStats } from '../types'
import { MEMBER_STATUS, ROLE_TEXT, debounce } from '../utils'

const props = defineProps<{ task: Task; stats: TaskStats | null }>()
const emit = defineEmits<{ (e: 'refresh'): void }>()

const members = computed<MemberStat[]>(() => props.stats?.members ?? [])

// ---------------------------------------------------------------- 添加成员

interface FoundUser {
  id: number
  username: string
  school: string
  is_member: boolean
}
const schools = ref<{ school: string; users: number }[]>([])
const search = reactive({ school: auth.user?.school ?? '', q: '', role: 'annotator' as 'annotator' | 'manager' })
const found = ref<FoundUser[]>([])
const picked = ref(new Set<number>())
const searching = ref(false)

async function doSearch() {
  searching.value = true
  try {
    found.value = await api.get<FoundUser[]>('/api/users', {
      q: search.q,
      school: search.school,
      task_id: props.task.id,
      limit: 100,
    })
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    searching.value = false
  }
}
const searchDebounced = debounce(doSearch, 250)
watch(() => search.q, () => searchDebounced())
watch(() => search.school, doSearch)

onMounted(async () => {
  schools.value = await api.get<{ school: string; users: number }[]>('/api/schools').catch(() => [])
  doSearch()
})

function togglePick(u: FoundUser) {
  if (u.is_member) return
  const s = new Set(picked.value)
  if (s.has(u.id)) s.delete(u.id)
  else s.add(u.id)
  picked.value = s
}

function pickAll() {
  picked.value = new Set(found.value.filter((u) => !u.is_member).map((u) => u.id))
}

async function addPicked() {
  if (!picked.value.size) return
  try {
    const r = await api.post<{ added: number }>(`/api/tasks/${props.task.id}/members`, {
      user_ids: Array.from(picked.value),
      role: search.role,
    })
    toast(`已添加 ${r.added} 名成员`, 'success')
    picked.value = new Set()
    emit('refresh')
    doSearch()
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

// ---------------------------------------------------------------- 成员操作

async function setRole(m: MemberStat, role: 'annotator' | 'manager') {
  try {
    await api.patch(`/api/tasks/${props.task.id}/members/${m.user_id}`, { role })
    emit('refresh')
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function remove(m: MemberStat) {
  const ok = await confirmDialog(
    `移除 ${m.username}`,
    `分配给 TA 的 ${m.assigned} 张图片会回到未分配池（已有标注会保留）。`,
    { danger: true, okText: '移除' },
  )
  if (!ok) return
  try {
    await api.del(`/api/tasks/${props.task.id}/members/${m.user_id}`)
    toast('已移除', 'success')
    emit('refresh')
    doSearch()
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function reclaim(m: MemberStat) {
  if (!(await confirmDialog(`回收 ${m.username} 未完成的图片`, `${m.todo} 张未完成的图片将回到未分配池。`))) return
  try {
    const r = await api.post<{ reclaimed: number }>(`/api/tasks/${props.task.id}/members/${m.user_id}/reclaim`)
    toast(`已回收 ${r.reclaimed} 张`, 'success')
    emit('refresh')
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

// ---------------------------------------------------------------- 分配

const alloc = reactive({
  mode: 'even' as 'even' | 'count' | 'ratio',
  order: 'sequential' as 'sequential' | 'random',
  reclaim: false,
  include: {} as Record<number, boolean>,
  values: {} as Record<number, number>,
  busy: false,
})

watch(
  members,
  (ms) => {
    for (const m of ms) {
      if (!(m.user_id in alloc.include)) alloc.include[m.user_id] = m.role === 'annotator'
      if (!(m.user_id in alloc.values)) alloc.values[m.user_id] = 0
    }
  },
  { immediate: true },
)

const pool = computed(() => {
  if (!props.stats) return 0
  if (!alloc.reclaim) return props.stats.unassigned
  return props.stats.unassigned + members.value.reduce((s, m) => s + m.todo, 0)
})

const chosen = computed(() => members.value.filter((m) => alloc.include[m.user_id]))

const preview = computed<Record<number, number>>(() => {
  const n = pool.value
  const list = chosen.value
  const out: Record<number, number> = {}
  if (!list.length) return out
  if (alloc.mode === 'even') {
    const base = Math.floor(n / list.length)
    const extra = n % list.length
    list.forEach((m, i) => (out[m.user_id] = base + (i < extra ? 1 : 0)))
  } else if (alloc.mode === 'count') {
    list.forEach((m) => (out[m.user_id] = Math.max(0, Math.floor(alloc.values[m.user_id] || 0))))
  } else {
    const exact = list.map((m) => (n * Math.max(0, alloc.values[m.user_id] || 0)) / 100)
    const counts = exact.map(Math.floor)
    const target = Math.min(n, Math.round(exact.reduce((a, b) => a + b, 0)))
    const order = exact.map((x, i) => [x - counts[i], i] as const).sort((a, b) => b[0] - a[0])
    for (let k = 0; k < target - counts.reduce((a, b) => a + b, 0) && k < order.length; k++) counts[order[k][1]]++
    list.forEach((m, i) => (out[m.user_id] = counts[i]))
  }
  return out
})

const previewTotal = computed(() => Object.values(preview.value).reduce((a, b) => a + b, 0))
const ratioSum = computed(() => chosen.value.reduce((s, m) => s + (alloc.values[m.user_id] || 0), 0))
const allocError = computed(() => {
  if (!chosen.value.length) return '请至少勾选一名成员'
  if (!pool.value) return '没有可分配的图片'
  if (alloc.mode === 'count' && previewTotal.value > pool.value) return `分配总数 ${previewTotal.value} 超过可分配的 ${pool.value} 张`
  if (alloc.mode === 'ratio' && ratioSum.value > 100.0001) return `比例总和 ${ratioSum.value}% 超过 100%`
  return ''
})

function fillEvenRatio() {
  const list = chosen.value
  if (!list.length) return
  const each = Math.floor((100 / list.length) * 10) / 10
  list.forEach((m) => (alloc.values[m.user_id] = each))
}

async function doAssign() {
  if (allocError.value) return
  alloc.busy = true
  try {
    const r = await api.post<{ assigned: Record<string, number>; remaining: number; reclaimed: number }>(
      `/api/tasks/${props.task.id}/assign`,
      {
        mode: alloc.mode,
        order: alloc.order,
        reclaim: alloc.reclaim,
        entries: chosen.value.map((m) => ({ user_id: m.user_id, value: alloc.values[m.user_id] || 0 })),
      },
    )
    const n = Object.values(r.assigned).reduce((a, b) => a + b, 0)
    toast(`已分配 ${n} 张${r.remaining ? `，剩余 ${r.remaining} 张未分配` : ''}`, 'success')
    emit('refresh')
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    alloc.busy = false
  }
}
</script>

<template>
  <div>
    <div class="card">
      <div class="card-title">任务成员 <span class="faint">{{ members.length }} 人</span></div>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>成员</th>
              <th>角色</th>
              <th>状态</th>
              <th style="width: 28%">进度</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in members" :key="m.user_id">
              <td>
                <b>{{ m.username }}</b>
                <div class="faint">{{ m.school }}</div>
              </td>
              <td>
                <span v-if="m.role === 'owner'" class="badge badge-orange">创建者</span>
                <select
                  v-else
                  class="select input-sm"
                  style="width: 100px"
                  :value="m.role"
                  @change="setRole(m, ($event.target as HTMLSelectElement).value as 'annotator' | 'manager')"
                >
                  <option value="annotator">{{ ROLE_TEXT.annotator }}</option>
                  <option value="manager">{{ ROLE_TEXT.manager }}</option>
                </select>
              </td>
              <td>
                <span v-if="m.assigned" class="badge" :class="MEMBER_STATUS[m.status].cls">{{ MEMBER_STATUS[m.status].text }}</span>
                <span v-else class="faint">-</span>
              </td>
              <td>
                <ProgressBar v-if="m.assigned" :value="m.done" :total="m.assigned" label />
                <span v-else class="faint">未分配</span>
              </td>
              <td class="nowrap" style="text-align: right">
                <button v-if="m.todo" class="link-btn" @click="reclaim(m)">回收未完成</button>
                <button v-if="m.role !== 'owner'" class="link-btn danger" style="margin-left: 12px" @click="remove(m)">移除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="faint mt-8">管理员可以管理任务、审核和导出；任何成员（包括管理员）都可以被分配图片进行标注。</div>
    </div>

    <div class="grid-2 mt-16 members-grid">
      <div class="card">
        <div class="card-title">添加成员</div>
        <div class="row mb-8">
          <select v-model="search.school" class="select" style="flex: 1; min-width: 160px">
            <option :value="auth.user?.school ?? ''">本校（{{ auth.user?.school }}）</option>
            <option value="">全部学校</option>
            <option v-for="s in schools.filter((x) => x.school !== auth.user?.school)" :key="s.school" :value="s.school">
              {{ s.school }}（{{ s.users }}人）
            </option>
          </select>
          <input v-model="search.q" class="input" style="flex: 1; min-width: 140px" placeholder="搜索用户名" />
        </div>
        <div class="user-list">
          <div v-if="!found.length" class="empty" style="padding: 24px">{{ searching ? '搜索中…' : '没有找到用户' }}</div>
          <label
            v-for="u in found"
            :key="u.id"
            class="user-row"
            :class="{ disabled: u.is_member, on: picked.has(u.id) }"
          >
            <input type="checkbox" :checked="picked.has(u.id) || u.is_member" :disabled="u.is_member" @change="togglePick(u)" />
            <b>{{ u.username }}</b>
            <span class="faint ellipsis" style="flex: 1">{{ u.school }}</span>
            <span v-if="u.is_member" class="badge badge-gray">已加入</span>
          </label>
        </div>
        <div class="row mt-16">
          <button class="btn btn-sm" @click="pickAll">全选</button>
          <div class="spacer" />
          <span class="faint">添加为</span>
          <select v-model="search.role" class="select input-sm" style="width: 100px">
            <option value="annotator">标注员</option>
            <option value="manager">管理员</option>
          </select>
          <button class="btn btn-primary" :disabled="!picked.size" @click="addPicked">添加 {{ picked.size || '' }} 人</button>
        </div>
      </div>

      <div class="card">
        <div class="card-title">分配图片</div>
        <div class="row mb-16">
          <div class="seg">
            <button :class="{ on: alloc.mode === 'even' }" @click="alloc.mode = 'even'">一键均分</button>
            <button :class="{ on: alloc.mode === 'count' }" @click="alloc.mode = 'count'">按张数</button>
            <button :class="{ on: alloc.mode === 'ratio' }" @click="alloc.mode = 'ratio'">按比例</button>
          </div>
          <button v-if="alloc.mode === 'ratio'" class="btn btn-sm" @click="fillEvenRatio">平均填充比例</button>
        </div>

        <div class="alloc-list">
          <div v-for="m in members" :key="m.user_id" class="alloc-row" :class="{ off: !alloc.include[m.user_id] }">
            <label class="check" style="flex: 1; min-width: 0">
              <input v-model="alloc.include[m.user_id]" type="checkbox" />
              <b class="ellipsis">{{ m.username }}</b>
              <span class="faint nowrap">已有 {{ m.assigned }}（完成 {{ m.done }}）</span>
            </label>
            <template v-if="alloc.include[m.user_id]">
              <template v-if="alloc.mode !== 'even'">
                <input v-model.number="alloc.values[m.user_id]" class="input input-sm" type="number" min="0" style="width: 80px" />
                <span class="faint">{{ alloc.mode === 'ratio' ? '%' : '张' }}</span>
              </template>
              <span class="plus">+{{ preview[m.user_id] ?? 0 }}</span>
            </template>
          </div>
        </div>

        <div class="col mt-16" style="gap: 6px">
          <label class="check">
            <input v-model="alloc.reclaim" type="checkbox" />
            先回收所有人未完成的图片，再一起重新分配（用于重新平衡工作量）
          </label>
          <label class="check">
            <input :checked="alloc.order === 'sequential'" type="radio" name="order" @change="alloc.order = 'sequential'" />
            按文件名连续分块（视频序列推荐，方便复制上一帧标注）
          </label>
          <label class="check">
            <input :checked="alloc.order === 'random'" type="radio" name="order" @change="alloc.order = 'random'" />
            随机打散
          </label>
        </div>

        <div class="alloc-foot mt-16">
          <div>
            可分配 <b>{{ pool }}</b> 张，本次分配 <b>{{ previewTotal }}</b> 张
            <span v-if="pool - previewTotal > 0" class="faint">，剩余 {{ pool - previewTotal }} 张留在未分配池</span>
            <div v-if="allocError" class="error-text">{{ allocError }}</div>
          </div>
          <div class="spacer" />
          <button class="btn btn-primary" :disabled="!!allocError || alloc.busy" @click="doAssign">确认分配</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.members-grid {
  align-items: start;
}
.user-list {
  max-height: 320px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.user-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
}
.user-row:last-child {
  border-bottom: none;
}
.user-row:hover {
  background: #fafbfc;
}
.user-row.on {
  background: var(--brand-50);
}
.user-row.disabled {
  cursor: default;
  opacity: 0.6;
}
.user-row input {
  accent-color: var(--brand);
}
.alloc-list {
  max-height: 300px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.alloc-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
}
.alloc-row:last-child {
  border-bottom: none;
}
.alloc-row.off {
  opacity: 0.55;
}
.plus {
  min-width: 56px;
  text-align: right;
  color: var(--green);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.alloc-foot {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
@media (max-width: 1000px) {
  .members-grid {
    grid-template-columns: 1fr;
  }
}
</style>

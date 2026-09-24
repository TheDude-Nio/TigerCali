<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { api, errMsg } from '../api'
import ProgressBar from '../components/ProgressBar.vue'
import { confirmDialog, promptDialog, toast } from '../store'
import type { MemberStat, Task, TaskStats } from '../types'
import { MEMBER_STATUS, fmtTime } from '../utils'

const props = defineProps<{ task: Task; stats: TaskStats | null }>()
const emit = defineEmits<{ (e: 'refresh'): void }>()
const router = useRouter()

const ORDER: Record<string, number> = { submitted: 0, rejected: 1, labeling: 2, approved: 3 }
const list = computed(() =>
  (props.stats?.members ?? [])
    .filter((m) => m.assigned > 0)
    .sort((a, b) => ORDER[a.status] - ORDER[b.status] || (a.submitted_at ?? '').localeCompare(b.submitted_at ?? '')),
)

interface ReviewResult {
  status: string
  task_finished: boolean
}

async function approve(m: MemberStat) {
  if (!(await confirmDialog(`通过 ${m.username} 的标注`, `共 ${m.assigned} 张图片、${m.ann_count} 个标注。通过后该成员的标注结束。`))) return
  try {
    const r = await api.post<ReviewResult>(`/api/tasks/${props.task.id}/members/${m.user_id}/review`, { action: 'approve' })
    toast(r.task_finished ? '已通过。所有标注均已审核通过，任务已自动结束 🎉' : '已通过', 'success', 4000)
    emit('refresh')
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function reject(m: MemberStat) {
  const comment = await promptDialog(`打回 ${m.username} 的标注`, {
    message: m.flagged ? `已标记 ${m.flagged} 张有问题的图片，打回后这些图片会变成「需返工」。` : '建议先在逐张审核里标记有问题的图片。',
    placeholder: '审核意见（标注员可以看到）',
    multiline: true,
    okText: '打回',
    danger: true,
  })
  if (comment === null) return
  try {
    await api.post(`/api/tasks/${props.task.id}/members/${m.user_id}/review`, { action: 'reject', comment })
    toast('已打回', 'success')
    emit('refresh')
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}
</script>

<template>
  <div class="card">
    <div class="card-title">
      审核
      <span class="faint">标注员全部完成并提交后，在这里逐张检查，通过或打回</span>
    </div>
    <div v-if="!list.length" class="empty">还没有成员被分配图片</div>
    <div v-else class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>成员</th>
            <th>状态</th>
            <th style="width: 24%">进度</th>
            <th class="num">装甲板</th>
            <th class="num">问题标记</th>
            <th>提交时间</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in list" :key="m.user_id">
            <td>
              <b>{{ m.username }}</b>
              <div class="faint">{{ m.school }}</div>
            </td>
            <td>
              <span class="badge" :class="MEMBER_STATUS[m.status].cls">{{ MEMBER_STATUS[m.status].text }}</span>
              <div v-if="m.review_comment" class="faint ellipsis" style="max-width: 160px" :title="m.review_comment">
                {{ m.review_comment }}
              </div>
            </td>
            <td><ProgressBar :value="m.done" :total="m.assigned" :green="m.done === m.assigned" label /></td>
            <td class="num">{{ m.ann_count }}</td>
            <td class="num" :style="{ color: m.flagged ? 'var(--red)' : '' }">{{ m.flagged || '' }}</td>
            <td class="faint nowrap">{{ fmtTime(m.submitted_at) }}</td>
            <td class="nowrap" style="text-align: right">
              <button class="btn btn-sm" @click="router.push(`/tasks/${task.id}/review/${m.user_id}`)">逐张审核</button>
              <template v-if="m.status === 'submitted'">
                <button class="btn btn-sm btn-success" style="margin-left: 6px" @click="approve(m)">通过</button>
                <button class="btn btn-sm btn-danger" style="margin-left: 6px" @click="reject(m)">打回</button>
              </template>
              <button v-else-if="m.status === 'approved'" class="btn btn-sm btn-danger" style="margin-left: 6px" @click="reject(m)">
                撤销通过
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

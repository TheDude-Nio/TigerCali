<script setup lang="ts">
import { computed } from 'vue'
import { api, errMsg } from '../api'
import MarkdownView from '../components/MarkdownView.vue'
import ProgressBar from '../components/ProgressBar.vue'
import { confirmDialog, toast } from '../store'
import type { Task, TaskStats } from '../types'
import { MEMBER_STATUS, ROLE_TEXT, pct } from '../utils'

type TabKey = 'overview' | 'images' | 'members' | 'review' | 'export' | 'settings' | 'mywork'
const props = defineProps<{ task: Task; stats: TaskStats | null }>()
const emit = defineEmits<{ (e: 'refresh'): void; (e: 'tab', t: TabKey): void }>()

const workers = computed(() => (props.stats?.members ?? []).filter((m) => m.assigned > 0 || m.role === 'annotator'))
const steps = computed(() => {
  const s = props.stats
  return [
    { done: !!s && s.total > 0, text: '上传图片', tab: 'images' as TabKey },
    { done: !!s && s.members.length > 1, text: '添加标注员', tab: 'members' as TabKey },
    { done: !!s && s.total > 0 && s.unassigned === 0, text: '分配图片', tab: 'members' as TabKey },
    { done: !!s && s.total > 0 && s.done === s.total, text: '等待标注完成', tab: 'overview' as TabKey },
    { done: props.task.status === 'finished', text: '审核通过', tab: 'review' as TabKey },
    { done: false, text: '导出 YOLO 数据集', tab: 'export' as TabKey },
  ]
})

async function setStatus(status: 'active' | 'finished') {
  const text = status === 'finished' ? '结束任务后标注员将不能再修改标注。确定结束吗？' : '重新开启后标注员可以继续修改。'
  if (!(await confirmDialog(status === 'finished' ? '结束任务' : '重新开启任务', text))) return
  try {
    await api.patch(`/api/tasks/${props.task.id}`, { status })
    toast('已更新', 'success')
    emit('refresh')
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}
</script>

<template>
  <div v-if="stats">
    <div class="card">
      <div class="steps">
        <button v-for="(s, i) in steps" :key="i" class="step" :class="{ done: s.done }" @click="emit('tab', s.tab)">
          <span class="step-no">{{ s.done ? '✓' : i + 1 }}</span>{{ s.text }}
        </button>
      </div>
    </div>

    <div class="grid-4 mt-16">
      <div class="stat"><div class="num">{{ stats.total }}</div><div class="lbl">图片总数</div></div>
      <div class="stat">
        <div class="num">{{ stats.done }}</div>
        <div class="lbl">已完成 {{ pct(stats.done, stats.total) }}%</div>
      </div>
      <div class="stat">
        <div class="num" :style="{ color: stats.unassigned ? 'var(--orange)' : '' }">{{ stats.unassigned }}</div>
        <div class="lbl">未分配</div>
      </div>
      <div class="stat"><div class="num">{{ stats.ann_count }}</div><div class="lbl">装甲板标注数 · 今日完成 {{ stats.done_today }} 张</div></div>
    </div>

    <div class="card mt-16">
      <div class="card-title">
        标注进度
        <div class="spacer" />
        <button class="btn btn-sm" @click="emit('refresh')">刷新</button>
        <button class="btn btn-sm" @click="emit('tab', 'members')">分配图片</button>
      </div>
      <div v-if="!workers.length" class="empty">还没有标注员。去「成员与分配」添加队员并分配图片。</div>
      <div v-else class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>成员</th>
              <th>状态</th>
              <th style="width: 34%">进度</th>
              <th class="num">装甲板</th>
              <th class="num">今日</th>
              <th class="num">返工</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in workers" :key="m.user_id">
              <td>
                <b>{{ m.username }}</b>
                <div class="faint">{{ m.school }} · {{ ROLE_TEXT[m.role] }}</div>
              </td>
              <td><span class="badge" :class="MEMBER_STATUS[m.status].cls">{{ MEMBER_STATUS[m.status].text }}</span></td>
              <td><ProgressBar :value="m.done" :total="m.assigned" :green="m.assigned > 0 && m.done === m.assigned" label /></td>
              <td class="num">{{ m.ann_count }}</td>
              <td class="num">{{ m.done_today }}</td>
              <td class="num">{{ m.rework || '' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="grid-2 mt-16">
      <div class="card">
        <div class="card-title">
          标注要求
          <div class="spacer" />
          <button class="btn btn-sm" @click="emit('tab', 'settings')">编辑</button>
        </div>
        <div class="req">
          <MarkdownView v-if="task.description.trim()" :source="task.description" />
          <div v-else class="faint">还没有填写标注要求</div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">任务状态</div>
        <p v-if="task.status === 'active'" class="muted">
          任务进行中。所有图片都分配完、完成并审核通过后，任务会自动结束；也可以手动结束。
        </p>
        <p v-else class="muted">任务已结束，标注员不能再修改。随时可以导出数据集。</p>
        <div class="row">
          <button v-if="task.status === 'active'" class="btn" @click="setStatus('finished')">手动结束任务</button>
          <button v-else class="btn" @click="setStatus('active')">重新开启任务</button>
          <button class="btn btn-primary" @click="emit('tab', 'export')">导出数据集</button>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="empty">加载中…</div>
</template>

<style scoped>
.steps {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.step {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px 6px 6px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #fff;
  font: inherit;
  color: var(--text-2);
  cursor: pointer;
}
.step:hover {
  border-color: var(--brand);
}
.step-no {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #eef0f3;
  font-size: 12px;
  font-weight: 700;
}
.step.done {
  color: var(--green);
  border-color: #bbf7d0;
  background: #f0fdf4;
}
.step.done .step-no {
  background: var(--green);
  color: #fff;
}
.req {
  max-height: 320px;
  overflow: auto;
}
</style>

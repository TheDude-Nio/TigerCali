<script setup lang="ts">
import { computed } from 'vue'
import { api, errMsg } from '../api'
import MarkdownView from '../components/MarkdownView.vue'
import ProgressBar from '../components/ProgressBar.vue'
import StatCard from '../components/StatCard.vue'
import { confirmDialog, toast } from '../store'
import type { Task, TaskStats } from '../types'
import { MEMBER_STATUS, ROLE_TEXT, pct } from '../utils'

type TabKey = 'overview' | 'images' | 'members' | 'review' | 'export' | 'settings' | 'mywork'
const props = defineProps<{ task: Task; stats: TaskStats | null }>()
const emit = defineEmits<{ (e: 'refresh'): void; (e: 'tab', t: TabKey): void }>()

const workers = computed(() => (props.stats?.members ?? []).filter((m) => m.assigned > 0 || m.role === 'annotator'))
// 只提示当前该做的一件事。各步骤并不严格按顺序完成（比如管理员可以不加人、直接分给自己），
// 逐项打勾会出现「第 2 步没勾、第 3 步勾了」的混乱状态
const nextStep = computed<{ tag: string; text: string; action?: string; tab?: TabKey } | null>(() => {
  const s = props.stats
  if (!s) return null
  if (s.total === 0) return { tag: '下一步', text: '还没有图片：上传图片、文件夹或 zip，可附带预标注 txt', action: '上传图片', tab: 'images' }
  if (s.unassigned > 0) {
    return s.members.length > 1
      ? { tag: '下一步', text: `还有 ${s.unassigned} 张图片没有分配`, action: '分配图片', tab: 'members' }
      : { tag: '下一步', text: '把队员加入任务，再把图片分配给他们（也可以分给自己）', action: '添加成员', tab: 'members' }
  }
  if (props.task.status === 'finished') return { tag: '已完成', text: '全部图片已审核通过，可以导出数据集训练了', action: '导出数据集', tab: 'export' }
  const submitted = s.members.filter((m) => m.status === 'submitted').length
  if (submitted) return { tag: '下一步', text: `${submitted} 人已提交，等待你审核`, action: '去审核', tab: 'review' }
  return { tag: '进行中', text: `正在标注：已完成 ${s.done} / ${s.total} 张，标注员提交后会在这里提醒你审核` }
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
    <div v-if="nextStep" class="next">
      <span class="next-tag">{{ nextStep.tag }}</span>
      <span>{{ nextStep.text }}</span>
      <div class="spacer" />
      <button v-if="nextStep.tab" class="btn btn-sm btn-primary" @click="emit('tab', nextStep.tab)">{{ nextStep.action }} →</button>
    </div>

    <div class="grid-4 mt-16">
      <StatCard icon="image" tone="blue" :value="stats.total" label="图片总数" />
      <StatCard icon="check" tone="green" :value="stats.done" :label="`已完成 ${pct(stats.done, stats.total)}%`" />
      <StatCard icon="inbox" :tone="stats.unassigned ? 'brand' : 'gray'" :value="stats.unassigned" label="未分配" />
      <StatCard icon="target" tone="purple" :value="stats.ann_count" :label="`装甲板标注数 · 今日完成 ${stats.done_today} 张`" />
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
.next {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 12px 14px 12px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow);
}
.next-tag {
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--brand-50);
  color: var(--brand-600);
  font-size: 12px;
  font-weight: 600;
}
.req {
  max-height: 320px;
  overflow: auto;
}
</style>

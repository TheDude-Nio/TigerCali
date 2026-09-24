<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errMsg } from '../api'
import MarkdownView from '../components/MarkdownView.vue'
import ProgressBar from '../components/ProgressBar.vue'
import { confirmDialog, toast } from '../store'
import type { MyProgress, Task } from '../types'
import { MEMBER_STATUS, classColor, fmtTime, pct } from '../utils'

const props = defineProps<{ task: Task }>()
const emit = defineEmits<{ (e: 'refresh'): void }>()
const router = useRouter()

const prog = ref<MyProgress | null>(null)
const busy = ref(false)

async function load() {
  try {
    prog.value = await api.get<MyProgress>(`/api/tasks/${props.task.id}/my-progress`)
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}
onMounted(load)

const allDone = computed(() => !!prog.value && prog.value.assigned > 0 && prog.value.done === prog.value.assigned)
const canEdit = computed(
  () => props.task.status === 'active' && !!prog.value && ['labeling', 'rejected'].includes(prog.value.status),
)

function start(filter?: string) {
  router.push({ path: `/tasks/${props.task.id}/label`, query: filter ? { filter } : {} })
}

async function submit() {
  if (!(await confirmDialog('提交审核', '提交后需要等待管理员审核，审核期间不能修改（可以撤回）。确定提交吗？'))) return
  busy.value = true
  try {
    await api.post(`/api/tasks/${props.task.id}/submit`)
    toast('已提交，等待管理员审核', 'success')
    await load()
    emit('refresh')
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    busy.value = false
  }
}

async function withdraw() {
  busy.value = true
  try {
    await api.post(`/api/tasks/${props.task.id}/withdraw`)
    toast('已撤回，可以继续修改', 'success')
    await load()
    emit('refresh')
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="mywork">
    <div class="main-col">
      <div v-if="prog" class="card">
        <div class="card-title">
          我的进度
          <span class="badge" :class="MEMBER_STATUS[prog.status].cls">{{ MEMBER_STATUS[prog.status].text }}</span>
          <div class="spacer" />
          <span class="faint">今日完成 {{ prog.done_today }} 张</span>
        </div>

        <div v-if="task.status === 'finished'" class="notice notice-ok mb-16">任务已结束，感谢参与！</div>
        <div v-else-if="prog.status === 'rejected'" class="notice notice-error mb-16">
          <b>被打回，需要修改后重新提交。</b>
          <div v-if="prog.review_comment" class="mt-8" style="white-space: pre-wrap">审核意见：{{ prog.review_comment }}</div>
          <div v-if="prog.rework" class="mt-8">有 <b>{{ prog.rework }}</b> 张图片被标记为需要返工。</div>
        </div>
        <div v-else-if="prog.status === 'submitted'" class="notice notice-info mb-16">
          已于 {{ fmtTime(prog.submitted_at) }} 提交，等待管理员审核。审核期间不能修改，如需修改请先撤回。
        </div>
        <div v-else-if="prog.status === 'approved'" class="notice notice-ok mb-16">
          审核已通过 🎉 {{ prog.review_comment ? `审核意见：${prog.review_comment}` : '' }}
        </div>

        <template v-if="prog.assigned > 0">
          <ProgressBar :value="prog.done" :total="prog.assigned" :green="allDone" label />
          <div class="grid-4 mt-16">
            <div class="stat"><div class="num">{{ prog.assigned }}</div><div class="lbl">分配给我</div></div>
            <div class="stat"><div class="num">{{ prog.done }}</div><div class="lbl">已完成 {{ pct(prog.done, prog.assigned) }}%</div></div>
            <div class="stat"><div class="num">{{ prog.todo }}</div><div class="lbl">未完成</div></div>
            <div class="stat">
              <div class="num" :style="{ color: prog.rework ? 'var(--red)' : '' }">{{ prog.rework }}</div>
              <div class="lbl">需返工</div>
            </div>
          </div>
          <div class="row mt-24">
            <button class="btn btn-primary btn-lg" @click="start()">
              {{ !canEdit ? '查看我的标注' : prog.done === 0 ? '开始标注' : '继续标注' }}
            </button>
            <button v-if="prog.rework && canEdit" class="btn btn-lg btn-danger" @click="start('rework')">
              只看需返工的 {{ prog.rework }} 张
            </button>
            <div class="spacer" />
            <template v-if="task.status === 'active'">
              <button v-if="prog.status === 'submitted'" class="btn btn-lg" :disabled="busy" @click="withdraw">撤回提交</button>
              <button
                v-else-if="canEdit"
                class="btn btn-success btn-lg"
                :disabled="!allDone || busy"
                :title="allDone ? '' : '全部图片完成后才能提交'"
                @click="submit"
              >
                提交审核
              </button>
            </template>
          </div>
          <div v-if="canEdit && !allDone" class="faint mt-8">还有 {{ prog.assigned - prog.done }} 张未完成，全部完成后才能提交审核。</div>
        </template>
        <div v-else class="empty">管理员还没有给你分配图片</div>
      </div>

      <div class="card">
        <div class="card-title">标注要求</div>
        <MarkdownView v-if="task.description.trim()" :source="task.description" />
        <div v-else class="faint">管理员没有填写标注要求</div>
      </div>
    </div>

    <div class="side-col">
      <div class="card">
        <div class="card-title">类别（{{ task.classes.length }}）</div>
        <div class="cls-grid">
          <div v-for="(c, i) in task.classes" :key="c.name" class="cls-item">
            <span class="sw" :style="{ background: classColor(task.classes, i) }" />
            <span class="mono">{{ c.name }}</span>
            <span class="faint">#{{ i }}</span>
          </div>
        </div>
        <div class="faint mt-16">
          点序：{{ task.settings.auto_sort ? '已开启自动规范（左上→左下→右下→右上）' : '请严格按 左上→左下→右下→右上 点击' }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mywork {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 16px;
  align-items: start;
}
.main-col .card + .card {
  margin-top: 16px;
}
.cls-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 10px;
}
.cls-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.sw {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}
@media (max-width: 900px) {
  .mywork {
    grid-template-columns: 1fr;
  }
}
</style>

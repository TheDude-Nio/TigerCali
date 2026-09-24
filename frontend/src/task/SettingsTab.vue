<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errMsg } from '../api'
import LabelConfigEditor from '../components/LabelConfigEditor.vue'
import MarkdownEditor from '../components/MarkdownEditor.vue'
import { confirmDialog, promptDialog, toast } from '../store'
import type { LabelConfig, Task } from '../types'

const props = defineProps<{ task: Task }>()
const emit = defineEmits<{ (e: 'saved', t: Task): void; (e: 'refresh'): void }>()
const router = useRouter()

const form = reactive({
  name: props.task.name,
  description: props.task.description,
  label_config: JSON.parse(JSON.stringify(props.task.label_config)) as LabelConfig,
  auto_sort: props.task.settings.auto_sort,
})
const busy = ref(false)

async function save() {
  busy.value = true
  try {
    const t = await api.patch<Task>(`/api/tasks/${props.task.id}`, {
      name: form.name,
      description: form.description,
      label_config: form.label_config,
      settings: { auto_sort: form.auto_sort },
    })
    emit('saved', t)
    toast('已保存', 'success')
  } catch (e) {
    toast(errMsg(e), 'error', 5000)
  } finally {
    busy.value = false
  }
}

async function removeTask() {
  const name = await promptDialog('删除任务', {
    message: `所有图片和标注都会被永久删除，无法恢复！\n请输入任务名称「${props.task.name}」确认：`,
    danger: true,
    okText: '永久删除',
  })
  if (name === null) return
  if (name.trim() !== props.task.name) {
    toast('任务名称不一致，已取消', 'warn')
    return
  }
  try {
    await api.del(`/api/tasks/${props.task.id}`)
    toast('任务已删除', 'success')
    router.replace('/')
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function toggleStatus() {
  const finishing = props.task.status === 'active'
  if (!(await confirmDialog(finishing ? '结束任务' : '重新开启任务', finishing ? '结束后标注员不能再修改。' : '重新开启后可以继续标注。')))
    return
  try {
    await api.patch(`/api/tasks/${props.task.id}`, { status: finishing ? 'finished' : 'active' })
    emit('refresh')
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}
</script>

<template>
  <div>
    <div class="card">
      <div class="card-title">基本信息</div>
      <div class="field">
        <label>任务名称</label>
        <input v-model="form.name" class="input" maxlength="100" />
      </div>
      <div class="field">
        <label>标注要求</label>
        <MarkdownEditor v-model="form.description" :task-id="task.id" :rows="14" />
      </div>
    </div>

    <div class="card">
      <div class="card-title">类别</div>
      <LabelConfigEditor v-model="form.label_config" disabled-note="修改类别后已有标注会按类别名自动重新编号；已被使用的类别不能删除" />
      <label class="check mt-16">
        <input v-model="form.auto_sort" type="checkbox" />
        自动规范点序（画完后整理成 左上 → 左下 → 右下 → 右上）
      </label>
    </div>

    <div class="row mt-16">
      <div class="spacer" />
      <button class="btn btn-primary btn-lg" :disabled="busy" @click="save">保存设置</button>
    </div>

    <div class="card mt-24 danger-zone">
      <div class="card-title">危险操作</div>
      <div class="row">
        <button class="btn" @click="toggleStatus">{{ task.status === 'active' ? '结束任务' : '重新开启任务' }}</button>
        <button v-if="task.my_role === 'owner'" class="btn btn-danger" @click="removeTask">删除任务</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.danger-zone {
  border-color: #fecaca;
}
</style>

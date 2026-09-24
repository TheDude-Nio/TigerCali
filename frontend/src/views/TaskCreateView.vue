<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errMsg } from '../api'
import LabelConfigEditor from '../components/LabelConfigEditor.vue'
import MarkdownEditor from '../components/MarkdownEditor.vue'
import { toast } from '../store'
import type { LabelConfig, Task } from '../types'

const DEFAULT_REQUIREMENTS = `## 标注要求

1. 每个装甲板标 **4 个点**：左灯条上端 → 左灯条下端 → 右灯条下端 → 右灯条上端（即 左上 → 左下 → 右下 → 右上）。
   开启「自动规范点序」后点击顺序可以随意，系统会自动整理。
2. 点要落在 **灯条的端点中心**，放大后再点，尽量精确到像素。
3. 选择正确的 **颜色** 和 **编号**；熄灭的装甲板选「灰」。
4. 被遮挡超过一半、或者模糊到无法辨认编号的装甲板 **不标**。
5. 图中没有装甲板时，直接按 \`D\` 确认为空图并进入下一张。
`

const router = useRouter()
const form = reactive({
  name: '',
  description: DEFAULT_REQUIREMENTS,
  label_config: { mode: 'armor', colors: ['B', 'R'], tags: ['G', '1', '2', '3', '4', '5', 'O', 'Bs', 'Bb'] } as LabelConfig,
  auto_sort: true,
})
const busy = ref(false)

async function submit() {
  if (!form.name.trim()) {
    toast('请填写任务名称', 'warn')
    return
  }
  busy.value = true
  try {
    const t = await api.post<Task>('/api/tasks', {
      name: form.name,
      description: form.description,
      label_config: form.label_config,
      settings: { auto_sort: form.auto_sort },
    })
    toast('任务已创建，接下来上传图片', 'success')
    router.replace({ path: `/tasks/${t.id}`, query: { tab: 'images' } })
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="page page-narrow">
    <div class="page-head">
      <h1>发布标注任务</h1>
    </div>
    <form @submit.prevent="submit">
      <div class="card">
        <div class="card-title">基本信息</div>
        <div class="field">
          <label>任务名称</label>
          <input v-model="form.name" class="input" maxlength="100" placeholder="如：2026 赛季哨兵视角装甲板" autofocus />
        </div>
        <div class="field">
          <label>标注类型</label>
          <div class="row">
            <span class="chip on">四点模型 · RoboMaster 装甲板</span>
            <span class="faint">更多类型后续支持</span>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">标注要求 <span class="faint">所有标注员都能看到</span></div>
        <MarkdownEditor v-model="form.description" :rows="12" />
        <div class="faint mt-8">创建任务后，可在「设置」里直接粘贴截图作为示例图。</div>
      </div>

      <div class="card">
        <div class="card-title">类别</div>
        <LabelConfigEditor v-model="form.label_config" />
        <label class="check mt-16">
          <input v-model="form.auto_sort" type="checkbox" />
          自动规范点序：画完后自动把 4 个点整理成 左上 → 左下 → 右下 → 右上
        </label>
      </div>

      <div class="row mt-24">
        <div class="spacer" />
        <router-link to="/" class="btn btn-lg">取消</router-link>
        <button class="btn btn-primary btn-lg" :disabled="busy">创建任务</button>
      </div>
    </form>
  </div>
</template>

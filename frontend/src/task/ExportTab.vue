<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { api, qs } from '../api'
import { metaStore } from '../store'
import type { Task, TaskStats } from '../types'
import { debounce } from '../utils'

const props = defineProps<{ task: Task; stats: TaskStats | null }>()

const opt = reactive({
  fmt: 'yolo_pose',
  scope: props.task.status === 'finished' ? 'approved' : 'done',
  val_ratio: 10,
  include_images: true,
  include_empty: true,
  point_order: 'tl_bl_br_tr',
  seed: 0,
})

const formats = computed(() =>
  (metaStore.meta?.export_formats ?? []).filter((f) => f.key !== 'sjtu' || props.task.label_config.mode === 'armor'),
)
const current = computed(() => formats.value.find((f) => f.key === opt.fmt))
const approvedCount = computed(() =>
  (props.stats?.members ?? []).filter((m) => m.status === 'approved').reduce((s, m) => s + m.assigned, 0),
)

const params = computed(() => ({
  fmt: opt.fmt,
  scope: opt.scope,
  val_ratio: opt.fmt === 'json' ? 0 : opt.val_ratio / 100,
  include_images: opt.include_images,
  include_empty: opt.include_empty,
  point_order: opt.point_order,
  seed: opt.seed,
}))
const url = computed(() => `/api/tasks/${props.task.id}/export` + qs(params.value))

interface Preview {
  images: number
  annotations: number
  empty: number
  train: number
  val: number
}
const preview = ref<Preview | null>(null)
const loadPreview = debounce(async () => {
  preview.value = await api
    .get<Preview>(`/api/tasks/${props.task.id}/export`, { ...params.value, preview: true })
    .catch(() => null)
}, 200)
watch(params, () => loadPreview(), { immediate: true })

const example = computed(() => {
  switch (opt.fmt) {
    case 'yolo_pose':
      return '3 0.512300 0.433100 0.061200 0.042500 0.481700 0.412300 0.482100 0.455600 0.542900 0.453800 0.542400 0.410600'
    case 'rm4':
      return '3 0.481700 0.412300 0.482100 0.455600 0.542900 0.453800 0.542400 0.410600'
    case 'sjtu':
      return '0 3 0.481700 0.412300 0.482100 0.455600 0.542900 0.453800 0.542400 0.410600'
    case 'yolo_det':
      return '3 0.512300 0.433100 0.061200 0.042500'
    default:
      return '{ "file": "images/xxx.jpg", "width": 1280, "height": 1024, "annotations": [{ "cls": 3, "name": "B_3", "pts": [[x, y], …] }] }'
  }
})
</script>

<template>
  <div class="grid-2 export">
    <div class="card">
      <div class="card-title">导出数据集</div>
      <div class="field">
        <label>格式</label>
        <div class="col" style="gap: 6px">
          <label v-for="f in formats" :key="f.key" class="check fmt" :class="{ on: opt.fmt === f.key }">
            <input v-model="opt.fmt" type="radio" :value="f.key" />
            <span>
              <b>{{ f.name }}</b>
              <div class="faint mono">{{ f.line }}</div>
            </span>
          </label>
        </div>
      </div>
      <div class="field">
        <label>范围</label>
        <select v-model="opt.scope" class="select">
          <option value="approved">只导出审核通过的（{{ approvedCount }} 张）</option>
          <option value="done">导出所有已完成的（{{ stats?.done ?? 0 }} 张）</option>
          <option value="all">全部图片（包括未完成，{{ stats?.total ?? 0 }} 张）</option>
        </select>
      </div>
      <div v-if="opt.fmt !== 'yolo_det' && opt.fmt !== 'json'" class="field">
        <label>关键点顺序</label>
        <select v-model="opt.point_order" class="select">
          <option v-for="o in metaStore.meta?.point_orders ?? []" :key="o.key" :value="o.key">{{ o.name }}</option>
        </select>
      </div>
      <div v-if="opt.fmt !== 'json'" class="field">
        <label>验证集比例：{{ opt.val_ratio }}%</label>
        <input v-model.number="opt.val_ratio" type="range" min="0" max="50" step="1" style="accent-color: var(--brand)" />
        <span class="hint">随机划分（随机种子 {{ opt.seed }}，种子相同则划分结果相同）；0% 时 val 使用训练集</span>
      </div>
      <div class="col" style="gap: 8px">
        <label class="check"><input v-model="opt.include_images" type="checkbox" />包含图片（取消则只导出标签，速度很快）</label>
        <label class="check"><input v-model="opt.include_empty" type="checkbox" />包含没有装甲板的图片（负样本）</label>
      </div>
      <div v-if="preview" class="notice mt-16" :class="preview.images ? 'notice-info' : 'notice-warn'">
        <template v-if="preview.images">
          将导出 <b>{{ preview.images }}</b> 张图片、<b>{{ preview.annotations }}</b> 个装甲板
          <template v-if="opt.fmt !== 'json'">（训练 {{ preview.train }} / 验证 {{ preview.val }}）</template>
          <template v-if="preview.empty">，其中 {{ preview.empty }} 张是空图</template>
        </template>
        <template v-else>没有符合条件的图片，换个导出范围试试</template>
      </div>
      <div class="row mt-16">
        <a v-if="preview?.images" class="btn btn-primary btn-lg" :href="url" download>⬇ 下载 zip</a>
        <button v-else class="btn btn-primary btn-lg" disabled>⬇ 下载 zip</button>
        <span class="faint">边打包边下载，数据集很大也不用等</span>
      </div>
    </div>

    <div class="card">
      <div class="card-title">格式说明</div>
      <p class="muted">每张图片对应一个同名 .txt，每行一个装甲板：</p>
      <pre class="code">{{ current?.line }}</pre>
      <p class="muted">示例：</p>
      <pre class="code">{{ example }}</pre>
      <ul class="muted notes">
        <li>坐标全部归一化到 0~1（x ÷ 图宽，y ÷ 图高）。</li>
        <li>class id 就是类别列表里的序号，<code>data.yaml</code> / <code>classes.txt</code> 里有完整对照。</li>
        <li>YOLO Pose 的 <code>data.yaml</code> 已写好 <code>kpt_shape: [4, 2]</code> 和 <code>flip_idx</code>，可直接用 Ultralytics 训练。</li>
        <li>装甲板数字左右翻转后含义会变，训练时建议 <code>fliplr=0</code>。</li>
      </ul>
      <p class="muted">目录结构：</p>
      <pre class="code">dataset.zip
├── data.yaml
├── classes.txt
├── README.txt
├── images/
│   ├── train/*.jpg
│   └── val/*.jpg
└── labels/
    ├── train/*.txt
    └── val/*.txt</pre>
    </div>
  </div>
</template>

<style scoped>
.export {
  align-items: start;
}
.fmt {
  align-items: flex-start;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.fmt input {
  margin-top: 3px;
}
.fmt.on {
  border-color: var(--brand);
  background: var(--brand-50);
}
.code {
  margin: 0 0 12px;
  padding: 10px 12px;
  border-radius: 6px;
  background: #0f172a;
  color: #e2e8f0;
  font-family: var(--mono);
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
.notes {
  padding-left: 18px;
}
.notes li {
  margin: 4px 0;
}
@media (max-width: 1000px) {
  .export {
    grid-template-columns: 1fr;
  }
}
</style>

<script setup lang="ts">
import { computed } from 'vue'
import { metaStore } from '../store'
import type { LabelConfig } from '../types'

const props = defineProps<{ modelValue: LabelConfig; disabledNote?: string }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: LabelConfig): void }>()

const colors = computed(() => metaStore.meta?.armor_colors ?? [])
const tags = computed(() => metaStore.meta?.armor_tags ?? [])

const armor = computed(() => (props.modelValue.mode === 'armor' ? props.modelValue : null))
const customText = computed(() => (props.modelValue.mode === 'custom' ? props.modelValue.names.join('\n') : ''))

function setMode(mode: 'armor' | 'custom') {
  if (mode === props.modelValue.mode) return
  if (mode === 'armor') emit('update:modelValue', { mode: 'armor', colors: ['B', 'R'], tags: tags.value.map((t) => t.key) })
  else emit('update:modelValue', { mode: 'custom', names: ['armor'] })
}

function toggle(kind: 'colors' | 'tags', key: string) {
  if (!armor.value) return
  const cur = new Set(armor.value[kind])
  if (cur.has(key)) cur.delete(key)
  else cur.add(key)
  const order = (kind === 'colors' ? colors.value : tags.value).map((x) => x.key)
  emit('update:modelValue', { ...armor.value, [kind]: order.filter((k) => cur.has(k)) })
}

function preset(colorKeys: string[], tagKeys: string[] | 'all') {
  emit('update:modelValue', {
    mode: 'armor',
    colors: colorKeys,
    tags: tagKeys === 'all' ? tags.value.map((t) => t.key) : tagKeys,
  })
}

function setCustom(text: string) {
  emit('update:modelValue', { mode: 'custom', names: text.split('\n').map((s) => s.trim()) })
}

const preview = computed(() => {
  if (armor.value) {
    const out: string[] = []
    for (const c of colors.value.filter((c) => armor.value!.colors.includes(c.key)))
      for (const t of tags.value.filter((t) => armor.value!.tags.includes(t.key))) out.push(`${c.key}_${t.key}`)
    return out
  }
  return props.modelValue.mode === 'custom' ? props.modelValue.names.filter((n) => n.trim()) : []
})
</script>

<template>
  <div class="lce">
    <div class="row mb-16">
      <div class="seg">
        <button type="button" :class="{ on: modelValue.mode === 'armor' }" @click="setMode('armor')">装甲板（颜色 × 编号）</button>
        <button type="button" :class="{ on: modelValue.mode === 'custom' }" @click="setMode('custom')">自定义类别</button>
      </div>
      <span v-if="disabledNote" class="faint">{{ disabledNote }}</span>
    </div>

    <template v-if="armor">
      <div class="field">
        <label>装甲板颜色</label>
        <div class="chip-group">
          <span
            v-for="c in colors"
            :key="c.key"
            class="chip"
            :class="{ on: armor.colors.includes(c.key) }"
            @click="toggle('colors', c.key)"
          >
            <span class="dot" :style="{ background: c.hex }" />{{ c.name }} <span class="faint">{{ c.key }}</span>
          </span>
        </div>
      </div>
      <div class="field">
        <label>装甲板编号</label>
        <div class="chip-group">
          <span
            v-for="t in tags"
            :key="t.key"
            class="chip"
            :class="{ on: armor.tags.includes(t.key) }"
            @click="toggle('tags', t.key)"
          >
            <b>{{ t.key }}</b> {{ t.name }}
          </span>
        </div>
      </div>
      <div class="row mb-16">
        <span class="faint">快速选择：</span>
        <button type="button" class="btn btn-sm" @click="preset(['B', 'R'], 'all')">蓝红 · 全部编号</button>
        <button type="button" class="btn btn-sm" @click="preset(['B', 'R', 'N'], 'all')">蓝红灰 · 全部编号</button>
        <button type="button" class="btn btn-sm" @click="preset(['B', 'R', 'N', 'P'], 'all')">全部 36 类</button>
        <button type="button" class="btn btn-sm" @click="preset(['B', 'R'], ['G', '1', '2', '3', '4', 'O', 'Bs', 'Bb'])">RMUC 2024+（无 5 号）</button>
      </div>
    </template>

    <div v-else class="field">
      <label>类别名称（每行一个，顺序即 class id）</label>
      <textarea class="textarea mono" rows="6" :value="customText" @input="setCustom(($event.target as HTMLTextAreaElement).value)" />
    </div>

    <div class="preview">
      <div class="faint mb-8">共 {{ preview.length }} 个类别（class id: 名称）</div>
      <div class="cls-list">
        <span v-for="(n, i) in preview" :key="n + i" class="cls"><b>{{ i }}</b>{{ n }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.preview {
  padding: 12px;
  border: 1px dashed var(--border-strong);
  border-radius: 8px;
  background: #fafbfc;
}
.cls-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.cls {
  display: inline-flex;
  gap: 6px;
  padding: 2px 8px;
  border-radius: 4px;
  background: #fff;
  border: 1px solid var(--border);
  font-family: var(--mono);
  font-size: 12px;
}
.cls b {
  color: var(--brand-600);
}
</style>

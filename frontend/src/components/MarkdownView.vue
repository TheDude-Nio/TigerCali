<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed } from 'vue'

const props = defineProps<{ source: string }>()

marked.setOptions({ gfm: true, breaks: true })

const html = computed(() => DOMPurify.sanitize(marked.parse(props.source || '', { async: false }) as string))
</script>

<template>
  <div class="md" v-html="html" />
</template>

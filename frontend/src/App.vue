<script setup lang="ts">
import { useRoute } from 'vue-router'
import AppHeader from './components/AppHeader.vue'
import DialogHost from './components/DialogHost.vue'
import { toasts } from './store'

const route = useRoute()
</script>

<template>
  <AppHeader v-if="!route.meta.bare" />
  <router-view />
  <div class="toasts">
    <div v-for="t in toasts" :key="t.id" class="toast" :class="t.kind">{{ t.text }}</div>
  </div>
  <DialogHost />
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errMsg } from '../api'
import AuthShell from '../components/AuthShell.vue'
import { setUser } from '../store'
import type { User } from '../types'

const router = useRouter()
const route = useRoute()
const form = reactive({ username: '', password: '' })
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  if (!form.username.trim() || !form.password) {
    error.value = '请输入用户名和密码'
    return
  }
  busy.value = true
  try {
    setUser(await api.post<User>('/api/auth/login', form))
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    router.replace(redirect.startsWith('/') ? redirect : '/')
  } catch (e) {
    error.value = errMsg(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <AuthShell title="登录" subtitle="欢迎回来，继续一起标！">
    <form @submit.prevent="submit">
      <div class="field">
        <label>用户名</label>
        <input v-model="form.username" class="input" autocomplete="username" autofocus />
      </div>
      <div class="field">
        <label>密码</label>
        <input v-model="form.password" class="input" type="password" autocomplete="current-password" />
      </div>
      <p v-if="error" class="error-text">{{ error }}</p>
      <button class="btn btn-primary btn-lg btn-block" :disabled="busy">{{ busy ? '登录中…' : '登录' }}</button>
    </form>
    <p class="switch">还没有账号？<router-link :to="{ path: '/register', query: route.query }">注册一个</router-link></p>
  </AuthShell>
</template>

<style scoped>
.switch {
  margin: 18px 0 0;
  text-align: center;
  color: var(--text-2);
}
</style>

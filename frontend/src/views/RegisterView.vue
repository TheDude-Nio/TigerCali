<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errMsg } from '../api'
import AuthShell from '../components/AuthShell.vue'
import { metaStore, setUser } from '../store'
import type { User } from '../types'

const router = useRouter()
const route = useRoute()
const form = reactive({ username: '', password: '', password2: '', school: '', invite_code: '' })
const error = ref('')
const busy = ref(false)
const schools = ref<{ school: string; users: number }[]>([])
const inviteRequired = computed(() => metaStore.meta?.invite_required ?? false)

onMounted(async () => {
  schools.value = await api.get<{ school: string; users: number }[]>('/api/schools').catch(() => [])
})

async function submit() {
  error.value = ''
  if (form.password !== form.password2) {
    error.value = '两次输入的密码不一致'
    return
  }
  busy.value = true
  try {
    setUser(
      await api.post<User>('/api/auth/register', {
        username: form.username,
        password: form.password,
        school: form.school,
        invite_code: form.invite_code,
      }),
    )
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
  <AuthShell title="注册账号" subtitle="注册后即可发布任务，或被邀请参与标注">
    <form @submit.prevent="submit">
      <div class="field">
        <label>用户名</label>
        <input v-model="form.username" class="input" autocomplete="username" maxlength="32" placeholder="2~32 位，中英文/数字/下划线" autofocus />
      </div>
      <div class="field">
        <label>学校</label>
        <input v-model="form.school" class="input" list="school-list" maxlength="64" placeholder="如：广东工业大学" />
        <datalist id="school-list">
          <option v-for="s in schools" :key="s.school" :value="s.school">{{ s.users }} 人</option>
        </datalist>
        <span class="hint">请尽量从下拉列表选择已有学校，方便管理员按学校查找队员</span>
      </div>
      <div class="field">
        <label>密码</label>
        <input v-model="form.password" class="input" type="password" autocomplete="new-password" placeholder="至少 6 位" />
      </div>
      <div class="field">
        <label>确认密码</label>
        <input v-model="form.password2" class="input" type="password" autocomplete="new-password" />
      </div>
      <div v-if="inviteRequired" class="field">
        <label>邀请码</label>
        <input v-model="form.invite_code" class="input" placeholder="向管理员索取" />
      </div>
      <p v-if="error" class="error-text">{{ error }}</p>
      <button class="btn btn-primary btn-lg btn-block" :disabled="busy">{{ busy ? '注册中…' : '注册并登录' }}</button>
    </form>
    <p class="switch">已有账号？<router-link :to="{ path: '/login', query: route.query }">去登录</router-link></p>
  </AuthShell>
</template>

<style scoped>
.switch {
  margin: 18px 0 0;
  text-align: center;
  color: var(--text-2);
}
</style>

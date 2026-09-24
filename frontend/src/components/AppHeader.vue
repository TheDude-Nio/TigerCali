<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errMsg } from '../api'
import { auth, setUser, toast } from '../store'
import type { User } from '../types'

const router = useRouter()
const menuOpen = ref(false)
const accountOpen = ref(false)
const form = reactive({ school: '', old_password: '', new_password: '', new_password2: '' })
const busy = ref(false)
const menuEl = ref<HTMLElement | null>(null)

function onDocClick(e: MouseEvent) {
  if (menuEl.value && !menuEl.value.contains(e.target as Node)) menuOpen.value = false
}
onMounted(() => document.addEventListener('mousedown', onDocClick))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocClick))

async function logout() {
  await api.post('/api/auth/logout').catch(() => null)
  setUser(null)
  router.replace('/login')
}

function openAccount() {
  menuOpen.value = false
  Object.assign(form, { school: auth.user?.school ?? '', old_password: '', new_password: '', new_password2: '' })
  accountOpen.value = true
}

async function saveAccount() {
  busy.value = true
  try {
    if (form.school.trim() && form.school.trim() !== auth.user?.school) {
      setUser(await api.patch<User>('/api/auth/me', { school: form.school.trim() }))
      toast('学校已更新', 'success')
    }
    if (form.new_password) {
      if (form.new_password !== form.new_password2) throw new Error('两次输入的新密码不一致')
      await api.post('/api/auth/password', { old_password: form.old_password, new_password: form.new_password })
      toast('密码已修改', 'success')
    }
    accountOpen.value = false
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <header class="hdr">
    <div class="hdr-in">
      <router-link to="/" class="logo">
        <img src="/favicon.svg" alt="" />
        <span>华南虎一起标</span>
      </router-link>
      <nav class="nav">
        <router-link to="/" class="nav-a">我的任务</router-link>
        <router-link to="/tasks/new" class="nav-a">发布任务</router-link>
      </nav>
      <div class="spacer" />
      <div v-if="auth.user" ref="menuEl" class="user">
        <button class="user-btn" @click="menuOpen = !menuOpen">
          <span class="avatar">{{ auth.user.username.slice(0, 1).toUpperCase() }}</span>
          <span class="user-name">{{ auth.user.username }}</span>
          <span class="user-school">{{ auth.user.school }}</span>
        </button>
        <div v-if="menuOpen" class="menu">
          <button @click="openAccount">账号设置</button>
          <button class="danger" @click="logout">退出登录</button>
        </div>
      </div>
    </div>
  </header>

  <div v-if="accountOpen" class="modal-mask" @mousedown.self="accountOpen = false">
    <div class="modal">
      <div class="modal-head">账号设置</div>
      <div class="modal-body" style="white-space: normal">
        <div class="field">
          <label>学校</label>
          <input v-model="form.school" class="input" maxlength="64" />
        </div>
        <div class="field">
          <label>修改密码（不修改请留空）</label>
          <input v-model="form.old_password" class="input" type="password" placeholder="原密码" autocomplete="current-password" />
          <input v-model="form.new_password" class="input" type="password" placeholder="新密码（至少 6 位）" autocomplete="new-password" />
          <input v-model="form.new_password2" class="input" type="password" placeholder="再次输入新密码" autocomplete="new-password" />
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn" @click="accountOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="busy" @click="saveAccount">保存</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hdr {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: saturate(180%) blur(8px);
  border-bottom: 1px solid var(--border);
}
.hdr-in {
  display: flex;
  align-items: center;
  gap: 20px;
  max-width: 1240px;
  height: 56px;
  margin: 0 auto;
  padding: 0 24px;
}
.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.5px;
}
.logo:hover {
  text-decoration: none;
}
.logo img {
  width: 28px;
  height: 28px;
}
.nav {
  display: flex;
  gap: 4px;
}
.nav-a {
  padding: 6px 12px;
  border-radius: 6px;
  color: var(--text-2);
  font-weight: 550;
}
.nav-a:hover {
  background: #f3f4f6;
  text-decoration: none;
}
.nav-a.router-link-exact-active {
  color: var(--brand-600);
  background: var(--brand-50);
}
.user {
  position: relative;
}
.user-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  border: none;
  background: none;
  padding: 4px 8px;
  border-radius: 8px;
  cursor: pointer;
  font: inherit;
}
.user-btn:hover {
  background: #f3f4f6;
}
.avatar {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--brand);
  color: #fff;
  font-weight: 700;
  font-size: 13px;
}
.user-name {
  font-weight: 600;
}
.user-school {
  color: var(--text-3);
  font-size: 12px;
}
.menu {
  position: absolute;
  right: 0;
  top: calc(100% + 6px);
  min-width: 160px;
  padding: 6px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  box-shadow: var(--shadow-lg);
}
.menu button {
  display: block;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 6px;
  background: none;
  text-align: left;
  font: inherit;
  cursor: pointer;
}
.menu button:hover {
  background: #f3f4f6;
}
.menu .danger {
  color: var(--red);
}
@media (max-width: 700px) {
  .user-school,
  .nav {
    display: none;
  }
}
</style>

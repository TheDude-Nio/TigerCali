<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <div class="auth">
    <div class="auth-side">
      <img class="logo" src="/favicon.svg" alt="" />
      <h2 class="headline">华南虎多人协作标注平台</h2>
    </div>
    <div class="auth-main">
      <div class="auth-card">
        <h1>{{ title }}</h1>
        <p v-if="subtitle" class="sub">{{ subtitle }}</p>
        <slot />
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth {
  display: flex;
  min-height: 100vh;
  padding: 16px;
  gap: 16px;
}
.auth-side {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 56px 72px;
  border-radius: 20px;
  background: #f0eee6;
}
.logo {
  width: 48px;
  height: 48px;
}
.headline {
  margin-top: 24px;
  font-size: 40px;
  line-height: 1.25;
}
.auth-main {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 500px;
  max-width: 100%;
  padding: 32px;
}
.auth-card {
  width: 100%;
  max-width: 360px;
}
.auth-card h1 {
  font-size: 30px;
}
.sub {
  margin: 8px 0 28px;
  color: var(--text-2);
}
@media (max-width: 900px) {
  .auth-side {
    display: none;
  }
  .auth-main {
    width: 100%;
  }
}
</style>

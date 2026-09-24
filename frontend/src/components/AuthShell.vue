<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <div class="auth">
    <div class="auth-side">
      <div class="brand">
        <img src="/favicon.svg" alt="" />
        <div>
          <div class="brand-name">华南虎一起标</div>
          <div class="brand-sub">RoboMaster 装甲板协同标注平台</div>
        </div>
      </div>
      <ul class="feats">
        <li><b>四点精标</b>放大镜 + 十字准星 + 微调，亚像素级角点</li>
        <li><b>多人协作</b>跨学校邀请队员，按张数 / 比例 / 一键均分</li>
        <li><b>审核闭环</b>逐张标记问题，打回返工，审核通过即结束</li>
        <li><b>直出 YOLO</b>YOLO Pose / RM 四点 / 检测框，一键导出训练</li>
      </ul>
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
}
.auth-side {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 40px;
  padding: 48px 64px;
  background:
    radial-gradient(circle at 20% 20%, rgba(255, 255, 255, 0.12), transparent 40%),
    linear-gradient(135deg, #7c2d12 0%, #c2410c 45%, #f97316 100%);
  color: #fff;
}
.brand {
  display: flex;
  align-items: center;
  gap: 16px;
}
.brand img {
  width: 64px;
  height: 64px;
  border-radius: 14px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
}
.brand-name {
  font-size: 34px;
  font-weight: 800;
  letter-spacing: 2px;
}
.brand-sub {
  opacity: 0.85;
  margin-top: 2px;
}
.feats {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 16px;
  max-width: 460px;
}
.feats li {
  padding: 14px 16px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.18);
  line-height: 1.6;
}
.feats b {
  display: block;
  font-size: 15px;
}
.auth-main {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 520px;
  max-width: 100%;
  padding: 32px;
  background: #fff;
}
.auth-card {
  width: 100%;
  max-width: 380px;
}
.auth-card h1 {
  font-size: 24px;
}
.sub {
  margin: 6px 0 24px;
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

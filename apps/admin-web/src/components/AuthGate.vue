<template>
  <div v-if="!auth.isAuthed || authFailed" class="auth-gate">
    <div class="auth-card">
      <h2>管理员登录</h2>
      <p class="auth-hint">请输入管理员账号</p>
      <a-input
        v-model:value="username"
        placeholder="用户名"
        :disabled="auth.checking"
        class="auth-field"
        @press-enter="handleLogin"
      />
      <a-input-password
        v-model:value="password"
        placeholder="密码"
        :disabled="auth.checking"
        class="auth-field"
        @press-enter="handleLogin"
      />
      <div v-if="errorText" class="auth-error">{{ errorText }}</div>
      <a-button type="primary" block :loading="auth.checking" @click="handleLogin">
        进入
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useAdminAuthStore } from '../stores/auth'
import { bindSessionSync } from '../../../shared/session'

const auth = useAdminAuthStore()
const username = ref('')
const password = ref('')
const errorText = ref('')
const authFailed = ref(false)
let unbindSync: (() => void) | null = null

onMounted(async () => {
  // 跨应用会话同步：userweb 登出后，adminweb 在获得焦点/同源 storage 变化时同步退出
  unbindSync = bindSessionSync(() => auth.syncExternal())
  if (!auth.isAuthed) return
  try {
    await auth.refreshMe()
    authFailed.value = false
  } catch {
    authFailed.value = true
  }
})

onUnmounted(() => {
  unbindSync?.()
})

async function handleLogin() {
  errorText.value = ''
  if (!username.value.trim() || !password.value) {
    errorText.value = '请输入用户名和密码'
    return
  }
  try {
    await auth.login(username.value.trim(), password.value)
    authFailed.value = false
  } catch (e: any) {
    errorText.value = e?.message || '登录失败，请检查账号密码'
  }
}
</script>

<style scoped>
.auth-gate {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
}
.auth-card {
  width: 360px;
  padding: 32px 28px;
  border-radius: 12px;
  background: var(--panel-bg);
  border: 1px solid var(--border-color);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
  color: var(--text-primary);
}
.auth-card h2 {
  margin: 0 0 8px;
  font-size: 20px;
}
.auth-hint {
  margin: 0 0 20px;
  color: var(--text-secondary);
  font-size: 13px;
}
.auth-field {
  margin-bottom: 12px;
}
.auth-error {
  margin: 8px 0;
  color: #ff4d4f;
  font-size: 13px;
}
</style>

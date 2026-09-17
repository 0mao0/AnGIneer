<template>
  <div v-if="!auth.isAuthed || authFailed" class="auth-gate">
    <div class="auth-card">
      <h2>登录 AnGIneer</h2>
      <p class="auth-hint">请输入管理员为您创建的账号</p>
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
      <a-button class="auth-guest" block :disabled="auth.checking" @click="handleGuest">
        以游客身份开始
      </a-button>
      <p class="auth-guest-hint">游客可直接提问（默认知识库），累计 30 轮后需登录继续</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { bindSessionSync } from '../../../shared/session'

const auth = useAuthStore()
const username = ref('')
const password = ref('')
const errorText = ref('')
const authFailed = ref(false)
let unbindSync: (() => void) | null = null

onMounted(async () => {
  // 跨应用会话同步：adminweb 登出后，userweb 在获得焦点/同源 storage 变化时同步退出
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

/** 游客进站（D2）：签发游客 cookie 后进入，30 轮闸由服务端按 g: 桶计数 */
async function handleGuest() {
  errorText.value = ''
  try {
    await auth.enterGuestMode()
  } catch {
    errorText.value = '游客通道初始化失败，请重试'
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
  text-align: center;
  color: var(--text-primary);
}
.auth-hint {
  margin: 0 0 16px;
  color: var(--text-secondary);
  text-align: center;
  font-size: 13px;
}
.auth-field {
  margin-bottom: 12px;
}
.auth-error {
  margin-bottom: 12px;
  color: var(--danger, #cf1322);
  font-size: 13px;
}
.auth-guest {
  margin-top: 10px;
}
.auth-guest-hint {
  margin: 10px 0 0;
  color: var(--text-secondary);
  text-align: center;
  font-size: 12px;
}
</style>

<template>
  <div v-if="!auth.isAuthed || authFailed" class="auth-gate">
    <div class="auth-card">
      <h2>登录工作台</h2>
      <p class="auth-hint">请输入管理员发放的 API Key（已绑定您的知识库）</p>
      <a-input-password
        v-model:value="keyInput"
        placeholder="ag_xxxxxxxxxxxxxxxx"
        :disabled="auth.checking"
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
import { onMounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const keyInput = ref('')
const errorText = ref('')
const authFailed = ref(false)

onMounted(async () => {
  if (!auth.isAuthed) return
  try {
    await auth.refreshMe()
    authFailed.value = false
  } catch {
    authFailed.value = true
  }
})

async function handleLogin() {
  errorText.value = ''
  try {
    await auth.login(keyInput.value)
    authFailed.value = false
  } catch (e: any) {
    errorText.value = e?.message || '登录失败，请检查 API Key'
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
  background: rgba(15, 23, 42, 0.92);
}
.auth-card {
  width: 360px;
  padding: 32px 28px;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
}
.auth-card h2 {
  margin: 0 0 8px;
  text-align: center;
}
.auth-hint {
  margin: 0 0 16px;
  color: #666;
  text-align: center;
  font-size: 13px;
}
.auth-card .ant-input-affix-wrapper {
  margin-bottom: 12px;
}
.auth-error {
  margin-bottom: 12px;
  color: #cf1322;
  font-size: 13px;
}
</style>

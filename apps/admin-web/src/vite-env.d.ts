/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

interface ImportMetaEnv {
  readonly VITE_APP_VERSION: string
  /** 当前版本发版摘要（构建期从根 README「当前版本」行提取，缺失时为空串） */
  readonly VITE_APP_RELEASE_NOTES: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

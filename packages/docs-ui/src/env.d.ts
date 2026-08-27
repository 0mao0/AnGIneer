// 宿主 Vite 注入的运行时环境类型。独立包不直接依赖 vite 类型包，仅声明用到的字段。
interface ImportMetaEnv {
  readonly BASE_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

// Vite 静态资源 ?url 后缀导入（返回资源 URL 字符串）
declare module '*?url' {
  const src: string
  export default src
}

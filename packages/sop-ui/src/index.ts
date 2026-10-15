export * from './components'
export * from './composables'
// `export type *` 会把 types/index.ts 里的值导出（normalizeSopData 等）静默吞掉——
// 公开页只读渲染需要 normalizeSopData（raw JSON → SopData），改回 `export *` 同时带类型与值。
export * from './types'

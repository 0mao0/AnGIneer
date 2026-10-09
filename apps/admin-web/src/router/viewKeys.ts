/**
 * 模块视图 tab 的 key ↔ URL 段映射：App.vue（可写 computed，tab 唯一真相源）
 * 与 router（缺段/非法段补默认段）共用。
 *
 * 单一真相源：tab 清单曾抄过第二份硬编码白名单，加新 tab 时没同步，
 * 表现是「tab 显示着、点了却不动」（见 App.vue handleViewChange 注释）。
 * 新增 tab 只改这里 + 对应 viewItems。
 */

// ── 知识库：总览 | 详情 | 夜巡（+ AI对话，头部不出现在 tab 里，由详情工具条按钮进入）──
export type KnowledgeViewKey = 'multilib' | 'maintenance' | 'nightly' | 'aichat'
export const KB_SLUG_TO_KEY: Record<string, KnowledgeViewKey> = {
  overview: 'multilib',
  detail: 'maintenance',
  nightly: 'nightly',
  aichat: 'aichat'
}
export const KB_KEY_TO_SLUG: Record<KnowledgeViewKey, string> = {
  multilib: 'overview',
  maintenance: 'detail',
  nightly: 'nightly',
  aichat: 'aichat'
}
/** 无段/非法段的落地段 */
export const KB_DEFAULT_SLUG = 'overview'

// ── 评测集：日测 | 夜测 | 解析回归 ──
export type EvalViewKey = 'workbench' | 'nightly' | 'parse-regression'
export const EVAL_VIEW_KEYS = ['workbench', 'nightly', 'parse-regression'] as const
export const EVAL_DEFAULT_SLUG: EvalViewKey = 'workbench'
export const isEvalViewKey = (v: string): v is EvalViewKey =>
  (EVAL_VIEW_KEYS as readonly string[]).includes(v)

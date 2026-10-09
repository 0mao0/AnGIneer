/**
 * 知识库「组」的显示名——单一真相源。
 *
 * 内置组的 display_name 后端返回空串（显示名由前端定版），所以任何地方要展示组名都必须走这里，
 * 否则会裸露出 `system` / `evals` 这类内部标识（2026-10-09 业主在导出弹框里看到 `system` 指出）。
 * 自定义组走后端 display_name（建组时填的，带「外服 · / 内测 ·」前缀）。
 */
export const GROUP_LABELS: Record<string, string> = {
  system: '外服 · 系统库',
  standards: '外服 · 规范库',
  dredgeai: '外服 · DredgeAI',
  evals: '内测 · 评测语料',
}

interface GroupLike {
  group_name: string
  display_name?: string
}

/** 组显示名：内置组走内置表 → 自定义组走后端 display_name → 兜底原值（未注册组） */
export function groupLabel(groupName: string, groups?: GroupLike[] | null): string {
  if (GROUP_LABELS[groupName]) return GROUP_LABELS[groupName]
  return groups?.find((g) => g.group_name === groupName)?.display_name || groupName
}

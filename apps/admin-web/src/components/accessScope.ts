/**
 * 「授权知识库」（原名「可访问知识库」，2026-10-09 业主改名）授权单位聚合（同日业主定版显示规则）：
 * 勾选集合 → 按授权单位聚合的标签——组整勾满＝「组名（全部）」、组内勾 ≥2＝「组名（N）」、
 * 组内只勾 1 个＝直接显示该库名；无组归属的散库按库名单列。
 * 选择框（AccessScopeSelect）与用户列表列（UserManage）共用本模块，改规则只改这里。
 */
import type { LibraryGroupItem } from '@/api/knowledge'
import type { LibraryOptionItem } from '@/api/users'

/** 内置组中文名（授权选择器口径：不带域前缀，2026-10-09 业主定版「直接显示知识组的名称」）。
 *  注意与 MultiLibraryManager 的域标签口径有意不同：那边「外服/内测 ·」前缀是库管理页分域排序与 tag 的编码，勿同改 */
const GROUP_LABELS: Record<string, string> = {
  system: '系统库',
  standards: '规范库',
  dredgeai: 'DredgeAI',
  evals: '评测语料',
}

/** 自建组显示名可能带「外服 ·/内测 ·」域前缀（库管理页的域编码）——选择器侧剥掉，只显组名 */
function stripDomainPrefix(label: string): string {
  return label.replace(/^(外服|内测)\s*·\s*/, '').trim() || label
}

export function groupLabel(g: LibraryGroupItem): string {
  return GROUP_LABELS[g.group_name] || stripDomainPrefix(g.display_name || '') || g.group_name
}

export interface AccessUnit {
  key: string
  label: string
  ids: string[]
}

/** 勾选集合 → 聚合标签（点 ×/展示共用；ids 为该标签覆盖的全部勾选库） */
export function buildAccessUnits(
  checked: string[],
  groups: LibraryGroupItem[],
  loose: LibraryOptionItem[],
): AccessUnit[] {
  const checkedSet = new Set(checked)
  const out: AccessUnit[] = []
  for (const g of groups) {
    const members = g.libraries.filter((l) => checkedSet.has(l.id))
    if (members.length === 1) {
      out.push({ key: `g:${g.group_name}`, label: members[0].name || members[0].id, ids: members.map((m) => m.id) })
    } else if (members.length >= 2) {
      const label =
        members.length === g.libraries.length
          ? `${groupLabel(g)}（全部）`
          : `${groupLabel(g)}（${members.length}）`
      out.push({ key: `g:${g.group_name}`, label, ids: members.map((m) => m.id) })
    }
  }
  for (const l of loose) {
    if (checkedSet.has(l.id)) out.push({ key: `l:${l.id}`, label: l.name || l.id, ids: [l.id] })
  }
  // 派生集里出现但清单没有的 id（如已退役库的历史勾选）：兜底单列，保证「看得见才删得掉」
  const known = new Set(groups.flatMap((g) => g.libraries.map((l) => l.id)))
  for (const l of loose) known.add(l.id)
  for (const id of checked) {
    if (!known.has(id)) out.push({ key: `x:${id}`, label: id, ids: [id] })
  }
  return out
}

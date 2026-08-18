/** 归一化 pdfPageRange：去重、升序、过滤 1..total 之外的页码；
 *  undefined/空数组/全部越界时退化为整篇 [1..total]。 */
export function normalizePageRange(range: number[] | undefined, total: number): number[] {
  const count = Math.max(1, Math.floor(total) || 1)
  if (!Array.isArray(range) || range.length === 0) {
    return Array.from({ length: count }, (_, i) => i + 1)
  }
  const set = new Set<number>()
  for (const raw of range) {
    const page = Math.floor(raw)
    if (Number.isFinite(page) && page >= 1 && page <= count) set.add(page)
  }
  if (set.size === 0) {
    return Array.from({ length: count }, (_, i) => i + 1)
  }
  return [...set].sort((a, b) => a - b)
}

/** 将任意页码吸附到最近子集页；距离相等取较小页；空数组返回 1。 */
export function clampPageToRange(page: number, range: number[]): number {
  const list = Array.isArray(range) ? range : []
  if (!list.length) return 1
  const value = Math.round(Number(page))
  if (!Number.isFinite(value)) return list[0]
  if (value <= list[0]) return list[0]
  if (value >= list[list.length - 1]) return list[list.length - 1]
  let best = list[0]
  let bestDist = Number.POSITIVE_INFINITY
  for (const candidate of list) {
    const dist = Math.abs(candidate - value)
    if (dist < bestDist || (dist === bestDist && candidate < best)) {
      bestDist = dist
      best = candidate
    }
  }
  return best
}

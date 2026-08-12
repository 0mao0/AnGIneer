/**
 * 将 token 数量格式化为紧凑单位：
 * 千以内原样显示，千用 k、万用 w、百万用 m，小数最多一位。
 */
export function formatTokenCount(tokens: number): string {
  const count = Math.max(0, Math.round(tokens || 0))
  if (count < 1_000) {
    return String(count)
  }
  const tiers = [
    { threshold: 1_000_000, unit: 1_000_000, suffix: 'm' },
    { threshold: 10_000, unit: 10_000, suffix: 'w' },
    { threshold: 1_000, unit: 1_000, suffix: 'k' },
  ]
  for (const tier of tiers) {
    if (count >= tier.threshold) {
      return `${(count / tier.unit).toFixed(1).replace(/\.0$/, '')}${tier.suffix}`
    }
  }
  return String(count)
}

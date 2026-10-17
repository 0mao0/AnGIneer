/** 游客公开配置客户端（/api/guest/config，免鉴权；docs/design-guest-settings.md §3.2） */
import { docsApiClient } from '../../../shared/apiClient'

export interface GuestConfigGroup {
  group_name: string
  display_name?: string
  libraries: { id: string; name: string }[]
}

/** 公开配置：enabled（是否开放）/ rounds（轮数上限）/ 允许集分组库清单（evals 永不出现） */
export interface GuestConfig {
  enabled: boolean
  rounds: number
  groups: GuestConfigGroup[]
}

export const guestApi = {
  getConfig: (): Promise<GuestConfig> => docsApiClient.get('/guest/config'),
}

export default guestApi

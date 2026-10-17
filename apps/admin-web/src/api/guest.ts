/** 游客设置客户端（/api/guest/settings，管理员鉴权；公开 config 端点在 user-web 侧） */
import { docsApiClient } from '../../../shared/apiClient'

export interface GuestSettings {
  enabled: boolean
  rounds: number
  library_ids: string[]
  /** 非空 = 配置文件读坏（fail-closed 中）；后台醒目提示，保存一次即恢复 */
  load_error: string
}

export const guestApi = {
  getSettings: (): Promise<GuestSettings> => docsApiClient.get('/guest/settings'),
  saveSettings: (data: { enabled: boolean; rounds: number; library_ids: string[] }): Promise<GuestSettings> =>
    docsApiClient.put('/guest/settings', data),
}

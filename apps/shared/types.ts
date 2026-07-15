export interface ApiErrorDetail {
  status: number
  detail?: unknown
  message: string
  raw: unknown
}

export type ApiErrorCode =
  | 'graph_not_built'
  | 'validation_error'
  | 'not_found'
  | 'unauthorized'
  | string

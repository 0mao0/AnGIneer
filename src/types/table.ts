export interface TableData {
  id: string
  name: string
  source: string
  type: TableType
  dimensions: TableDimension[]
  outputs: TableOutput[]
  data: Record<string, any>[]
  rules?: TableRule[]
  notes?: string[]
}

export type TableType = 'simple' | 'conditional' | 'interpolation' | 'chart'

export interface TableDimension {
  key: string
  name: string
  type: 'discrete' | 'range' | 'continuous'
  unit?: string
  values?: (string | number)[]
  ranges?: ValueRange[]
}

export interface ValueRange {
  label: string
  min?: number
  max?: number
  minInclusive?: boolean
  maxInclusive?: boolean
}

export interface TableOutput {
  key: string
  name: string
  unit?: string
  formula?: string
}

export interface TableRule {
  condition: string
  action: 'modify' | 'append' | 'warning'
  content: string
}

export interface TableQueryResult {
  tableId: string
  inputs: Record<string, any>
  outputs: Record<string, any>
  interpolated?: boolean
  warnings?: string[]
}

export interface ThemeConfig {
  primaryColor: string
  mode: 'light' | 'dark'
  compact?: boolean
}

export interface LayoutConfig {
  leftPanelWidth: number
  rightPanelWidth: number
  showLeftPanel: boolean
  showRightPanel: boolean
}

export interface PanelProps {
  title?: string
  collapsible?: boolean
  defaultCollapsed?: boolean
  width?: number | string
  minWidth?: number
  maxWidth?: number
}

export type { SmartTreeNode, TreeNodeAction, DropEvent } from './tree'

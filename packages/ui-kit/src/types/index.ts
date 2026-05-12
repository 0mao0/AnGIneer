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

export type {
  CitationRichMediaOrderItem,
  CitationRichMediaValue,
  CitationReference,
  CitationRange,
  CitationBinding,
  InlineCitationDraftValue,
  InlineCitationCandidate,
  InlineCitationSearchPayload
} from './citation'
export type {
  BaseChatMessageRole,
  BaseChatMessage,
  BaseChatSendPayload,
  BaseChatCitation,
  CitationRichMedia,
  BaseChatContextItem,
  BaseChatModelOption,
  AIChatCitation,
  AIChatMessage,
  QueryRequest,
  QueryResponse,
  SessionKey,
  SessionSnapshot,
  AIChatContextConfig
} from './chat'
export type { SmartTreeNode, TreeNodeAction, DropEvent } from './tree'

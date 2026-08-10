# PDF_Viewer 可折叠解析面板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 PDF_Viewer 具备通用的可折叠右侧面板能力，并把现有解析面板（PDFParsedViewerCombo）接入其中，形成一个可复用的 PDFParsedWorkspace 合并组件，管理后台与用户端共用。

**Architecture:** PDF_Viewer 只新增通用侧栏（props / emit / slot / 宽度过渡 / 自适应监听），不引入解析逻辑；PDFParsedViewerCombo 增加只读模式并收敛图谱 Tab；PDFParsedWorkspace 负责把解析面板放入插槽并提供默认展开/收起、面板宽度、默认 Tab 等配置。管理后台不传新 prop 保持现状，用户端传入默认收起 + 默认树形并接入图数据。

**Tech Stack:** Vue 3.4 + TypeScript + Less + ant-design-vue 4 + @ant-design/icons-vue 7 + pdfjs-dist 4；pnpm workspace 管理。

---

## 文件总览

| 文件 | 职责 | 动作 |
| --- | --- | --- |
| `packages/docs-ui/src/components/common/viewers/PDF_Viewer.vue` | 通用侧栏能力 | 修改 |
| `packages/docs-ui/src/components/common/index/Preview_IndexTree.vue` | 只读模式 | 修改 |
| `packages/docs-ui/src/components/common/workspace/PDFParsedViewerCombo.vue` | 只读模式 + 图谱 Tab 收敛 | 修改 |
| `packages/docs-ui/src/types/knowledge.ts` | 事件契约 | 修改 |
| `packages/docs-ui/src/components/common/workspace/PDFParsedWorkspace.vue` | 合并组件升级 | 修改 |
| `apps/user-web/src/views/DocumentView.vue` | 用户端接入 | 修改 |
| `packages/docs-ui/README.md` | 文档说明 | 修改 |

所有任务都直接提交到 `main` 分支。工作区已有用户未提交的改动，提交时只 `git add` 本任务涉及的文件，绝不 `git add -A`。

---

### Task 1: PDF_Viewer 增加通用侧栏能力

**Files:**
- Modify: `packages/docs-ui/src/components/common/viewers/PDF_Viewer.vue`

- [ ] **Step 1: 修改 Vue 与图标 import**

把：

```ts
import { computed, ref, shallowRef, watch, onMounted, onBeforeUnmount, nextTick, reactive } from 'vue'
```

改成：

```ts
import { computed, ref, shallowRef, watch, onMounted, onBeforeUnmount, nextTick, reactive, useSlots } from 'vue'
```

把：

```ts
import { LeftOutlined, RightOutlined, ZoomInOutlined, ZoomOutOutlined, CompressOutlined, BulbOutlined, SearchOutlined, CloseOutlined } from '@ant-design/icons-vue'
```

改成：

```ts
import { LeftOutlined, RightOutlined, ZoomInOutlined, ZoomOutOutlined, CompressOutlined, BulbOutlined, SearchOutlined, CloseOutlined, MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons-vue'
```

- [ ] **Step 2: 新增 props 并改用 withDefaults**

把：

```ts
const props = defineProps<{
  node: PDFViewerNode
  theme?: 'light' | 'dark' | 'auto'
  isPdf: boolean
  isOffice: boolean
  isImage: boolean
  isText: boolean
  pdfViewerUrl: string
  officePreviewUrl: string
  fileUrl: string
  textContent: string
  searchText?: string
  currentPdfPage: number
  pdfPageCount?: number
  highlights: LinkedHighlight[]
  activeHighlightId: string | null
  activeClickItemId?: string | null
  pageLabels?: Record<number, string>
  textScrollPercent: number
}>()
```

替换为：

```ts
const props = withDefaults(defineProps<{
  node: PDFViewerNode
  theme?: 'light' | 'dark' | 'auto'
  isPdf: boolean
  isOffice: boolean
  isImage: boolean
  isText: boolean
  pdfViewerUrl: string
  officePreviewUrl: string
  fileUrl: string
  textContent: string
  searchText?: string
  currentPdfPage: number
  pdfPageCount?: number
  highlights: LinkedHighlight[]
  activeHighlightId: string | null
  activeClickItemId?: string | null
  pageLabels?: Record<number, string>
  textScrollPercent: number
  sidePanelOpen?: boolean
  showSidePanelToggle?: boolean
  sidePanelWidth?: number
}>(), {
  showSidePanelToggle: false,
  sidePanelWidth: 400
})
```

- [ ] **Step 3: 新增 emit**

把：

```ts
const emit = defineEmits<{
  download: []
  'text-scroll': [percent: number]
  'hover-highlight': [id: string | null]
  'select-highlight': [highlight: LinkedHighlight]
  'pdf-active-page': [page: number]
  'search-jump': [page: number, lineNumber: number]
}>()
```

替换为：

```ts
const emit = defineEmits<{
  download: []
  'text-scroll': [percent: number]
  'hover-highlight': [id: string | null]
  'select-highlight': [highlight: LinkedHighlight]
  'pdf-active-page': [page: number]
  'search-jump': [page: number, lineNumber: number]
  'update:sidePanelOpen': [value: boolean]
}>()
```

- [ ] **Step 4: 新增侧栏状态**

在 `const emit = defineEmits<...>()` 之后、`// --- 常量配置 ---` 之前插入：

```ts
const slots = useSlots()
const internalSidePanelOpen = ref(false)
const sidePanelOpenValue = computed({
  get: () => props.sidePanelOpen ?? internalSidePanelOpen.value,
  set: (value: boolean) => {
    internalSidePanelOpen.value = value
    emit('update:sidePanelOpen', value)
  }
})
const sidePanelVisible = computed(() => sidePanelOpenValue.value && Boolean(slots['side-panel']))
const toggleSidePanel = () => {
  sidePanelOpenValue.value = !sidePanelOpenValue.value
}
```

- [ ] **Step 5: 修改模板根结构**

把模板第一行：

```html
<div :class="['split-pane', themeClass]">
```

替换为：

```html
<div class="pdf-viewer-shell" :class="[themeClass, { 'has-side-panel': sidePanelVisible }]">
  <div ref="splitPaneRef" class="split-pane">
```

把模板结尾（`</template>` 之前的部分）：

```html
    </div>
  </div>
</template>
```

替换为：

```html
    </div>
  </div>
  <div
    :class="['pdf-viewer-side-panel', { 'pdf-viewer-side-panel-open': sidePanelVisible }]"
    :style="{ width: sidePanelVisible ? `${sidePanelWidth}px` : '0px' }"
    role="complementary"
    aria-label="解析对比面板"
  >
    <slot name="side-panel" />
  </div>
</div>
</template>
```

注意：原文件模板结尾的缩进是 `    </div>`（file-preview 关闭）+ `  </div>`（split-pane 关闭），替换时保留前一个 `</div>` 不变。

- [ ] **Step 6: 在头部右侧加入展开/收起按钮**

把：

```html
<div v-if="isPdf" class="pane-title-right">
  <template v-if="!useNativePdfPreview">
```

替换为：

```html
<div class="pane-title-right">
  <Button
    v-if="showSidePanelToggle && $slots['side-panel']"
    size="small"
    class="pdf-tool-btn"
    :class="{ 'pdf-tool-btn-active': sidePanelVisible }"
    :title="sidePanelVisible ? '收起解析对比' : '展开解析对比'"
    @click="toggleSidePanel"
  >
    <template #icon>
      <MenuFoldOutlined v-if="sidePanelVisible" />
      <MenuUnfoldOutlined v-else />
    </template>
  </Button>
  <template v-if="isPdf && !useNativePdfPreview">
```

该按钮不受文件类型限制；搜索/定位框按钮仍只对 PDF 显示。

- [ ] **Step 7: 新增容器宽度监听**

在现有共享 DOM 引用附近（`const toolbarMeasureRef = ref<HTMLElement | null>(null)` 之后）插入：

```ts
const splitPaneRef = ref<HTMLElement | null>(null)
const splitPaneResizeObserver = shallowRef<ResizeObserver | null>(null)
```

在 `onMounted(() => { ... })` 之前插入：

```ts
function setupSplitPaneResizeObserver() {
  if (typeof ResizeObserver === 'undefined' || !splitPaneRef.value) return
  splitPaneResizeObserver.value?.disconnect()
  splitPaneResizeObserver.value = new ResizeObserver(() => {
    if (zoom.isFitToWindowMode.value) zoom.scheduleFitToWindowScale()
  })
  splitPaneResizeObserver.value.observe(splitPaneRef.value)
}
```

把：

```ts
onMounted(() => {
  header.setup()
  zoom.watchIntrinsicWidth()
  zoom.watchFitMode()
  nextTick(() => {
    scroll.scheduleRenderedPageRangeUpdate()
    if (zoom.isFitToWindowMode.value) zoom.scheduleFitToWindowScale()
  })
})

onBeforeUnmount(() => {
  doc.onBeforeUnmount()
  header.teardown()
})
```

替换为：

```ts
onMounted(() => {
  header.setup()
  zoom.watchIntrinsicWidth()
  zoom.watchFitMode()
  setupSplitPaneResizeObserver()
  nextTick(() => {
    scroll.scheduleRenderedPageRangeUpdate()
    if (zoom.isFitToWindowMode.value) zoom.scheduleFitToWindowScale()
  })
})

onBeforeUnmount(() => {
  doc.onBeforeUnmount()
  header.teardown()
  splitPaneResizeObserver.value?.disconnect()
})
```

- [ ] **Step 8: 新增外壳与侧栏样式**

在 `<style lang="less" scoped>` 内、`.split-pane {` 规则之前插入：

```less
.pdf-viewer-shell {
  position: relative;
  flex: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: row;
  align-items: stretch;
  border-radius: 8px;
  overflow: hidden;
  --dp-bg: var(--dp-bg-override, var(--dp-bg, #f3f5f8));
  --dp-pane-bg: var(--dp-pane-bg-override, var(--dp-pane-bg, #fff));
  --dp-pane-border: var(--dp-pane-border-override, var(--dp-pane-border, #e8edf4));
  --dp-title-bg: var(--dp-title-bg-override, var(--dp-title-bg, #fff));
  --dp-title-border: var(--dp-title-border-override, var(--dp-title-border, #edf1f7));
  --dp-title-text: var(--dp-title-text-override, var(--dp-title-text, #595959));
  --dp-title-strong: var(--dp-title-strong-override, var(--dp-title-strong, #4f5d7a));
  --dp-sub-text: var(--dp-sub-text-override, var(--dp-sub-text, #8c8c8c));
  --dp-progress-bg: var(--dp-progress-bg-override, var(--dp-progress-bg, #fcfdff));
  --dp-content-bg: var(--dp-content-bg-override, var(--dp-content-bg, #fff));
  --dp-scroll-thumb: var(--dp-scroll-thumb-override, var(--dp-scroll-thumb, rgba(15,23,42,0.22)));
  --dp-empty-overlay: var(--dp-empty-overlay-override, var(--dp-empty-overlay, rgba(255,255,255,0.92)));
  --dp-empty-text: var(--dp-empty-text-override, var(--dp-empty-text, rgba(0,0,0,0.45)));
  --dp-segment-bg: var(--dp-segment-bg-override, var(--dp-segment-bg, #dfe5f2));
  --dp-segment-border: var(--dp-segment-border-override, var(--dp-segment-border, #cdd6e7));
  --dp-segment-selected-bg: var(--dp-segment-selected-bg-override, var(--dp-segment-selected-bg, #fff));
  --dp-segment-selected-text: var(--dp-segment-selected-text-override, var(--dp-segment-selected-text, #1f2937));
  --dp-segment-shared-bg: var(--dp-segment-shared-bg-override, var(--dp-segment-shared-bg, linear-gradient(90deg, #52c41a 0%, #389e0d 100%)));
  --dp-segment-shared-border: var(--dp-segment-shared-border-override, var(--dp-segment-shared-border, #389e0d));
  --dp-math-bg: var(--dp-math-bg-override, var(--dp-math-bg, #eef3ff));
  --dp-math-color: var(--dp-math-color-override, var(--dp-math-color, #1d3a8a));
  --dp-bg-tertiary: var(--dp-bg-tertiary-override, var(--dp-bg-tertiary, #eef1f5));
}

.pdf-viewer-shell.has-side-panel {
  border: 1px solid var(--dp-pane-border);
}

.pdf-viewer-shell.has-side-panel .split-pane {
  border: none;
  border-radius: 0;
}

.pdf-viewer-side-panel {
  flex: 0 0 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--dp-pane-bg);
  border-left: 1px solid var(--dp-pane-border);
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transition: width 0.2s ease, opacity 0.2s ease, border-color 0.2s ease;
}

.pdf-viewer-side-panel-open {
  opacity: 1;
  visibility: visible;
  pointer-events: auto;
}
```

在 `.split-pane.dark-mode {` 规则之前插入（沿用现有 dark 变量值）：

```less
.pdf-viewer-shell.dark-mode {
  --dp-bg: var(--dp-bg-override, #101319);
  --dp-pane-bg: var(--dp-pane-bg-override, #171b24);
  --dp-pane-border: var(--dp-pane-border-override, #2a3140);
  --dp-title-bg: var(--dp-title-bg-override, #171b24);
  --dp-title-border: var(--dp-title-border-override, #2a3140);
  --dp-title-text: var(--dp-title-text-override, rgba(255,255,255,0.78));
  --dp-title-strong: var(--dp-title-strong-override, rgba(255,255,255,0.92));
  --dp-sub-text: var(--dp-sub-text-override, rgba(255,255,255,0.62));
  --dp-progress-bg: var(--dp-progress-bg-override, #171b24);
  --dp-content-bg: var(--dp-content-bg-override, #171b24);
  --dp-scroll-thumb: var(--dp-scroll-thumb-override, rgba(148,163,184,0.42));
  --dp-empty-overlay: var(--dp-empty-overlay-override, rgba(16,19,25,0.92));
  --dp-empty-text: var(--dp-empty-text-override, rgba(255,255,255,0.6));
  --dp-segment-bg: var(--dp-segment-bg-override, #2a3345);
  --dp-segment-border: var(--dp-segment-border-override, #38445b);
  --dp-segment-selected-bg: var(--dp-segment-selected-bg-override, #3a4660);
  --dp-segment-selected-text: var(--dp-segment-selected-text-override, rgba(255,255,255,0.9));
  --dp-math-bg: var(--dp-math-bg-override, rgba(59,130,246,0.18));
  --dp-math-color: var(--dp-math-color-override, rgba(219,234,254,0.95));
  --dp-bg-tertiary: var(--dp-bg-tertiary-override, #1a1f2e);
}

.pdf-viewer-shell.dark-mode .search-panel {
  border-color: rgba(255, 255, 255, 0.28);
}
```

在 `.split-pane.light-mode {` 规则之前插入（沿用现有 light 变量值）：

```less
.pdf-viewer-shell.light-mode {
  --dp-bg: var(--dp-bg-override, #f3f5f8);
  --dp-pane-bg: var(--dp-pane-bg-override, #fff);
  --dp-pane-border: var(--dp-pane-border-override, #e8edf4);
  --dp-title-bg: var(--dp-title-bg-override, #fff);
  --dp-title-border: var(--dp-title-border-override, #edf1f7);
  --dp-title-text: var(--dp-title-text-override, #595959);
  --dp-title-strong: var(--dp-title-strong-override, #4f5d7a);
  --dp-sub-text: var(--dp-sub-text-override, #8c8c8c);
  --dp-progress-bg: var(--dp-progress-bg-override, #fcfdff);
  --dp-content-bg: var(--dp-content-bg-override, #fff);
  --dp-scroll-thumb: var(--dp-scroll-thumb-override, rgba(15,23,42,0.22));
  --dp-empty-overlay: var(--dp-empty-overlay-override, rgba(255,255,255,0.92));
  --dp-empty-text: var(--dp-empty-text-override, rgba(0,0,0,0.45));
  --dp-segment-bg: var(--dp-segment-bg-override, #dfe5f2);
  --dp-segment-border: var(--dp-segment-border-override, #cdd6e7);
  --dp-segment-selected-bg: var(--dp-segment-selected-bg-override, #fff);
  --dp-segment-selected-text: var(--dp-segment-selected-text-override, #1f2937);
  --dp-math-bg: var(--dp-math-bg-override, #eef3ff);
  --dp-math-color: var(--dp-math-color-override, #1d3a8a);
  --dp-bg-tertiary: var(--dp-bg-tertiary-override, #eef1f5);
}
```

- [ ] **Step 9: 验证类型检查**

Run: `pnpm --filter @angineer/user-web exec vue-tsc -b --pretty false`

Expected: 退出码 0，无 TypeScript 错误。

- [ ] **Step 10: 提交**

Run:

```bash
git add packages/docs-ui/src/components/common/viewers/PDF_Viewer.vue
git commit -m "feat(ui): add generic collapsible side panel to PDF_Viewer"
```

Expected: 提交成功，且未包含任何其他工作区改动。

---

### Task 2: Preview_IndexTree 支持只读模式

**Files:**
- Modify: `packages/docs-ui/src/components/common/index/Preview_IndexTree.vue`

- [ ] **Step 1: 新增 readonly prop**

把：

```ts
interface Props {
  loading?: boolean
  dark?: boolean
  nodeMap: Map<string, DocBlockNode>
  childrenMap: Map<string, string[]>
  roots: DisplayRoot[]
  expandedNodeIds: Set<string>
  activeNodeId: string | null
  selectedNodeIds?: Set<string>
  sourceFilePath?: string
  showFurniture?: boolean
}
```

替换为：

```ts
interface Props {
  loading?: boolean
  dark?: boolean
  nodeMap: Map<string, DocBlockNode>
  childrenMap: Map<string, string[]>
  roots: DisplayRoot[]
  expandedNodeIds: Set<string>
  activeNodeId: string | null
  selectedNodeIds?: Set<string>
  sourceFilePath?: string
  showFurniture?: boolean
  readonly?: boolean
}
```

- [ ] **Step 2: 模板中禁用右键菜单、隐藏勾选框与编辑按钮**

把：

```html
<a-dropdown v-else :trigger="['contextmenu']">
```

替换为：

```html
<a-dropdown v-else :trigger="['contextmenu']" :disabled="readonly">
```

把：

```html
<a-checkbox
  class="tree-select-checkbox"
  :checked="row.checked"
  @click.stop
  @change="onToggleCheck(row.id)"
/>
```

替换为：

```html
<a-checkbox
  v-if="!readonly"
  class="tree-select-checkbox"
  :checked="row.checked"
  @click.stop
  @change="onToggleCheck(row.id)"
/>
```

把：

```html
<a-button
  v-if="row.hasNode"
  type="text"
  size="small"
  class="tree-edit-btn"
  aria-label="编辑"
  @click.stop="onEdit(row.id)"
>
```

替换为：

```html
<a-button
  v-if="row.hasNode && !readonly"
  type="text"
  size="small"
  class="tree-edit-btn"
  aria-label="编辑"
  @click.stop="onEdit(row.id)"
>
```

- [ ] **Step 3: 验证类型检查**

Run: `pnpm --filter @angineer/user-web exec vue-tsc -b --pretty false`

Expected: 退出码 0。

- [ ] **Step 4: 提交**

Run:

```bash
git add packages/docs-ui/src/components/common/index/Preview_IndexTree.vue
git commit -m "feat(ui): support readonly mode in Preview_IndexTree"
```

Expected: 提交成功。

---

### Task 3: PDFParsedViewerCombo 只读模式与图谱 Tab 收敛

**Files:**
- Modify: `packages/docs-ui/src/components/common/workspace/PDFParsedViewerCombo.vue`

- [ ] **Step 1: 新增 readonly 与 canShowKnowledgeGraph**

在 `const emit = defineEmits<ParsedPdfViewerComponentEventMap>()` 之后插入：

```ts
const readonly = computed(() =>
  !props.onUpdateStructuredNode
  && !props.onBatchStructuredOperation
  && !props.onUndoLastOperation
)
const canShowKnowledgeGraph = computed(() => Boolean(props.onLoadGraphSnapshot && props.onBuildGraph))
```

- [ ] **Step 2: 隐藏编辑工具栏**

把：

```html
<div class="summary-actions">
```

替换为：

```html
<div v-if="!readonly" class="summary-actions">
```

- [ ] **Step 3: 隐藏知识图谱 Tab**

把：

```html
<a-radio-button value="Preview_KnowledgeGraph" title="知识图谱">
  <DotChartOutlined />
</a-radio-button>
```

替换为：

```html
<a-radio-button v-if="canShowKnowledgeGraph" value="Preview_KnowledgeGraph" title="知识图谱">
  <DotChartOutlined />
</a-radio-button>
```

- [ ] **Step 4: 给树组件传 readonly**

在 `Preview_IndexTree` 的 props 中、`:show-furniture="showFurniture"` 之后加一行：

```html
:readonly="readonly"
```

- [ ] **Step 5: 回调缺失时回退 Tab**

在现有 `watch(indexSearchKeyword, ...)` 之后插入：

```ts
watch(canShowKnowledgeGraph, (enabled) => {
  if (!enabled && (props.activeTab === 'Preview_KnowledgeGraph' || props.activeTab === 'Preview_IndexGraph')) {
    emit('update:activeTab', props.graphData?.nodes?.length ? 'Preview_IndexTree' : 'Preview_Markdown')
  }
})
```

- [ ] **Step 6: 验证类型检查**

Run: `pnpm --filter @angineer/admin-web exec vue-tsc -b --pretty false`

Expected: 退出码 0。

- [ ] **Step 7: 提交**

Run:

```bash
git add packages/docs-ui/src/components/common/workspace/PDFParsedViewerCombo.vue
git commit -m "feat(ui): add readonly mode and graph tab gating to parsed viewer"
```

Expected: 提交成功。

---

### Task 4: PDFParsedWorkspace 升级为可折叠合并组件

**Files:**
- Modify: `packages/docs-ui/src/types/knowledge.ts`
- Modify: `packages/docs-ui/src/components/common/workspace/PDFParsedWorkspace.vue`

- [ ] **Step 1: 事件契约增加 update:sidePanelOpen**

把：

```ts
export interface PDFParsedWorkspaceEventMap {
  parse: [node: KnowledgeTreeNode]
  'query-structured': [itemType?: string, keyword?: string]
  'update-structured-node': [payload: StructuredNodeUpdatePayload]
  'toggle-visible': [node: KnowledgeTreeNode]
}
```

替换为：

```ts
export interface PDFParsedWorkspaceEventMap {
  parse: [node: KnowledgeTreeNode]
  'query-structured': [itemType?: string, keyword?: string]
  'update-structured-node': [payload: StructuredNodeUpdatePayload]
  'toggle-visible': [node: KnowledgeTreeNode]
  'update:sidePanelOpen': [value: boolean]
}
```

- [ ] **Step 2: PDFParsedWorkspace 新增 props**

在 `interface Props` 的 `dark?: boolean` 之后插入：

```ts
  sidePanelOpen?: boolean
  sidePanelDefaultOpen?: boolean
  sidePanelWidth?: number
  defaultParsedTab?: PreviewMode
```

把：

```ts
const props = withDefaults(defineProps<Props>(), {
  graphDataFullLoaded: false,
  dark: false
})
```

替换为：

```ts
const props = withDefaults(defineProps<Props>(), {
  graphDataFullLoaded: false,
  dark: false,
  sidePanelDefaultOpen: true,
  sidePanelWidth: 400
})
```

- [ ] **Step 3: 保存 emit 引用并新增面板状态**

把：

```ts
defineEmits<PDFParsedWorkspaceEventMap>()
```

替换为：

```ts
const emit = defineEmits<PDFParsedWorkspaceEventMap>()
```

在 `const emit = defineEmits<PDFParsedWorkspaceEventMap>()` 之后插入：

```ts
const internalSidePanelOpen = ref(props.sidePanelDefaultOpen)
const sidePanelOpen = computed({
  get: () => props.sidePanelOpen ?? internalSidePanelOpen.value,
  set: (value: boolean) => {
    internalSidePanelOpen.value = value
    emit('update:sidePanelOpen', value)
  }
})
```

在 `const hasParsedContent = computed(...)` 之后插入：

```ts
const showSidePanelToggle = computed(() => (
  hasParsedContent.value || Boolean(props.graphData?.nodes?.length)
))
```

- [ ] **Step 4: 默认 Tab 支持外部指定**

把：

```ts
const getDefaultParsedTab = (): PreviewMode => (
  props.graphData?.nodes?.length ? 'Preview_IndexTree' : 'Preview_Markdown'
)
```

替换为：

```ts
const getDefaultParsedTab = (): PreviewMode => {
  if (props.defaultParsedTab) return props.defaultParsedTab
  return props.graphData?.nodes?.length ? 'Preview_IndexTree' : 'Preview_Markdown'
}
```

- [ ] **Step 5: 切换文档时重置面板状态**

把：

```ts
watch(() => props.node.key, () => {
  activeTab.value = getDefaultParsedTab()
  resetPreviewState()
  resetLinkageState()
})
```

替换为：

```ts
watch(() => props.node.key, () => {
  internalSidePanelOpen.value = props.sidePanelDefaultOpen
  activeTab.value = getDefaultParsedTab()
  resetPreviewState()
  resetLinkageState()
})
```

- [ ] **Step 6: 模板改为插槽结构**

把 `.split-preview` 中的整段 `PDF_Viewer ... />` 与 `PDFParsedViewerCombo ... />` 替换为：

```html
<PDF_Viewer
  ref="pdfViewerRef"
  :theme="dark ? 'dark' : 'light'"
  :node="node"
  :isPdf="isPdf"
  :isOffice="isOffice"
  :isImage="isImage"
  :isText="isText"
  :pdfViewerUrl="pdfViewerUrl"
  :officePreviewUrl="officePreviewUrl"
  :fileUrl="fileUrl"
  :textContent="textContent"
  :currentPdfPage="pdfPage"
  :pdfPageCount="inferredPdfPageCount"
  :highlights="linkedHighlights"
  :activeHighlightId="activeLeftHighlightId"
  :activeClickItemId="pdfClickActiveItemId"
  :searchText="markdownContent"
  :pageLabels="printedPageLabels"
  :textScrollPercent="leftScrollPercent"
  :show-side-panel-toggle="showSidePanelToggle"
  :side-panel-open="sidePanelOpen"
  :side-panel-width="sidePanelWidth"
  @download="downloadFile"
  @text-scroll="onLeftTextScrollPercent"
  @pdf-active-page="onPdfPageChanged"
  @hover-highlight="onHoverLinkedItem"
  @select-highlight="onSelectPdfHighlight"
  @search-jump="onSearchJump"
  @update:side-panel-open="sidePanelOpen = $event"
>
  <template #side-panel>
    <PDFParsedViewerCombo
      v-model:activeTab="activeTab"
      :markdownContent="markdownContent"
      :structuredItems="structuredItemsValue"
      :indexSummaryStats="indexSummaryStats"
      :hasParsedContent="hasParsedContent"
      :contentScrollPercent="rightScrollPercent"
      :activeLinkedItemId="activeLinkedItemId"
      :activeLineRange="activeLinkedLineRange"
      :sourceFilePath="filePath"
      :graphData="props.graphData"
      :libraryId="'default'"
      :docId="props.node.key"
      :onUpdateStructuredNode="props.onUpdateStructuredNode"
      :onBatchStructuredOperation="props.onBatchStructuredOperation"
      :onUndoLastOperation="props.onUndoLastOperation"
      :onLoadGraphSnapshot="props.onLoadGraphSnapshot"
      :onBuildGraph="props.onBuildGraph"
      :dark="dark"
      :show-furniture="showFurniture"
      @update:show-furniture="showFurniture = $event"
      @content-scroll="onRightPaneScrollPercent"
      @select-item="onSelectItemFromRight"
      @select-line="onSelectLineFromRight"
    />
  </template>
</PDF_Viewer>
```

保留原有 `.split-preview` 外层 div 不变。

- [ ] **Step 7: 去除解析面板在侧栏内的重复边框**

在 `<style lang="less" scoped>` 的 `.doc-preview { ... }` 规则内（`.split-preview` 规则之后）插入：

```less
.split-preview :deep(.pdf-viewer-side-panel .split-pane) {
  border: none;
  border-radius: 0;
}
```

- [ ] **Step 8: 验证类型检查**

Run: `pnpm --filter @angineer/admin-web exec vue-tsc -b --pretty false`

Expected: 退出码 0。

- [ ] **Step 9: 提交**

Run:

```bash
git add packages/docs-ui/src/types/knowledge.ts packages/docs-ui/src/components/common/workspace/PDFParsedWorkspace.vue
git commit -m "feat(ui): make PDFParsedWorkspace collapsible and reusable"
```

Expected: 提交成功。

---

### Task 5: 用户端 DocumentView 接入合并组件

**Files:**
- Modify: `apps/user-web/src/views/DocumentView.vue`

- [ ] **Step 1: 修改 import**

把：

```ts
import { PDF_Viewer, Preview_Markdown } from '@angineer/docs-ui'
```

替换为：

```ts
import { PDFParsedWorkspace, Preview_Markdown } from '@angineer/docs-ui'
```

- [ ] **Step 2: 模板换成 PDFParsedWorkspace**

把：

```html
<PDF_Viewer
  v-else-if="isPdfView && pdfUrl"
  :node="{ status: 'completed', filePath: pdfFilePath }"
  :is-pdf="true"
  :is-office="false"
  :is-image="false"
  :is-text="false"
  :pdf-viewer-url="pdfUrl"
  :office-preview-url="''"
  :file-url="pdfUrl"
  :text-content="''"
  :current-pdf-page="pdfPage"
  :highlights="[]"
  :active-highlight-id="null"
  :text-scroll-percent="0"
  theme="auto"
/>
```

替换为：

```html
<PDFParsedWorkspace
  v-else-if="isPdfView && pdfUrl"
  :node="{ status: 'completed', filePath: pdfFilePath }"
  :content="document.content"
  :render-pdf-path="pdfFilePath"
  :graph-data="graphData"
  :graph-data-full-loaded="graphDataFullLoaded"
  :on-load-full-graph-data="loadGraphData"
  :side-panel-default-open="false"
  :default-parsed-tab="'Preview_IndexTree'"
/>
```

非 PDF 文档仍走原来的 `Preview_Markdown` 分支。

- [ ] **Step 3: 新增图数据状态**

在 `const pdfPage = ref(1)` 之后插入：

```ts
const graphData = ref<{ nodes: any[]; edges: any[] } | null>(null)
const graphDataFullLoaded = ref(false)
const graphDataLoading = ref(false)
const currentDocId = ref('')
```

- [ ] **Step 4: loadDocument 初始化图数据**

在 `loadDocument` 内、`loading.value = true` 之后插入：

```ts
currentDocId.value = docId
graphData.value = null
graphDataFullLoaded.value = false
graphDataLoading.value = false
```

把：

```ts
const result = await knowledgeApi.getDocument(libraryId, docId) as {
  content?: string
  title?: string
  storage?: { render_pdf?: string }
}
```

替换为：

```ts
const result = await knowledgeApi.getDocument(libraryId, docId) as {
  content?: string
  title?: string
  storage?: { render_pdf?: string }
  graph_data?: { nodes: any[]; edges: any[] } | null
}
```

在 `document.value = { ... }` 赋值之后插入：

```ts
graphData.value = result?.graph_data || null
graphDataFullLoaded.value = Boolean(graphData.value?.nodes?.length)
```

- [ ] **Step 5: 新增 loadGraphData 懒加载函数**

在 `loadDocument` 函数之后插入：

```ts
const loadGraphData = async () => {
  const docId = currentDocId.value
  if (!docId || graphDataLoading.value || graphDataFullLoaded.value) return
  graphDataLoading.value = true
  try {
    const result = await knowledgeApi.getDocBlocksGraph('default', docId) as any
    const payload = result?.data || result || null
    graphData.value = payload?.nodes?.length ? payload : null
    graphDataFullLoaded.value = true
  } catch (error) {
    console.warn('[DocumentView] 加载文档图谱数据失败:', error)
    graphDataFullLoaded.value = true
  } finally {
    graphDataLoading.value = false
  }
}
```

- [ ] **Step 6: 验证构建**

Run: `pnpm --filter @angineer/user-web build`

Expected: 退出码 0，vue-tsc 与 vite 均通过。

- [ ] **Step 7: 提交**

Run:

```bash
git add apps/user-web/src/views/DocumentView.vue
git commit -m "feat(user-web): use collapsible parsed workspace in document view"
```

Expected: 提交成功。

---

### Task 6: README 组件说明更新

**Files:**
- Modify: `packages/docs-ui/README.md`

- [ ] **Step 1: 更新 PDF_Viewer 与 PDFParsedWorkspace 说明**

在 README 的组件总览表格中，把 `PDF_Viewer.vue` 的职责描述改为：

```markdown
| `PDF_Viewer.vue` | 左侧文件预览/高亮层，支持通用可折叠侧栏插槽 | `download` `text-scroll` `hover-highlight` `select-highlight` `update:sidePanelOpen` | 由 Workspace 注入数据 |
```

把 `PDFParsedWorkspace.vue` 的职责描述改为：

```markdown
| `PDFParsedWorkspace.vue` | 文档解析工作区编排器（左侧 PDF + 可折叠解析面板） | `parse` `save-content` `change-strategy` `query-structured` `rebuild-structured` `update:sidePanelOpen` | `useWorkspacePreview` `useWorkspaceIngest` `useWorkspaceLinkage` |
```

同时把导出清单中的 `PDF_Viewer` 说明行补充“含 `side-panel` 插槽与 `sidePanelOpen` / `showSidePanelToggle` / `sidePanelWidth` props”。

- [ ] **Step 2: 提交**

Run:

```bash
git add packages/docs-ui/README.md
git commit -m "docs(ui): document collapsible side panel API"
```

Expected: 提交成功。

---

### Task 7: 全量验证与手工回归

**Files:** 无

- [ ] **Step 1: 运行两个前端构建**

Run:

```bash
pnpm --filter @angineer/admin-web build
pnpm --filter @angineer/user-web build
```

Expected: 两个构建均退出码 0。

- [ ] **Step 2: 运行现有纯逻辑测试**

Run: `pnpm test:docs-ui-display-roots`

Expected: 全部通过。

- [ ] **Step 3: 管理后台手工回归**

启动 `pnpm dev:admin`，在文档解析工作区验证：

- 打开文档后，左侧 PDF 与右侧解析面板默认同时显示（未传新 prop，行为不变）；
- 树形编辑（层级调整、合并、拆分、撤销）、知识图谱 Tab 正常；
- 左右联动高亮、搜索跳转正常。

- [ ] **Step 4: 用户端手工回归**

启动 `pnpm dev:frontend`，打开 PDF 文档页验证：

- 默认只显示 PDF，头部右侧有“展开解析对比”按钮；
- 点击按钮后面板展开（宽度过渡），默认停在树形视图；
- 图数据未就绪时树形 Tab 置灰、显示 Markdown，图数据就绪后自动切到树形；
- 面板内无编辑工具栏、无知识图谱 Tab（只读模式）；
- 树节点点击可跳转 PDF 对应页；搜索/翻页/缩放/定位框功能正常；
- 再次点击按钮收起，面板内部 Tab 与滚动位置保留；
- 展开/收起后 PDF 自动重新适应宽度，无需手动缩放。

- [ ] **Step 5: 若发现问题，修复后补充提交**

针对发现的问题修改对应文件，运行对应构建后按 Task 规则单独提交，禁止 `git add -A`。

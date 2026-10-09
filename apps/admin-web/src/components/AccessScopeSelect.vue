<template>
  <a-popover
    v-model:open="open"
    trigger="click"
    placement="bottomLeft"
    :overlay-style="{ width: '420px' }"
    :overlay-inner-style="{ padding: '8px 10px' }"
    @open-change="(v: boolean) => !v && (filter = '')"
  >
    <div class="scope-box" :class="{ 'is-open': open }">
      <template v-if="units.length">
        <a-tag v-for="u in units" :key="u.key" closable class="scope-tag" @close="removeUnit(u)">
          {{ u.label }}
        </a-tag>
      </template>
      <span v-else class="scope-placeholder">{{ PLACEHOLDER }}</span>
      <DownOutlined class="scope-caret" :class="{ 'is-open': open }" />
    </div>

    <template #content>
      <a-input
        v-model:value="filter"
        size="small"
        allow-clear
        placeholder="搜索知识库/组名"
        class="scope-search"
      >
        <template #prefix><search-outlined style="color: rgba(255, 255, 255, 0.25)" /></template>
      </a-input>
      <div class="scope-list">
        <template v-for="sec in sections" :key="sec.key">
          <!-- @mousedown.prevent：点不可聚焦的行体不夺焦点——否则 a-select 输入框失焦，antd 判「点到外面」把下拉关掉
               （antd 自有选项同款处理；搜索框不能加，它要靠 mousedown 聚焦） -->
          <div class="scope-sec-head" @mousedown.prevent @click="onSectionHeadClick($event, sec)">
            <!-- 默认按组折叠（2026-10-09 业主定版：全展开太长）；整行是展开热区（2026-10-09 二锤），
                 点复选框区域只切勾选（事件目标守卫：label 转发点击也挡得住） -->
            <span class="scope-sec-toggle" :title="isExpanded(sec) ? '收起' : '展开组内库'">
              <DownOutlined v-if="isExpanded(sec)" />
              <RightOutlined v-else />
            </span>
            <a-checkbox
              v-if="sec.toggleable"
              :checked="sec.allIds.length > 0 && secChecked(sec).length === sec.allIds.length"
              :indeterminate="secChecked(sec).length > 0 && secChecked(sec).length < sec.allIds.length"
              :aria-label="`选择 ${sec.label}`"
              @change="(e: any) => setSection(sec, e.target.checked)"
            />
            <!-- 名字独立占行（不在复选框里）：点名字=展开、点方块=勾选整组（2026-10-09 二锤） -->
            <span class="scope-sec-name" :class="{ 'scope-sec-label': !sec.toggleable }">{{ sec.label }}</span>
            <span v-if="sec.toggleable" class="scope-sec-count">
              {{ secChecked(sec).length }}/{{ sec.allIds.length }}
            </span>
          </div>
          <div v-show="isExpanded(sec)" class="scope-sec-libs">
            <div v-for="lib in sec.shown" :key="lib.id" class="scope-lib-row" @mousedown.prevent>
              <a-checkbox
                :checked="checkedSet.has(lib.id)"
                @change="(e: any) => toggleLib(lib.id, e.target.checked)"
              >{{ lib.name }}</a-checkbox>
            </div>
          </div>
        </template>
        <div v-if="!sections.length" class="scope-empty">无匹配知识库</div>
      </div>
    </template>
  </a-popover>
</template>

<script setup lang="ts">
/**
 * 授权知识库两级选择器（2026-10-09 业主定版显示规则；原名「可访问知识库」）：
 * 选中态按「授权单位」聚合显示——整组勾满＝「组名（全部）」、组内勾了 2 个及以上＝「组名（N）」、
 * 组内只勾 1 个＝直接显示该库名；散库按库名单列。数据模型仍是勾选的库 id 列表，
 * 与后端 UserAccessPayload（组订阅+直选）换算层 serializeAccess 解耦，回滚窗口语义不变。
 */
import { computed, ref } from 'vue'
import { DownOutlined, RightOutlined, SearchOutlined } from '@ant-design/icons-vue'
import type { LibraryGroupItem } from '@/api/knowledge'
import type { LibraryOptionItem } from '@/api/users'
import { buildAccessUnits, groupLabel, type AccessUnit } from './accessScope'

const props = defineProps<{
  modelValue: string[]
  groups: LibraryGroupItem[]
  loose: LibraryOptionItem[]
}>()

const emit = defineEmits<{ 'update:modelValue': [ids: string[]] }>()

const PLACEHOLDER = '勾选知识库组＝整组授权（展开可扣组内库）；散库区可单勾'

const open = ref(false)
const filter = ref('')

const checkedSet = computed(() => new Set(props.modelValue))

/** 勾选集合 → 选择框聚合标签（聚合规则在 ./accessScope，与用户列表列共用；点 × 整单元取消） */
const units = computed<AccessUnit[]>(() => buildAccessUnits(props.modelValue, props.groups, props.loose))

interface Section {
  key: string
  label: string
  toggleable: boolean
  allIds: string[]
  shown: LibraryOptionItem[]
}

/** 下拉清单：组段（头行可整组勾选/取消）+ 散库段（无组级勾选）；搜索命中组名→整段显示，否则只列命中库 */
const sections = computed<Section[]>(() => {
  const kw = filter.value.trim().toLowerCase()
  const out: Section[] = []
  for (const g of props.groups) {
    if (!g.libraries.length) continue
    const label = groupLabel(g)
    const nameHit = !kw || label.toLowerCase().includes(kw)
    const shown = g.libraries.filter((l) => nameHit || (l.name || l.id).toLowerCase().includes(kw))
    if (!shown.length) continue
    out.push({ key: `g:${g.group_name}`, label, toggleable: true, allIds: g.libraries.map((l) => l.id), shown })
  }
  if (props.loose.length) {
    const shown = kw ? props.loose.filter((l) => (l.name || l.id).toLowerCase().includes(kw)) : props.loose
    if (shown.length) {
      out.push({ key: 'loose', label: '散库（不属于任何组，单勾＝直选）', toggleable: false, allIds: [], shown })
    }
  }
  return out
})

function secChecked(sec: Section): string[] {
  return sec.allIds.filter((id) => checkedSet.value.has(id))
}

/** 分组展开态：默认折叠；搜索时自动展开命中段（搜到了就要看得见） */
const expandedKeys = ref<string[]>([])
function isExpanded(sec: Section): boolean {
  return filter.value.trim() !== '' || expandedKeys.value.includes(sec.key)
}
function toggleExpanded(sec: Section): void {
  const i = expandedKeys.value.indexOf(sec.key)
  if (i >= 0) expandedKeys.value.splice(i, 1)
  else expandedKeys.value.push(sec.key)
}

/** 组头行点击：只豁免复选框小方块本身（名字已移出复选框，是行热区的一部分）；
 *  点方块=勾选整组，点名字/箭头/空白=展开收起 */
function onSectionHeadClick(e: MouseEvent, sec: Section): void {
  const target = e.target as HTMLElement | null
  if (target && target.closest('.ant-checkbox')) return
  toggleExpanded(sec)
}

function setSection(sec: Section, on: boolean): void {
  const next = new Set(props.modelValue)
  for (const id of sec.allIds) {
    if (on) next.add(id)
    else next.delete(id)
  }
  emit('update:modelValue', [...next])
}

function toggleLib(id: string, on: boolean): void {
  const next = new Set(props.modelValue)
  if (on) next.add(id)
  else next.delete(id)
  emit('update:modelValue', [...next])
}

function removeUnit(u: AccessUnit): void {
  emit(
    'update:modelValue',
    props.modelValue.filter((id) => !u.ids.includes(id)),
  )
}
</script>

<style scoped lang="less">
.scope-box {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  width: 100%;
  min-height: 32px;
  padding: 4px 22px 4px 8px;
  border: 1px solid var(--border-color, #d9d9d9);
  border-radius: 6px;
  cursor: pointer;
  background: transparent;
  transition: border-color 0.2s;
  &:hover {
    border-color: var(--primary-color, #1890ff);
  }
  &.is-open {
    border-color: var(--primary-color, #1890ff);
  }
}

.scope-placeholder {
  color: var(--text-tertiary, rgba(128, 128, 128, 0.45));
  font-size: 12px;
  line-height: 22px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.scope-tag {
  margin-inline: 0;
  user-select: none;
}

.scope-caret {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 10px;
  color: var(--text-tertiary, rgba(128, 128, 128, 0.45));
  transition: transform 0.2s;
  &.is-open {
    transform: translateY(-50%) rotate(180deg);
  }
}

.scope-search {
  width: 100%;
  margin-bottom: 6px;
}

.scope-list {
  max-height: 300px;
  overflow-y: auto;
  padding: 2px 4px 2px 2px;
  min-width: 380px;
}

.scope-sec-head {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 4px 0 2px;
  font-weight: 600;
  font-size: 12px;
  cursor: pointer;
  border-radius: 4px;

  &:hover {
    background: var(--bg-tertiary, rgba(0, 0, 0, 0.02));
  }

  :deep(.ant-checkbox-wrapper) {
    flex-shrink: 0;
  }
}

/* 名字独立占行（不在复选框里）：留给行点击做展开热区 */
.scope-sec-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scope-sec-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  flex-shrink: 0;
  cursor: pointer;
  font-size: 10px;
  color: var(--text-tertiary, rgba(128, 128, 128, 0.45));

  &:hover {
    color: var(--text-primary, rgba(128, 128, 128, 0.85));
  }
}

.scope-sec-label {
  flex: 1;
  color: var(--text-secondary, rgba(128, 128, 128, 0.7));
}

.scope-sec-count {
  color: var(--text-tertiary, rgba(128, 128, 128, 0.45));
  font-weight: 400;
}

.scope-sec-libs {
  padding-left: 22px;
}

.scope-lib-row {
  font-size: 12px;
  line-height: 22px;
}

.scope-empty {
  padding: 8px 4px;
  color: var(--text-tertiary, rgba(128, 128, 128, 0.45));
  font-size: 12px;
}
</style>

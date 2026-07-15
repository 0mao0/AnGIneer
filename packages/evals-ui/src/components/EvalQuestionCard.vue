<template>
  <div
    class="eval-question-card"
    :class="{ 'eval-question-card--expanded': expanded }"
  >
    <div class="eval-question-card__header">
      <EvalLevelBadge :level="localIntentLevel" />
      <span class="eval-question-card__id">{{ question.question_id }}</span>
      <span class="eval-question-card__text">{{ localQuestionText }}</span>
      <a-tag v-if="displayStatusTag" :color="displayStatusTag.color" class="eval-question-card__status">
        {{ displayStatusTag.label }}
      </a-tag>
      <a-button
        type="link"
        size="small"
        class="eval-question-card__eval-btn"
        :loading="evaluating"
        @click.stop="$emit('evaluate', question.question_id)"
      >
        评测
      </a-button>
      <button
        type="button"
        class="eval-question-card__arrow-btn"
        :aria-label="expanded ? '收起题目详情' : '展开题目详情'"
        @click.stop="$emit('toggle', question.question_id)"
      >
        <RightOutlined class="eval-question-card__arrow" :class="{ 'eval-question-card__arrow--expanded': expanded }" />
      </button>
    </div>
    <div v-if="expanded" class="eval-question-card__body">
      <div class="eval-question-card__editor">
        <div class="eval-question-card__editor-header">
          <div class="eval-question-card__editor-title">题目内容</div>
          <a-space size="small">
            <a-button
              v-if="!editing"
              size="small"
              class="eval-question-card__editor-action"
              :disabled="evaluating"
              @click="startEditing"
            >
              编辑题目
            </a-button>
            <template v-else>
              <a-button
                size="small"
                type="primary"
                class="eval-question-card__editor-action"
                :loading="savingEdit"
                @click="saveEdit"
              >
                保存
              </a-button>
              <a-button
                size="small"
                class="eval-question-card__editor-action"
                :disabled="savingEdit"
                @click="cancelEdit"
              >
                取消
              </a-button>
            </template>
          </a-space>
        </div>
        <div v-if="editing" class="eval-question-card__edit-form">
          <div class="eval-question-card__edit-row">
            <span class="eval-question-card__edit-label">意图等级</span>
            <a-radio-group v-model:value="editLevel" size="small" :disabled="savingEdit">
              <a-radio-button value="L1">L1</a-radio-button>
              <a-radio-button value="L2">L2</a-radio-button>
              <a-radio-button value="L3">L3</a-radio-button>
              <a-radio-button value="L4">L4</a-radio-button>
            </a-radio-group>
          </div>
          <a-textarea
            v-model:value="editText"
            class="eval-question-card__edit-input"
            :auto-size="{ minRows: 2, maxRows: 6 }"
            :disabled="savingEdit"
            @keydown.ctrl.enter.prevent="saveEdit"
          />
        </div>
        <div v-else class="eval-question-card__editor-content">{{ localQuestionText }}</div>
      </div>

      <div v-if="evaluating && !detail" class="eval-question-card__loading-state">
        <a-spin size="small" />
        <span>正在评测，结果返回后会自动展示。</span>
      </div>

      <div v-if="detail && isFlowTraceLevel" class="eval-chain">
        <div class="eval-chain__title">
          {{ flowTraceTitle }}
          <a-spin v-if="evaluating" size="small" class="eval-chain__spinner" />
        </div>
        <div
          v-for="(stage, idx) in flowTraceStages"
          :key="stage.key"
          class="eval-chain__step"
        >
          <span class="eval-chain__badge">{{ idx + 1 }}</span>
          <a-tag v-if="stage.timing !== undefined" color="processing" class="eval-chain__timing">
            {{ (stage.timing as number).toFixed(2) }}s
          </a-tag>
          <span class="eval-chain__label">{{ stage.label }}</span>
          <span class="eval-chain__value">{{ stage.value }}</span>
          <a-button
            v-if="stage.hasDetail"
            type="link"
            size="small"
            @click.stop="toggleStep(stage.key)"
          >
            {{ isExpanded(stage.key) ? '收起' : '详情' }}
          </a-button>
          <div v-if="stage.hasDetail && isExpanded(stage.key)" class="eval-chain__detail">
            <template v-if="stage.detailType === 'intent'">
              <div class="eval-detail-row">
                <span class="eval-detail-label">任务类型:</span>
                <span>{{ String(prediction?.task_type || question.task_type || '—') }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">识别层级:</span>
                <span>{{ intentDebug.intent_level || traceMeta.level || '—' }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">首选层级:</span>
                <span>{{ primaryIntentLevel || '—' }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">意图类型:</span>
                <span>{{ intentDebug.intent_type || '—' }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">服务模式:</span>
                <span>{{ intentDebug.service_mode || traceMeta.service_mode || '—' }}</span>
              </div>
              <div v-if="hasTieredRouting" class="eval-detail-row">
                <span class="eval-detail-label">执行计划:</span>
                <span>{{ formatExecutionPlanText(executionPlan) }}</span>
              </div>
              <div v-if="intentDebug.reason" class="eval-detail-block">
                <div class="eval-prompt-label">判定理由:</div>
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(intentDebug.reason)" />
              </div>
            </template>

            <template v-else-if="stage.detailType === 'source'">
              <div class="eval-detail-row">
                <span class="eval-detail-label">执行类型:</span>
                <span>{{ flowTraceTitle }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">SOP 名称:</span>
                <span>{{ flowDebug.sop_name || routeDebug.matched_sop_name || routeDebug.matched_sop_id || '—' }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">置信度:</span>
                <span>{{ routeConfidenceText }}</span>
              </div>
              <div v-if="flowDebug.summary || routeDebug.reason" class="eval-detail-block">
                <div class="eval-prompt-label">{{ isDynamicFlowLevel ? '动态摘要:' : '执行摘要:' }}</div>
                <div
                  class="eval-rich-text eval-rich-text--compact"
                  v-html="renderRichText(flowDebug.summary || routeDebug.reason || '—')"
                />
              </div>
            </template>

            <template v-else-if="stage.detailType === 'route'">
              <div class="eval-detail-row">
                <span class="eval-detail-label">路由类型:</span>
                <span>{{ hasTieredRouting ? '分层尝试链' : (routeDebug.route_kind || '—') }}</span>
              </div>
              <div v-if="hasTieredRouting" class="eval-detail-row">
                <span class="eval-detail-label">尝试路径:</span>
                <span>{{ formatExecutionPlanText(executionPlan) }}</span>
              </div>
              <div v-if="finalPath" class="eval-detail-row">
                <span class="eval-detail-label">最终落点:</span>
                <span>{{ formatExecutionPathLabel(finalPath) }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">命中 SOP:</span>
                <span class="eval-matched-sop">{{ routeDebug.matched_sop_name || routeDebug.matched_sop_id || '—' }}</span>
              </div>
              <div v-if="fallbackReason" class="eval-detail-block">
                <div class="eval-prompt-label">回退原因:</div>
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(fallbackReason)" />
              </div>

              <div v-if="routeCandidates.length" class="eval-detail-block">
                <div class="eval-prompt-label">Stage 1 - 候选召回 ({{ routeCandidates.length }} 个):</div>
                <div
                  v-for="candidate in routeCandidates"
                  :key="candidate.id"
                  class="eval-citation-card"
                >
                  <div class="eval-citation-meta">
                    <span class="eval-citation-index">{{ candidate.name_zh || candidate.id }}</span>
                    <span class="eval-citation-score">
                      召回分: {{ candidate.recall_score !== undefined ? Number(candidate.recall_score).toFixed(4) : '—' }}
                    </span>
                  </div>
                  <div
                    class="eval-citation-content"
                    v-html="renderRichText(candidate.description || '—')"
                  />
                </div>
              </div>

              <div v-if="routeDebug.confidence !== null && routeDebug.confidence !== ''" class="eval-detail-block">
                <div class="eval-prompt-label">Stage 2 - LLM 精排结果:</div>
                <div class="eval-detail-row">
                  <span class="eval-detail-label">置信度:</span>
                  <span>{{ routeConfidenceText }}</span>
                </div>
                <div v-if="routeDebug.reason" class="eval-detail-row">
                  <span class="eval-detail-label">精排理由:</span>
                  <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(routeDebug.reason)" />
                </div>
              </div>
            </template>

            <template v-else-if="stage.detailType === 'steps'">
              <div v-if="sopTraceSteps.length" class="eval-flow-chart-layout">
                <!-- 左侧：流程图 -->
                <div class="eval-flow-chart">
                  <svg
                    :width="FLOW_CHART_W"
                    :height="flowChartHeight"
                    class="eval-flow-chart__svg"
                  >
                    <defs>
                      <marker :id="'flow-arrow-' + question.question_id" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
                        <polygon points="0 0, 8 3, 0 6" :fill="flowLineColor" />
                      </marker>
                    </defs>
                    <template v-for="(step, idx) in sopTraceSteps" :key="step.step_id">
                      <!-- 连线（非首节点） -->
                      <line
                        v-if="idx > 0"
                        :x1="FLOW_CHART_W / 2"
                        :y1="flowNodeY(idx - 1) + FLOW_NODE_H"
                        :x2="FLOW_CHART_W / 2"
                        :y2="flowNodeY(idx)"
                        :stroke="flowLineColor"
                        stroke-width="1.5"
                        :marker-end="'url(#flow-arrow-' + question.question_id + ')'"
                      />
                      <!-- 节点矩形 -->
                      <rect
                        :x="(FLOW_CHART_W - FLOW_NODE_W) / 2"
                        :y="flowNodeY(idx)"
                        :width="FLOW_NODE_W"
                        :height="FLOW_NODE_H"
                        rx="6"
                        :fill="flowStepColor(step.status).fill"
                        :stroke="selectedStepId === step.step_id ? flowStepColor(step.status).border : flowStepColor(step.status).border"
                        :stroke-width="selectedStepId === step.step_id ? 2.5 : 1.5"
                        class="eval-flow-chart-node"
                        @click="onFlowNodeClick(step.step_id)"
                      />
                      <!-- 序号圆点 -->
                      <circle
                        :cx="(FLOW_CHART_W - FLOW_NODE_W) / 2 + 16"
                        :cy="flowNodeY(idx) + FLOW_NODE_H / 2"
                        r="10"
                        :fill="flowStepColor(step.status).dot"
                        class="eval-flow-chart-node"
                        @click="onFlowNodeClick(step.step_id)"
                      />
                      <text
                        :x="(FLOW_CHART_W - FLOW_NODE_W) / 2 + 16"
                        :y="flowNodeY(idx) + FLOW_NODE_H / 2 + 1"
                        text-anchor="middle"
                        dominant-baseline="middle"
                        fill="#fff"
                        font-size="11"
                        font-weight="600"
                        class="eval-flow-chart-node"
                        @click="onFlowNodeClick(step.step_id)"
                      >{{ step.step_index }}</text>
                      <!-- 步骤名称 -->
                      <text
                        :x="(FLOW_CHART_W - FLOW_NODE_W) / 2 + 32"
                        :y="flowNodeY(idx) + 22"
                        :fill="flowStepTextColor"
                        font-size="12"
                        font-weight="500"
                        class="eval-flow-chart-node"
                        @click="onFlowNodeClick(step.step_id)"
                      >{{ step.step_name.length > 14 ? step.step_name.slice(0, 13) + '…' : step.step_name }}</text>
                      <!-- 工具名 -->
                      <text
                        v-if="step.tool"
                        :x="(FLOW_CHART_W - FLOW_NODE_W) / 2 + 32"
                        :y="flowNodeY(idx) + 42"
                        :fill="flowStepColor(step.status).border"
                        font-size="10"
                        class="eval-flow-chart-node"
                        @click="onFlowNodeClick(step.step_id)"
                      >{{ step.tool }}</text>
                    </template>
                  </svg>
                </div>
                <!-- 右侧：详情面板 -->
                <div class="eval-flow-chart-detail">
                  <template v-if="selectedStep">
                    <div class="eval-flow-chart-detail__header">
                      <span class="eval-flow-step-card__index">{{ selectedStep.step_index }}</span>
                      <span class="eval-flow-step-card__name">{{ selectedStep.step_name }}</span>
                      <span v-if="selectedStep.tool" class="eval-flow-step-card__tool">{{ selectedStep.tool }}</span>
                      <a-tag v-if="selectedStep.duration" color="processing" class="eval-flow-step-card__duration">
                        {{ selectedStep.duration.toFixed(2) }}s
                      </a-tag>
                      <a-tag
                        :color="selectedStep.status === 'success' ? 'success' : selectedStep.status === 'error' ? 'error' : 'default'"
                      >{{ selectedStep.status }}</a-tag>
                    </div>
                    <div v-if="selectedStep.description" class="eval-flow-chart-detail__desc">
                      <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(selectedStep.description)" />
                    </div>
                    <div
                      v-if="selectedStep.error"
                      class="eval-flow-step-card__error"
                    >
                      {{ selectedStep.error }}
                    </div>
                    <!-- 思考过程 -->
                    <div v-if="selectedStep.thinking" class="eval-prompt-block">
                      <div class="eval-prompt-label">思考过程:</div>
                      <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(selectedStep.thinking)" />
                    </div>
                    <!-- 证据 -->
                    <div v-if="selectedStep.evidence && Object.keys(selectedStep.evidence).length" class="eval-prompt-block">
                      <div class="eval-prompt-label">证据:</div>
                      <table v-if="isTableLike(selectedStep.evidence)" class="eval-known-params-table">
                        <thead><tr><th>来源</th><th>内容</th></tr></thead>
                        <tbody>
                          <tr v-for="(val, key) in selectedStep.evidence" :key="key">
                            <td>{{ key }}</td>
                            <td>{{ val }}</td>
                          </tr>
                        </tbody>
                      </table>
                      <div v-else class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(selectedStep.evidence)" />
                    </div>
                    <!-- 输入 -->
                    <div class="eval-prompt-block">
                      <div class="eval-prompt-label">
                        输入:
                        <a-button type="link" size="small" @click.stop="copyToClipboard(formatOutputVal(selectedStep.inputs))">复制</a-button>
                      </div>
                      <table v-if="isTableLike(selectedStep.inputs)" class="eval-known-params-table">
                        <thead><tr><th>参数</th><th>值</th></tr></thead>
                        <tbody>
                          <tr v-for="(val, key) in selectedStep.inputs" :key="key">
                            <td class="eval-param-key">{{ key }}</td>
                            <td><span v-html="renderFieldValue(val)" /></td>
                          </tr>
                        </tbody>
                      </table>
                      <div v-else-if="selectedStep.inputs && typeof selectedStep.inputs === 'object' && !Array.isArray(selectedStep.inputs)" class="eval-field-list">
                        <div v-for="(val, key) in selectedStep.inputs" :key="key" class="eval-field-item">
                          <span class="eval-field-key">{{ key }}</span>
                          <span v-if="val === null || val === undefined || typeof val === 'string' || typeof val === 'number' || typeof val === 'boolean'" v-html="renderFieldValue(val)" />
                          <pre v-else class="eval-field-json">{{ JSON.stringify(val, null, 2) }}</pre>
                        </div>
                      </div>
                      <div v-else class="eval-prompt-text">{{ formatOutputVal(selectedStep.inputs) }}</div>
                    </div>
                    <!-- 输出 -->
                    <div class="eval-prompt-block">
                      <div class="eval-prompt-label">
                        输出:
                        <a-button type="link" size="small" @click.stop="copyToClipboard(formatOutputVal(selectedStep.outputs))">复制</a-button>
                      </div>
                      <table v-if="isTableLike(selectedStep.outputs)" class="eval-known-params-table">
                        <thead><tr><th>字段</th><th>值</th></tr></thead>
                        <tbody>
                          <tr v-for="(val, key) in selectedStep.outputs!" :key="key">
                            <td class="eval-param-key">{{ key }}</td>
                            <td><span v-html="renderFieldValue(val)" /></td>
                          </tr>
                        </tbody>
                      </table>
                      <div v-else-if="selectedStep.outputs && typeof selectedStep.outputs === 'object' && !Array.isArray(selectedStep.outputs)" class="eval-field-list">
                        <div v-for="(val, key) in selectedStep.outputs!" :key="key" class="eval-field-item">
                          <span class="eval-field-key">{{ key }}</span>
                          <span v-if="val === null || val === undefined || typeof val === 'string' || typeof val === 'number' || typeof val === 'boolean'" v-html="renderFieldValue(val)" />
                          <pre v-else class="eval-field-json">{{ JSON.stringify(val, null, 2) }}</pre>
                        </div>
                      </div>
                      <div v-else-if="typeof selectedStep.outputs === 'string'" class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(selectedStep.outputs)" />
                      <div v-else class="eval-prompt-text">{{ formatOutputVal(selectedStep.outputs) }}</div>
                    </div>
                  </template>
                  <div v-else class="eval-detail-empty">点击流程图节点查看详情</div>
                </div>
              </div>
              <div v-else-if="attemptedPaths.length" class="eval-flow-steps">
                <div
                  v-for="(path, pathIdx) in attemptedPaths"
                  :key="`attempted-path-${pathIdx}-${path.path}`"
                  class="eval-flow-step-card"
                  :class="{
                    'eval-flow-step-card--success': path.status === 'success',
                    'eval-flow-step-card--error': isErrorStatus(path.status),
                  }"
                >
                  <div class="eval-flow-step-card__header">
                    <span class="eval-flow-step-card__index">{{ pathIdx + 1 }}</span>
                    <span class="eval-flow-step-card__name">{{ formatExecutionPathLabel(path.path) }}</span>
                    <span class="eval-flow-step-card__tool">{{ formatAttemptedStatus(path.status) }}</span>
                    <a-tag v-if="path.duration" color="processing" class="eval-flow-step-card__duration">
                      {{ path.duration.toFixed(2) }}s
                    </a-tag>
                  </div>
                  <div v-if="path.reason" class="eval-flow-step-card__desc">{{ path.reason }}</div>
                </div>
              </div>
              <div v-else class="eval-detail-empty">暂无 SOP 步骤追踪</div>
            </template>

            <template v-else-if="stage.detailType === 'answer'">
              <div v-if="prediction?.thinking" class="eval-thinking-block">
                <div class="eval-prompt-label">思考过程:</div>
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(prediction.thinking)" />
              </div>
              <div v-if="answerHeadline" class="eval-answer-summary">
                {{ answerHeadline }}
              </div>
              <div class="eval-prompt-block">
                <div class="eval-prompt-label">最终回答:</div>
                <div class="eval-rich-text eval-rich-text--answer" v-html="renderRichText(answerText)" />
              </div>
              <div v-if="citations.length" class="eval-detail-block">
                <div class="eval-prompt-label">引用证据:</div>
                <div
                  v-for="(c, ci) in citations"
                  :key="`flow-answer-citation-${ci}`"
                  class="eval-citation-card"
                >
                  <div class="eval-citation-meta">
                    <span class="eval-citation-index">[{{ ci + 1 }}]</span>
                    <span v-if="getCitationDocTitle(c)" class="eval-citation-source">
                      {{ getCitationDocTitle(c) }}
                    </span>
                  </div>
                  <div v-if="getCitationEntryLabel(c)" class="eval-citation-location">
                    {{ getCitationEntryLabel(c) }}
                  </div>
                  <div
                    v-if="getCitationText(c)"
                    class="eval-citation-content"
                    v-html="renderRichText(getCitationText(c).slice(0, 2000))"
                  />
                </div>
              </div>
            </template>

            <template v-else-if="stage.detailType === 'evaluation'">
              <div v-if="traceSummary" class="eval-detail-block">
                <div class="eval-prompt-label">诊断摘要:</div>
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(traceSummary)" />
              </div>
              <div v-if="correctnessSummary" class="eval-detail-block">
                <div class="eval-prompt-label">正确性校验:</div>
                <div class="eval-check-summary" :class="correctnessSummaryClass">
                  <span class="eval-check-icon">{{ correctnessAllPassed ? '✓' : '✗' }}</span>
                  <span>{{ correctnessSummary }}</span>
                </div>
              </div>
              <div v-if="traceIssues.length" class="eval-detail-block">
                <div class="eval-prompt-label">诊断问题:</div>
                <div
                  v-for="issue in traceIssues"
                  :key="issue.code"
                  class="eval-citation-card"
                >
                  <div class="eval-citation-meta">
                    <span class="eval-citation-index">{{ issue.code }}</span>
                  </div>
                  <div class="eval-citation-content" v-html="renderRichText(issue.message)" />
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>

      <div v-else-if="detail && isCasualTraceLevel" class="eval-chain">
        <div class="eval-chain__title">
          {{ casualTraceTitle }}
          <a-spin v-if="evaluating" size="small" class="eval-chain__spinner" />
        </div>
        <div
          v-for="(step, idx) in casualTraceSteps"
          :key="step.key"
          class="eval-chain__step"
        >
          <span class="eval-chain__badge">{{ idx + 1 }}</span>
          <a-tag v-if="step.timing !== undefined" color="processing" class="eval-chain__timing">
            {{ (step.timing as number).toFixed(2) }}s
          </a-tag>
          <span class="eval-chain__label">{{ step.label }}</span>
          <span class="eval-chain__value">{{ step.value }}</span>
          <a-button
            v-if="step.hasDetail"
            type="link"
            size="small"
            @click.stop="toggleStep(step.key)"
          >
            {{ isExpanded(step.key) ? '收起' : '详情' }}
          </a-button>
          <div v-if="step.hasDetail && isExpanded(step.key)" class="eval-chain__detail">
            <template v-if="step.detailType === 'intent'">
              <div class="eval-detail-row">
                <span class="eval-detail-label">意图层级:</span>
                <span>{{ intentDebug.intent_level || traceMeta.level || '—' }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">服务模式:</span>
                <span>{{ intentDebug.service_mode || traceMeta.service_mode || 'casual_chat' }}</span>
              </div>
              <div v-if="intentDebug.reason" class="eval-detail-block">
                <div class="eval-prompt-label">判定理由:</div>
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(intentDebug.reason)" />
              </div>
            </template>
            <template v-else>
              <div v-if="prediction?.thinking" class="eval-thinking-block">
                <div class="eval-prompt-label">思考过程:</div>
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(prediction.thinking)" />
              </div>
              <div v-if="answerHeadline" class="eval-answer-summary">
                {{ answerHeadline }}
              </div>
              <div class="eval-prompt-block">
                <div class="eval-prompt-label">最终回答:</div>
                <div class="eval-rich-text eval-rich-text--answer" v-html="renderRichText(answerText)" />
              </div>
            </template>
          </div>
        </div>
      </div>

      <div v-else-if="detail" class="eval-chain">
        <div class="eval-chain__title">
          {{ knowledgeTraceTitle }}
          <a-spin v-if="evaluating" size="small" class="eval-chain__spinner" />
        </div>
        <div
          v-for="(step, idx) in knowledgeTraceSteps"
          :key="step.key"
          class="eval-chain__step"
        >
          <span class="eval-chain__badge">{{ idx + 1 }}</span>
          <a-tag v-if="step.timing !== undefined" color="processing" class="eval-chain__timing">
            {{ (step.timing as number).toFixed(2) }}s
          </a-tag>
          <span class="eval-chain__label">{{ step.label }}</span>
          <span class="eval-chain__value">{{ step.value }}</span>
          <a-button
            v-if="step.hasDetail"
            type="link"
            size="small"
            @click.stop="toggleStep(step.key)"
          >
            {{ isExpanded(step.key) ? '收起' : '详情' }}
          </a-button>
          <div v-if="step.hasDetail && isExpanded(step.key)" class="eval-chain__detail">
            <!-- 意图识别详情 -->
            <template v-if="step.label === '意图识别'">
              <div class="eval-detail-row">
                <span class="eval-detail-label">任务类型:</span>
                <span>{{ String(prediction?.task_type || question.task_type || '—') }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">识别层级:</span>
                <span>{{ intentDebug.intent_level || traceMeta.level }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">首选层级:</span>
                <span>{{ primaryIntentLevel || '—' }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">服务模式:</span>
                <span>{{ intentDebug.service_mode || traceMeta.service_mode || '—' }}</span>
              </div>
              <div v-if="intentDebug.reason" class="eval-detail-block">
                <div class="eval-prompt-label">判定理由:</div>
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(intentDebug.reason)" />
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">元 SOP:</span>
                <span>{{ metaSopPath }}</span>
              </div>
            </template>

            <!-- 证据检索详情 -->
            <template v-if="step.label === '证据检索' || step.label === 'SQL/条款定位'">
              <div
                v-for="(c, ci) in citations"
                :key="`citation-${ci}`"
                class="eval-citation-card"
              >
                <div class="eval-citation-meta">
                  <span class="eval-citation-index">[{{ ci + 1 }}]</span>
                  <span
                    v-if="c.score !== undefined && c.score !== null && c.score !== ''"
                    class="eval-citation-score"
                  >得分: {{ Number(c.score).toFixed(4) }}</span>
                  <span v-if="c.fusion_sources && c.fusion_sources.length" class="eval-citation-source">
                    来源: {{ formatFusionSources(c.fusion_sources) }}
                  </span>
                </div>
                <div v-if="getCitationEntryLabel(c)" class="eval-citation-location">
                  {{ getCitationEntryLabel(c) }}
                </div>
                <div v-if="getCitationDocTitle(c)" class="eval-citation-location">
                  {{ getCitationDocTitle(c) }}
                  <template v-if="getCitationPage(c)"> · 页码: P{{ getCitationPage(c) }}</template>
                </div>
                <div v-if="getCitationSectionPath(c)" class="eval-citation-section">
                  章节: {{ getCitationSectionPath(c) }}
                </div>
                <div
                  v-if="getCitationText(c)"
                  class="eval-citation-content"
                  v-html="renderRichText(getCitationText(c).slice(0, 2000))"
                />
              </div>
              <div v-if="!citations.length" class="eval-detail-empty">无检索结果</div>
              <div v-if="step.label === 'SQL/条款定位'" class="eval-detail-row">
                <span class="eval-detail-label">查询策略:</span>
                <span>{{ String(prediction?.strategy || routeDebug.route_kind || '—') }}</span>
              </div>
              <div v-if="sqlDebug" class="eval-sql-debug">
                <div class="eval-prompt-label">SQL 执行详情</div>
                <div class="eval-detail-row">
                  <span class="eval-detail-label">执行状态:</span>
                  <span :class="sqlDebug.execution_success ? 'eval-sql-success' : 'eval-sql-fail'">
                    {{ sqlDebug.execution_success ? '成功' : '失败' }}
                  </span>
                  <span v-if="sqlDebug.score !== undefined" class="eval-sql-score">
                    得分: {{ (sqlDebug.score * 100).toFixed(0) }}
                  </span>
                </div>
                <div v-if="sqlDebug.execution_status" class="eval-detail-row">
                  <span class="eval-detail-label">执行状态码:</span>
                  <span>{{ sqlDebug.execution_status }}</span>
                </div>
                <div v-if="sqlDebug.generated_sql" class="eval-prompt-block">
                  <div class="eval-prompt-label">生成 SQL:</div>
                  <pre class="eval-sql-code">{{ sqlDebug.generated_sql }}</pre>
                </div>
                <div v-if="question.sql_gold?.expected_sql" class="eval-prompt-block">
                  <div class="eval-prompt-label">期望 SQL:</div>
                  <pre class="eval-sql-code">{{ question.sql_gold.expected_sql }}</pre>
                </div>
                <div v-if="sqlDebug.sql_exact_match !== undefined" class="eval-detail-row">
                  <span class="eval-detail-label">SQL 精确匹配:</span>
                  <span :class="sqlDebug.sql_exact_match ? 'eval-sql-success' : 'eval-sql-fail'">
                    {{ sqlDebug.sql_exact_match ? '是' : '否' }}
                  </span>
                </div>
                <div v-if="sqlDebug.execution_result" class="eval-prompt-block">
                  <div class="eval-prompt-label">执行结果:</div>
                  <pre class="eval-sql-code">{{ sqlDebug.execution_result }}</pre>
                </div>
                <div v-if="sqlDebug.error" class="eval-sql-error">
                  错误: {{ sqlDebug.error }}
                </div>
              </div>
              <div v-if="retrievalScores" class="eval-retrieval-scores">
                <div class="eval-detail-row">
                  <span class="eval-detail-label">检索评测:</span>
                  <span>
                    <template v-if="retrievalScores['hit@3'] !== undefined">Hit@3: {{ ((retrievalScores['hit@3'] as number) * 100).toFixed(1) }}% </template>
                    <template v-if="retrievalScores['hit@5'] !== undefined">Hit@5: {{ ((retrievalScores['hit@5'] as number) * 100).toFixed(1) }}% </template>
                    <template v-if="retrievalScores.mrr !== undefined">MRR: {{ ((retrievalScores.mrr as number) * 100).toFixed(1) }}%</template>
                    <template v-if="retrievalScores.evaluated === false">未评测（无检索标准）</template>
                  </span>
                </div>
              </div>
            </template>

            <!-- Prompt 拼装详情 -->
            <template v-if="step.label === 'Prompt 拼装'">
              <div v-if="systemPromptText" class="eval-prompt-block">
                <div class="eval-prompt-label">System Prompt:</div>
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(systemPromptText)" />
              </div>
              <div class="eval-prompt-block">
                <div class="eval-prompt-label">User Message - 问题:</div>
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(question.question)" />
              </div>
              <div class="eval-prompt-block">
                <div class="eval-prompt-label">User Message - 证据片段:</div>
                <div
                  v-for="(c, ci) in citations.slice(0, 5)"
                  :key="`prompt-citation-${ci}`"
                  class="eval-prompt-citation"
                >
                  <span class="eval-citation-index">[{{ ci + 1 }}]</span>
                  {{ getCitationText(c).slice(0, 200) || '(无片段)' }}
                </div>
              </div>
            </template>

            <!-- LLM 回答详情 -->
            <template v-if="step.label === 'LLM 回答'">
              <div v-if="prediction?.thinking" class="eval-thinking-block">
                <div class="eval-prompt-label">思考过程:</div>
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(prediction.thinking)" />
              </div>
              <div v-if="answerHeadline" class="eval-answer-summary">
                {{ answerHeadline }}
              </div>
              <div class="eval-prompt-block">
                <div class="eval-prompt-label">最终回答:</div>
                <div class="eval-rich-text eval-rich-text--answer" v-html="renderRichText(answerText)" />
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- 正确性校验 -->
      <div v-if="correctnessSummary" class="eval-section">
        <div class="eval-section__header">
          <div class="eval-section__title">正确性校验</div>
          <a-button
            v-if="checkDetails.length"
            type="link"
            size="small"
            @click.stop="toggleStep('correctness-rules')"
          >
            {{ isExpanded('correctness-rules') ? '收起规则' : '查看规则' }}
          </a-button>
        </div>
        <div class="eval-check-summary" :class="correctnessSummaryClass">
          <span class="eval-check-icon">{{ correctnessAllPassed ? '✓' : '✗' }}</span>
          <span>{{ correctnessSummary }}</span>
        </div>
        <div v-if="checkDetails.length && isExpanded('correctness-rules')" class="eval-check-rules">
          <div
            v-for="(check, ci) in checkDetails"
            :key="`check-${ci}`"
            class="eval-check-rule"
          >
            <span class="eval-check-type">{{ check.type }}</span>
            <span class="eval-check-keywords">{{ formatCheckRule(check) }}</span>
          </div>
        </div>
      </div>

      <!-- 标准答案对比 -->
      <div class="eval-section">
        <div class="eval-section__title">答案对比</div>
        <div class="eval-comparison">
          <div class="eval-comparison__col">
            <div class="eval-comparison__label">系统回答</div>
            <div class="eval-comparison__content">
              <div v-if="answerHeadline" class="eval-answer-summary">
                {{ answerHeadline }}
              </div>
              <div class="eval-rich-text eval-rich-text--answer" v-html="renderRichText(answerText)" />
            </div>
          </div>
          <div class="eval-comparison__col">
            <div class="eval-comparison__label">标准答案</div>
            <div class="eval-comparison__content">
              <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(question.answer_gold?.gold_answer || '—')" />
            </div>
          </div>
        </div>
      </div>

      <!-- 标准思考过程 -->
      <div v-if="question.answer_gold?.thought_process" class="eval-section">
        <div class="eval-section__title">标准思考过程</div>
        <div class="eval-rich-text eval-rich-text--answer" v-html="renderRichText(question.answer_gold.thought_process)" />
      </div>

      <!-- 语义评判 -->
      <div v-if="semanticResult" class="eval-section">
        <div class="eval-semantic-header">
          <span class="eval-section__title">语义评判</span>
          <span
            class="eval-semantic-score"
            :class="{
              'eval-semantic-score--passed': semanticResult.semantic_passed === true,
              'eval-semantic-score--failed': semanticResult.semantic_passed === false,
              'eval-semantic-score--fallback': semanticResult.semantic_fallback,
            }"
          >
            {{ semanticResult.semantic_score !== null ? Math.round(semanticResult.semantic_score * 100) + '分' : '—' }}
          </span>
          <span class="eval-semantic-threshold">
            （阈值{{ Math.round(semanticResult.semantic_threshold * 100) }}分）
          </span>
        </div>
        <div
          v-if="semanticResult.semantic_reason"
          class="eval-semantic-reason eval-rich-text eval-rich-text--compact"
          v-html="renderRichText(semanticResult.semantic_reason)"
        />
        <div v-if="semanticResult.semantic_fallback" class="eval-semantic-fallback-hint">
          ⚠ LLM 语义评判失败，已降级为关键词匹配
        </div>
      </div>

      <!-- 错误信息 -->
      <div v-if="detail?.error" class="eval-section eval-section--error">
        错误: {{ detail.error }}
      </div>
      <div v-else-if="!detail && !evaluating" class="eval-question-card__empty">
        点击“评测”后可在此查看链路详情和结果。
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { RightOutlined } from '@ant-design/icons-vue'
import { renderMarkdownToHtml } from '@angineer/ui-kit/utils/markdown'
import { useTheme } from '@angineer/ui-kit'
import {
  getCitationDocTitle,
  getCitationEntryLabel,
  getCitationPage,
  getCitationSectionPath,
  getCitationText,
  type EvalCitationItem,
} from '../utils/citation'
import EvalLevelBadge from './EvalLevelBadge.vue'
import type { EvalQuestion, EvalRunDetail, SemanticEvalResult, EvalIntentLevel } from '../types/eval'

interface ThinkingStep {
  key: string
  label: string
  value: string
  hasDetail: boolean
  detailType?: 'intent' | 'source' | 'route' | 'steps' | 'answer' | 'evaluation'
  timing?: number
}

interface SopTraceStep {
  step_id: string
  step_name: string
  step_index: number
  tool: string
  description: string
  inputs: Record<string, unknown>
  outputs: Record<string, unknown> | null
  duration: number
  status: string
  error: string | null
  thinking?: string | null
  evidence?: Record<string, unknown> | null
}

/** 判断值是否可渲染为紧凑表格（简单 key-value 对象，所有值均为原始类型） */
function isTableLike(val: unknown): val is Record<string, unknown> {
  if (!val || typeof val !== 'object' || Array.isArray(val)) return false
  const keys = Object.keys(val)
  return keys.length > 0 && keys.every(k => {
    const v = (val as Record<string, unknown>)[k]
    return v === null || v === undefined || typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean'
  })
}

/** 渲染单个值：字符串用富文本，对象/数组用格式化文本 */
function renderFieldValue(val: unknown): string {
  if (val === null || val === undefined) return '—'
  if (typeof val === 'string') return renderMarkdownToHtml(val, '')
  if (typeof val === 'object') return '<pre style="margin:0;font-size:11px;white-space:pre-wrap">' + escapeHtml(JSON.stringify(val, null, 2)) + '</pre>'
  return escapeHtml(String(val))
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

interface RouteCandidate {
  id: string
  name?: string
  name_zh?: string
  description?: string
  recall_score?: number
}

interface AttemptedPathEntry {
  path: string
  status: string
  reason?: string
  duration?: number
}

interface TraceIssue {
  code: string
  message: string
}

interface CorrectnessDetail {
  type: string
  keywords: string[]
  passed: boolean
}

const props = defineProps<{
  question: EvalQuestion
  detail: EvalRunDetail | null
  expanded: boolean
  evaluating: boolean
}>()

const emit = defineEmits<{
  toggle: [questionId: string]
  evaluate: [questionId: string]
  updated: []
}>()

const expandedSteps = ref<Set<string>>(new Set())
const selectedStepId = ref<string | null>(null)
const { isDark } = useTheme()
const editing = ref(false)
const editText = ref('')
const editLevel = ref<EvalIntentLevel>(props.question.intent_level)
const localQuestionText = ref(props.question.question)
const localIntentLevel = ref<EvalIntentLevel>(props.question.intent_level)
const savingEdit = ref(false)

/** 记录上一步的步骤数量，用于检测增量变化。 */
const prevStepCount = ref(0)

watch(() => props.question.question, (value) => {
  localQuestionText.value = value
})

watch(() => props.question.intent_level, (value) => {
  localIntentLevel.value = value
})

watch(() => props.expanded, (value) => {
  if (!value) {
    cancelEdit()
  }
})

/** 进入展开区题目编辑模式。 */
const startEditing = () => {
  editText.value = localQuestionText.value
  editLevel.value = localIntentLevel.value
  editing.value = true
}

/** 取消题目编辑并恢复到当前已知文本和等级。 */
const cancelEdit = () => {
  editing.value = false
  editText.value = localQuestionText.value
  editLevel.value = localIntentLevel.value
}

/** 保存编辑后的题目文本和意图等级。 */
const saveEdit = async () => {
  const trimmed = editText.value.trim()
  if (!trimmed) {
    message.warning('题目不能为空')
    return
  }
  const textChanged = trimmed !== localQuestionText.value
  const levelChanged = editLevel.value !== localIntentLevel.value
  if (!textChanged && !levelChanged) {
    editing.value = false
    return
  }
  savingEdit.value = true
  try {
    const payload: Record<string, string> = {}
    if (textChanged) payload.question = trimmed
    if (levelChanged) payload.intent_level = editLevel.value
    const resp = await fetch(
      `/api/evals/datasets/${props.question.dataset_id}/questions/${props.question.question_id}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }
    )
    if (resp.ok) {
      if (textChanged) localQuestionText.value = trimmed
      if (levelChanged) localIntentLevel.value = editLevel.value
      editing.value = false
      message.success('题目已保存')
      emit('updated')
    } else {
      const errText = await resp.text().catch(() => '')
      message.error(`保存失败: ${errText || resp.status}`)
    }
  } catch (e: any) {
    message.error(`保存失败: ${e.message || e}`)
  } finally {
    savingEdit.value = false
  }
}

/** 切换链路节点或步骤详情的展开状态。 */
const toggleStep = (key: string) => {
  const next = new Set(expandedSteps.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  expandedSteps.value = next
}

/** 判断链路节点或步骤详情当前是否处于展开状态。 */
const isExpanded = (key: string) => expandedSteps.value.has(key)

const displayStatusTag = computed(() => {
  if (props.evaluating || props.detail?.status === 'running') {
    return { color: 'processing', label: '评测中' }
  }

  const status = props.detail?.status || 'pending'
  const quality = props.detail?.quality as string | null | undefined
  if (status === 'completed') {
    if (quality === 'correct') {
      return { color: 'success', label: '已完成 · 正确' }
    }
    if (quality === 'wrong') {
      return { color: 'error', label: '已完成 · 错误' }
    }
    return { color: 'success', label: '已完成' }
  }

  if (status === 'error') {
    return { color: 'error', label: '出错' }
  }

  return { color: 'default', label: '待评测' }
})

const prediction = computed(() => {
  const p = props.detail?.prediction as Record<string, unknown> | null
  return p
})

const traceMeta = computed<Record<string, unknown>>(() => {
  return (prediction.value?.trace_meta as Record<string, unknown>) || {}
})

const intentDebug = computed<Record<string, unknown>>(() => {
  const fromPrediction = (prediction.value?.intent_debug as Record<string, unknown>) || {}
  const fromIntent = (prediction.value?.intent as Record<string, unknown>) || {}
  return { ...fromIntent, ...fromPrediction }
})

const routeDebug = computed<Record<string, unknown>>(() => {
  return (prediction.value?.route_debug as Record<string, unknown>) || {}
})

const flowDebug = computed<Record<string, unknown>>(() => {
  return (prediction.value?.flow_debug as Record<string, unknown>) || {}
})

const traceIssues = computed<TraceIssue[]>(() => {
  const issues = prediction.value?.issues
  return Array.isArray(issues) ? (issues as TraceIssue[]) : []
})

const traceSummary = computed(() => {
  return String(prediction.value?.trace_summary || prediction.value?.summary || '')
})

const citations = computed<EvalCitationItem[]>(() => {
  const c = prediction.value?.citations
  return Array.isArray(c) ? (c as EvalCitationItem[]) : []
})

const retrievalScores = computed<Record<string, unknown> | null>(() => {
  const allScores = props.detail?.all_scores as Record<string, Record<string, unknown>> | null
  if (allScores?.retrieval) {
    return allScores.retrieval
  }
  const scores = props.detail?.scores as Record<string, unknown> | null
  if (scores?.['hit@5'] !== undefined) {
    return scores
  }
  return null
})

interface SqlDebugInfo {
  score?: number
  execution_success?: boolean
  execution_status?: string
  sql_exact_match?: boolean | null
  generated_sql?: string
  execution_result?: string
  error?: string
}

const sqlDebug = computed<SqlDebugInfo | null>(() => {
  const allScores = props.detail?.all_scores as Record<string, Record<string, unknown>> | null
  const allPredictions = props.detail?.all_predictions as Record<string, Record<string, unknown>> | null
  const t2sScores = allScores?.text2sql
  const t2sPred = allPredictions?.text2sql as Record<string, unknown> | undefined
  if (!t2sScores && !t2sPred) return null
  const sqlPayload = t2sPred?.sql as Record<string, unknown> | undefined
  const execResult = sqlPayload?.execution_result
  return {
    score: t2sScores?.score as number | undefined,
    execution_success: t2sScores?.execution_success as boolean | undefined,
    execution_status: t2sScores?.execution_status as string | undefined,
    sql_exact_match: t2sScores?.sql_exact_match as boolean | null | undefined,
    generated_sql: (t2sPred?.generated_sql as string) || (sqlPayload?.generated_sql as string),
    execution_result: execResult ? JSON.stringify(execResult, null, 2) : undefined,
    error: sqlPayload?.error as string | undefined,
  }
})

const checkDetails = computed<CorrectnessDetail[]>(() => {
  const allScores = props.detail?.all_scores as Record<string, Record<string, unknown>> | null
  const answerScores = allScores?.answer || props.detail?.scores
  if (!answerScores) return []
  const details = answerScores.check_details as CorrectnessDetail[] | undefined
  return details || []
})

const correctnessAllPassed = computed(() => {
  return checkDetails.value.length > 0 && checkDetails.value.every(check => check.passed)
})

const correctnessSummary = computed(() => {
  if (!checkDetails.value.length) return ''
  if (correctnessAllPassed.value) {
    if (explicitAnswerOption.value) {
      return `关键词校验通过，命中标准答案选项 ${explicitAnswerOption.value}`
    }
    return '关键词校验通过'
  }
  if (explicitAnswerOption.value) {
    return `关键词校验未完全通过，但当前回答显式给出了选项 ${explicitAnswerOption.value}`
  }
  const passedCount = checkDetails.value.filter(check => check.passed).length
  return `关键词校验未通过（${passedCount}/${checkDetails.value.length}）`
})

const correctnessSummaryClass = computed(() => {
  return correctnessAllPassed.value ? 'eval-check-summary--passed' : 'eval-check-summary--failed'
})

const semanticResult = computed<SemanticEvalResult | null>(() => {
  const allScores = props.detail?.all_scores as Record<string, Record<string, unknown>> | null
  const answerScores = allScores?.answer || props.detail?.scores
  if (!answerScores) return null
  const evaluated = answerScores.semantic_evaluated as boolean | undefined
  if (evaluated === undefined) return null
  return {
    semantic_score: (answerScores.semantic_score as number | null) ?? null,
    semantic_reason: String(answerScores.semantic_reason || ''),
    semantic_evaluated: evaluated,
    semantic_fallback: Boolean(answerScores.semantic_fallback),
    semantic_passed: answerScores.semantic_passed as boolean | null ?? null,
    semantic_threshold: Number(answerScores.semantic_threshold || 0.7),
    eval_duration: (answerScores.eval_duration as number | null) ?? null,
  }
})

const stageTimings = computed<Record<string, number>>(() => {
  return (prediction.value?.stage_timings as Record<string, number>) || {}
})

const detailStatus = computed(() => String(props.detail?.status || 'pending'))

/** 获取步骤耗时，支持多 key 回退。 */
const getStageTiming = (...keys: string[]): number | undefined => {
  const t = stageTimings.value
  for (const k of keys) {
    if (typeof t[k] === 'number' && t[k] > 0) return t[k]
  }
  return undefined
}

const currentIntentLevel = computed(() => {
  return String(
    intentDebug.value.intent_level || traceMeta.value.level || 'L1'
  )
})

const primaryIntentLevel = computed(() => {
  return String(
    intentDebug.value.primary_level
    || routeDebug.value.primary_level
    || traceMeta.value.primary_level
    || currentIntentLevel.value
    || 'L1'
  )
})

const executionPlan = computed<string[]>(() => {
  const plan = routeDebug.value.execution_plan ?? intentDebug.value.execution_plan
  return Array.isArray(plan) ? plan.map(item => String(item)).filter(Boolean) : []
})

const attemptedPaths = computed<AttemptedPathEntry[]>(() => {
  const raw = routeDebug.value.attempted_paths ?? intentDebug.value.attempted_paths
  if (!Array.isArray(raw)) return []
  return raw.map(item => {
    const record = (item as Record<string, unknown>) || {}
    return {
      path: String(record.path || ''),
      status: String(record.status || ''),
      reason: record.reason ? String(record.reason) : '',
      duration: typeof record.duration === 'number' ? record.duration : undefined,
    }
  }).filter(item => item.path)
})

const finalPath = computed(() => {
  return String(routeDebug.value.final_path || intentDebug.value.final_path || '')
})

const fallbackReason = computed(() => {
  return String(routeDebug.value.fallback_reason || intentDebug.value.fallback_reason || '')
})

const hasTieredRouting = computed(() => {
  return executionPlan.value.length > 1 || attemptedPaths.value.length > 1
})

const executionPathLabels: Record<string, string> = {
  casual_chat: 'L0 闲聊直答',
  semantic_retrieval: 'L1 语义检索',
  sql_first: 'L2 条文/SQL',
  standard_sop: 'L3 标准 SOP',
  dynamic_orchestration: 'L4 语义兜底',
}

/** 将 service_mode 路径格式化为可读的层级文案。 */
const formatExecutionPathLabel = (path: string): string => {
  return executionPathLabels[path] || path || '—'
}

/** 将执行计划格式化为首选层级与回退链的摘要文本。 */
const formatExecutionPlanText = (paths: string[]): string => {
  if (!paths.length) return '—'
  return paths.map(path => formatExecutionPathLabel(path)).join(' -> ')
}

/** 将路径尝试状态格式化为前端可读文案。 */
const formatAttemptedStatus = (status: string): string => {
  const labels: Record<string, string> = {
    success: '成功',
    insufficient: '结果不足',
    no_match: '未命中',
    failed: '失败',
    skipped: '跳过',
  }
  return labels[status] || status || '—'
}

/** 用于展示的意图层级：未识别完成时返回空字符串，前端显示"识别中"。 */
const displayIntentLevel = computed(() => {
  const raw = intentDebug.value.intent_level
  return raw || ''
})

/** 格式化意图步骤的展示文本，未识别完成时显示"识别中"。 */
const formatIntentLabel = (): string => {
  const taskType = enrichedQuestion.value.taskTypeLabel || enrichedQuestion.value.task_type
  const level = primaryIntentLevel.value || displayIntentLevel.value
  if (!level) return `${taskType} · 识别中...`
  if (hasTieredRouting.value) return `${taskType} · 首选 ${level}`
  return `${taskType} · ${level}`
}

/** 判断是否为需要展示闲聊直答链路的题目。 */
const isCasualTraceLevel = computed(() => currentIntentLevel.value === 'L0')

/** 判断是否为 L3/L4 的流程执行链路。 */
const isFlowTraceLevel = computed(() => {
  return (
    currentIntentLevel.value === 'L3'
    || currentIntentLevel.value === 'L4'
    || executionPlan.value.some(path => ['standard_sop', 'dynamic_orchestration'].includes(path))
    || attemptedPaths.value.some(item => ['standard_sop', 'dynamic_orchestration'].includes(item.path))
  )
})

const isDynamicFlowLevel = computed(() => {
  return currentIntentLevel.value === 'L4' || finalPath.value === 'dynamic_orchestration'
})

const flowTraceTitle = computed(() => {
  if (hasTieredRouting.value) return '分层尝试链路'
  return String(traceMeta.value.title || (isDynamicFlowLevel.value ? '动态 SOP 执行' : '标准 SOP 执行'))
})

const knowledgeTraceTitle = computed(() => {
  if (hasTieredRouting.value) return '分层尝试链路'
  return String(traceMeta.value.title || (currentIntentLevel.value === 'L2' ? '分析链路（SQL/条款定位）' : '分析链路'))
})

const casualTraceTitle = computed(() => {
  return String(traceMeta.value.title || '闲聊链路')
})

/** 获取 SOP 追踪步骤列表，并插入第0步显示题干已知条件。 */
const sopTraceSteps = computed<SopTraceStep[]>(() => {
  const trace = prediction.value?.sop_trace
  const steps: SopTraceStep[] = Array.isArray(trace) ? [...trace] : []
  const args = routeArgsEntries.value
  if (args.length) {
    const inputs: Record<string, unknown> = {}
    for (const [key, val] of args) {
      inputs[key] = val
    }
    steps.unshift({
      step_id: 'step_0',
      step_name: '已知条件',
      step_index: 0,
      tool: '',
      description: '从题干中提取的已知参数',
      inputs,
      outputs: null,
      duration: 0,
      status: 'success',
      error: null,
    })
  }
  return steps
})

/** 返回真实的 SOP 执行步骤，不包含虚拟的第0步已知条件。 */
const realSopTraceSteps = computed(() => {
  return sopTraceSteps.value.filter(step => step.step_index > 0)
})

// ---- 流程图 SVG 参数 ----
const FLOW_NODE_W = 220
const FLOW_NODE_H = 60
const FLOW_NODE_GAP = 16
const FLOW_CHART_W = 240

const flowChartHeight = computed(() => {
  const n = sopTraceSteps.value.length
  return n > 0 ? n * (FLOW_NODE_H + FLOW_NODE_GAP) : 0
})

const selectedStep = computed(() => {
  if (!selectedStepId.value) return null
  return sopTraceSteps.value.find(s => s.step_id === selectedStepId.value) || null
})

const flowStepColor = (status: string): { border: string; fill: string; dot: string } => {
  const dark = isDark.value
  switch (status) {
    case 'success': return {
      border: dark ? '#49aa19' : '#52c41a',
      fill: dark ? '#162312' : '#f6ffed',
      dot: dark ? '#49aa19' : '#52c41a',
    }
    case 'error': return {
      border: dark ? '#e84749' : '#ff4d4f',
      fill: dark ? '#2a1215' : '#fff2f0',
      dot: dark ? '#e84749' : '#ff4d4f',
    }
    case 'running': return {
      border: dark ? '#177ddc' : '#1890ff',
      fill: dark ? '#111d2c' : '#e6f7ff',
      dot: dark ? '#177ddc' : '#1890ff',
    }
    default: return {
      border: dark ? '#434343' : '#d9d9d9',
      fill: dark ? '#262626' : '#fafafa',
      dot: dark ? '#595959' : '#bfbfbf',
    }
  }
}

const flowStepTextColor = computed(() => isDark.value ? 'rgba(255,255,255,0.85)' : '#262626')
const flowLineColor = computed(() => isDark.value ? '#434343' : '#bfbfbf')

/** 流程图节点 Y 坐标 */
const flowNodeY = (idx: number): number => idx * (FLOW_NODE_H + FLOW_NODE_GAP)

const onFlowNodeClick = (stepId: string) => {
  selectedStepId.value = stepId
}

/** 初始化默认选中第一步实际步骤 */
const initFlowSelection = () => {
  const real = realSopTraceSteps.value
  if (real.length > 0) {
    selectedStepId.value = real[0].step_id
  } else if (sopTraceSteps.value.length > 0) {
    selectedStepId.value = sopTraceSteps.value[0].step_id
  }
}


/** 当 SOP 步骤逐个到达时，自动展开"步骤推进"详情面板，并初始化流程图选中。 */
watch(() => prediction.value?.sop_trace as SopTraceStep[] | undefined, (trace) => {
  const steps = (trace || []).filter((s: SopTraceStep) => s.step_index > 0)
  if (steps.length === 0) {
    prevStepCount.value = 0
    return
  }
  if (steps.length > prevStepCount.value) {
    prevStepCount.value = steps.length
    const next = new Set(expandedSteps.value)
    next.add('flow-steps')
    expandedSteps.value = next
    if (!selectedStepId.value || !steps.find(s => s.step_id === selectedStepId.value)) {
      initFlowSelection()
    }
    return
  }
  prevStepCount.value = steps.length
}, { deep: true })

/** 当用户展开"路径推进"面板时，若流程图未选中则自动初始化。 */
watch(() => expandedSteps.value.has('flow-steps'), (isOpen) => {
  if (isOpen && !selectedStepId.value && sopTraceSteps.value.length > 0) {
    initFlowSelection()
  }
})

const routeCandidates = computed<RouteCandidate[]>(() => {
  const candidates = routeDebug.value.candidates
  return Array.isArray(candidates) ? (candidates as RouteCandidate[]) : []
})

const routeArgsEntries = computed<Array<[string, unknown]>>(() => {
  const args = routeDebug.value.args
  if (!args || Array.isArray(args) || typeof args !== 'object') return []
  return Object.entries(args as Record<string, unknown>)
})

const routeConfidenceText = computed(() => {
  const confidence = routeDebug.value.confidence
  if (typeof confidence === 'number') {
    return `${(confidence * 100).toFixed(1)}%`
  }
  return '—'
})

const answerText = computed(() => String(prediction.value?.answer || ''))

/** 格式化输出值，截断过长的内容 */
const formatOutputVal = (val: unknown): string => {
  if (val === null || val === undefined) return '—'
  const str = typeof val === 'object' ? JSON.stringify(val, null, 2) : String(val)
  return str.length > 2000 ? str.slice(0, 2000) + '\n\n[内容过长，已截断前2000字符。完整内容可通过导出查看]' : str
}

const copyToClipboard = async (text: string) => {
  try {
    await navigator.clipboard.writeText(text)
    message.success('已复制到剪贴板')
  } catch {
    message.error('复制失败')
  }
}

/** 将 markdown/公式文本渲染为可读 HTML。 */
const renderRichText = (content: unknown): string => {
  const text = String(content || '').trim()
  if (!text) return '<p>—</p>'
  return renderMarkdownToHtml(text, '')
}

/** 从回答中提取显式选项，便于生成最终结论摘要。 */
const extractExplicitOption = (text: string): string => {
  const normalizedText = text.replace(/\r\n/g, '\n')
  const lines = normalizedText
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)

  const strongPatterns = [
    /正确答案(?:是|为)?\s*[:：]?\s*[\*\s]*[\(\[]?\s*([A-D])\s*[\)\]]?/i,
    /对应选项(?:是|为)?\s*[:：]?\s*[\*\s]*[\(\[]?\s*([A-D])\s*[\)\]]?/i,
    /答案(?:是|为)?\s*[:：]?\s*[\*\s]*[\(\[]?\s*([A-D])\s*[\)\]]?/i,
    /故选\s*([A-D])/i,
    /因此选\s*([A-D])/i,
    /应选\s*([A-D])/i,
    /选\s*项?\s*[\(\[]?\s*([A-D])\s*[\)\]]?\s*(?:正确|即可|为答案)/i,
  ]

  // 优先从答案末尾往前找“明确结论句式”，避免误命中前面的选项列表。
  for (const line of [...lines].reverse()) {
    if (/对比选项|备选项|选项对比/i.test(line)) continue
    for (const pattern of strongPatterns) {
      const match = line.match(pattern)
      if (match?.[1]) return match[1].toUpperCase()
    }
  }

  // 兜底时只接受“看起来像结论”的单行，不接受包含多个候选项的列表行。
  const fallbackLines = [...lines].reverse().filter(line => {
    const optionTokenCount = (line.match(/[\(\[]\s*[A-D]\s*[\)\]]/gi) || []).length
    if (optionTokenCount > 1) return false
    if (/对比选项|备选项|选项对比/i.test(line)) return false
    return true
  })
  for (const line of fallbackLines) {
    const match = line.match(/\*\*[\(\[]?\s*([A-D])\s*[\)\]]\*\*|[\(\[]\s*([A-D])\s*[\)\]]/)
    const option = match?.[1] || match?.[2]
    if (option) return option.toUpperCase()
  }
  return ''
}

const explicitAnswerOption = computed(() => extractExplicitOption(answerText.value))

const answerHeadline = computed(() => {
  if (explicitAnswerOption.value) {
    return `最终结论：选项 ${explicitAnswerOption.value}`
  }
  const firstLine = answerText.value
    .split('\n')
    .map(line => line.trim())
    .find(Boolean)
  if (!firstLine) return ''
  const normalized = firstLine.replace(/^#+\s*/, '').replace(/\*\*/g, '')
  return normalized.length > 48 ? `${normalized.slice(0, 48)}...` : normalized
})

/** 判断步骤状态是否应视为错误。 */
const isErrorStatus = (status: string) => ['error', 'failed', 'fail'].includes(status)

const knowledgeTraceSteps = computed<ThinkingStep[]>(() => {
  const steps: ThinkingStep[] = []
  const timings = stageTimings.value
  steps.push({
    key: 'knowledge-intent',
    label: '意图识别',
    value: formatIntentLabel(),
    hasDetail: true,
    detailType: 'intent',
    timing: timings['intent'],
  })
  if (citations.value.length) {
    const rd = (prediction.value?.retrieval_debug as Record<string, unknown>) || {}
    const sources = (rd.sources as Record<string, Record<string, unknown>>) || {}
    const denseCount = ((sources.canonical_dense?.input_hits as number) || 0)
    const sparseCount = ((sources.canonical_sparse?.input_hits as number) || 0)
    let tableCount = 0
    for (const key of Object.keys(sources)) {
      if (key.startsWith('table_') || key.startsWith('table')) {
        tableCount += (sources[key]?.input_hits as number) || 0
      }
    }
    const deduped = (rd.deduped_hits as number) || citations.value.length
    steps.push({
      key: 'knowledge-evidence',
      label: currentIntentLevel.value === 'L2' ? 'SQL/条款定位' : '证据检索',
      value: `模糊语义 ${denseCount} 条 | 精确匹配 ${sparseCount} 条 | 表格 ${tableCount} 条 = 去重后 ${deduped} 条`,
      hasDetail: true,
      detailType: 'route',
      timing: timings['retrieval'],
    })
  }
  if (citations.value.length && prediction.value?.answer) {
    const promptTokens = (timings['prompt_tokens'] as number) || 0
    steps.push({
      key: 'knowledge-prompt',
      label: 'Prompt 拼装',
      value: promptTokens ? `${promptTokens} tokens` : 'System Prompt + 问题 + 证据 → LLM',
      hasDetail: true,
      timing: timings['prompt'],
    })
  }
  if (prediction.value?.answer) {
    steps.push({
      key: 'knowledge-answer',
      label: 'LLM 回答',
      value: 'LLM 生成',
      hasDetail: true,
      timing: getStageTiming('llm', 'answer', 'generation'),
    })
  }
  // 渐进展示：评测中时只显示意图步骤，完成后显示全部
  if (props.detail?.status === 'completed') return steps
  if (currentStage.value === 'intent') return steps.slice(0, 1)
  return steps
})

const casualTraceSteps = computed<ThinkingStep[]>(() => {
  const timings = stageTimings.value
  const allSteps: ThinkingStep[] = [
    {
      key: 'casual-intent',
      label: '意图识别',
      value: formatIntentLabel(),
      hasDetail: true,
      detailType: 'intent',
      timing: timings['intent'],
    },
    {
      key: 'casual-direct',
      label: '闲聊直答',
      value: String(traceMeta.value.title || 'casual_chat'),
      hasDetail: false,
      timing: timings['llm'],
    },
    {
      key: 'casual-answer',
      label: '最终回答',
      value: prediction.value?.answer ? 'LLM 生成' : '—',
      hasDetail: true,
      detailType: 'answer',
      timing: getStageTiming('llm', 'answer', 'generation'),
    },
  ]
  // 渐进展示：评测中时只显示意图步骤，完成后显示全部
  if (props.detail?.status === 'completed') return allSteps
  if (currentStage.value === 'intent') return allSteps.slice(0, 1)
  return allSteps
})

/** 计算 SOP 步骤执行总耗时（不含虚拟的第0步）。 */
const sopExecutionTiming = computed(() => {
  const steps = realSopTraceSteps.value
  if (!steps.length) return undefined
  const total = steps.reduce((sum, s) => sum + (s.duration || 0), 0)
  return total || undefined
})

/** 当前评测所处的阶段，用于渐进式展示步骤。 */
const currentStage = computed(() => {
  return (prediction.value?.stage as string) || ''
})

/** 判断流程链路是否已经拿到可展示的 SOP 路由结果。 */
const hasFlowRoute = computed(() => {
  return Boolean(
    executionPlan.value.length
    || attemptedPaths.value.length
    || routeDebug.value.matched_sop_id
    || routeDebug.value.matched_sop_name
    || routeCandidates.value.length
  )
})

const attemptedPathTotalDuration = computed(() => {
  return attemptedPaths.value.reduce((sum, item) => sum + (item.duration || 0), 0)
})

/** 判断流程链路是否已经拿到最终回答。 */
const hasFlowAnswer = computed(() => Boolean(prediction.value?.answer))

/**
 * 基于数据可用性动态计算应展示的步骤数。
 * 比纯 stage 字符串更可靠：即使轮询错过中间回调，
 * 只要数据已写入 DB 就能正确展示对应步骤。
 */
const stageDisplayMax = computed(() => {
  const stage = currentStage.value
  const isCompleted = detailStatus.value === 'completed'

  if (isCompleted) return 5

  if (hasFlowAnswer.value) return 4
  if (realSopTraceSteps.value.length > 0 || attemptedPaths.value.length > 0) return 3
  if (hasFlowRoute.value) return 2

  const idxMap: Record<string, number> = {
    intent: 1,
    route_completed: 2,
    sop_executing: 3,
    answer_generated: 4,
  }
  return idxMap[stage] ?? 1
})

const flowTraceStages = computed<ThinkingStep[]>(() => {
  const timings = stageTimings.value
  const allStages: ThinkingStep[] = [
    {
      key: 'flow-intent',
      label: '意图识别',
      value: formatIntentLabel(),
      hasDetail: true,
      detailType: 'intent',
      timing: timings['intent'],
    },
    {
      key: 'flow-route',
      label: hasTieredRouting.value ? '分层尝试' : 'SOP 路由',
      value: String(
        hasTieredRouting.value
          ? (attemptedPaths.value.length
              ? `${formatExecutionPlanText(executionPlan.value)} | 已尝试 ${attemptedPaths.value.length} 段`
              : formatExecutionPlanText(executionPlan.value))
          : (
              routeDebug.value.matched_sop_name
              || routeDebug.value.matched_sop_id
              || (routeCandidates.value.length ? `候选 ${routeCandidates.value.length} 个` : '已完成')
            )
      ),
      hasDetail: true,
      detailType: 'route',
      timing: getStageTiming('route', 'sop_route', 'sql_first', 'standard_sop', 'dynamic_orchestration', 'semantic_retrieval'),
    },
    {
      key: 'flow-steps',
      label: hasTieredRouting.value ? '路径推进' : '步骤推进',
      value: (() => {
        const realStepCount = realSopTraceSteps.value.length
        if (realStepCount) return `${realStepCount} 步`
        if (attemptedPaths.value.length) return `${attemptedPaths.value.length} 段路径`
        return '暂无步骤追踪'
      })(),
      hasDetail: true,
      detailType: 'steps',
      timing: sopExecutionTiming.value || (attemptedPathTotalDuration.value > 0 ? attemptedPathTotalDuration.value : undefined),
    },
    {
      key: 'flow-answer',
      label: '最终回答',
      value: prediction.value?.answer ? 'LLM 生成' : '—',
      hasDetail: true,
      detailType: 'answer',
      timing: getStageTiming('llm', 'answer', 'generation'),
    },
    {
      key: 'flow-evaluation',
      label: '评测结论',
      value: traceIssues.value.length ? `${traceIssues.value.length} 个诊断问题` : '通过当前链路校验',
      hasDetail: true,
      detailType: 'evaluation',
      timing: semanticResult.value?.eval_duration || getStageTiming('eval', 'evaluation'),
    },
  ]
  return allStages.slice(0, stageDisplayMax.value)
})

const enrichedQuestion = computed(() => {
  const q = { ...props.question } as EvalQuestion & { taskTypeLabel?: string }
  const taskTypeLabels: Record<string, string> = {
    casual_chat: '闲聊',
    definition: '定义查询',
    content_qa: '内容问答',
    locate: '定位查询',
    locate_qa: '定位问答',
    table_explain: '表格解读',
    table_qa: '表格问答',
    table_lookup: '表格查找',
    schema_qa: 'Schema 问答',
    analytic_sql: '分析 SQL',
    sql: 'SQL 查询',
    exam_case: '案例题',
    mixed: '混合题',
  }
  q.taskTypeLabel = taskTypeLabels[q.task_type] || q.task_type
  return q
})

const metaSopPath = computed(() => {
  if (hasTieredRouting.value) {
    return formatExecutionPlanText(executionPlan.value)
  }
  const level = currentIntentLevel.value || 'L1'
  const approachMap: Record<string, string> = {
    L0: '闲聊直答 → 回答（非工程规范问题，不进入检索与 SOP）',
    L1: '语义检索 → 直接回答（基于检索到的规范条文给出定义/组成）',
    L2: '语义检索 → 条款定位 → 回答（定位到具体条款后给出答案）',
    L3: '标准 SOP 执行 → 步骤推进 → 回答（命中预定义 SOP 并执行）',
    L4: '动态 SOP 执行 → 步骤推进 → 回答（通过 LLM 生成临时 SOP 并执行）',
  }
  return approachMap[level] || '—'
})

const systemPromptText = computed(() => {
  return (prediction.value?.system_prompt as string) || ''
})

const fusionSourceLabels: Record<string, string> = {
  canonical_dense: 'Dense',
  canonical_sparse: 'Sparse',
  table_row_key: 'Table-RowKey',
  table_schema: 'Table-Schema',
  table_summary: 'Table-Summary',
  table_text_row: 'Table-TextRow',
  table_mapping: 'Table-Mapping',
  toc_dense: 'TOC-Dense',
  toc_sparse: 'TOC-Sparse',
}

/** 格式化检索来源标签 */
const formatFusionSources = (sources: string[]): string => {
  return sources.map(s => fusionSourceLabels[s] || s).join(' + ')
}

/** 将原始关键词规则整理为更适合前端展示的摘要。 */
const formatCheckRule = (check: CorrectnessDetail): string => {
  if (check.keywords?.length) {
    return `${check.passed ? '通过' : '失败'} / ${check.keywords.join('、')}`
  }
  return check.passed ? '通过' : '失败'
}
</script>

<style lang="less" scoped>
.eval-question-card {
  border: 1px solid var(--border-color);
  border-radius: 6px;
  margin-bottom: 8px;
  transition: all 0.2s;
  background: var(--bg-secondary);

  &:hover {
    border-color: @evals-primary;
  }

  &--expanded {
    border-color: @evals-primary;
  }

  &__header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
  }

  &__id {
    font-size: 12px;
    color: var(--text-secondary);
    flex-shrink: 0;
  }

  &__text {
    flex: 1;
    min-width: 0;
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    cursor: text;
    user-select: text;
  }

  &__text:hover {
    white-space: normal;
    overflow: visible;
    background: var(--bg-secondary);
    z-index: 10;
    position: relative;
  }

  &__edit-form {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  &__edit-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  &__edit-label {
    font-size: 12px;
    color: var(--text-secondary);
    white-space: nowrap;
  }

  &__edit-input {
    font-size: 13px;
    width: 100%;
  }

  &__status {
    flex-shrink: 0;
    white-space: nowrap;
  }

  &__eval-btn {
    flex-shrink: 0;
    padding: 0 4px;
    font-size: 12px;
  }

  &__arrow-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    padding: 0;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
    transition: background-color 0.2s ease, color 0.2s ease;

    &:hover {
      background: var(--bg-tertiary);
      color: var(--text-primary);
    }
  }

  &__arrow {
    transition: transform 0.2s;

    &--expanded {
      transform: rotate(90deg);
    }
  }

  &__body {
    padding: 12px;
    border-top: 1px solid var(--border-color);
  }

  &__editor {
    border: 1px solid var(--border-color);
    border-radius: 6px;
    padding: 10px 12px;
    background: var(--bg-primary);
  }

  &__editor-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 8px;
  }

  &__editor-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }

  &__editor-action {
    font-size: 12px;
  }

  &__editor-content {
    font-size: 13px;
    line-height: 1.7;
    color: var(--text-primary);
    white-space: pre-wrap;
    user-select: text;
  }

  &__loading-state {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
    padding: 10px 12px;
    border-radius: 6px;
    background: fade(@evals-primary, 8%);
    border: 1px solid fade(@evals-primary, 18%);
    color: var(--text-secondary);
    font-size: 12px;
  }

  &__empty {
    margin-top: 12px;
    padding: 12px;
    border-radius: 6px;
    background: var(--bg-tertiary);
    color: var(--text-secondary);
    font-size: 12px;
  }
}

.eval-chain {
  margin-top: 10px;

  &__title {
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 8px;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 6px;
  }

  &__spinner {
    flex-shrink: 0;
  }

  &__step {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 4px 0;
    font-size: 12px;
    line-height: 1.6;
    flex-wrap: wrap;
    align-items: center;
    animation: eval-step-enter 0.3s ease-out both;
  }

  &__badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: @evals-primary;
    color: var(--bg-secondary);
    font-size: 11px;
    flex-shrink: 0;
  }

  &__label {
    font-weight: 500;
    color: var(--text-primary);
    flex-shrink: 0;
  }

  &__value {
    color: var(--text-secondary);
    font-size: 11px;
  }

  &__timing {
    flex-shrink: 0;
    font-size: 11px;
    line-height: 1;
    padding: 0 4px;
    border-radius: 2px;
  }

  &__detail {
    width: 100%;
    margin-left: 24px;
    padding: 8px;
    background: var(--bg-tertiary);
    border-radius: 4px;
    margin-top: 4px;
  }
}

.eval-sop-trace {
  margin-top: 10px;

  &__title {
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 8px;
    color: var(--text-primary);
  }

  &__layout {
    display: flex;
    gap: 12px;
  }

  &__left,
  &__right {
    flex: 1;
    min-width: 0;
  }

  &__col-header {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-secondary);
    padding: 4px 8px;
    border-bottom: 1px solid var(--border-color);
    margin-bottom: 4px;
  }

  &__step-row {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 6px 8px;
    font-size: 12px;
    border-bottom: 1px dashed var(--border-color);
  }

  &__step-index {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: @evals-primary;
    color: var(--bg-secondary);
    font-size: 11px;
    flex-shrink: 0;
  }

  &__step-name {
    font-weight: 500;
    color: var(--text-primary);
  }

  &__step-desc {
    color: var(--text-secondary);
    font-size: 11px;
    margin-left: 4px;
  }

  &__exec-row {
    padding: 6px 8px;
    font-size: 12px;
    border-bottom: 1px dashed var(--border-color);

    &--success {
      border-left: 2px solid var(--chat-success-color, #52c41a);
    }

    &--error {
      border-left: 2px solid var(--chat-error-color);
    }

    &--pending {
      border-left: 2px solid var(--text-secondary);
    }
  }

  &__exec-status {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  &__status-icon {
    font-size: 12px;
    font-weight: 700;

    &--success {
      color: var(--chat-success-color, #52c41a);
    }

    &--error {
      color: var(--chat-error-color);
    }

    &--pending {
      color: var(--text-secondary);
    }
  }

  &__tool-name {
    color: @evals-primary;
    font-size: 11px;
  }

  &__duration {
    font-size: 11px;
    line-height: 1;
    padding: 0 4px;
    border-radius: 2px;
    margin-left: auto;
  }

  &__outputs {
    margin-top: 4px;
    padding: 4px 8px;
    background: var(--bg-tertiary);
    border-radius: 4px;
  }

  &__output-item {
    display: flex;
    gap: 4px;
    font-size: 11px;
    padding: 2px 0;
  }

  &__output-key {
    color: var(--text-secondary);
    flex-shrink: 0;
  }

  &__output-val {
    color: var(--text-primary);
    word-break: break-all;
    max-height: 200px;
    overflow-y: auto;
  }

  &__error {
    margin-top: 4px;
    color: var(--chat-error-color);
    font-size: 11px;
  }
}

.eval-detail-row {
  display: flex;
  gap: 8px;
  font-size: 12px;
  padding: 2px 0;
}

.eval-detail-label {
  color: var(--text-secondary);
  flex-shrink: 0;
  min-width: 60px;
}

.eval-detail-empty {
  font-size: 12px;
  color: var(--text-secondary);
  font-style: italic;
}

.eval-detail-block {
  margin-top: 8px;
}

.eval-answer-summary {
  margin-bottom: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid fade(@evals-primary, 25%);
  background: fade(@evals-primary, 8%);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
}

.eval-rich-text {
  color: inherit;
  line-height: 1.7;
  word-break: break-word;

  &--compact {
    font-size: 12px;
  }

  &--answer {
    font-size: 12px;
  }

  :deep(p) {
    margin: 0 0 10px;
  }

  :deep(p:last-child) {
    margin-bottom: 0;
  }

  :deep(h1),
  :deep(h2),
  :deep(h3),
  :deep(h4) {
    margin: 12px 0 8px;
    font-size: 13px;
    line-height: 1.5;
    font-weight: 600;
  }

  :deep(ul),
  :deep(ol) {
    margin: 8px 0 8px 18px;
    padding: 0;
  }

  :deep(li) {
    margin: 4px 0;
  }

  :deep(strong) {
    font-weight: 700;
  }

  :deep(code) {
    padding: 1px 4px;
    border-radius: 4px;
    background: var(--bg-tertiary);
    font-family: Consolas, 'Courier New', monospace;
    font-size: 11px;
  }

  :deep(pre) {
    margin: 8px 0;
    padding: 10px;
    border-radius: 6px;
    background: var(--bg-tertiary);
    overflow-x: auto;
  }

  :deep(pre code) {
    padding: 0;
    background: transparent;
  }

  :deep(blockquote) {
    margin: 8px 0;
    padding-left: 10px;
    border-left: 3px solid fade(@evals-primary, 35%);
    color: var(--text-secondary);
  }

  :deep(table) {
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0;
    font-size: 12px;
  }

  :deep(th),
  :deep(td) {
    padding: 6px 8px;
    border: 1px solid #c0c0c0;
    text-align: left;
    vertical-align: top;
  }

  :deep(th) {
    background: var(--bg-tertiary);
  }

  :deep(.katex-display) {
    margin: 8px 0;
    overflow-x: auto;
    overflow-y: hidden;
  }
}

.eval-flow-chart-layout {
  display: flex;
  gap: 16px;
  min-height: 300px;
}

.eval-flow-chart {
  flex: 0 0 240px;
  overflow-y: auto;
  max-height: 520px;
  padding-right: 4px;

  &__svg {
    display: block;
  }
}

.eval-flow-chart-node {
  cursor: pointer;
  transition: stroke-width 0.15s ease;

  &:hover {
    filter: brightness(0.96);
  }
}

.eval-flow-chart-detail {
  flex: 1;
  min-width: 0;
  padding-left: 16px;
  border-left: 1px solid var(--border-color);
  overflow-y: auto;
  max-height: 520px;

  &__header {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 8px;
  }

  &__desc {
    margin-bottom: 8px;
    color: var(--text-secondary);
    font-size: 12px;
    line-height: 1.5;
    padding: 6px 8px;
    background: var(--bg-tertiary);
    border-radius: 4px;
  }
}

.eval-known-params-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  margin-top: 4px;

  th, td {
    padding: 5px 8px;
    border: 1px solid #c0c0c0;
    text-align: left;
    vertical-align: top;
  }

  th {
    background: var(--bg-tertiary);
    font-weight: 600;
    color: var(--text-secondary);
    white-space: nowrap;
  }

  .eval-param-key {
    white-space: nowrap;
    font-weight: 500;
    color: var(--text-secondary);
    width: 30%;
  }
}

.eval-field-item {
  border: 1px solid #c0c0c0;
  border-radius: 4px;
  padding: 4px 8px;
  font-size: 12px;
}

.eval-field-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 4px;
}

.eval-field-key {
  display: inline-block;
  font-weight: 600;
  color: var(--text-secondary);
  margin-right: 8px;
  min-width: 80px;
  white-space: nowrap;
}

.eval-field-json {
  margin: 4px 0 0 0;
  padding: 4px 8px;
  font-size: 11px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}

.eval-flow-steps {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.eval-flow-step-card {
  padding: 8px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-secondary);
  animation: eval-step-enter 0.3s ease-out both;

  &--success {
    border-color: fade(#52c41a, 35%);
  }

  &--error {
    border-color: fade(@evals-error, 40%);
  }

  &__header {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  &__index {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: @evals-primary;
    color: var(--bg-secondary);
    font-size: 11px;
    flex-shrink: 0;
  }

  &__name {
    font-weight: 600;
    color: var(--text-primary);
  }

  &__tool {
    color: @evals-primary;
    font-size: 11px;
    padding: 0 6px;
    background: fade(@evals-primary, 10%);
    border-radius: 10px;
  }

  &__duration {
    font-size: 11px;
    line-height: 1;
    padding: 0 4px;
    border-radius: 2px;
  }

  &__desc {
    margin-top: 6px;
    color: var(--text-secondary);
    font-size: 12px;
    line-height: 1.5;
  }

  &__error {
    margin-top: 6px;
    color: var(--chat-error-color);
    font-size: 12px;
  }

  &__detail {
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px dashed var(--border-color);
  }
}

.eval-retrieval-scores {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed var(--border-color);
}

.eval-citation-card {
  padding: 6px 8px;
  margin-bottom: 4px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  font-size: 12px;
}

.eval-citation-meta {
  display: flex;
  gap: 8px;
  align-items: center;
}

.eval-citation-index {
  color: @evals-primary;
  font-weight: 600;
}

.eval-matched-sop {
  color: var(--chat-success-color, #52c41a);
  font-weight: 600;
}

.eval-citation-score {
  color: var(--text-secondary);
}

.eval-citation-source {
  color: @evals-primary;
  font-size: 11px;
  margin-left: auto;
}

.eval-citation-location {
  color: var(--text-secondary);
  font-family: 'KaiTi', 'STKaiti', serif;
  margin-top: 2px;
}

.eval-citation-section {
  color: var(--text-secondary);
  font-family: 'KaiTi', 'STKaiti', serif;
  margin-top: 2px;
}

.eval-citation-content {
  color: var(--text-primary);
  font-size: 13px;
  margin-top: 4px;
  line-height: 1.5;
  max-height: 300px;
  overflow-y: auto;
}

.eval-prompt-block {
  margin-bottom: 8px;
}

.eval-prompt-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.eval-prompt-text {
  font-size: 12px;
  line-height: 1.6;
  padding: 6px 8px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  max-height: 400px;
  overflow-y: auto;
}

.eval-prompt-citation {
  font-size: 12px;
  padding: 4px 8px;
  margin-bottom: 2px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  line-height: 1.5;
}

.eval-thinking-block {
  margin-bottom: 8px;
}

.eval-thinking-text {
  font-size: 12px;
  line-height: 1.6;
  padding: 6px 8px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  max-height: 400px;
  overflow-y: auto;
  white-space: pre-wrap;
}

.eval-section {
  margin-top: 12px;

  &__title {
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 6px;
    color: var(--text-primary);
  }

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 6px;
  }

  &--error {
    color: @evals-error;
    font-size: 12px;
  }
}

.eval-check-summary {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  line-height: 1.6;
  padding: 8px 10px;
  border-radius: 6px;

  &--passed {
    background: fade(#52c41a, 8%);
    border: 1px solid fade(#52c41a, 20%);
    color: var(--chat-success-color, #52c41a);
  }

  &--failed {
    background: fade(@evals-error, 8%);
    border: 1px solid fade(@evals-error, 20%);
    color: var(--chat-error-color);
  }
}

.eval-check-icon {
  font-weight: 700;
}

.eval-check-rules {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.eval-check-rule {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
}

.eval-check-type {
  font-weight: 500;
  min-width: 84px;
  color: var(--text-primary);
}

.eval-check-keywords {
  color: var(--text-secondary);
}

.eval-semantic-header {
  display: flex;
  align-items: center;
}

.eval-semantic-header .eval-section__title {
  flex: 1;
}

.eval-semantic-score {
  font-weight: 600;

  &--passed {
    color: var(--chat-success-color, #52c41a);
  }

  &--failed {
    color: var(--chat-error-color);
  }

  &--fallback {
    color: @evals-warning;
  }
}

.eval-semantic-threshold {
  color: var(--text-secondary);
  font-size: 11px;
}

.eval-semantic-reason {
  margin-top: 4px;
  color: var(--text-secondary);
}

.eval-semantic-fallback-hint {
  margin-top: 4px;
  color: @evals-warning;
  font-size: 11px;
}

.eval-score-grid {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.eval-score-item {
  display: flex;
  gap: 6px;
  font-size: 12px;

  &--na {
    color: var(--text-secondary);
  }
}

.eval-score-label {
  color: var(--text-secondary);
}

.eval-score-value {
  font-weight: 500;
}

.eval-comparison {
  display: flex;
  gap: 12px;

  &__col {
    flex: 1;
  }

  &__label {
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary);
    margin-bottom: 4px;
  }

  &__content {
    font-size: 12px;
    line-height: 1.6;
    padding: 8px;
    background: var(--bg-tertiary);
    border-radius: 4px;
    max-height: 400px;
    overflow-y: auto;
  }
}

.eval-thinking-gold {
  font-size: 12px;
  line-height: 1.6;
  padding: 8px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  max-height: 400px;
  overflow-y: auto;
  white-space: pre-wrap;
}

.eval-sql-debug {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed var(--border-color);
}

.eval-sql-code {
  margin: 4px 0;
  padding: 8px;
  background: #1e1e1e;
  color: #d4d4d4;
  border-radius: 4px;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.eval-sql-success {
  color: var(--chat-success-color, #52c41a);
  font-weight: 600;
}

.eval-sql-fail {
  color: var(--chat-error-color);
  font-weight: 600;
}

.eval-sql-score {
  color: var(--text-secondary);
  margin-left: 8px;
}

.eval-sql-error {
  margin-top: 4px;
  padding: 6px 8px;
  background: rgba(255, 77, 79, 0.08);
  border: 1px solid rgba(255, 77, 79, 0.2);
  border-radius: 4px;
  color: var(--chat-error-color);
  font-size: 12px;
  font-family: Consolas, 'Courier New', monospace;
}

@keyframes eval-step-enter {
  from {
    opacity: 0;
    transform: translateY(-6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>

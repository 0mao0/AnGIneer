<template>
  <div class="dc-workspace" :class="appClass">
    <SplitPanes class="workspace-container"
      :initial-left-ratio="0.16" :left-min-ratio="0.14" :left-max-ratio="0.25"
      :initial-right-ratio="0.30" :right-min-ratio="0.22" :right-max-ratio="0.42"
      left-collapsible right-collapsible>

      <!-- ═══ 左栏：报告榜 ═══ -->
      <template #left>
        <Panel title="报告" :icon="h(HistoryOutlined)">
          <template #actions>
            <a-button size="small" type="primary" :loading="running"
              :disabled="systemStatus && !systemStatus.enabled" @click="handleTriggerRun">
              <PlayCircleOutlined /> 运行
            </a-button>
          </template>
          <div v-if="systemStatus" class="dc-meta"><ClockCircleOutlined /> 上次：{{ systemStatus.last_run || '无' }}</div>
          <div class="dc-list">
            <div v-if="!loadingReports && !reports.length" class="dc-guide-sm"><a-empty><template #description>暂无报告</template></a-empty></div>
            <div v-for="r in reports" :key="r.date" class="dc-litem"
              :class="{on:r.date===selectedDate}" @click="selectReport(r.date)">
              <div class="dc-lih">
                <CalendarOutlined /><span>{{ r.date }}</span>
                <a-tag v-if="r.total_findings" color="orange" size="small">{{ r.total_findings }}项</a-tag>
              </div>
              <div class="dc-lim"><span>{{ r.run_duration_seconds.toFixed(1) }}s</span><span>{{ r.total_auto_fixed?'修复'+r.total_auto_fixed:r.total_findings?'待处理':'正常' }}</span></div>
            </div>
          </div>
        </Panel>
      </template>

      <!-- ═══ 中栏：总览 + 任务列表 ═══ -->
      <template #center>
        <Panel :title="selectedDate?selectedDate+' 报告':'健康检查'" :icon="h(selectedDate?FileTextOutlined:MedicineBoxOutlined)">
          <div v-if="!selectedDate&&!loadingDetail&&!reportDetail" class="dc-center-guide">
            <MedicineBoxOutlined class="dc-guide-icon" />
            <h3>知识库健康检查</h3>
            <p>选择左侧报告或点击运行</p>
            <a-button type="primary" :loading="running" @click="handleTriggerRun"><PlayCircleOutlined /> 立即运行</a-button>
          </div>
          <div v-else-if="loadingDetail" class="dc-center-guide"><a-spin size="large" /><p style="margin-top:8px">加载中...</p></div>
          <div v-else-if="reportDetail" class="dc-ov">
            <div class="dc-ovrow">
              <div class="dc-ovc"><div class="dc-ovv primary">{{ reportDetail.total_findings }}</div><div class="dc-ovl">问题</div></div>
              <div class="dc-ovc"><div class="dc-ovv green">{{ reportDetail.total_auto_fixed }}</div><div class="dc-ovl">修复</div></div>
              <div class="dc-ovc"><div class="dc-ovv">{{ reportDetail.run_duration_seconds.toFixed(1) }}s</div><div class="dc-ovl">耗时</div></div>
            </div>
            <div class="dc-ovsec">检查项目</div>
            <div v-for="t in reportDetail.task_results" :key="t.task_name" class="dc-tc"
              :class="{focus: focusTask===t.task_name}" @click="pickTask(t.task_name)">
              <div class="dc-tch">
                <span class="dc-dot" :class="'d'+t.status" />
                <span class="dc-tcn">{{ t.task_name }}</span>
                <a-tag size="small" :color="TASK_STATUS_COLOR[t.status] || 'default'">
                  {{ TASK_STATUS_LABEL[t.status] || t.status }}
                </a-tag>
              </div>
              <div class="dc-tcm">{{ t.message }}</div>
              <div class="dc-tcf">
                <template v-if="t.task_name==='实体去重检查'">
                  {{ pendingDedupCount() }} 项待处理 · {{ taskCount(t.task_name) - pendingDedupCount() }} 项已处理
                </template>
                <template v-else>
                  {{ taskCount(t.task_name) }} 项发现
                </template>
                · {{ t.duration_seconds.toFixed(1) }}s
              </div>
            </div>
          </div>
          <div v-else class="dc-center-guide"><a-empty description="报告不可用"><template #extra><a-button size="small" @click="loadReports">刷新</a-button></template></a-empty></div>
        </Panel>
      </template>

      <!-- ═══ 右栏：任务详情 ═══ -->
      <template #right>
        <Panel :title="focusTask||'详情'" :icon="h(focusTask?FileTextOutlined:InfoCircleOutlined)">
          <div v-if="!focusTask||!reportDetail" class="dc-rg"><a-empty description="选择检查项目查看详情" /></div>

          <!-- 实体去重 -->
          <div v-else-if="focusTask==='实体去重检查'" class="dc-rb">
            <div class="dc-rh">{{ reportDetail.duplicate_candidates.length }} 对疑似重复</div>
            <div v-if="!reportDetail.duplicate_candidates.length" class="dc-rempty"><a-empty description="无发现" /></div>
            <div v-for="(d,idx) in reportDetail.duplicate_candidates" :key="idx" class="dd-card">
              <div class="dd-top">
                <div class="dd-meta">
                  <span class="dd-tag" :class="dedupTagColor(d)">{{ dedupTagText(d) }}</span>
                  <span class="dd-method">{{ DEDUP_METHOD_LABEL[d.match_method] || d.match_method }}</span>
                </div>
                <div class="dd-sim">
                  <div class="dd-simtrack">
                    <div class="dd-simfill" :style="{width:(d.confidence*100)+'%'}" />
                  </div>
                  <span class="dd-simval">{{ (d.confidence*100).toFixed(0) }}%</span>
                </div>
              </div>
              <div class="dd-pair">
                <div class="dd-ent">{{ d.entity_a_name }}</div>
                <div class="dd-vs"><ArrowRightOutlined /></div>
                <div class="dd-ent dd-ent-merge">{{ d.entity_b_name }}</div>
              </div>
              <div v-if="d.suggested_canonical_name" class="dd-canon">建议统一为 <strong>{{ d.suggested_canonical_name }}</strong></div>
              <div v-if="dedupDone(dkey(d))" class="dd-bot">
                <span class="dd-stamp" :class="dedupDone(dkey(d))==='merged'?'s-ok':'s-no'">{{ dedupDone(dkey(d))==='merged'?'已合并':'已驳回' }}</span>
                <a-button size="small" type="link" class="dd-undo" @click="dedupUndo(dkey(d))">撤销</a-button>
              </div>
              <div v-else-if="d.suggested_action==='review'" class="dd-bot">
                <a-button size="small" class="dd-btn" @click="doMerge(d)">合并</a-button>
                <a-button size="small" class="dd-btn" @click="doDismiss(d)">误报</a-button>
              </div>
            </div>
          </div>

          <!-- 矛盾 -->
          <div v-else-if="focusTask==='矛盾关系检测'" class="dc-rb">
            <div class="dc-rh">{{ reportDetail.contradiction_candidates.length }} 处矛盾</div>
            <div v-if="!reportDetail.contradiction_candidates.length" class="dc-rempty"><a-empty description="无发现" /></div>
            <div v-for="(c,idx) in reportDetail.contradiction_candidates" :key="idx" class="dc-rc dc-rcwarn">
              <div class="dc-rcsubj"><WarningOutlined /> <strong>{{ c.entity_subject }}</strong> → <strong>{{ c.entity_object||'?' }}</strong></div>
              <div class="dc-rcdoc"><small>A</small> {{ c.relation_a.source_doc }}<br><span class="dc-rctype">{{ c.relation_a.relation_type }}</span></div>
              <div v-if="c.relation_a.evidence" class="dc-evi">{{ c.relation_a.evidence }}</div>
              <div class="dc-rcdoc"><small>B</small> {{ c.relation_b.source_doc }}<br><span class="dc-rctype">{{ c.relation_b.relation_type }}</span></div>
              <div v-if="c.relation_b.evidence" class="dc-evi">{{ c.relation_b.evidence }}</div>
              <div class="dc-rchint">{{ c.suggested_resolution }}</div>
            </div>
          </div>

          <!-- 孤立 -->
          <div v-else-if="focusTask==='孤立实体清理'" class="dc-rb">
            <div class="dc-rh">{{ reportDetail.orphan_entities.length }} 个孤立实体</div>
            <div v-if="!reportDetail.orphan_entities.length" class="dc-rempty"><a-empty description="无发现" /></div>
            <div v-for="o in reportDetail.orphan_entities" :key="o.entity_id" class="dc-rc">
              <div class="dc-rctop">
                <a-tag size="small" :color="o.suggested_action==='auto_mark_inactive'?'default':'orange'">
                  {{ o.suggested_action==='auto_mark_inactive'?'已标记':'待确认' }}
                </a-tag>
                <span class="dc-rcpct">存在 {{ o.age_days }} 天</span>
              </div>
              <div class="dc-rcpair"><span class="dc-rcent">{{ o.entity_name }}</span></div>
              <div class="dc-rcname">层级：{{ o.entity_layer }}</div>
              <div v-if="orphanDone(o.entity_id)" class="dc-rcbot right">
                <span class="dc-stamp" :class="orphanDone(o.entity_id)==='kept'?'sg':'so'">
                  {{ orphanDone(o.entity_id)==='kept'?'已保留':'已清理' }}
                </span>
                <a-button size="small" type="link" @click="orphanUndo(o.entity_id)">撤销</a-button>
              </div>
              <div v-else-if="o.suggested_action==='review'" class="dc-rcbot right">
                <a-button size="small" type="primary" ghost @click="doOrphanKeep(o)">保留</a-button>
                <a-button size="small" @click="doOrphanDelete(o)">确认清理</a-button>
              </div>
            </div>
          </div>

          <!-- 过期 -->
          <div v-else-if="focusTask==='过期知识标记'" class="dc-rb">
            <div class="dc-rh">{{ reportDetail.staleness_candidates.length }} 条过时</div>
            <div v-if="!reportDetail.staleness_candidates.length" class="dc-rempty"><a-empty description="无发现" /></div>
            <div v-for="(s,idx) in reportDetail.staleness_candidates" :key="idx" class="dc-rc dc-rcwarn">
              <div class="dc-rctop"><a-tag color="warning" size="small">待确认</a-tag></div>
              <div class="dc-rcpair"><span class="dc-rcent">{{ s.entity_name }}</span></div>
              <div class="dc-rcdoc">{{ s.source_doc_title }} → {{ s.superseded_by_doc_title }}</div>
            </div>
          </div>

          <!-- SOP -->
          <div v-else-if="focusTask==='SOP 健康统计'" class="dc-rb">
            <div v-if="reportDetail.sop_health" class="dc-sop">
              <div class="dc-soprow">
                <div class="dc-sopb"><div class="dc-sopv">{{ reportDetail.sop_health.total_sops }}</div><div class="dc-sopl">总数</div></div>
                <div class="dc-sopb"><div class="dc-sopv">{{ reportDetail.sop_health.active_sops }}</div><div class="dc-sopl">活跃</div></div>
                <div class="dc-sopb"><div class="dc-sopv">{{ reportDetail.sop_health.total_steps||'-' }}</div><div class="dc-sopl">步骤</div></div>
              </div>
              <div v-if="reportDetail.sop_health.most_used_sop" class="dc-findmeta">常用：{{ reportDetail.sop_health.most_used_sop }}</div>
            </div>
            <div v-else class="dc-rempty"><a-empty description="无数据" /></div>
          </div>
        </Panel>
      </template>
    </SplitPanes>
  </div>
</template>

<script setup lang="ts">
import { h, ref, reactive, onMounted } from 'vue'
import { message, Modal } from 'ant-design-vue'
import {
  HistoryOutlined, PlayCircleOutlined, CalendarOutlined, FileTextOutlined,
  MedicineBoxOutlined, ClockCircleOutlined, ArrowRightOutlined,
  WarningOutlined, InfoCircleOutlined,
} from '@ant-design/icons-vue'
import { SplitPanes, Panel, useTheme } from '@angineer/ui-kit'
import { dreamCycleApi, DuplicateCandidate } from '../api/dreamCycle'

const { appClass } = useTheme()

const loadingReports = ref(false)
const loadingDetail = ref(false)
const running = ref(false)
const reports = ref<any[]>([])
const selectedDate = ref('')
const reportDetail = ref<any>(null)
const systemStatus = ref<any>(null)
const focusTask = ref('')

const TASK_STATUS_COLOR: Record<string, string> = {
  success: 'green',
  warning: 'orange',
  error: 'red',
  skipped: 'default',
}
const TASK_STATUS_LABEL: Record<string, string> = {
  success: '成功',
  warning: '警告',
  error: '失败',
  skipped: '跳过',
}
const DEDUP_METHOD_LABEL: Record<string, string> = {
  edit_distance: '编辑相似',
  alias_overlap: '别名重合',
  llm_semantic: '语义匹配',
}

const dedupState = reactive<Record<string,string>>({})
const dkey = (d:DuplicateCandidate)=>`${d.entity_a_id}::${d.entity_b_id}`
const dedupDone = (k:string)=>dedupState[k]||''
const dedupUndo = (k:string)=>{delete dedupState[k]}
const pendingDedupCount = ()=>reportDetail.value?.duplicate_candidates?.filter((d:DuplicateCandidate)=>!dedupState[dkey(d)]&&d.suggested_action==='review').length||0
const dedupTagColor = (d:DuplicateCandidate)=>dedupDone(dkey(d))?(dedupDone(dkey(d))==='merged'?'t-ok':'t-no'):d.suggested_action==='auto_merge'?'t-ok':'t-pending'
const dedupTagText = (d:DuplicateCandidate)=>{
  if(dedupDone(dkey(d))) return dedupDone(dkey(d))==='merged'?'已合并':'已驳回'
  return d.suggested_action==='auto_merge'?'已自动合并':'待确认'
}

// 孤立实体操作状态
const orphanState = reactive<Record<string,string>>({})
const orphanDone = (id:string)=>orphanState[id]||''
const orphanUndo = (id:string)=>{delete orphanState[id]}

const taskCount = (name:string)=>{
  if(!reportDetail.value) return 0
  switch(name){
    case '实体去重检查': return reportDetail.value.duplicate_candidates?.length||0
    case '矛盾关系检测': return reportDetail.value.contradiction_candidates?.length||0
    case '孤立实体清理': return reportDetail.value.orphan_entities?.length||0
    case '过期知识标记': return reportDetail.value.staleness_candidates?.length||0
    default: return 0
  }
}

const pickTask = (name:string)=>{ focusTask.value = focusTask.value===name ? '' : name }

const loadReports = async()=>{
  loadingReports.value=true
  try{ const d=await dreamCycleApi.listReports(30); reports.value=d.reports
    if(d.reports.length&&!selectedDate.value) selectReport(d.reports[0].date)
  }catch{}
  finally{loadingReports.value=false}
}
const loadHealth=async()=>{try{systemStatus.value=await dreamCycleApi.health()}catch{}}

const selectReport=async(date:string)=>{
  selectedDate.value=date; focusTask.value=''; loadingDetail.value=true; reportDetail.value=null
  try{
    reportDetail.value=await dreamCycleApi.getReport(date)
    const first=reportDetail.value?.task_results?.find((t:any)=>taskCount(t.task_name)>0)
    if(first) focusTask.value=first.task_name
  }catch(e:any){
    const s=e?.response?.status,m=e?.response?.data?.detail||e?.message||''
    if(s===404) message.info(`尚未生成（${m}）`)
    else{message.error(`[${s||'?'}] ${m||'加载失败'}`);selectedDate.value=''}
  }finally{loadingDetail.value=false}
}

const handleTriggerRun=async()=>{
  running.value=true; selectedDate.value=''; reportDetail.value=null
  try{
    await dreamCycleApi.triggerRun(); message.success('已启动...')
    let n=0; const iv=setInterval(async()=>{
      n++; await loadReports(); await loadHealth()
      const t=new Date().toISOString().split('T')[0]
      if(reports.value.some((r:any)=>r.date===t)){clearInterval(iv);message.success('完成！')}
      else if(n>=40){clearInterval(iv);message.warning('超时，请刷新')}
    },3000)
  }catch{message.error('触发失败')}
  finally{running.value=false}
}

const doMerge=(d:DuplicateCandidate)=>{
  Modal.confirm({title:'合并',content:`「${d.entity_b_name}」→「${d.entity_a_name}」？`,
    okText:'合并',cancelText:'取消',
    onOk:async()=>{
      try{const r=await dreamCycleApi.confirmMerge(d.entity_a_id,d.entity_b_id,d.suggested_canonical_name)
        dedupState[dkey(d)]='merged'; message.success(r.message||'已合并')
      }catch(e:any){message.error(e?.response?.data?.detail||e?.message||'')}
    }
  })
}
const doDismiss=(d:DuplicateCandidate)=>{
  Modal.confirm({title:'误报',content:`「${d.entity_a_name}」与「${d.entity_b_name}」不重复？`,
    okText:'确认',cancelText:'取消',
    onOk:async()=>{
      try{const r=await dreamCycleApi.dismissDedup(d.entity_a_id,d.entity_b_id)
        dedupState[dkey(d)]='dismissed'; message.success(r.message||'已标记')
      }catch(e:any){message.error(e?.response?.data?.detail||e?.message||'')}
    }
  })
}

// ── 孤立实体操作 ──
const doOrphanKeep=(o:any)=>{
  Modal.confirm({title:'保留',content:`确认「${o.entity_name}」不是孤立实体？`,
    okText:'保留',cancelText:'取消',
    onOk:async()=>{
      try{await dreamCycleApi.orphanKeep(o.entity_id); orphanState[o.entity_id]='kept'; message.success('已保留')
      }catch(e:any){message.error(e?.response?.data?.detail||e?.message||'')}
    }
  })
}
const doOrphanDelete=(o:any)=>{
  Modal.confirm({title:'清理',content:`将「${o.entity_name}」标记为不活跃？`,
    okText:'清理',cancelText:'取消',
    onOk:async()=>{
      try{await dreamCycleApi.orphanConfirmDelete(o.entity_id); orphanState[o.entity_id]='deleted'; message.success('已清理')
      }catch(e:any){message.error(e?.response?.data?.detail||e?.message||'')}
    }
  })
}

onMounted(()=>{loadHealth();loadReports()})
</script>

<style lang="less" scoped>
.dc-workspace{height:100%;background:var(--bg-primary)}
.workspace-container{height:100%}

/* 左栏 */
.dc-meta{padding:4px 14px;font-size:11px;color:var(--text-secondary)}
.dc-list{padding:2px 0}
.dc-guide-sm{padding:40px 0}
.dc-litem{padding:7px 14px;cursor:pointer;border-bottom:1px solid var(--border-color);transition:.12s}
.dc-litem:hover{background:var(--bg-hover,rgba(0,0,0,.03))}
.dc-litem.on{background:var(--primary-color-fade,rgba(24,144,255,.08));border-left:3px solid var(--primary-color,#1677ff)}
.dc-lih{display:flex;align-items:center;gap:4px;font-size:13px;font-weight:600;color:var(--text-primary)}
.dc-lih .finding-badge{margin-left:auto}
.dc-lim{display:flex;justify-content:space-between;margin-top:2px;font-size:11px;color:var(--text-secondary)}

/* 中栏引导 */
.dc-center-guide{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;padding:24px;text-align:center}
.dc-guide-icon{font-size:48px;color:var(--primary-color,#1677ff);margin-bottom:12px}
.dc-center-guide h3{font-size:18px;font-weight:600;color:var(--text-primary);margin:0 0 6px}
.dc-center-guide p{font-size:13px;color:var(--text-secondary);margin-bottom:20px}
.dc-center-load{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:12px;color:var(--text-secondary)}

/* 中栏总览 */
.dc-ov{padding:12px 14px;overflow-y:auto;height:100%}
.dc-ovrow{display:flex;gap:10px;margin-bottom:16px}
.dc-ovc{flex:1;text-align:center;padding:10px 6px;border-radius:8px;background:var(--bg-secondary,rgba(0,0,0,.02));border:1px solid var(--border-color)}
.dc-ovv{font-size:22px;font-weight:700;line-height:1.2}
.dc-ovv.primary{color:var(--primary-color,#1677ff)}
.dc-ovv.green{color:#52c41a}
.dc-ovl{font-size:11px;color:var(--text-secondary);margin-top:2px}
.dc-ovsec{font-size:12px;font-weight:600;color:var(--text-secondary);margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid var(--border-color);text-transform:uppercase;letter-spacing:.04em}

/* 任务卡片（中栏） */
.dc-tc{padding:8px 10px;margin-bottom:6px;border-radius:6px;border:1px solid var(--border-color);cursor:pointer;transition:.15s}
.dc-tc:hover{border-color:var(--primary-color,#1677ff);background:var(--primary-color-fade,rgba(24,144,255,.03))}
.dc-tc.focus{border-color:var(--primary-color,#1677ff);background:var(--primary-color-fade,rgba(24,144,255,.06))}
.dc-tch{display:flex;align-items:center;gap:5px}
.dc-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.d-dot-success{background:#52c41a}.d-dot-warning{background:#fa8c16}.d-dot-error{background:#ff4d4f}.d-dot-skipped{background:#d9d9d9}
.dc-tcn{font-size:13px;font-weight:600;color:var(--text-primary);flex:1}
.dc-tcm{font-size:11px;color:var(--text-secondary);margin-top:2px;padding-left:12px}
.dc-tcf{font-size:11px;color:var(--primary-color,#1677ff);margin-top:3px;padding-left:12px}

/* 右栏 */
.dc-rg{display:flex;align-items:center;justify-content:center;height:100%}
.dc-rb{padding:10px 12px;overflow-y:auto;height:100%}
.dc-rh{font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--border-color)}
.dc-rempty{padding:32px 0}

/* 右栏卡片 */
.dc-rc{border-radius:6px;border:1px solid var(--border-color);padding:10px;margin-bottom:7px;background:var(--bg-secondary,rgba(0,0,0,.02));transition:.12s}
.dc-rc:hover{border-color:var(--primary-color,#1677ff);box-shadow:0 1px 4px rgba(0,0,0,.04)}
.dc-rcwarn{border-left:3px solid #fa8c16}.dc-rcwarn:hover{border-color:#fa8c16;border-left-color:#fa8c16}
.dc-rctop{display:flex;align-items:center;gap:6px;margin-bottom:6px}
.dc-rcpct{margin-left:auto;font-size:12px;font-weight:600;color:var(--text-primary)}
.dc-rcmatch{font-size:11px;color:var(--text-secondary)}
.dc-rcpair{display:flex;align-items:center;gap:6px;margin-bottom:4px}
.dc-rcent{font-family:'SF Mono','Cascadia Code',monospace;font-size:13px;font-weight:600;color:var(--text-primary);background:var(--bg-tertiary,rgba(0,0,0,.04));padding:2px 6px;border-radius:4px;max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dc-rcarrow{font-size:11px;color:var(--text-secondary);flex-shrink:0}
.dc-rcname{font-size:12px;color:var(--text-secondary);margin-top:2px}

/* 实体去重卡片（专属样式） */
.dd-card{border-radius:6px;border:1px solid var(--border-color);padding:10px;margin-bottom:7px;background:var(--bg-secondary,rgba(0,0,0,.02));transition:all .15s}
.dd-card:hover{border-color:var(--primary-color,#1677ff)}
.dd-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;gap:6px}
.dd-meta{display:flex;align-items:center;gap:4px}
.dd-tag{display:inline-flex;align-items:center;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:600;line-height:1.6}
.dd-tag.t-pending{background:var(--primary-color-fade,rgba(24,144,255,.1));color:var(--primary-color,#1677ff)}
.dd-tag.t-ok{color:var(--text-secondary)}
.dd-tag.t-no{color:var(--text-secondary)}
.dd-method{font-size:11px;color:var(--text-tertiary,rgba(255,255,255,.35))}
.dd-sim{display:flex;align-items:center;gap:4px}
.dd-simtrack{width:48px;height:3px;border-radius:2px;background:var(--border-color);overflow:hidden}
.dd-simfill{height:100%;border-radius:2px;background:var(--primary-color,#1677ff)}
.dd-simval{font-size:11px;font-weight:600;color:var(--text-secondary);min-width:28px;text-align:right}
.dd-pair{display:flex;align-items:center;gap:6px;margin-bottom:6px;background:var(--bg-tertiary,rgba(0,0,0,.04));border-radius:4px;padding:4px}
.dd-ent{flex:1;font-size:13px;font-weight:600;color:var(--text-primary);padding:5px 8px;line-height:1.3;text-align:center}
.dd-ent-merge{opacity:.65}
.dd-vs{flex-shrink:0;width:24px;height:24px;display:flex;align-items:center;justify-content:center;border-radius:50%;color:var(--text-tertiary,rgba(255,255,255,.35));font-size:11px}
.dd-canon{font-size:11px;color:var(--text-secondary);margin-bottom:6px;padding:4px 8px}
.dd-canon strong{color:var(--text-primary)}
.dd-bot{display:flex;align-items:center;justify-content:flex-end;gap:4px;padding-top:6px;border-top:1px solid var(--border-color)}
.dd-btn{height:26px;padding:0 10px;border-radius:4px;font-size:11px;font-weight:500;border:1px solid var(--border-color);background:transparent;cursor:pointer;transition:all .12s;color:var(--text-secondary);font-family:inherit}
.dd-btn:hover{border-color:var(--primary-color,#1677ff);color:var(--primary-color,#1677ff)}
.dd-stamp{display:inline-flex;align-items:center;gap:3px;padding:0 6px;border-radius:3px;font-size:11px;font-weight:600;line-height:1.6}
.dd-stamp.s-ok{color:var(--text-secondary)}
.dd-stamp.s-no{color:var(--text-secondary)}
.dd-undo{font-size:11px;color:var(--text-tertiary,rgba(255,255,255,.35))}
.dc-rcdoc{font-size:12px;color:var(--text-primary);padding:3px 6px;margin:2px 0;background:var(--bg-tertiary,rgba(0,0,0,.03));border-radius:4px;line-height:1.5}
.dc-rcdoc small{display:inline-block;width:14px;height:14px;line-height:14px;text-align:center;border-radius:3px;background:var(--primary-color,#1677ff);color:#fff;font-size:10px;font-weight:700;margin-right:4px}
.dc-rcwarn .dc-rcdoc small{background:#fa8c16}
.dc-rctype{font-size:11px;color:var(--text-secondary);padding-left:18px}
.dc-rcsubj{font-size:13px;color:var(--text-primary);margin-bottom:6px}
.dc-evi{font-size:12px;color:var(--text-primary);padding:6px 8px;margin:4px 0;background:var(--bg-secondary,rgba(0,0,0,.04));border-radius:4px;line-height:1.6;border-left:2px solid var(--primary-color,#1677ff);word-break:break-all}
.dc-rchint{font-size:11px;color:var(--text-secondary);margin-top:6px;padding:4px 6px;background:rgba(250,140,22,.06);border-radius:4px}
.dc-rcbot{display:flex;align-items:center;gap:6px;margin-top:6px;padding-top:6px;border-top:1px dashed var(--border-color)}
.dc-rcbot.right{justify-content:flex-end}

/* 印章 */
.dc-stamp{display:inline-flex;align-items:center;padding:0 8px;border-radius:3px;font-size:11px;font-weight:700;letter-spacing:.08em;border:2px solid;line-height:1.6}
.dc-stamp.sg{color:#52c41a;border-color:#52c41a;background:rgba(82,196,26,.06)}
.dc-stamp.so{color:#fa8c16;border-color:#fa8c16;background:rgba(250,140,22,.06)}

/* SOP */
.dc-soprow{display:flex;gap:10px;margin-bottom:8px}
.dc-sopb{flex:1;text-align:center;padding:10px;border-radius:6px;background:var(--bg-secondary,rgba(0,0,0,.02))}
.dc-sopv{font-size:20px;font-weight:700;color:var(--text-primary)}
.dc-sopl{font-size:11px;color:var(--text-secondary);margin-top:2px}
</style>

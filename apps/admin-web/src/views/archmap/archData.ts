/**
 * 对话全链路架构图数据：节点 / 边 / 问题清单（纯静态，锚点均为源码 file:line）
 * 布局：纵向两大主线——上=后端逻辑（主轴直下，意图分级横向扇出 L0/L1/L2/L3·L4 四列，
 *       底部汇入共享循环与守卫），下=前端展示；SSE 总线是两侧唯一的连接点。
 *       左侧外挂评测注入链（answer_format 口子）：评测调用方→注入槽→汇入意图分级装配。
 * 状态语义：ok=现役正常 warn=有隐患 gap=缺失 planned=◇待新建
 */

export type NodeStatus = 'ok' | 'warn' | 'gap' | 'planned'

export interface ArchNodeData {
  label: string
  sub?: string
  status: NodeStatus
  summary: string
  details: string[]
  anchors: string[]
  problems?: string[]
  [key: string]: unknown
}

export interface ArchNode {
  id: string
  type: 'arch' | 'lane' | 'bus'
  position: { x: number; y: number }
  data: ArchNodeData
  draggable: boolean
  selectable: boolean
  connectable: boolean
}

export interface ArchEdge {
  id: string
  source: string
  target: string
  label?: string
  kind: 'flow' | 'loop' | 'sse' | 'sse-broken' | 'planned'
  sourceHandle?: string
  targetHandle?: string
}

export interface ArchProblem {
  id: string
  title: string
  severity: 'high' | 'mid' | 'low'
  desc: string
  anchors: string[]
  nodeIds: string[]
}

const N = (
  id: string,
  x: number,
  y: number,
  data: ArchNodeData
): ArchNode => ({
  id,
  type: 'arch',
  position: { x, y },
  data,
  draggable: false,
  selectable: true,
  connectable: false
})

const LANE = (id: string, x: number, y: number, label: string): ArchNode => ({
  id,
  type: 'lane',
  position: { x, y },
  data: { label, status: 'ok', summary: '', details: [], anchors: [] },
  draggable: false,
  selectable: false,
  connectable: false
})

const BUS = (id: string, x: number, y: number, data: ArchNodeData): ArchNode => ({
  id,
  type: 'bus',
  position: { x, y },
  data,
  draggable: false,
  selectable: true,
  connectable: false
})

const CX = 720 // 主轴中线 x（与四列意图线区域的中点对齐）

export const ARCH_NODES: ArchNode[] = [
  LANE('lane-back', 660, 480, '后端逻辑'),
  LANE('lane-front', 1680, 350, '前端展示'),

  // ── 后端主轴：入口 → 闸门 → 路由 → 意图分级 ──────────────────
  N('n-user', CX, 0, {
    label: '用户提问',
    sub: 'POST /api/chat/agent',
    status: 'ok',
    summary: 'SSE 流式入口，一切从这里开始',
    details: ['FastAPI 端点，SSE 逐帧下发', 'agent run 在线程池执行，asyncio.Queue 泵成 SSE 帧'],
    anchors: ['services/aichat-api/main.py:406', 'services/aichat-api/main.py:592']
  }),
  N('n-gate', CX, 110, {
    label: '接入闸门',
    sub: '游客轮闸 + 库级授权',
    status: 'ok',
    summary: '两道硬闸：配额与越权都在进循环前挡掉',
    details: [
      '游客 30 轮硬闸（ANGINEER_GUEST_ROUNDS），超限 403 login_required',
      'enforce_bound_libraries：按用户绑定库过滤，匿名只进默认库'
    ],
    anchors: ['services/aichat-api/chat_auth.py:207', 'services/aichat-api/chat_auth.py:116']
  }),
  N('n-route', CX, 220, {
    label: '路由层',
    sub: '分类 ∥ 赌博式预检',
    status: 'ok',
    summary: '意图分类与「赌 L1」预检索并行起跑，命中则检索段移出关键路径',
    details: [
      'IntentClassifier：规则快路（命中即返回）→ LLM 主力 → 规则兜底 → 显式降 L1；失败留痕不静默',
      '预检 daemon 线程按主路同参数（top_k=20, rerank=True）先跑 knowledge_search',
      '跳过：短问有上文 / 表题必输局（ANGINEER_SPECULATIVE_SKIP_TABLE）/ 总闸关',
      '结果挂检索 memo（TTL 120s），主路撞在途会按预算等待'
    ],
    anchors: [
      'services/aichat-api/route_pre.py:43',
      'services/angineer-core/src/angineer_core/classifier.py:869',
      'services/angineer-core/src/angineer_core/agent_tools.py:392'
    ]
  }),
  N('n-level', CX, 330, {
    label: '意图分级',
    sub: '横向扇出四条执行线',
    status: 'ok',
    summary: 'L0–L4 五级意图映射为分段执行计划（AttemptMachine），按级走四条线',
    details: [
      'L0 闲聊：直接对话档，无工具强制',
      'L1 语义检索：QA 档 + force_first_search=knowledge_search',
      'L2 结构化查表：段1 table_search → 失败回退 L1 线',
      'L3 标准计算 / L4 动态编排：complex 档（max_turns=8）+ sop_execute 工具'
    ],
    anchors: ['services/angineer-core/src/angineer_core/agent_policy.py:123', 'services/angineer-core/src/angineer_core/classifier.py:60']
  }),

  // ── 评测侧注入链（answer_format 口子，左侧外挂）──────────────
  N('n-eval', 30, 110, {
    label: '评测调用方',
    sub: 'POST /api/evals/runs · answer_format',
    status: 'ok',
    summary: '评测请求体可带一条「答案收尾形态」注入句；聊天线无此参数',
    details: [
      'StartEvalRunRequest.answer_format 可选，evals_routes 透传进 runner',
      'suite_runner 铺到每题；manifest 留痕 {enabled, text}，缺留痕判实验无效',
      'OfficeQA §7.7 注入实验首用：旁证口径 15.0%/24.1% vs 对照 12.8%/14.3%'
    ],
    anchors: [
      'services/aichat-api/evals_routes.py:272',
      'services/evals-core/src/evals_core/contracts.py:67',
      'services/evals-core/src/evals_core/runner/suite_runner.py:722'
    ]
  }),
  N('n-afslot', 30, 220, {
    label: '答案格式注入槽',
    sub: 'None＝提示词逐字节不变',
    status: 'ok',
    summary: '核心装配链的可选空位：仅评测调用方传参，非空才追加进系统提示词',
    details: [
      '穿线：run_eval_query → run_policy_query → build_attempts → build_qa/complex_config',
      '终端消费：system_prompt += 换行 + 注入句（QA 档与 L3 复杂档各一处）',
      '默认 None 时提示词逐字节不变（8 条回归测锁形态）；每题 prediction 留痕',
      'L0 聊天线永不携带；生产生效随下次发版'
    ],
    anchors: [
      'services/angineer-core/src/angineer_core/agent_configs.py:507',
      'services/angineer-core/src/angineer_core/agent_configs.py:809',
      'services/angineer-core/src/angineer_core/agent_policy.py:136'
    ]
  }),
  N('n-afprod', 30, 330, {
    label: '◇ 注入口子对外产品化',
    sub: 'HTTP 暴露 / 发包 / 模板约束（未拍板）',
    status: 'planned',
    summary: '待产品决策：把评测侧口子升级为客户可自定义答案格式的产品能力',
    details: [
      'HTTP chat 路由有意不暴露该参数（防提示词注入面外扩）',
      '外部应用当前只能以函数签名调 angineer-core（该包未上 PyPI）',
      '产品化三件：HTTP 暴露评估、angineer-core 打包发版、注入面收敛（模板约束）'
    ],
    anchors: ['docs/plan-officeqa-arms.md §7.7']
  }),

  // ── 四列意图线（y 自上而下）────────────────────────────────
  N('n-l0', 30, 450, {
    label: 'L0 线 · 闲聊',
    sub: '无工具，直接作答',
    status: 'ok',
    summary: '不携带检索工具，LLM 直接生成回答',
    details: ['对话档预算与提示词（chat 档）', '无强制检索、无证据守卫强制项'],
    anchors: ['services/angineer-core/src/angineer_core/agent_policy.py:145']
  }),

  N('n-inject', 330, 450, {
    label: 'L1 线 · 首轮强检注入',
    sub: 'memo 复用预检',
    status: 'ok',
    summary: '段首：后端自己先跑一次检索，省掉「空首轮」往返',
    details: [
      '注入 assistant(tool_calls) + tool(结果) 两条消息进消息列表',
      'memo 命中则零延迟复用预检结果；未中现场检索；失败不注入',
      '跟进式短问先经 _contextualize_followup_query 改写'
    ],
    anchors: ['services/angineer-core/src/angineer_core/agent_loop.py:1293']
  }),
  N('n-ks', 330, 560, {
    label: 'knowledge_search',
    sub: '文本检索 top_k=20 · doc_ids 显式回看',
    status: 'ok',
    summary: '知识库正文检索主入口；HTTP（docs-api）优先，本地端口兜底',
    details: [
      'QA 档注入 top_k=20、rerank=True',
      '先走 ANGINEER_DOCS_API_URL，失败回退本地 ports.get_knowledge_local_search()',
      'doc_ids 入参对 LLM 开放（2026-10-06）：压缩摘要行里的 doc 指针可据此回看原文（显式 inspect）'
    ],
    anchors: ['services/angineer-core/src/angineer_core/agent_tools.py:907', 'services/angineer-core/src/angineer_core/agent_tools.py:719']
  }),
  N('n-pipe', 330, 670, {
    label: '检索管线',
    sub: '4路召回 → 加权RRF → rerank',
    status: 'ok',
    summary: 'dense/sparse/clause 常驻 + formula/table 条件触发，加权 RRF 融合后 rerank 截 top15',
    details: [
      'dense：embedding→qdrant（拉取上限 top_k×8）；sparse：FTS5/BM25（扇出 24 文档）',
      'clause：条款号直达（基础分 12.0 压过稀疏）；formula/table 按查询特征触发',
      '融合：RRF(1/(60+rank))×源权重+任务加成，跨源同 key 累加，去目录块截 20',
      'rerank：在线 reranker → LLM 二排（可选）→ phrase 兜底，截 ANGINEER_CONTEXT_TOP_N=15'
    ],
    anchors: [
      'services/docs-core/src/docs_core/step09_query/agent_port.py:38',
      'services/docs-core/src/docs_core/step09_query/retrieval/hybrid_retriever.py:182',
      'services/angineer-core/src/angineer_core/retrieval_pipeline.py:394'
    ]
  }),
  N('n-table', 330, 780, {
    label: '上桌处理',
    sub: '判官 / cite / 标签 / 软帽',
    status: 'ok',
    summary: 'rerank 后 top15 过 LLM 上桌判官，再打引用标记、相关性标签、体积软帽',
    details: [
      '上桌判官（默认 oversize 模式，est>90k 才启用）：LLM 批量 0/1，判 0 且 rerank<0.3 丢弃',
      'cite 标记 K1.. + 《文档名》前缀；相关性标签（高/中/低）注入 text 头部',
      '体积软帽 80k est：按 rank 装填，装不下截尾或整条丢',
      '空桌 → 走标准拒答，不回退'
    ],
    anchors: [
      'services/angineer-core/src/angineer_core/agent_tools.py:802',
      'services/angineer-core/src/angineer_core/agent_tools.py:100',
      'services/angineer-core/src/angineer_core/agent_tools.py:43'
    ]
  }),

  N('n-ts', 630, 450, {
    label: 'L2 线 · table_search',
    sub: '表格/公式两路',
    status: 'ok',
    summary: 'TableRetriever + FormulaRetriever 按 table_qa 融合；不上桌判官只过硬帽',
    details: ['prefix=T；L2 意图的首选工具', '段1 失败时回退到 L1 线（AttemptMachine 分段）'],
    anchors: ['services/angineer-core/src/angineer_core/agent_tools.py:985', 'services/docs-core/src/docs_core/step09_query/agent_port.py:165']
  }),
  N('n-es', 630, 560, {
    label: 'entity_search',
    sub: 'KG 实体直查',
    status: 'ok',
    summary: '知识图谱实体/关系直查；无命中自动回退正文检索（prefix=E）',
    details: ['GraphStore.search_entities，KG_DB_PATH 可配'],
    anchors: ['services/angineer-core/src/angineer_core/agent_tools.py:1076', 'services/docs-core/src/docs_core/step09_query/agent_port.py:237']
  }),

  N('n-sop', 930, 450, {
    label: 'L3/L4 线 · sop_execute',
    sub: 'complex 档专属工具',
    status: 'ok',
    summary: '把「sop_query + 参数」路由到已发布 SOP 并执行',
    details: ['仅 published 状态对路由可见', '结果：final_context（变量黑板）+ sop_trace + citations'],
    anchors: ['services/angineer-core/src/angineer_core/agent_tools.py:1257']
  }),
  N('n-soproute', 930, 560, {
    label: 'SOP 路由',
    sub: 'TF-IDF 粗筛 → LLM 精排',
    status: 'gap',
    summary: '字符 bigram TF-IDF 粗筛 top5，LLM 精排+拒绝+抽参；未命中只回 error',
    details: [
      '零命中时 fallback 全量 SOP 再排；置信度低于阈值拒路由',
      '⚠ 未命中路径只返回「未匹配到合适的 SOP」，无生成 fallback'
    ],
    anchors: ['services/angineer-core/src/angineer_core/classifier.py:995', 'services/angineer-core/src/angineer_core/agent_tools.py:1287'],
    problems: ['P1']
  }),
  N('n-runner', 930, 670, {
    label: 'SopRunner',
    sub: '线性执行 + 变量黑板',
    status: 'warn',
    summary: '逐步执行 SOP，步骤变量落 Memory.blackboard（单次 run 生命周期）',
    details: [
      '支持 smart 步骤（LLM 选工具）、conditional 分支工具、ask_user',
      '⚠ 注释明写「Simple linear execution for now」：不遍历 next_step_id 图',
      '执行日志写 markdown；record_run 记统计'
    ],
    anchors: ['services/angineer-core/src/angineer_core/sop_runner.py:186', 'services/angineer-core/src/angineer_core/sop_runner.py:46'],
    problems: ['P5']
  }),
  N('n-gen', 1200, 560, {
    label: '◇ 生成实时 SOP',
    sub: 'topk 证据 → LLM 生成',
    status: 'planned',
    summary: '待新建：SOP 未命中时用本轮检索证据 + 问题生成实时 SOP，本轮立即跑通',
    details: [
      '复用 generate-from-doc 的 LLM 生成套路（sop_path_generator.py:384）',
      'save_generated_sop() 校验+落盘+刷索引，现成挂载点（当前零调用方）',
      '只对 L3/L4 生效；生成与回答可并行（复用赌博式预检模式）'
    ],
    anchors: ['services/aichat-api/sop_routes.py:820', 'services/sop-core/src/sop_core/sop_loader.py:338'],
    problems: ['P1']
  }),
  N('n-draft', 1200, 670, {
    label: '◇ draft → 人审',
    sub: '待审核模块（待开发）',
    status: 'planned',
    summary: '生成的 SOP 落 draft 进待审核队列，人审后 published，下次同类问题直接命中',
    details: [
      'draft→review→published 契约已存在；待审核 UI 模块待独立开发',
      '生成物直接进 published = 模型自写自批，闸门必须保留（论文「人审收件箱」模式）'
    ],
    anchors: ['services/aichat-api/sop_routes.py:575', 'services/aichat-api/sop_routes.py:603']
  }),

  // ── 主轴共享收尾：循环 → 守卫 → 落库 ────────────────────────
  N('n-loop', CX, 900, {
    label: 'Agent 循环',
    sub: 'LLM流式 ⇄ 工具批 · 压缩留 doc 指针可回看',
    status: 'warn',
    summary: '所有意图线最终都跑进同一个手写循环：预算压缩 → LLM 流式 → 工具批 → 下一轮',
    details: [
      'max_turns 轮预算；steer 用户插话在轮边界汇入；cancel 在轮边界/等待点检查（工具线程执行中打不断）',
      '预算压缩：est 超档时最老 tool 消息压成一行（投影式，落库不受影响）；est>120k 优雅停（仅 complex 档接线，QA/L0 无停止线）',
      '压缩摘要保留 doc 指针（K号·文档名·doc_id，2026-10-06），模型可用 doc_ids 回看原文',
      'ANGINEER_EAGER_COMPRESS（默认关）：每轮即压跨 run 证据，不等阈值——指针回看让损失可回收',
      '工具批：jsonschema 校验 → 并行执行（声明 sequential 的转串行），超时 120s/工具',
      'DeltaFenceFilter：```tool_calls 围栏在出口前截掉，永不外泄',
      '⚠ 回看是语义重检索（rerank 可能挤掉当轮条目），非 VISTA 式确定性回放——回放通道待建'
    ],
    anchors: [
      'services/angineer-core/src/angineer_core/agent_loop.py:1369',
      'services/angineer-core/src/angineer_core/agent_loop.py:676',
      'services/angineer-core/src/angineer_core/agent_loop.py:48',
      'services/angineer-core/src/angineer_core/agent_configs.py:547',
      'services/angineer-core/src/angineer_core/agent_configs.py:839'
    ],
    problems: ['P4']
  }),
  N('n-guard', CX, 1010, {
    label: '终答守卫',
    sub: '拒答策略 + 重试/代检索',
    status: 'ok',
    summary: 'LLM 给出终答后逐条判：无证据/外引/半拒答都会被改写；拒答有两道保险',
    details: [
      '工具错误 JSON 冒充答案 / 证据全空 → 替换拒答话术',
      '引用证据外规范编号（has_unsupported_reference）→ 替换拒答',
      '半拒答只剥开头保正文；模型自己拒答则保留原文',
      '保险一：硬拒答可重试时换路再答一轮（refusal_retry）',
      '保险二：本段要求工具却始终未调且重试耗尽 → 系统代执行 knowledge_search 再答一轮（不判是否拒答；注释与代码口径不一致）',
      '拒答话术：「没有检索到足够证据支持最终结论…」可挂追问'
    ],
    anchors: [
      'services/angineer-core/src/angineer_core/agent_configs.py:151',
      'services/angineer-core/src/angineer_core/agent_messages.py:12',
      'services/angineer-core/src/angineer_core/agent_loop.py:1090',
      'services/angineer-core/src/angineer_core/agent_loop.py:1115'
    ]
  }),
  N('n-end', CX, 1120, {
    label: 'run_end 落库',
    sub: 'chat.sqlite（未压缩原文）',
    status: 'ok',
    summary: '本轮增量切片落库；预算压缩是投影式，库里永远存原文',
    details: [
      'run_meta：run_id/model/latency/status/scene/library_ids',
      '客户端断开按 cancelled 兜底补写；初始化失败降级纯内存池',
      '游客 30 轮闸 / 90 天保留期 GC（scripts/chat_db_gc.py）'
    ],
    anchors: ['services/aichat-api/main.py:604', 'services/chat-history/src/chat_history/store/sqlite_store.py:229']
  }),

  // ── SSE 总线：纵向贯通条，左侧收后端各环节帧，右侧顶部发给前端 ──
  BUS('n-bus', 1450, 220, {
    label: 'SSE 总线',
    sub: 'stage 首帧 · route_debug 紧随 · 伴随全程',
    status: 'warn',
    summary: 'POST 响应体本身就是这条流：首帧 stage:classify（分类起算），route_debug 紧随（route_pre 开时），末帧 run_end——前后端并行，后端边跑边推、前端边收边渲染',
    details: [
      '路由/分类 → stage:classify（无条件首帧）→ route_debug（route_pre 开时紧随）；循环每轮 → turn_start',
      'LLM 生成 → message_delta；工具调用 → tool_start / tool_end；守卫改写 → answer；收尾 → run_end（末帧）',
      '⚠ route_debug（route_pre.py:177 已发）前端无分支丢弃——「走了哪条线」不可见',
      '⚠ turn_end 帧同样无处理分支'
    ],
    anchors: ['services/aichat-api/main.py:592', 'services/aichat-api/route_pre.py:177'],
    problems: ['P3']
  }),

  // ── 前端主轴（右列，与后端路由层同高度起跑 = 并行）───────────
  N('n-transport', 1750, 220, {
    label: 'chatTransport',
    sub: 'SSE 按行解析（唯一客户端）',
    status: 'warn',
    summary: 'fetch 流式读取（非 EventSource），逐帧分发到四个渲染区',
    details: [
      '只认 data: 前缀逐行 JSON.parse；未匹配的帧类型静默丢弃',
      '⚠ steer 端点（main.py:687）前端零调用：插队=abort 当前 run 后重新 POST',
      'cleanStreamText 二次过滤围栏（双保险）'
    ],
    anchors: ['apps/shared/chatTransport.ts:40', 'apps/shared/chatTransport.ts:101', 'apps/shared/chatTransport.ts:374'],
    problems: ['P6']
  }),
  N('n-state', 1750, 340, {
    label: 'useAIChat',
    sub: '50ms 合帧 + 会话池',
    status: 'ok',
    summary: '状态层：合帧缓冲、待发送队列、历史加载',
    details: [
      '历史加载剔除 tool 角色与 tool_calls 形态的内部消息',
      'run_end 的 msg_seqs 回写展示字段（citations/thinking_trace）'
    ],
    anchors: ['packages/aichat-ui/src/composables/useAIChat.ts:433']
  }),
  N('n-render', 1750, 460, {
    label: '聊天渲染',
    sub: '气泡 / 思考轨迹 / 引用圆标',
    status: 'warn',
    summary: '三段阶段文案 + 流式气泡 + 思考轨迹折叠卡 + [K1] 数字圆标',
    details: [
      'spinner：意图理解…/检索规范库…/生成回答…（带秒数）',
      '引用：hover 预览（CitationPopover）→ 点击打开右侧溯源面板',
      '⚠ sop_trace 只渲染一行字「SOP x 执行 N 步」，无步骤图'
    ],
    anchors: [
      'packages/aichat-ui/src/components/BaseChat.vue:86',
      'apps/shared/chatTransport.ts:563'
    ],
    problems: ['P2']
  }),
  N('n-doc', 1750, 580, {
    label: '溯源面板',
    sub: 'DocumentView 55% 右栏',
    status: 'ok',
    summary: '点击引用圆标打开原文：PDF 按页跳+bbox 高亮，md 按章节定位',
    details: ['多库按 marker→target→doc 回填 library_id'],
    anchors: ['apps/user-web/src/views/DocumentView.vue:98', 'packages/docs-ui/src/composables/useKnowledgeCitation.ts:204']
  }),
  N('n-graphb', 2020, 460, {
    label: '◇ 图 B：SOP 步骤图',
    sub: 'SOPFlowCanvas 进聊天页',
    status: 'planned',
    summary: '待接线：实时/命中 SOP 的步骤图直接在对话里渲染（图 B 落点）',
    details: [
      'SOPFlowCanvas（vue-flow）现成，admin 经验库已在用',
      'user-web 已声明 @angineer/sop-ui 依赖但 src 零 import——接入无需新画布依赖',
      'product-chat-layout-v2.svg 设计稿已存在；缺 SSE 帧携带 SOP 结构 + ChatHome 挂载'
    ],
    anchors: ['packages/sop-ui/src/components/SOPFlowCanvas.vue:155', 'docs/graphs/product-chat-layout-v2.svg'],
    problems: ['P2', 'P7']
  })
]

// 句柄约定（ArchNode 四向不可见句柄）：source: s-b/s-t/s-l/s-r，target: t-t/t-b/t-l/t-r
export const ARCH_EDGES: ArchEdge[] = [
  // 后端主轴
  { id: 'e1', source: 'n-user', target: 'n-gate', kind: 'flow' },
  { id: 'e2', source: 'n-gate', target: 'n-route', kind: 'flow' },
  { id: 'e3', source: 'n-route', target: 'n-level', label: 'RouteDecision', kind: 'flow' },

  // 意图四分线（横向扇出）
  { id: 'e4', source: 'n-level', target: 'n-l0', label: 'L0 闲聊', kind: 'flow' },
  { id: 'e5', source: 'n-level', target: 'n-inject', label: 'L1 语义检索', kind: 'flow' },
  { id: 'e6', source: 'n-level', target: 'n-ts', label: 'L2 查表', kind: 'flow' },
  { id: 'e7', source: 'n-level', target: 'n-sop', label: 'L3/L4 SOP', kind: 'flow' },

  // L1 线（直下）
  { id: 'e8', source: 'n-inject', target: 'n-ks', kind: 'flow' },
  { id: 'e9', source: 'n-ks', target: 'n-pipe', kind: 'flow' },
  { id: 'e10', source: 'n-pipe', target: 'n-table', label: 'top15', kind: 'flow' },

  // L2 线
  { id: 'e11', source: 'n-ts', target: 'n-es', kind: 'flow' },
  { id: 'e12', source: 'n-ts', target: 'n-inject', label: '失败回退 L1', kind: 'loop', sourceHandle: 's-l', targetHandle: 't-r' },

  // L3/L4 线
  { id: 'e13', source: 'n-sop', target: 'n-soproute', kind: 'flow' },
  { id: 'e14', source: 'n-soproute', target: 'n-runner', label: '命中 published', kind: 'flow' },
  { id: 'e15', source: 'n-soproute', target: 'n-gen', label: '未命中 ◇', kind: 'planned', sourceHandle: 's-r', targetHandle: 't-l' },
  { id: 'e16', source: 'n-gen', target: 'n-runner', label: '本轮即跑 ◇', kind: 'planned' },
  { id: 'e17', source: 'n-gen', target: 'n-draft', label: '落 draft ◇', kind: 'planned' },

  // 四线汇入共享循环 → 守卫 → 落库
  { id: 'e18', source: 'n-l0', target: 'n-loop', kind: 'flow' },
  { id: 'e19', source: 'n-table', target: 'n-loop', kind: 'flow' },
  { id: 'e20', source: 'n-es', target: 'n-loop', kind: 'flow' },
  { id: 'e21', source: 'n-runner', target: 'n-loop', kind: 'flow' },
  { id: 'e22', source: 'n-loop', target: 'n-guard', label: '终答', kind: 'flow' },
  { id: 'e23', source: 'n-guard', target: 'n-loop', label: '拒答重试/代检索', kind: 'loop', sourceHandle: 's-r', targetHandle: 't-r' },
  { id: 'e24', source: 'n-guard', target: 'n-end', label: '放行', kind: 'flow' },

  // SSE 总线：后端各环节横向推帧入总线（并行，非串行等待），总线顶部发给前端
  { id: 'e25a', source: 'n-route', target: 'n-bus', label: 'stage（首帧）· route_debug', kind: 'sse', sourceHandle: 's-r', targetHandle: 't-l1' },
  { id: 'e25b', source: 'n-loop', target: 'n-bus', label: 'turn_start · message_delta · tool_start/end', kind: 'sse', sourceHandle: 's-r', targetHandle: 't-l2' },
  { id: 'e25c', source: 'n-guard', target: 'n-bus', label: 'answer', kind: 'sse', sourceHandle: 's-r', targetHandle: 't-l3' },
  { id: 'e25d', source: 'n-end', target: 'n-bus', label: 'run_end（末帧）', kind: 'sse', sourceHandle: 's-r', targetHandle: 't-l4' },
  { id: 'e26', source: 'n-bus', target: 'n-transport', label: '逐帧分发', kind: 'sse', sourceHandle: 's-r', targetHandle: 't-l' },

  // 前端主轴（直下）
  { id: 'e27', source: 'n-transport', target: 'n-state', kind: 'flow' },
  { id: 'e28', source: 'n-state', target: 'n-render', kind: 'flow' },
  { id: 'e29', source: 'n-render', target: 'n-doc', label: '点引用', kind: 'flow' },
  { id: 'e30', source: 'n-render', target: 'n-graphb', label: '◇ sop 结构帧', kind: 'planned', sourceHandle: 's-r', targetHandle: 't-l' },

  // 评测注入链：调用方→槽→汇入意图分级装配；◇ 为待产品化
  { id: 'e31', source: 'n-eval', target: 'n-afslot', label: '穿线', kind: 'flow' },
  { id: 'e32', source: 'n-afslot', target: 'n-level', label: '注入 system prompt', kind: 'flow', sourceHandle: 's-r', targetHandle: 't-l' },
  { id: 'e33', source: 'n-afslot', target: 'n-afprod', label: '◇ 产品化', kind: 'planned' }
]

export const ARCH_PROBLEMS: ArchProblem[] = [
  {
    id: 'P1',
    title: 'sop_execute 未命中无 fallback',
    severity: 'high',
    desc: '未命中只返回 error 文案（agent_tools.py:1304）。已定方案：topk 证据+问题 → LLM 生成实时 SOP → 本轮即跑 → 落 draft 进待审核（模块待开发）→ 人审后 published。',
    anchors: ['services/angineer-core/src/angineer_core/agent_tools.py:1304', 'services/sop-core/src/sop_core/sop_loader.py:338'],
    nodeIds: ['n-soproute', 'n-gen', 'n-draft']
  },
  {
    id: 'P2',
    title: 'SOP 在聊天里只有一行字',
    severity: 'high',
    desc: 'sop_trace 被压成「SOP x 执行 N 步」摘要（chatTransport.ts:563）。图 B 渲染缺三样：SSE 帧带 SOP 结构、ChatHome 挂 SOPFlowCanvas、路由帧喂「走了哪条线」。',
    anchors: ['apps/shared/chatTransport.ts:563'],
    nodeIds: ['n-render', 'n-graphb']
  },
  {
    id: 'P3',
    title: 'route_debug 帧前端丢弃',
    severity: 'mid',
    desc: '后端 route_pre.py:177 发 route_debug（route_pre 开时紧随 stage:classify），前端 transport 无分支——「这题走了哪条线」用户不可见；接上即可服务图 B 的路径展示。',
    anchors: ['services/aichat-api/route_pre.py:177', 'apps/shared/chatTransport.ts:101'],
    nodeIds: ['n-bus']
  },
  {
    id: 'P4',
    title: '证据压缩丢指针（已缓解，余回放档位差）',
    severity: 'low',
    desc: '2026-10-06 已落地：压缩摘要保留 doc 指针（K号·文档名·doc_id，agent_configs.py:547）+ knowledge_search 对 LLM 开放 doc_ids 入参回看（agent_tools.py:929）+ ANGINEER_EAGER_COMPRESS 激进压缩开关（默认关）。残余缺口：回看是语义重检索而非确定性回放；对话黑板 conv_graph 已按业主指令回退（c4a3aaf/e2f3f4e），论文路线未必全对，黑板方案保留观察不删。',
    anchors: ['services/angineer-core/src/angineer_core/agent_configs.py:547', 'services/angineer-core/src/angineer_core/agent_tools.py:929'],
    nodeIds: ['n-loop']
  },
  {
    id: 'P5',
    title: 'runner 线性执行与图编辑不对齐',
    severity: 'mid',
    desc: 'sop_runner.py:186 注释明写不遍历 next_step_id；sop-ui 里画的 fork 分支运行时无效——图 B 若只做展示无碍，要让分支生效需另算。',
    anchors: ['services/angineer-core/src/angineer_core/sop_runner.py:186'],
    nodeIds: ['n-runner']
  },
  {
    id: 'P6',
    title: 'steer / turn_end 未消费',
    severity: 'low',
    desc: 'steer 端点（main.py:687）前端零调用，插队=abort+新发；turn_end 帧无处理分支。皆为低损。',
    anchors: ['services/aichat-api/main.py:687'],
    nodeIds: ['n-transport']
  },
  {
    id: 'P7',
    title: 'sop-ui 弹药闲置',
    severity: 'low',
    desc: 'user-web package.json 已声明 @angineer/sop-ui 依赖但 src 零 import；接图 B 无需新增画布依赖，纯接线活。',
    anchors: ['apps/user-web/package.json:18'],
    nodeIds: ['n-graphb']
  }
]

export interface ArchReference {
  id: string
  name: string
  link: string
  match: string
  advantage: string
}

export const ARCH_REFERENCES: ArchReference[] = [
  {
    id: 'R1',
    name: 'Harness Engineering（arXiv:2609.00006）',
    link: 'https://arxiv.org/abs/2609.00006',
    match: '高度同构：手写循环、零 agentic 框架、克制只读工具、策略入 env 配置、单 agent——七个子系统逐项对上；差距：无 Skills/MCP 生态、无持久记忆、压缩非 LLM 式',
    advantage: '检索锚定工具箱（知识/表格/图谱/SOP 四线）＋引用守卫与拒答双保险＋nightly 评测单一真相源——论文是通用编码 agent，我们是知识库 QA 纵深'
  },
  {
    id: 'R2',
    name: 'VISTA（视觉记忆，何恺明团队）',
    link: '',
    match: '原则对齐：无损外部存储＋模型主动决定何时回看——已落地为压缩摘要留 doc 指针＋knowledge_search(doc_ids) 显式回看（2026-10-06）；差距：我们是语义重检索，VISTA 是确定性回放（保真差一档，回放通道待建）',
    advantage: '文本域 clause 条款号直达＋memo 检索复用＋投影式压缩不改写落库原文——且 VISTA 的视觉帧成本高，我们的指针回看几乎是零新增基建'
  }
]

export const STATUS_META: Record<NodeStatus, { label: string; color: string }> = {
  ok: { label: '现役正常', color: '#52c41a' },
  warn: { label: '有隐患', color: '#fa8c16' },
  gap: { label: '缺失', color: '#f5222d' },
  planned: { label: '◇ 待新建', color: '#722ed1' }
}

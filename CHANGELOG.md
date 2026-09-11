# Changelog

All notable changes to AnGIneer are documented here.

## v0.2.51

评测判分引擎接入 DeepEval（`EVAL_ENGINE=deepeval` 开关，默认 legacy 自研判分行为不变）：GEval 逐条移植 v3 判分 rubric（阈值 0.65 不变、显式参数面 actual vs expected output），新增 faithfulness（忠实度/防幻觉）/answer_relevancy/contextual_precision 三个扩展维度（首版只展示不进门禁，`EVAL_DEEPVAL_EXTRA=0` 可关闭以提速 nightly）；`DGXJudge`（deepeval DeepEvalBaseLLM 子类）内部复用 ai_inference 候选链——run 级 UI 指定 > EVAL_JUDGE_CONFIGS > EVAL_JUDGE_MODEL 优先级不变、绝不落到被测模型自判的纪律与 judge_used/judge_failover 哨兵留痕不变；GEval 失败走原有关键词兜底 + nightly judge_fail 补判通道，扩展维度独立失败独立记 None 不污染 correctness；nightly 报告新增扩展维度 median 表、归档/run 汇总带 eval_engine 口径留痕。离线 A/B（存量 prediction 30 题双跑）：秩序保持（Spearman 0.757）、DeepEval 系统性偏严 8.3pp（判分口径变化，切换后首晚重钉基线；翻转 3/30 核读成立，详见 docs/plan-deepeval-judge.md）。回滚 = `EVAL_ENGINE=legacy` 重启。

## v0.2.50

- 修多轮会话「代检索」取错问题导致的误拒答（生产与开发 2026-09-11 同时复现）：模型某一轮没调检索工具时，兜底会替它执行 `knowledge_search`，取 query 却用「会话里第一条 user 消息」——先问「你好」再问「王飞」的多轮对话于是拿开场白去检索，命中 0 条、耗时 0.00s，被判定「无证据」后按边界规则输出「没有检索到足够证据支持最终结论」，现改为取最近一条用户真实提问，并跳过循环自身注入的 5 种提示文案（`请先调用检索工具获取证据后再回答` 等），`_latest_user_query()` 带 3 条单测
- 拒答定向重试补「证据回喂」：有有效证据但模型仍整体拒答时，原实现只追加一句「已检索到有效证据，请基于证据作答」，小模型常当耳旁风，现在先把证据原文节选（最多 3 条、每条 800 字）回喂给它再要求作答，轨迹注记带「附证据节选 N 条」
- 半拒答只删拒答开头：模型有时先写「没有检索到足够证据支持最终结论」、随后又带着引用继续作答，这句自相矛盾的开头现在会被删掉、正文保留，原先处理它的 `ANGINEER_GUARD_HALF_REFUSAL` 开关（默认关闭，且开启后是整体替换成纯拒答、把事实一起丢掉）本次移除，剥离门槛只认硬拒答话术且要求后文有引用，「证据不足/部分未覆盖」这类 prompt 要求如实说明的部分覆盖提示不误删（单测实踩：第一版门槛复用 `is_half_refusal_text`，而它的软表述词表里没有该硬话术，要修的场次反而不触发）

## v0.2.49

- 修生产图谱检索一直失效：`entity_search` 的图谱库路径原先按进程 cwd 拼成 `data/knowledge_graph.sqlite`，容器里 cwd 是 `services/aichat-api`、该目录下没有 `data/`（真实库在挂载卷 `/app/data/`），每次调用都抛 `unable to open database file`；连带「图谱无命中自动回退正文检索」的兜底也失效——兜底写在异常之后，异常先抛出、回退根本没跑。答案仍由 `knowledge_search` 正常产出，故障因此被完全掩盖，表现为同一问题在开发侧（cwd 恰好是仓库根）有图谱步骤、生产侧那一步只剩一句占位符。改为复用 `docs_core.paths.resolve_graph_db_path()`（与 docs-api 图谱路由同一套仓库根解析，`KG_DB_PATH` 仍可覆盖），生产 `.env` 同时补 `KG_DB_PATH=/app/data/knowledge_graph.sqlite` 兜底
- 修思考过程把工具错误吞成占位符：`summarizeToolResult` 原先只要 `JSON.parse` 失败就统一返回「工具已返回结果（完整内容见最终轨迹）」，而这条文案在两种相反情况下完全一样——「流式阶段工具结果按设计截断到 300 字符」（正常，整轮结束由 `run_end` 帧全量回填）与「工具真的返回了纯文本错误」（故障），生产上那次图谱报错因此在界面上没有任何提示，只能靠两侧日志对拍才发现。现在非 JSON 的纯文本如实透出（如 `工具执行失败: unable to open database file`），只有截断的 JSON 残片才给占位符，并补 `summarizeToolResult` 回归用例

## v0.2.48

- 对话输入区改造（第一批）：生成期间不再禁用输入框——发送即入队（上限 10 条），当前回答结束后按序自动发出；每条队列项可「编辑」（取回输入框、连 @ 引用一并带回，改完再发）、「插队」（打断当前生成并立即处理该条，原会话上下文完整沿用，截断的回答按普通消息保留、不标「已停止生成」）、「删除」；生成中按「停止」= 当前回答停止 + 队列暂停保留，手动再发即恢复推进。队列内核在 `useAIChat`（不依赖 UI）；注意 `advanceQueue()` 必须放在 `sendMessage` 的 `finally` 最末尾——放在 `abortController.value = null` 之前会让下一轮新建的 AbortController 被本轮清掉、「停止」失效
- 知识库锁定：下拉从工具条中央移到输入框左侧（`@` 之后，为第二批的「+」留位），并在「对话起步」（存在非 system 消息）后锁定，锁定态 hover 提示换库请点新建对话；空会话仍可自由换库。工具条同时做自适应——两个下拉可收缩（库 96–160px / 模型 100–180px，≤480px 再收缩一档），`@` 与发送按钮永不参与收缩，被压缩的是下拉文字
- 待发送托盘 UI 重做：新增标题行「待发送 N 条」、圆形序号徽标、独立成组的动作区（编辑/插队/删除）；原底色 `--bg-tertiary` 在浅色主题下与输入框 `--bg-secondary` 数值相同（≈#fafafa）等于没有底色，改为 primary 淡染 + 同色描边并把圆角与输入框统一为 12px；颜色全部走 `--chat-queue-*` 双回退钩子
- aichat-api 修「插队/停止后立刻再发」撞单飞保护：客户端 abort 是毫秒级、服务端要等 LLM 调用退出才把 `AgentSession._running` 置回 False，毫秒级重发必然撞上 `RuntimeError: Agent run already in progress` 并把内部错误抛给用户；SSE 处理器启动 run 前先等会话空闲（30s 上限，超时返回明确提示）。实测空闲路径耗时 0.000s，正常发送零代价
- 删除 aichat-ui 输入区失效的图片上传入口整条链路（-117 行）与公开 prop `allowImageUpload`：该按钮只把图片读成 DataURL 做本地预览，不上传也不随消息发送，宿主侧早已硬编码禁用
- 独立包 aichat-ui 发 0.1.8（排队/锁库/托盘一并进入 npm 包），并清掉其 `package.json` 自 0.1.7 起带入的 UTF-8 BOM——registry 安装 pnpm 容忍，但 vendored（`file:`/目录）方式会以 `Unexpected token` 直接解析失败；0.1.8 tarball 首三字节已验为 `7b 0a 20`

## v0.2.47

- pnpm 9.0.0 → 11.7.0 全量迁移：`packageManager` 与 Dockerfile 同步升级（构建阶段 node:20→node:22，pnpm 11 要求 Node ≥22.13），装法由 corepack 改为 `npm i -g pnpm@11.7.0`；pnpm ≥10 起不再读取 `package.json` 的 `"pnpm"` 字段（留着既打 WARN 又让 overrides 静默失效），lodash/lodash-es overrides 与新增 allowBuilds（esbuild/resvg-js/vue-demi 放行、core-js/less 明确不需要——旧键 onlyBuiltDependencies 在 11 已不生效）一并迁入 `pnpm-workspace.yaml`；lockfile 仅 xlsx（SheetJS CDN tarball）补 integrity（pnpm 11 供应链策略缺 integrity 直接拒装）
- pnpm 迁移真机验证通过：容器内 `pnpm install --frozen-lockfile` 1m25.3s、双端 vite 构建 37.4s，`packageManager`、overrides 与 allowBuilds 在 node:22-alpine 下全部按预期生效
- 修 Dockerfile 镜像源失效：pnpm ≥11 不再读取 `npm_config_*` 环境变量（实测指向死端口仍装成功），原 `ENV npm_config_registry` 对 pnpm 静默失效——上次部署日志显示容器里 315 个包全从 registry.npmjs.org 直连拉取（xlsx ETIMEDOUT 重试与平均 32 KiB/s 警告即由此来）；改为构建阶段写项目级 `/app/.npmrc`，ENV 保留仅服务上面那句 `npm i -g pnpm`
- admin-web 首屏提速：按需引入 ant-design-vue（`unplugin-vue-components` + AntDesignVueResolver，`main.ts` 去掉 `app.use(Antd)` 全量注册），知识库三视图与 ApiKeyChart 改异步组件 + 空闲预热，预览面板经新增 `DocViewerPane` 薄包装动态引入；落地页必下资源 3977KB→2134KB，线上实测入口 chunk 1.57MB→608KB
- 清掉主仓库最后 4 个 UTF-8 BOM 文件（`.env.example` 与 3 个测试文件）：BOM 曾在本仓库与独立仓库反复出现，`.env.example` 的 BOM 会随 `cp` 进 `.env`——当前首行是注释故无害，但首行若改成真实变量会让变量名变成 `\ufeffKEY` 而静默失效
- 版本对齐与文档：`packages/docs-ui` 版本 0.2.1→0.2.2（与独立仓库 v0.2.2 / npm 上架版本一致），README 版本表补三处漂移（docs-ui v0.2.2、table-ui v0.1.2、ai-inference v0.2.0）

## v0.2.46

服务化内部解耦与依赖内化：docs-api 新增 `internal/entity-search`、`internal/doc-nodes`、`internal/graph-append-note` 三个内部端点；angineer-core 三处跨进程直读 SQLite（entity_search 图谱检索、policy_query 节点加载、knowledge_stats 统计兜底）与 dream_cycle 两处图谱裸连接全部改为 HTTP 优先 + 本地回退，`ANGINEER_DISABLE_LOCAL_FALLBACK=1` 可整体禁用回退（服务化部署消灭"共享数据库"反模式），新增双轨回归测试 7 例；user/api_key 模型从 docs-api/aichat-api 两份漂移副本收敛到 `services/shared`（新增 shared/paths.py 数据路径解析，两侧 models/ 改为模块替换别名层——既有导入与测试 patch 语义零改动，顺带清除 api_key.update_key 尾部死代码；中间件保持各自独立，aichat 的 /api/chat/* 可选鉴权策略本就不同）；PoPo 由 git submodule 内化为普通目录（上游 opendatalab/MinerU-Popo 对我们的定制 PR 从未合并、6 周无更新，fork 即唯一部署源头；2371 文件中 75 个运行时必需源码入库，eval 产物被其自带 .gitignore 合理排除；deploy.yml 移除 submodule update；新增 UPSTREAM_SYNC.md 记录上游同步点 97d5601；修复首版内化提交的孤儿 gitlink 边界问题）。B 项排查结论：import 期无界 DB 调用仅剩 embedding_provider 维度探测一处，Qdrant 下为 O(1) HTTP 查询，无量级问题。

## v0.2.45

- 首屏提速（实测线上首屏传输 3.26MB → 0.34MB）：网关 nginx 启用边缘 gzip（配置在服务器 `/etc/nginx/conf.d/ai-proxy.conf`，按约定不进 git）——容器 nginx 本就配了 gzip，但其依赖 Accept-Encoding 透传、经宿主机网关会丢失，实测静态资源此前完全未压缩（单个 JS 1.61MB→0.51MB）
- ant-design-vue 改按需引入：user-web 加 unplugin-vue-components + AntDesignVueResolver，`main.ts` 去掉 `app.use(Antd)` 全量注册，首包 `index.js` 1.57MB→435KB、对话页分块 1.51MB→578KB，产物内已无任何 `resolveComponent` 残留（即全部 `a-*` 标签静态解析成功），运行时校验 CSS-in-JS 样式注入与主题色正常
- 文档预览栈（pdf.js / KaTeX / xlsx / docx-preview）从对话页分块拆为独立 chunk（1.29MB），页面挂载后用 `requestIdleCallback` 静默预热——用户需要的是秒级打开，其后操作允许慢；点引用路径额外 `await loader` 兜底，极快点击也不会丢定位
- 顺带修复：`apps/shared/chatTransport` 的 `onWarning` 漏类型声明（运行时调用一直正常，但该缺失使 `vue-tsc -b` 恒红、`pnpm build` 脚本长期不可用，CI 走 `build:docker` 故未暴露），以及 `vite.config.ts` 里 `m.index` 可能为 undefined

## v0.2.44

- PDF 预览首屏提速：pdf.js 加载改 `disableStream: true` 走真分块按需加载（pdf.js 官方要求按需加载须同时关流，此前未关会先发一个不带 Range 的整文件 GET 并读到 EOF，85MB 文件被全量拉取且与首屏分块抢带宽），加载遮罩改显示真实「已下载 / 总大小」，文档未解析完不再把页数显示成「1 / 1」
- 服务端新增 PDF 预览副本：对页字典散落的老排版 PDF（pdf.js 加载时取末页会逐页跨文件取字典，13MB 文件须整份下完才出首屏）用 PyMuPDF 重排成对象流并缓存，原件不动、失败回退原件、`PDF_WEB_OPTIMIZE=0` 可关，JTS 165-2013 实测出首屏所需下载 12.90MB→1.20MB（请求数 28→4），渲染逐像素一致、文本层无差异
- 预览不再等整份 content.md：`GET /knowledge/document/{lib}/{doc}` 新增 `include_content=false`，预览面板先取 storage 拿到 render_pdf 立即发起 PDF 请求，全文在后台补进解析面板
- 其它：`/api/files` 补 `Cache-Control` 让重复打开走浏览器缓存、下载按钮带 `raw=1` 取原件，修「一次快速切换文档就把该 PDF 永久降级为全量下载」的降级缓存误判，页数超 200 不再逐页预取页高，容器内 nginx 对 `/api/files` 关 `proxy_buffering`

## v0.2.43

- 版本号 hover 弹层拆条修复：AppBrand 按全角分号拆条目改为括号/反引号深度感知——「」『』【】《》（）与代码段内的分号不作条目边界（0.2.42 摘要条目「发版摘要「；」分条约定落地」被裸 split 劈成两条孤句的实踩修复，拆条边界与发版约定、CHANGELOG 拆分规则对齐）

## v0.2.42

- 夜间测试页改版：头部接管定时开关与时间（旧版无 UI 可停用定时、改时间隐式开启定时两处回归一并消除），nightly.json 落盘 started_at（开跑时间，UTC→北京规范化），新增时长列（运行中行实时计算），常驻心跳轮询修复"页面早于调度器打开就看不到运行中条目"
- DataTable 消除两类恒定横向溢出：rowSelection 勾选列 32px 计入强制表宽（知识库日常维护表宽恒超容器），空间不足时全部非 fixed 可收缩列按 minWidth 下限迭代分摊收缩（夜间维护表弹性列余量兜不住即整表放弃致滚动条永存），Σmin 仍放不下才允许滚动，取整误差从最宽列逐列修正保证表宽精确等于容器
- nightly 通知修复与加固：_resolve_webhook 补旧契约回退（NIGHTLY_WECOM_WEBHOOK→WEBHOOK，杜绝配置改名导致的静默漏发，09-09 晨实踩），服务器 WEBHOOK_SYSTEM（运维群）与 WEBHOOK_OWNER（业主群）拆分，运维告警只进系统群、评测结论两群都发
- config_validator 不再把"容器内无 .env 文件"当致命错误：docker 部署 env 走 compose env_file 注入属正常形态，旧早退既在每次部署轰炸运维群假 ERROR、又让真正的 *_CONFIGS 漂移检不到；改为进程环境为真相源，仅无文件且零配置才报缺失
- 顶栏：AI 对话按钮恢复跳前台（dev 独立端口/生产同源，03aafd9 误留空函数致入口三个提交没反应）；健康检查入口与 /dream-cycle 路由下线（DreamCycleView 仍为知识库-夜间维护使用）
- 发版格式：摘要逐条「；」分条约定（版本号 hover 弹层拆 bullet），存量 CHANGELOG 19 个版本段重排为 - 列表

## v0.2.41

- 向量检索引擎切换 Qdrant（为 2000 本规模铺路）：新增 `DOCS_VECTORSTORE_PROVIDER=qdrant` provider——`QdrantVectorStore` 实现 VectorStore 五方法接口（on-disk 向量/HNSW + scalar int8 量化 always_ram=false，面向 4GB 小内存部署机；uuid5(record_id) 确定性 point id 保证重建幂等；payload 直存 content/metadata 命中即组装、无跨引擎回查；doc_id/entity_type/entity_id keyword 索引过滤下推 HNSW 层；collection 维度即期望维度，异构维度拒写语义与 SQLite 版对齐）
- 存量迁移 `scripts/migrate_vectors_to_qdrant.py`（canonical_vectors 直迁不重算 embedding、rowid 断点续传，生产 21.3 万条 10 分钟完成、数量核对一致）
- 双跑一致性校验 `scripts/verify_qdrant_parity.py`（content 去重口径 recall@20 门禁 0.95，本地实测无过滤 0.965/带过滤 0.997；record_id 口径受 table_row_key 单字符同分集群影响仅作参考）
- compose 新增 angineer-qdrant 容器（qdrant/qdrant:v1.19.0，仅回环 6333 + 内网 service 名，内存上限 1536M），Dockerfile.backend 纳入运维脚本（.dockerignore 白名单放行）
- 生产切换后启动向量守卫 604s→4.8s、docs-api/aichat-api 双进程全量矩阵缓存消除（部署机可用内存 648MB→2.4GB，Qdrant RSS 仅 42MB）、检索 P95 无过滤 69ms/单文档过滤 23ms
- 回滚 = .env 切回 sqlite 重启（canonical_vectors 表保留一个发版周期后 DROP+VACUUM）
- 测试：test_qdrant_vector_store.py 10 项集成测试（Qdrant 不可达自动 skip），docs-core 全量 329 passed 无回归

## v0.2.39

- 前端双端顶栏统一与跨应用会话同步：抽出共享品牌组件 `AppBrand`（logo + 名称 + 版本 hover 发版弹层 + 主题灯泡），userweb/admin 共用，顶栏高度（56px）、内边距、背景 `--panel-header-bg`、毛玻璃与按钮内边距对齐一致
- 版本 hover 发版摘要提取改为兼容 README「当前版本：X.Y.Z —— 摘要」无 v 前缀格式（修复此前摘要恒为空、弹层形同虚设）
- userweb：右上角用户名不再带图标、工作台仅管理员可见且点击跳转管理台（dev `/admin/`、prod `/admin/` 同源）
- admin：右上角新增用户名下拉（同 userweb 交互）、API 管理/用户管理对调、AI 对话按钮跳转 userweb 去重（删除 /chat 路由与 AIChatView）、左侧 logo 改用 `BASE_URL` 修复部署在 `/admin/` 子路径下图片 404、vite 注入 `VITE_APP_RELEASE_NOTES` 使发版弹层生效
- `DataTable`（@angineer/table-ui）改为表头与单元格内容默认居中（列级 `column.align` 仍可覆盖）
- 跨应用会话：会话 token 存 host cookie（端口无关），userweb(3005)/admin(3002) 共享同一会话，任一应用登录/退出在 focus 或同源 storage 变化时实时同步
- 后端 `/api/v1/auth/logout` 免库校验、无库用户也能幂等删除会话（此前会 403 且删不掉，导致「一个退、另一个不退」）

## v0.2.38

- 夜间维护列表验收三连修：起跑间隙（run 未建档）也出"评测启动中…"种子行、点立即运行立即可见（前端启动后立即补拉 + 8s 再拉真实进度），操作列按钮 click.stop 阻断冒泡不再顺带展开明细行，运行轮询 60s→15s（停止后行消失与按钮恢复从分钟级缩到 ~15s）
- 新增图描述（VLM figure_describe 阶段 + 全量回填）、M3.2 证据装配与 QA prompt v8、评测套件多线程并发（EVAL_CONCURRENCY=3）
- 升级 QA prompt v9（二元 Yes/No 结论禁止部分证据引申翻转）并撤回 CLAIM 数值/专名守卫（实测正常题误伤，宁漏勿伤，保留半拒答守卫）

## v0.2.37

- 夜间维护列表操作升级：运行中的评测以虚拟行进列表（状态「运行中」、题量 xxx/487 随 60s 轮询走、不可展开），表格全列居中，新增操作列——「停止」走 stopped 收口（当前题做完即退出，不落 error 档结论、不发企微、当天 slot 不自动重跑；起跑间隙按下由流水线拿到 run_id 后立即补停闭环），「删除」连带删除对应评测 run 且 run 在跑先停（运行中行删除=停止同语义，干净消失）
- 回归 4 例（停止拒止/置位停 run/不落盘不通知/虚拟行字段与 UTC→北京时区口径）

## v0.2.36

- 生产检索延迟修复第一弹（乘潮水位类 20s 问句分段计时定位 dense 2.4s/sparse 5.1s/formula 10.4s/rerank 首查 12s 冷启动）：formula 通道瘦加载——FormulaRetriever 不再 get_canonical_document 一次拉 6 张表（288 份规范单文档最大 7363 blocks/2878 chunks），改 data_port 单表单查 blocks/chunks，canonical_sql_store 的 blocks/chunks LIMIT 钳位 1000→20000（防大文档尾部公式被截断致行为不一致），公式候选构造逐行不变
- dense 通道只构造入选行——全量打分（召回口径不变）后按 np.partition 分界值把 top-k 与第 take 名同分并列行并入候选池，落选 ~22 万行不再做 VectorSearchHit 构造与 metadata JSON 解析，破平语义（score, 内容长度）与全排截断一致（新旧路径一致性回归 7 例）
- 服务器知识库健康与存储整理（knowledge_index.sqlite PRAGMA integrity_check ok、删两组旧备份保留 bak-recovery-20260906pm 兜底、释放 ~3.6GB）

## v0.2.35

- 评测可靠性补强与存量文档图描述补齐归档：向量库期望维度改 index_meta 持久化 O(1) 读取（v0.2.34 的全表多数表决被 embedding_provider 在模块 import 期调用，5.3GB/21 万行库每次容器启动被拖 15+ 分钟、两次部署窗口 502 实踩——meta 缺失才跑一次表决并落库、`strict_dimension=False` 迁移路径清 meta 重算，稳态零扫描）
- nightly 基线指针跨平台修复（Windows 钉的基线拷到 Linux 服务器后，反斜杠 raw 被 POSIX Path 当整串文件名拼出双重目录致 nightly FileNotFoundError 无结论失败——读侧 gate 分隔符归一化、写侧 pin 改存 as_posix）
- 存量文档图描述补齐阶段 1 归档（本地 26 + 生产 77 篇 VLM 全覆盖、4 篇无图块跳过；77 篇源文件在本地文件夹全数找回，本地整目录倒灌 + DB 行级重索引暂停为可选项，详见 docs/backlog-figure-describe-legacy-docs.md）

## v0.2.34

- 评测治理与对话体验合集：评测 53/487 全灭事故三连根治——流式 reasoning 增量事件恒带 text 键（Qwen3.8-Flash 直连 DGX 思考流 KeyError 根因，llm_client 4 处复制粘贴的 extra_body 构建收敛合一）、eval_run 记录 owner_pid（启动清扫只回收属主已死的 running，多实例共库误杀修复）、哨兵 b 全链路留痕被吞 LLM 失败（prediction/scores/run 汇总三级可见 `refusal_via_error`，拒答集"故障满分"假象可识破）
- `LLM_CONFIGS` 端点级 `enable_thinking` 显式开关（直连 vLLM/DGX 思考模型可显式关闭提速，优先级高于环境变量与隐式 URL 规则）
- 评测运行面板交互重排（EvalRunCreateModal 运行/评价/题集三选、进行中 item 置顶带实时状态标签、"重来"原地复用同 run_id 全量重跑、评价模型可选且绝落被测模型自判）
- 评测管理页三栏/拖拽/树全面复用知识库同款组件（ui-kit 新增 useSplitPanesLayout 共享比例与折叠持久化，拖拽落位兄弟排序真实落库）
- user-web 对话首页体验完善（顶栏品牌区含发版摘要、@ 提及文档级圈定检索范围、输入框知识库单选下拉、Shift+Enter 换行修复、references 搜索 500 修复）
- 向量库维度多数表决 + upsert 拒写异构维度（防异构维度行毒倒全库语义检索）
- 夜间维护面板宽度对齐知识库列表模式
- 图描述回填脚本升级（`--from-db` 自动筛存量队列 + `--dry-run` + 管理员会话直连）

## v0.2.33

- user-web 对话优先首页大改版（极简 Hero 入口→对话页→右侧溯源面板复用 PDF viewer bbox 定位、历史会话 localStorage 持久化 + 右侧抽屉恢复/删除、工作台迁 /workspace 路由，aichat-ui 同步新增 hero 模式/messagesChange/loadSession 三个向后兼容增量）
- 生产事故三连修：clean-orphaned 孤儿判定从进程内存快照改为直查 nodes 表实况 + 单次批量 >20 条强制 confirm 复核（源于误删事故，99 篇文档索引/向量已从服务器 09-05 快照双端完整恢复，档案与存量待办见 docs/backlog-figure-describe-legacy-docs.md），meta_query 快速通道枚举词收口（"库里有哪些X"类内容题不再误入统计通道）且统计拒答话术守卫同步，knowledge_stats 新增文档标题清单维度（列举题统计通道直答）
- 夜间维护全内置化（aichat-api 进程内北京时间调度器默认 01:00 启用、evals-core nightly 流水线"当天必有结论"不变式、执行计划预览、管理页调度工具条脏态交互），评测状态机治理（runner 三态如实反映排队/执行/完成、停止按钮 worker 端拦截真生效、服务重启清扫僵尸 running run、幽灵汇总数据修复、"重新评测"按钮按运行时模型语义化）

## v0.2.32

- agent 上下文截断 top10 放宽到 top15 可配（`ANGINEER_CONTEXT_TOP_N`）：离线覆盖度量（38 道翻转题）实测 top10 仅覆盖金标要点 ~64%、top15 ~70%、top20 ~71%，v0.2.23 的 top10 截断被证实是答案漏要点主因
- 同 section 去重/低信息块降权等多样性规则变体实测无增益，未采用

## v0.2.31

- 修复 meta_query 统计通道误路由（评测实测 9 题内容问题被误判为库统计而必错）：分类器 prompt v3 收紧边界（含统计词但答案在文档正文的一律走正文检索），统计通道新增兜底——产出"统计数据不包含该信息"式答非所问时自动回退 L1 正文检索重答

## v0.2.30

- 修复块级检索指标链：无 section/target 标注的数据集 hit@(sec)/citation_hit 由恒 0.0 改为 N/A（evaluator None 语义 + 报告 — 渲染 + evals-ui 防护），新增 `scripts/open_ragbench/annotate_gold_targets.py` 用金标答案自动回填章节/块/引用标注（subset-v2 已标注 473/487 题），换 embedding 模型后的块级召回质量自此可观测

## v0.2.29

- 上线 HTTPS 域名 angineer.cn（网关 80 端口改为 ACME + 全量 301，所有 `*_CONFIGS` 端点从 IP 明文迁到 https://angineer.cn），aichat-api 启动后台预热检索缓存（向量矩阵/FTS，消除冷态首查 sparse 段 12s+）

## v0.2.28

- 修复 AI 对话拒答重答时中间轮疑问句残留正文气泡（chatTransport 按 turn_start 重置流式正文），检索链路新增分段计时日志（dense/sparse/clause/fuse/rerank 各段耗时可直接定位慢查询），向量矩阵缓存改分批流式构建（消除全量回填后的 OOM 风险），新增 `scripts/rebuild_vectors.py` 全量向量回填工具（切 embedding 模型/向量库后重建 dense 索引，幂等可续跑）

## v0.2.27

- 修正向量索引提速路线：实测 DGX qwen3-embedding 对并发请求排队执行（双并发比串行慢 ~50%），并发默认回退 1（仅多 worker 本地端点值得调大），改为调大批次（`DOCS_EMBEDDING_BATCH_SIZE` 默认 32，DGX 端点建议 64；批内亚线性 103→59ms/条，该阶段实测可提速 ~2 倍）

## v0.2.26

- 修复 Docker 部署 LibreOffice 转 PDF 中文乱码（backend 镜像补 fonts-noto-cjk 中文字体，存量乱码文档需重跑格式转换阶段），向量索引分批嵌入改双并发（`DOCS_EMBEDDING_BATCH_CONCURRENCY`，默认 2，远程 embedding 场景该阶段耗时近减半）

## v0.2.25

- 新增统计/元数据查询 meta_query 通道（knowledge_stats 实时聚合 + LLM 提取报数，统计问题由 30s+ 拒答改为秒级直报数字；摸底否决裸 text2SQL：主模型 SQL 语义正确率仅 5%），修复 aichat 工具调用 JSON 泄漏到前端（流式围栏过滤）与 PDF 预览失败（nginx 补 .mjs MIME）

## v0.2.24

- 端点配置全面统一 `*_CONFIGS` 数组为唯一入口（MinerU/PoPo/Embedding/Reranker，顺序=优先级、失败自动切下一项），删除旧单变量（MINERU_API_URL/POPO_VLLM_URL/DOCS_EMBEDDING_*/ANGINEER_RERANKER_URL 等）兼容层

## v0.2.23

- 解析服务端点 configs 化（MINERU_CONFIGS/POPO_CONFIGS JSON 列表，数组顺序=优先级、主端点失败自动切换，接入 DGX 公网解析并统一 file_parse ZIP 协议），检索/向量性能优化（全量向量矩阵进程缓存），中文数字条款号检索修复（LawBench 法条题精确命中），agent 上下文 top10 截断（prefill 减半）

## v0.2.22

- 修订 v9 规则 15（证据无明确二元表述时给部分结论并标注缺口、禁止整体拒答，v2 全量 87.68% 历史最高）并将批量删除改为批量接口（软删/硬删，单条失败不中断 + 失败明细）

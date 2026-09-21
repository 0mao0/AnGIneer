# Changelog

All notable changes to AnGIneer are documented here.

## v0.2.73

- 拒答新增第三档「拒答开头+供参考」（prompt v10 规则 16）：诊断（09-20 nightly 逐题核对 8 道翻转题）——检索召回提升后不可答题也能检回 15 条主题相邻 chunk（翻转题两天 retrieved_items 均为 15），拒答出口只剩「检索为空→guard 模板」一种且几乎不再触发，模型面对「有相邻证据但答不了」没有合法措辞，改写「基于检索到的证据…未提及…」式对冲回答（不含任何拒答标记——「未提及/证据不足」是有意排除的弱措辞，收进来会误伤可答题的部分覆盖回答），nightly 39 题拒答 24→18。修法：规则 16 明确「证据只与主题相邻、不覆盖问题核心结论」时——第一句「没有检索到足够证据支持最终结论」+ 一句说明未找到什么 + 「以下相关信息供参考」引出相邻片段（正常标注引用），与规则 9 的「部分覆盖→答已支持部分」划界；`is_reference_refusal` 双命中认定（「供参考」信号 + 拒答标记，单出现任一不成立，防误伤）；guard 半拒答剥离与 agent_loop「有证据却拒答」定向重试对第三档**双豁免**——不豁免则规则 16 会被既有重试机制拆掉（重试正是逼模型把相邻证据改写成答案的失守路径）。评测侧零改动（强标记全文匹配自动识别）。实测（部署后 39 题拒答专项 run-dd86066d4dd2，prompt v10 快照确认）：18/39→**26/39**，超话术收窄前最好的 24/39；剩余 13 道为模型对相邻证据自信作答的真幻觉，属方案③（服务端可答性门控）覆盖范围。测试 +6（guard 保留第三档/双命中门槛/重试豁免/规则 16 契约/latest=v10）：tests/angineer-core 200 绿、aichat-api 77 绿
- prompts loader 版本排序改数字段比较：纯字符串 `max` 在注册 v10 后会把 latest 钉死在 v9（`"v9" > "v10"` 字典序）——「v10 注册了也不生效」的埋伏随本次首次注册 v10 引爆前拆除，`load`/`versions` 同改并以契约测试钉住
- 拒答话术恢复旧版「没有检索到足够证据支持最终结论。当前仅能确认已有片段与问题相关，但不足以安全地给出完整答案…」：v0.2.69 改的「知识库未能检索到相关答案。」语义收窄成「什么都没检到」，是本次拒答失守的一半根因（旧话术第二句正是「片段相关但不足」情形的合法出口）；`REFUSAL_MARKERS` 双标记并存（`没有检索到足够证据`=现话术、`未能检索到`=v0.2.70–72 历史话术，回放旧数据仍认），v0.2.70 的容错判定（强标记抗主题插入/弱标记只认引用前/英文软措辞）全保留；教训写入 `agent_messages` 注释：改话术先想清楚检索变好后模型会落在哪种情形

## v0.2.72

- 表格合并判据补「题注编号」一条（同构异表不再被当成续表吞并）：定向探针查出 `v1-8995872ae055` 的 `Table S1..S13` 被判成一条跨页续表链——PoPo 指令注入的校验只查「两端都是表格 + 列数一致」，而同构异表（仿真结果表）列数天然都是 7，这条判据只能**确认**、不能**否定**，于是 10 张独立表被吞进 3 个宿主：行数据拼接保留，但**被吞表的表号题注从 `plain_text`/`summary` 消失**（`60:1` 只留「Table S1: …」，S2–S5 不再出现），`canonical_tables` 15 行降为 5 行、`table-…:S2..S5` 级引用目标不复存在。后果（同一问题三态对照）：step 7 前「答对 + 表级引用 `table-…:61:1/62:1/63:1`」→ step 7 后连续 **3/3 答不出**并命中别篇文档的同名表（跨文档错引风险）；同病 `v1-549f025589ca` 的 `FIG. A.6/A.8/A.10–A.12` 被吞进 `A.5/A.7/A.9`。真实安全阀佐证方向：该篇 `merge.rejected_reasons` 只拦下两条「table_merge 链超过上限」——拦的是规模，不是「这是不是同一张表」。修法：题注编号解析收编单一真相源 `shared/table_caption.py`（题注取用 `caption` → `content_json.table_caption`；编号匹配 表/Table/Tab./图/Figure/FIG./Exhibit，去尾部句点——`FIG. A.6.` 的编号是 `A.6`；冲突判定「两侧都有编号且不同」），接入 `validate_instruction` 的 table_merge 分支（`_resolve_chain` 每跳都过同一校验，故注入与合并两处同时生效），续表启发式三个私有助手改引共享实现（两条入口判据统一）。实测：两篇重跑 structure+fts+向量后表块 15/16 全恢复（S1..S13 题注全回）、list 续接合并 4 处保留、覆盖 1.0000、B 层 severity=ok、探针 T1 恢复答对且引用回到表级
- 单测与回归：新增 5 例（编号不同拒——`Table S1←S2`、`FIG. A.5←A.6`；同号/无题注放行——真续表形态；提取器覆盖中英文题注与无编号兜底），并改写既有 `test_table_merge_keeps_source_caption_and_target_footnote` 的夹具为题注同号的真续表形态（原夹具用 `表1←表2` 两个不同编号，属被新判据正确拒收的形态，改夹具而非放宽判据）；docs-core 全套 **393 passed**（唯一 fail 为本地 qdrant 不可达的环境项），改动测试文件在生产容器内复跑 55 passed
- 回灌脚本 `scripts/backfill_structure_rebuild.py` 补齐 PoPo 推理阶段与逐阶段计时：新增 popo 阶段（防重入守卫——有有效 `enriched_blocks.json` 默认跳过、`--force-popo` 强制；强制重跑前旧产物备份进备份目录，推理失败回滚旧的再按 `fallback=solo` 继续，半成品不喂 structure；瞬时失败重试直接复用 `parse_pipeline` 的 `_POPO_INFERENCE_RETRIES`/`_is_transient_popo_failure` 单一真相源）；每阶段起止 UTC 时间戳 + 墙钟写 `progress.json`（step 6 缺计时、备份副本 mtime 不可用致吞吐只能粗估），**vectors 阶段补计时**——此前只写 `"ok"`，14893s 合计与分阶段之和差约 762s 只能当无名残差看，现与其余阶段同形（本轮补跑实测单篇 vectors 段约 16s）

## v0.2.71

- 结构层类型词汇漂移修复：PoPo 续接注入器的可续接集合与续表标记扫描集写的是 **canonical 名** `list_item`，而 solo 节点用 MinerU 行词汇——生产库实测 `list`=6157 / `list_item`=0，列表块的跨页续接 100% 被拒、「续表X」标记写在列表块里则续表漏检。修法：两处收编到单一真相源 `step04_structure/shared/row_vocabulary.ROW_TEXT_TYPES`（`paragraph`/`list`）；同时给 contd 判定加**两端同型**约束——`popo_block_merger._merge_text_fragments` 只要任一侧带 `paragraph_content` 就走文本拼接分支、另一侧 `list_items` 整块 flatten 丢失，故 paragraph↔list 混合续接一律拒收（放开 list 才有正收益，flatten 危害有正反实证用例各一）。新增 13 例含敏感度用例（把 `list` 从集合摘掉，两条规则必须转红）
- 词汇契约固化 + 一处误报撤下：新增 `tests/test_row_vocabulary_contract.py` 8 例钉住三层词汇边界（canonical 名不渗入行词汇层、`normalize_block_type("list")=="list_item"`、`CanonicalBlock(block_type="list")` 必须 ValidationError）；此前排查把 `formula_semantics` 的公式解释段候选集也判成漂移点，实为**误报**——该处两条调用路都已归一化、canonical Literal 也直接拒绝 `list`，撤下并改名为 canonical 词汇常量加注释留档（行为零变化）
- 续接文本重归属放宽到跨页：v0.2.70 首版「承载块 105/105 都在同页」是**语料假象**（OmniDocBench 1350 篇全为单页文档，跨页结构上不可能出现）。换生产库 `lib-b07ed174` 的 620 个空 paragraph 量去向：文本落在上一页末段的占 26.9%（167 例）、同页规则只覆盖 12.7%——只修同页漏掉七成。修法：同页找不到承载块时退一档取**上一页最后一段正文**，双守卫缺一不可（middle.json 独立证据：上一页末文本断在句中；几何证据：本行上方无任何非空正文段落），找承载块时跳过页眉页脚页码、遇表格/图片/公式/标题宁可放弃（越界命中的多是模板套话巧合）。实测：生产库 117 篇全量回灌 0 失败、重归属 219 处、跨页续接合并 478 次、空段落 480→305、title 块 2789→3042；reattach 单测 29 例
- 管线 stats 透传引擎计数：`build_structured_index_for_doc` 此前直接新建 dict 覆盖 `result.stats`，引擎侧可观测计数（`continuation_text_reattaches` 等）在管道层整批消失——回填/巡检时看不到规则跑没跑（09-19 canary 报「重归属 None」即此坑），改为引擎 stats 打底再叠加管线键；解析阶段步骤显式显示重归属处数；空文档时 `table_cells_stats` 先兜底防收尾 UnboundLocalError。新增 stats 契约 3 例 + 回填/A-B 分析脚本入库；solo_engine 兜底对候选集维持 paragraph-only 并注释原因（其合并写 `paragraph_content` 会绕过 list 块结构，与注入器的行词汇策略有意分歧）；回归：docs-core 全套 399 passed、tests/unit 失败集与 7 例预存基线逐一对上

## v0.2.70

- 拒答判定改容错匹配（度量修复，非行为改动）：生产实测 39 道拒答题只判出 6 道、整体正确率被虚增 17.85pp——逐题核对定性为**度量坏了而非行为坏了**（真作答/幻觉数未变，多出的 18 道全是「拒答了但没被识别」）。根因：判定用连续子串匹配 `REFUSAL_MARKERS`，而模型会把主题插进模板（「知识库未能检索到关于「原恒星」的定义……的相关答案」），中间被「关于X的」隔开即整段落空；旧话术模型逐字复述所以一直没暴露。修法：强标记改不会因插入而失配的核心片段（「未能检索到」+ 历史话术），英文软措辞全文匹配；判定逻辑写死在引擎 `is_refusal_text` 与 evals-core `answer_eval.is_refusal` 两处的第二份硬编码一并收敛为引引擎单真相
- 解析结构层「续接文本重归属」：先按误差质量拆「文本保真」——命中组合计 390.2 中空文本 100 组占 25.6%，只有这列可修。真相不是漏文而是**错归属**：MinerU 段落装配把续接段落并进前一块、留下 bbox 正确 content 为空的空壳（112 例可找回文本里 111 例已存在于同页紧邻前一 paragraph 块）。后果：承载块 bbox 与文本不一致（引用高亮落错区域、chunk 边界不对），空壳块 GT 对齐恒 0。修法：从承载块尾部摘掉这段文本写回空块（两边不重复、宁可不动也不造重复文本；+4+1 例外）；A/B（真实入口重建）：块文本相似度（命中）85.79%→90.64%（+4.85pp）、块召回 91.009%→91.037%（tau 不变）；小反向 figure_footnote −2.87pp / figure_caption −2.67pp（组数仅 9/47）；A① 官方口径 Edit_dist 0.0759→0.0785（切分插入空行，结构层正确、交付面轻微代价）。顺带查实测量盲区并写入文档：官方 TEDS 跨时段不可比（同日 production markdown 09-18 评 0.8945、09-19 重评 0.8921，文本/公式/阅读顺序逐位复现）——只有同场次 A/B 可比。单测 18 例（含真实入口端到端闸）
- 引擎 C1 库化解耦收尾（Seam 4，行为零变化）：`agent_tools` ~450 行检索/图谱配方平移到 docs-core 侧 `step09_query/agent_port` 适配器——`ports.py` 新增 agent_search 七端口（查询归一化 / 知识本地召回 / 表格召回 / 图谱直查 / 统计聚合 / 外部工具注册表 / 引用挑选；引用挑选为执行中新发现的第 7 处耦合），端口边界切在「本地召回配方」层，装配（rerank/引用标记/证据序列化）与 HTTP 优先本地回退双轨编排留引擎（`docs_retrieval_client` 是纯引擎模块），避免 docs-core 反向 import angineer_core；aichat-api 启动注册七端口，nightly/evals 同进程覆盖。计划初稿登记的 `graph_append_note` 为幽灵条目（真身在 docs_retrieval_client + dream_cycle_routes，不经引擎），无此端口
- 引擎 docs-core / engtools import 清零（注释也不留）：`agent_tools` 内 query_normalizer 归一化改走端口在双轨分叉前调用，`sop_runner` 模块级工具注册表 import 改经 engtool_registry 端口（吞异常降级语义保留）；`rg docs_core|engtools` 于 `services/angineer-core/src` 双 0 命中，`import angineer_core.agent_tools` 实测 ~230ms 且不加载两边——引擎成为只依赖 `angineer-ai-inference + pydantic + python-dotenv + requests` 的干净包，C2 库化（独立仓库/PyPI）只剩打包工程、没有架构活。pyproject 本就无 docs-core 依赖（sop-core 已于 v0.2.68 摘除），零改动达成
- 端口契约回归 7 例（`tests/angineer-core/test_ports_contract.py`）：每个端口一条「按生产形状注册 fake、走真实调用点、断言真被调通」用例，覆盖 agent_search 七端口（engtool_registry 含 EngtoolAdapter 与 SopRunner 双调用点、断言恰好被调两次——其 `_get_tool_registry` 会吞异常返回 None，只断言结果会被骗过）；铁律是 fake 一律显式签名、禁 `**kwargs` 兜底，调用点传错参必须让 TypeError 在测试里直接炸。动机固化：09-19 夜间全量拒答事故（端口契约两参 `(library_id, doc_ids)` 而调用点只传一参，TypeError 被 except 吞成空节点 → 检索恒 0 条，已修 1a6cb0c，CI 当时全绿）；经变异验证（临时抽掉引擎 knowledge_local 调用的 `formula` 参 → 契约用例如期 TypeError 爆红，还原后全绿）
- 回归验证：五测试套件全绿（tests/angineer-core + services/angineer-core/tests 218 绿——2 例 meta_query 规则失败为 HEAD 预存在、commit 607623d 有记录；tests/aichat-api 77 绿；evals-core 102 绿；tests/unit 与 7 例预存失败基线逐一对上）+ 未推送代码本地 nightly 冒烟集预演（open-ragbench-smoke-v1 25 题，与生产同一条流水线、同版端口注入，企微已禁发、结论重定向临时目录）：green、hit@1(doc) 0.85（检索无归零——事故签名不存在）、errored 0、门禁 +11pp 且逐题比对零变差

## v0.2.69

- 拒答话术改为「知识库未能检索到相关答案」：`REFUSAL_ANSWER_TEXT` 全文替换，`REFUSAL_MARKERS` 同步换子串「未能检索到相关答案」，`is_refusal` / 半拒答删头句 / `strip` 逻辑自动跟随（单一真相在 `agent_messages`）；prompt 指令同步（模型自答话术必须与新标记一致，否则检测失效）；`answer_eval.is_refusal` 主标记改引引擎常量，消除第二处硬编码；测试/注释/文档全量同步（含混血串清理）
- 解析结构层新增「短行段落提升为 title」：MinerU 把「独立单行短文本」（报纸栏目名/文章标题/小节名）输出成 `paragraph` 而 GT 标成 `title`——200 页基线 106 个漏检 title 里 93 个的落点就是它。判据只用几何 + 长度（高度 ≤1.5% 页高 且 ≤24 字），排除署名、项目符号项、书后索引条目、报头日期行、页面联系方式、句中标点、接续标记七类——文本形态规则（编号/结尾冒号/英文短行/【】）逐条实测精确率仅 18–32%、合用净亏 −2.54pp，已否证；PoPo 无额外信号（200 篇改标 title 数 = 0）、`middle.json` 在 OCR 路径下每段只有 1 行且无字号字段，两条替代路线也有数据否证。正文页提升的标题取 `level = 当前最深 + 1`，避免 `canonical_builder` 按默认 1 处理冲散 `section_path`。实测（真实入口 A/B，对照组逐位复现归档基线）：title 召回 79.2%→85.7%、结构层块召回 90.248%→91.009%、tau 不变；官方 markdown 口径七项指标逐位不变（markdown 确实变了 23 个文件，官方评测器会归一化 `#`）。新增单测 20 例，含走真实入口 `build_structured_from_rawfiles` 的端到端闸
- 管理后台解析记录列表新增「文件夹」列：行内下拉列出当前库全部文件夹（label 用「父 / 子」路径），选中即调 `knowledgeApi.updateNode(doc_id, { parent_id })` 移动；切库/手动刷新/上传后顺带取节点上下文（轮询静默刷新不带，省一半请求）；节点接口失败保留上一次上下文（下拉暂时不可用、不打断列表），文档挂在已删除/未知目录时兜底显示「（未知目录）」而不是裸 id；`vue-tsc -b` 通过
- 文档：三方对比刷新到 DGX MinerU 修复后口径——原「MinerU 单独」列取自 09-13 的离线存盘结果、与修复后的我们全链不同尺，改由同批 `mineru_raw/origin.zip` 重新提取（200/200、3.4.5/hybrid）后重评；结论更新为我们全链 A① 与上游 MinerU 重合（六项逐位相同、文本 0.0407 vs 0.0408），区分度在 A②（块召回 90.25% vs 79.06%）；09-13「文本落后 1.5 倍」落差消失的归因标注为未验证

## v0.2.68

- 引擎 `__init__` 惰性导出（PEP 562，C1 库化第一批）：`import angineer_core.agent_messages` / `history_store` 等轻量子模块从 520ms+ 且隐式拉起 ai_inference/docs-core 整条依赖树，降为 29ms 零重依赖；34 个既有导出（IntentClassifier/Memory/ScopeContext/base_config/base_di 等）经 `__getattr__` 按需加载并缓存到 globals()，`from angineer_core import X` 用法逐字兼容
- 新增 `angineer_core/ports.py` 端口注册表（引擎不认识具体实现，组装层注入）：`policy_query` 本地节点加载回退（原函数内 `from docs_core.docs_service import`）与 `retrieval_pipeline` 降级链末端 phrase-rank（原 `from docs_core...reranker import`）改经 `register_local_nodes_loader` / `register_local_rerank` 消费；`docs_retrieval_client` 的 `KnowledgeNode`/`RetrievedItem` 同步改为引擎内同字段 pydantic 镜像（线契约即 HTTP JSON 载荷，docs-api 为序列化方）；aichat-api `main.py` 启动时注册 docs-core 适配器，nightly/evals 在 aichat-api 进程内跑 `run_policy_query` 同路径覆盖；未注册时按既有降级语义走（警告 + 空结果/跳过 rerank），不 import 具体包；生产容器启动日志已验证「引擎端口已注册」
- pyproject 剪依赖：摘除 `angineer-sop-core`（引擎对其零 import，纯死重）；`angineer-docs-core` 留待下一批（`agent_tools` ~450 行检索/图谱配方仍是实体耦合，需整体搬入 docs-core 侧适配器 = 登记的 RetrievalPort 收尾专项）
- 验证与回归：`tests/angineer-core` + `tests/aichat-api` 264 例全绿（`test_retrieval_pipeline` 改用注册 fake 适配器替代 mock docs_core）；`tests/unit` 与干净树失败集逐条一致（stash 对比，7 例预存 flaky）；`import angineer_core.policy_query` 实测不再加载 docs_core；生产冒烟 guest/agent 全 200

## v0.2.67

- 聊天历史服务端化（计划 B 路线全量落地，docs/plan-chat-history.md）：新包 `services/chat-history` 两层解耦——引擎侧只加 `HistoryStore` Protocol + `scope_hash_for`（与池 key 同算法单真相源，既有引擎文件零改动），`store/` sqlite DAO（chat_sessions/chat_messages/chat_runs/chat_guests 四表落 `data/chat.sqlite`）+ `routes/` FastAPI 路由（身份解析注入、不 import aichat-api）；aichat-api 组装：run_end 落库（客户端断开按 cancelled 兜底补写）、池内新建 session 才回灌一次（D11，池命中不灌、按 scope_hash 过滤防跨 scope 串话）、SSE 契约升级 `X-Chat-Frame-Version` 响应头 + run_end 帧 `msg_seqs`；存储初始化失败自动降级纯内存池（行为同改造前）；顺手删 `QueryRequest.history` 死字段（全仓库无读取点）
- 无登录硬门 + 游客档（D2/D6/D12）：打开站点直接是聊天页（有 token 先 refreshMe 验证，过期落回游客态并补签 cookie）；游客 cookie `ag_guest_id`（HttpOnly）匿名桶由 `ip:` 升级为 `g:`——同 NAT 游客不再撞池，30 轮闸（`ANGINEER_GUEST_ROUNDS` 默认 30）按 g: 桶 user 消息数计，满阈值 → 403 `detail.code=login_required` → 前端弹登录页（当前对话不丢），登录自动 claim 把 g: 会话并入账号历史（先到先得幂等，在跑 run 落库 owner 跟随会话行当前归属不产生孤儿行），`session_id` 前后一致对话原地继续；会话管理端点：列表（带 message_count/后端复刻 deriveTitle/50 上限）/详情（AIChatMessage 形状）/单删/按库清空/展示字段快照 PUT（D10：seq 服务端唯一权威，只接受已下发 msg_seq、未知序号整体拒）/claim/`POST /chat/guest` 幂等签发；清 cookie 绕过登记为已知取舍（D12，引导登录而非强身份闸门）
- 前端历史切 HTTP（apps/user-web）：`chatHistory.ts` 三函数签名不变改 async，服务端真相源 + localStorage 降级缓存（懒加载 apiClient，HTTP 失败自然落缓存）；saveSession 只发带 msgSeq 消息的展示字段补丁（citations/thinking_trace/strategy，D8）；首次列表成功按 id 差集幂等补录 localStorage 存量（本地标记防重试风暴，服务端 session_id 幂等）；恢复会话以服务端详情为真相（失败降级缓存）；活跃会话 id 按库持久化 `ag_active_session_v1`、仅「新建对话/换库」轮换，`rotateSession` 单一生成点修 ChatHome 与 useAIChat 双生成 id 互相覆盖；契约贯通：run_end 帧 `msg_seqs` → transport `QueryResponse.msg_seqs?` → `AIChatMessage.msgSeq?`（可选字段向后兼容）→ PATCH，`useAIChat.startNewChat(explicitId?)` 支持宿主指定 id
- 90 天保留期 GC（D4/§7 默认值）：`ANGINEER_CHAT_RETENTION_DAYS`（默认 90）统一清消息/审计 run（created_at）、会话（updated_at 活跃自动续命）、游客档（last_seen_at）；`scripts/chat_db_gc.py` dry-run 默认、`--apply` 执行、`--vacuum` 归还空间（Dockerfile 白名单 COPY 进容器 `/app/scripts/`）；游客闸阈值 `ANGINEER_GUEST_ROUNDS` 可配（本地与服务器 .env 已按要求暂调 5 轮，删行即回默认 30）
- 测试与验证：pytest 新增 41 例（存储 round-trip/行级隔离/scope 过滤/回灌一次/claim 竞态/29→30 边界/PUT 拒未知 seq/GC 四类表/import 幂等/游客 cookie 优先级/env 阈值/fail-open），`tests/aichat-api` + `tests/angineer-core` 261 例全绿；前端 node:test 6 例（降级路径/淘汰/活跃 id 容错）；vue-tsc（user-web/aichat-ui）0 错、vite build 通过；`tests/unit` 7 例失败与干净树基线逐条一致（预存问题）

## v0.2.66

- A 层解析回归一键入口：`scripts/run_parse_regression.py` 把 predict + A② + A① 串成一条命令，并管住此前没人管的「这次和上次比怎么样」——页集合是否一致、官方产物目录残留会不会读到旧分、指标散在两套 JSON 里的比对口径，统一收进 `evals_core/parse_regression.py`（只加编排与口径守卫，评测口径一行不改）；数据集/GT/三方表两列改自动探测（`OMNIDOCBENCH_DATA` > 仓库内 `data/omnidocbench` > `D:/AI/tools/OmniDocBench_data` > `~/OmniDocBench_data`，取第一个真有 `images/` 的，显式参数仍最优先），探不到时列出试过的候选并报错、不糊一个错路径继续跑，最小用法收敛为 `python scripts/run_parse_regression.py --limit 200 --seed 42`
- 首份 fresh 基线 + 「换量尺」纪律：2026-09-17 首跑 200 页（`page_ids_hash` 与既有基线相同）——predict 45min（13.6s/页、200/200 零失败）/ A② 38s×2 / A① 官方镜像 3.2min，端到端 ≈50min，文档里 1.2–1.5h 的估计按实测改写；与 2026-09-13 那份「离线重投影」逐项吻合（≤0.08pp），09-14 担心的「管道表→HTML 表换量尺不可比」在聚合指标上没发生；官方评分 199/200（`yanbaopptmerge_yanbaoPPT_620` 因预测只有文本+整图、GT 无可比块而在逐页明细缺席，聚合 `page_count` 仍 200）如实记进文档；首次跑的 Δ 文案改为「本次即成为基线，Δ 从下次跑开始」，不再与 `--baseline none` 混着说「无基线」；09-13 归档目录（2.7MB）已删，文档改指向「数字登记在 omnidocbench-baseline.md + 重建命令」，免得下次照着文档找目录找不到
- 解析回归只读看板（评测页第三项 tab）：`admin-web` 头部加「日常测试 | 夜间测试 | 解析回归」，数据来自开发机跑完 `--publish` 同步上来的结论层文件、服务器只读不执行（A① 要 18GB 官方镜像、只装开发机，页面已明写）；`run_parse_regression.py` 产出 `publish.json`（指标五组 + Δ + 逐类目/逐文档类型 + 渲染元信息）并随 `--publish` 同步白名单文件（~140KB，不带 predictions/official），`--republish` 给早于本功能的 run 补档；后端 `evals_routes.py` 照 nightly 只读范式加 `GET /evals/parse-regression`（列表 + 详情）——列表按结果日期倒序而非目录名（`baseline-*` 会被字典序排到 `2026*` 前面、看着像最新），三种键格式先归一化成 `YYYY-MM-DD` 再比，鉴权与既有两个只读视图共用 `require_admin_session`（模块级装饰器，放段落内会 NameError）；测试 24 例（端到端入档、发布载荷契约、路由鉴权/排序/损坏降级/路径穿越），本机实测列表返回两条真 run
- 看板三轮实看反馈收敛：四张柱状图（A① 三方 / A② 两方 / 逐类目 / 逐文档类型）颜色改按来源分（参考模型蓝 / MinerU 青 / 我们绿，统一半透明对手 + 实心我们自己），「谁更好」改用 ★ 而非颜色、并列同标（初版只标了 MinerU 一侧，会被读成某方更好）；方向标注三处同给（图 y 轴后缀 ↑/↓、表格「方向」列、图下说明），方向值来自载荷 `metric_meta` 单点定义——初稿把「A② 预测块被解释率」写成越小越好，查 `evals_core.HIGHER_IS_BETTER` 实为 8 项全部越大越好，已按权威定义改正；顺带修 `barWidth` 致同组柱子紧贴（改 `barMaxWidth` + `barGap`/`barCategoryGap`）、图高按行数自适应、删掉与「方向」列重复的四处图下长说明（压成图上角标）、离线重投影行的 Δ 不再标红（那是换量尺的差、不是回归，行上本就有橙色标记）、窄窗口下 tab 被挤成竖排与宽表挤压（标签 `nowrap` + 表格横向滚动）；另修点「解析回归」tab 无反应（`App.vue` 另抄了一份硬编码 key 白名单，加第三个视图时没同步 → 改认 `viewItems` 单点清单），并把「本机在跑（目录已建、publish.json 还没写）」从误标的「离线重投影」区分为「未同步」、读不出来的标「损坏」、未同步目录默认收起（corrupt 仍常显）、未同步行日期列从 run_id 解出（不再出现裸 `—`）
- 逐类目/逐文档类型给出参照物与规则化结论：此前只有绝对值、既没有判据也不该拍阈值，参照物取同一批 GT 上 MinerU 原生 `content_list` 的结果（A② 产物里本来就有，之前只取了我们的）——载荷补 `by_category_mineru` / `by_data_source_mineru`，两张图改双序列（MinerU 青 / 我们绿）+ 逐行 ★，两张表补「召回率(MinerU 原生)」列，行名带样本数（n=GT 块数 / 页数，小样本别过度解读），并修一处会误导的措辞（「最差类目」原只给绝对值，`list_group` 0% 看着像自家短板，现附 MinerU 同项并分档：两边都低 ≤0.5pp → 属类目本身难/未建模、不是我们的短板）；结论改由本机按数字算（`evals_core.parse_regression.build_conclusions`，随载荷入档并写进 `summary.md` 的「## 结论（往哪改）」段，前端只渲染、不各算一遍），纪律为差距 <0.005 一律按持平（没测噪声底、D5 未做）、没有对手数据就不出结论段（无比较对象时任何「优劣」都是臆造）、提示只指方向不断言根因；据此第一次看清类目层面落后 MinerU 三项——`table_caption` −9.4pp、`table_footnote` −4.2pp、`text_block` −1.1pp（其余 11 项同分、`title` 领先 78pp）；表格同步标问题行（红=落后 MinerU 超 0.5pp、黄=低于本表平均，tooltip 分「类目本身难/未建模，不是我们的锅」与「绝对水平低但非短板」两档，实测逐类目 3 红 5 黄、逐文档类型 2 黄），并删掉 `summary.md` / 结构层报告两个折叠面板（每一项都已在面板里原生渲染、纯重复；结构层报告多出的逐类目样本数与公式相似度列已补进面板，归档文件照旧生成并 publish）
- aichat 匿名跨库检索与会话池跨用户串话修复（安全性）：线上探到 `POST /api/chat/agent` 匿名未鉴权（空 body 返回 422 ＝ 路由可达且中间件放行，服务器 `.env` 未设 `ANGINEER_CHAT_AUTH_REQUIRED`），而库归属校验对无身份请求原样透传 `library_id`——无凭证即可检索任意知识库；改为匿名只能落在 `default` 库、显式请求其它库 403（API key 单库 / 登录按授权集 / 管理员跨库三条分支不变）；另一处是 `session_id` 由客户端生成（`chat-<毫秒时间戳>`，可枚举）而池 key 只有 `scene:session_id:scope_hash`，同库不同用户猜中同一 id 就会让模型把他人 `history` 当上下文回答——池 key 前置身份位（`u:<id>` / `k:<id>` / `ip:<XFF 最左哈希>`），并修好测试里长期为红的 5 例（匿名锁库契约重写、新增跨 owner 池隔离用例、`route_pre` SSE 用例补绑定库的 API key 与 `_FakeSession.wait_for_idle` 与前置 warning 帧过滤），`tests/aichat-api` 由 27 例 5 红 → 36 例 0 红

## v0.2.65

- nightly 报告窗口对齐：结论归档保留 3→90 天、与 run 明细同窗——此前 run 明细留 90 天而结论只留 3 份，夜间测试页结论列表「只剩 3 条」，3–90 天历史结论不可回看（归档窗口改走 paths 统一常量，单测 1 例）
- docs-ui 清理：删除僵尸函数 `mapParseStageText` 及其旧 6 阶段解析词表与常量（全仓调用点 0、删除前验证；阶段抽屉实际走新实现），README 3 处登记同步移除——独立包已发 angineer-docs-ui v0.3.0（删公共导出属 breaking，其 CHANGELOG 已标 removed 与迁移说明），主仓库产品无感

## v0.2.64

- fts 写入锁防护——批量解析不再随机假失败：批量断点续跑每文档一个线程并发 `save_document` 打同一 `knowledge_index.sqlite`，大事务排队击穿 `timeout=10`（2026-09-15 实锤 3 篇在 fts 阶段 `database is locked` 误判 failed——resume 修复后 GPU 闸不再顺带串行化中后段，写并发面暴露），`sqlite_utils` 新增按库文件的进程内写锁 + busy 指数退避重试（跨进程写者兜底，非 busy 照旧立抛），`canonical` 三个写入口改锁+重试 wrapper；save_document 为 clear+insert 幂等形状、busy 抛出时事务已回滚可安全重放，内部清库直调 txn 避免嵌套自死锁（回归 8 例，含 6 线程并发全落库）
- parse_records 文件元信息自愈：终态（completed/failed）状态更新时若流水行 `file_name` 仍空，从节点补齐一次——只填空列绝不覆盖已有值、节点查不到保持现状（行为下界＝改前），另加迁移遗留 Windows 路径按 `\` 拆名（Linux 的 `os.path.basename` 不认反斜杠，否则整串 `D:\...` 当文件名显示）（2026-09-16 实锤：5 条流水（DredgeAI晨会 3 + OpenRAG 2）09-06 建行时节点查失败、三个元信息列停在空值且此后永不回填 → 管理端「文件名称」列永久空白；存量 5 行已在服务器按真实源文件一次性补好，本条代码只防再发；回归 5 例）

## v0.2.63

- 修解析中断积压：管理后台「解析 / 批量解析」改 resume 语义——部署重启打断的文档只补缺失阶段、复用 MinerU 产物，不再整条重跑（2026-09-15 实测 12 篇因重启永久挂 failed：启动自愈只标死不重排、无自动重试，唯一断点入口 v1 `/resume` 按 api_key_id 归属校验，管理员上传（该字段为 NULL）任何 key 都 403——错误文案给的出路对管理员不存在）；阶段记录已全终态却仍挂 failed 的（自愈对「只差图描述」类任务的误盖章）按阶段记录直接把状态同步正，零任务零 GPU；resume 阶段计算收敛进 docs-core 单一真相源——docs-api 复制版的流水线顺序缺 `figure_describe` 已实际漂移（resume 永远补不上图描述阶段），另修启动自愈文案
- 评测磁盘三级保留策略：run 明细 ≤3 天（含当天，按北京日界）全量、3–90 天裁 6 类过程快照字段（retrieval_debug / retrieved_items / evidences 等，约占体积 99%，保留 scores / answer / citations 供补判与溯源）、>90 天整 run 删除（基线指针与 running 保护）——一晚 526 题明细实测 ≈230 MiB，新策略稳态 <1G，取代旧「仅保留最近 3 轮」；上线后建议对现有库手动 `VACUUM` 一次收缩
- 向量索引静默失败收口：`rebuild_document_vectors` / `rebuild_document_indexes` 应写条数 ≠ 实写条数即抛错、并返回实写条数（2026-09-14 生产实踩：209 chunk 文档重建后 Qdrant 0 个点却无异常——qdrant `upsert_records` 对空向量记录只 logger.info 跳过，`clear_document` 之后全被跳过＝清库假成功；触发空向量的一次性 provider 异常未复现，不臆断归因；该问题由 B 层素材检查 ③ chunk→向量 抓出；回归 4 例）
- 公式符号校正禁止「删下标」式修正（归因纠正：真因是自家 step04 `_build_symbol_corrections` 规则，非 PoPo 上游）：说明段泛指参数（无下标的 F、a）被当真相源，把 `F_{1}`→`F`、`a_{1}`→`a` 直接丢语义；新守卫＝参数无下标且公式 token 有下标则拒绝修正（只允许补/换下标，即 OCR 纠错的设计方向）；回归 3 例含两枚生产样本
- 生产存量符号校正重算：`scripts/repair_symbol_corrections.py` 按新守卫重算已落库 corrected 字段（只用节点自带的 `formula_semantics.formula_params`，过滤逻辑与守卫等价，不依赖部署顺序）——462 个 symbol_mismatch 块中 205 块修正全被否（清空字段）、4 块部分保留（改写），坏修正合计 209 块涉 51 篇，余 257 块均为合法「补下标」方向（此前按 462 全量报规模偏大）；重索引 51/51 成功、素材检查终验 ok，jsonl 备份 `data/backups/symbol-fix-20260915/`；素材检查摘要的 symbol_mismatch 文案同步改口（「PoPo 校正」→「符号校正（step04 规则）」）

## v0.2.62

- ci(deploy)：构建缓存不再每次全清，改为「14 天内使用过 + 总量上限 8GB」——依赖安装层可跨部署复用（实测单次构建里前端 `pnpm install` 约 7.5 分钟、后端 11 个服务包 `pip editable` 编译 wheel 约 21 分钟，此前每次重装，两个 Dockerfile 分层本已正确）。上限取 8GB 的依据：后端 site-packages 实测 496MB、前端 builder 的 node_modules 同量级
- 评测报告：nightly 的「正确率」列统一为「正确题数 / 题数」（与门禁 `overall_score`、基线、回归矩阵同一口径，分母含拒答题），`judge` 连续分均值移入「分布口径」表并标明仅作诊断、不参与门禁（原先同一份报告里两个「正确率」差 5 个点、分母差 39，必然误读）
- 新增 `scripts/repair_plain_text.py`（B 路线）：就地补齐历史文档被吃掉的 5 类块 `plain_text`（chart / page_footnote / page_aside_text / code / algorithm）后重建索引，不重跑 MinerU/PoPo/structure——结构层其余差异不在本次修复范围，全量 structure 重跑按页计费（≈160 篇 13433 页）代价过高；默认 dry-run，`--apply --reindex` 才写盘
- nightly 单测改回密闭：素材检查与续跑探测不再打真实存储（此前整套会卡在 `test_stopped_pipeline_publishes_nothing`，现 592 passed / 4 skipped，27.6 秒）

## v0.2.61

- 修解析流水表：所有入库路径统一写入——此前管理端「日常维护」入口漏写，导致台账缺篇（评测与运维统计都读这张表）
- 修 B 层「素材检查」三项：「未索引」断言改按解析阶段事实判定（评测库与单阶段补跑不再被误报）、阶段状态改为一次性只读查询（原先经 `get_docs_service` 会加载整个知识库）、② 探针改用链路真正消费的字段 `plain_text_corrected` 并把符号改动单列报出
- 前端 `angineer-aichat-ui` 升到 0.1.9：补 `sideEffects` 声明（仅样式文件），组件模块可被消费方 bundler tree-shake
- 工程：发版收敛为 `pnpm release vX.Y.Z` 一条命令——固化「tag → sync:version → release commit → 一条命令推分支与 tag」的顺序（分两条命令推与部署的版本校验有竞态），并让 deploy.yml 拉取改为 `git fetch origin main --tags`，使「Version consistency check」真正生效（此前部署目录长期 0 个 tag，校验一直走 skip）

## v0.2.60

- 修 markdown 投影：默认保留 HTML 表（此前拍平成管道表，合并单元格结构在交付面丢失）——同批 200 页实测表格 TEDS +3.3 点、表格文字 Edit_dist 降 11.5 倍，差距全在投影这一步
- 修 `extract_plain_text`：补 chart / page_footnote / page_aside_text / code / algorithm 五个分支——这五类块的文本此前被整条链路吃掉（不进 chunk、不进检索）
- 修图描述阶段并发：`describe_figures_in_graph` 缺省 `max_workers=4` 而阶段调用未传参，使 `FIGURE_DESCRIBE_MAX_CONCURRENCY` 的任务级闸门被绕开（单篇可同时发 4 个远端 VLM 请求，端到端 8 路），现阶段路径固定每篇一次请求、由该闸门单点控制（上界 2，env 可调），同时把阶段编号由 3.1/3.2/4.5 统一为位次 1..9，`title` 不再带序号前缀
- 新增自建结构层评测 ParseStruct（jsonl 口径）——直接量 RAG 依赖的那一层（此前只看官方 markdown 口径），附 200 页抽样基线，A/B/C 三层评测框架定稿并写清引用规范
- 新增 B 层「素材检查」并固化进 nightly——断言 jsonl→canonical/chunk→向量 的传递性（素材有没有原样送到检索层），结论卡片独立成行、通过与否都可见
- 新增三方解析质量对比（参考模型 / MinerU 3.4.5 单独 / 我们全链）——把表格文字 8 倍差距归因到 markdown 投影这一步，并在修复后重建索引验证「改的内容真能被搜到」（全库 FTS 12/12 进前 100，其中 10 篇第 1）
- 修夜间报告口径可见性：`hit@*(sec)` 列的分母只是「有 section 级金标」的题（v3 = 473，另有 14 题仅有文档级金标、39 道拒答题无检索金标），现补一行口径说明（粒度不齐或有题无金标时出现），避免读者把 sec 列均值误当全量均值
- 修 39 道拒答题的 `gold_answer`：原先直接拷了上游的原始事实答案，与「本题期望拒答」自相矛盾（该字段从不参与判分），现统一归一化为哨兵文本并加归一化后置断言防回归
- 修基线快照被部署抹掉：基线移出版本控制（`data/evals/baseline`），此前服务器 `git reset --hard` 会把刚钉的基线清掉，nightly 只能拿旧基线比对，跑出过假绿灯
- 前端 `angineer-docs-ui` 升到 0.2.4：解析阶段列表补齐 `figure_describe`——阶段抽屉此前整行不渲染该阶段（状态/耗时/错误与「启动」按钮都没有），进度条会显示原始英文 key 且分母写死 8（现为 9），并修 `xlsx` 依赖为 SheetJS CDN 0.20.3 tarball（npm 版 0.18.5 无修复，CVE-2023-30533 / CVE-2024-22363）

## v0.2.59

- 修 `angineer-ai-inference`（DGX 车队缺陷报告，2026-09-12）：`LLM_CONFIGS` 里端点级 `enable_thinking` 声明被静默丢弃——`LLMModelConfig` 有该字段，但 `load_llm_models_from_env()` 构造时漏传，Pydantic 于是取默认 `None`，使「端点级显式 > `ANGINEER_CHAT_TEMPLATE_KWARGS` > 隐式 URL/模型名规则」里最高优先级整层失效（直连 vLLM/DGX 的端点三层全不命中、发不出任何思考控制），loader 现补传该字段，并新增宽松布尔解析 `_opt_bool()`：`true/false` 与 `"true"/"false"/"1"/"0"/"yes"/"no"/"on"/"off"` 都认，识别不了按默认值处理并 WARNING，不把原值直接透传给 pydantic（避免 `.env` 写成字符串或拼错时在加载期炸掉调用方进程）
- 同类隐患一并修：`enabled` 原为 `bool(item.get("enabled", True))`，而 `bool(None)` 是 `False`——线上 `.env` 里 `"enabled": null` 的 `Qwen3.8-Flash` 因此被静默**禁用**（并非"未声明取默认值"），现改走 `_opt_bool(default=True)`，`null`/缺失即启用，修复后实测该模型 `enabled=True` 且声明生效（`extra_body={'chat_template_kwargs': {'enable_thinking': False}}`）
- 修 `ANGINEER_CHAT_TEMPLATE_KWARGS` 空值/非法 JSON 打挂请求：`_build_extra_body` 内的 `json.loads(os.getenv(...))` 无 try/except、无空值短路，而它就在每次请求的热路径上——运维把该键清空（键保留、值清空）或写错 JSON 即全量请求抛 `JSONDecodeError`，又因该异常是 `ValueError` 子类，消费方容易把它误映射成"请求非法"（本库自身不做 400/500 映射，异常直接抛给调用方），现空串/纯空白按未设置处理、非法 JSON 降级为未设置并 WARNING，变量未设置时的行为与旧版完全一致
- `ai-inference` 测试补 loader 级回归：此前**没有任何测试走 `load_llm_models_from_env()`**（全是手工构造 `LLMModelConfig`，正好绕过漏参那一行，这是缺陷能活到线上的直接原因），新增断言覆盖声明 `false/true/省略`、字符串形态、无法识别值、`enabled: null`、以及"线上 `.env` 真实形态 → `extra_body`"的端到端用例，并修掉 `test_enable_thinking_switch.py` 一处假覆盖（原 `_extra_body_for` 把环境变量 patch 成空串后又 `pop`，实际测的是"未设置"，空串路径从未被覆盖）

## v0.2.58

修复「部分阶段运行永远停在 processing」：`_run_parse_task` 非全量分支的状态推导此前要求全部 9 个注册阶段终态，导致 v1 API 按 stages 子集解析（默认 structure、或解析评测用的 source_prep→structure 五阶段链）的任务在全部阶段完成、进度 100% 后状态仍永远卡 processing——现在未启动且无历史记录的阶段按 skipped 计入整体判定（不写库，仅修状态推导；OmniDocBench 接入实踩）。新增 `scripts/run_omnidocbench_eval.py`：OmniDocBench（文档解析公认基准，1651 标注页）解析质量评测工具，predict 子命令把页图转单页 PDF 走完整解析链（MinerU+PoPo+Solo）下载每页 markdown（断点续跑），eval 子命令调用官方 Docker 评测器算文本 Edit_dist / 表格 TEDS / 公式 CDM / 阅读顺序指标；v3 题集 JSON（v2 487+拒答 39）入库。

## v0.2.57

紧急修复 DeepEval 判分路径语法错误（v0.2.51 引入）：一次编辑事故把 `geval.measure(test_case)` 与上一行右括号粘连成 `)        geval.measure(...)`，导致 `judge_deepeval.py` 整体语法不合法——由于该模块是判分时才惰性导入，本地单测（未覆盖该编辑后重跑）与部署构建均未拦截，v0.2.51 起生产 deepeval 判分路径全题报 `invalid syntax`（今晚 nightly 前修复，否则全题判分失败）。本地冒烟复测：拒答题正确拒答、普通题 engine=deepeval 判分 1.0 + contextual_precision 0.78，链路完整。同时：nightly 默认题集切换 v3 = v2(487) + 拒答题集 v2(39) 合并（拒答题带 refusal_expected，报告「拒答专项」自动拆分统计，正确拒答计为答对）；新增 `scripts/build_subset_v3.py`（幂等构建 DB 行 + 数据集 JSON + manifest v3，本地/生产同构）。

## v0.2.56

- 后台模块切页提速（知识库/评测集/经验库）：管理端三个模块视图改 keep-alive 常驻缓存，切回不再重挂载与重取数据——实测切回耗时 135–468ms 降到 17–54ms，列表/树随 DOM 一起立刻回来（此前每次切换都要重挂载整棵组件树并重打 2–3 个列表接口）。缓存后 `onMounted` 只跑一次，各视图在 `onActivated` 静默补刷（知识库记录、评测集测试集与运行状态、经验库树列表、夜间健康与报告），`onDeactivated` 收口全部轮询表（知识库 records 与解析阶段、评测 run 轮询、夜间面板 15s 心跳），避免缓存实例在后台持续打接口（实测失活 66s 内 0 次请求）；经验库带未保存改动时不刷树，防止覆盖编辑。`include` 按组件名匹配，三个视图各补 `defineOptions({ name })`——名字对不上会静默不缓存
- 知识库落地路由关键路径减 895KB：`KnowledgeStats` 只取一个 `useKnowledgeParse` 却走 `@angineer/docs-ui` barrel，连带 re-export 的 `PDF_Viewer`/`OfficePreview` 把 katex(320KB)、pdf.js、xlsx 一起拖进落地路由块（生产该路由静态下载 2015KB→1120KB、路由自身块 725KB→86KB；dev 首屏渲染前请求 145→87、到表格可用 753ms→389ms。全量产物大小不变——预览栈只是从「挡住首屏」改成「空闲预热/按需加载」）。改法三处：docs-ui 新增 `./composables/useKnowledgeParse` 子路径出口并改子路径导入；7 个 UI 包（docs-ui/aichat-ui/sop-ui/evals-ui/table-ui/ui-kit/smartree）补 `sideEffects`（仅样式文件算副作用，源码模块可被 tree-shaking 丢弃——实测「仅补 sideEffects」与「仅改子路径导入」各自独立达成同一结果，CSS 规则计数逐项未变）；`vite.config.ts` 预置 echarts/pdfjs-dist/xlsx/docx-preview/katex/@vue-flow/core 进 `optimizeDeps.include`，避免首次切到该模块时 Vite 重新预打包并强制整页 reload

## v0.2.55

- 修解析任务在闸门前失败/退出时未让出「图描述」闸门序号，导致后续文档永久卡在「等待图描述 VLM 资源」（2026-09-11 生产实踩）：`ParseOrchestrator._run_parse_task` 的 `finally` 只对 MinerU / PoPo 闸门调了 `skip(arrival_seq)`，漏了图描述闸门。在 `raw_parse` 就失败的任务（如 MinerU 504）永远到不了 4.5，其提交序号会永久占据该闸门的 `_next_seq`，此后所有文档都在 4.5 排队直到 docs-api 重启——且表现为「整齐地在排队」而非报错，极易误读成 VLM 端点慢
- 补齐 `_FIGURE_DESCRIBE_GATE.skip(arrival_seq)`（三个闸门必须成套，任一漏 skip 都会让它永久停在死序号上），新增回归测试 `tests/test_gate_skip_on_task_exit.py`：撤掉该行即失败
- 图描述 VLM 并发上限改为可配置：新增 `FIGURE_DESCRIBE_MAX_CONCURRENCY` 开关（代码默认 1，即严格按提交序号先来先服务；生产置为 2，允许两篇文档的图描述并行，代价是同时压 VLM 端点）
- `.env.example` 全量重建：该文件自 `a03984f`（LLM/embedding 端点 IP→https 迁移）起被一次编码往返损坏——UTF-8 字节被按 GBK 误读，全部中文注释变乱码，且部分换行被吞、把赋值并进了注释行，导致 `POPO_INFERENCE_RETRIES` / `DOCS_EMBEDDING_PROVIDER` / `DOCS_VECTORSTORE_PROVIDER` / `JWT_SECRET` 四个赋值实际失活（模板照抄即丢配置），`LLM_CONFIGS` 里的「(付费)」也成了乱码。以最后一个干净版本 `da59aad` 的注释为骨架、保留损坏后新增的三段（企微 Webhook / Qdrant / 评测判分引擎）重建；逐字段比对文件名、URL、JSON 与 priority 均未变，仅注释与换行恢复，`python-dotenv` 解析出 17 个 active 键且无格式异常

## v0.2.54

单题评测卡片显示判分引擎与扩展维度（evals-ui，monorepo 内部包随主仓库发版）：`SemanticEvalResult` 类型补 `eval_engine`/`faithfulness_score`/`answer_relevancy_score`/`contextual_precision_score` 可选字段；「语义评判」区在 DeepEval 判分的题目上显示 DeepEval 徽标（tooltip 说明口径差异），判分理由下方按存在与否展示忠实度/相关性/上下文精度三个扩展维度分数（各带口径说明 tooltip）——判错归因时一眼区分「检索到了但答错」与「根本没检索到」。vue-tsc 通过。

## v0.2.53

夜间维护页判分引擎口径标记（配合 v0.2.51 DeepEval 切换防误读）：维护列表新增「判分」列——DeepEval 判分条目显示蓝色 DeepEval 徽标（tooltip 说明口径差异），legacy/历史条目分别显示 legacy/—；单日明细分析区对 DeepEval 条目追加口径提示行（「口径比 legacy 严约 8 个百分点，与 legacy 基线的分差含口径差，不代表系统回归」）。前端类型补 eval_engine 字段；vue-tsc 与 vite build 通过。

## v0.2.52

- 修「检索范围为空」被静默伪装成「没有检索到足够证据」（2026-09-11 生产与开发同时踩到）：检索用的文档范围取自后端**进程内内存节点列表**（`docs_service.self.nodes`），该列表为空时 `DenseRetriever.retrieve` 首行 `if not doc_nodes: return []` 直接返回，三个检索阶段全部 0.00s、结果恒 0 条，边界规则据此判定「无证据」并让模型输出拒答，而全过程**无告警、无日志**。排查取证：复现时请求 payload 完全干净（`library_id=default`、`doc_ids=[]`），失败窗口内既无 `/api/embed` 也无 qdrant 查询（dense 若执行必然先嵌入），而同一进程两分钟前的请求能取到 20 条。现在空范围会显式报出来——接口先发一条 `warning` 事件（界面弹横幅：「知识库当前没有可检索的文档（或检索服务尚未就绪），稍后重试通常可恢复」，不再让用户读到一句假的「没有证据」），`_load_doc_nodes` 同时打 WARNING 带上「该库节点总数 N / 进程内已加载库数 M」，`doc_ids` 匹配不到文档也单独告警
- 检索器异常不再被静默吞掉：`_run_knowledge_search` 里 dense/sparse/clause 抛错时原先只塞进 `sources["<x>_error"]` 且从不输出，日志形态与「确实没结果」完全一致，只能靠两侧日志对拍才能分辨，改为逐条 WARNING 留痕

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

# 代码问题修复计划

> 生成时间：2025-05-11
> 来源：全代码库分析报告

---

## 问题清单总览

| 编号 | 问题 | 严重程度 | 风险等级 | 预计工时 |
|------|------|---------|---------|---------|
| 1.1 | 模块间耦合度过高 — sys.path.append + 直接 import | 严重 | 高 | 2h |
| 1.2 | 全局单例滥用 | 中等 | 低 | 30min |
| 2.1 | 会话池并发安全问题 | 中等 | 低 | 15min |
| 2.2 | 评测并发控制锁可能死锁 | 中等 | 中 | 1h |
| 2.3 | 意图分类 L0 闲聊误判 | 中等 | 低 | 30min |
| 3.1 | 重复代码 — 前端入口抽取 | 低 | 低 | 20min |
| 3.2 | LLM 客户端 base_url 处理逻辑重复 | 低 | 极低 | 5min |
| 3.4 | 异常处理过于宽泛 | 中等 | 低 | 15min |
| 4.2 | AIChat 组件直接使用 fetch | 低 | 低 | 20min |

---

## 1.1 模块间耦合度过高

### 问题描述

多个服务模块通过 `sys.path.append` 和直接 import 强耦合，违反依赖倒置原则。

### 涉及文件

| 文件 | 行号 | 问题 |
|------|------|------|
| `services/api-server/main.py` | L28-L44 | `sys.path.append` 脆弱导入 |
| `services/angineer-core/src/angineer_core/dispatcher.py` | L28-L30, L100-L102, L120-L121 | 直接 import `docs_core`、`sop_core` |
| `services/angineer-core/src/angineer_core/classifier.py` | L10-L11 | 直接 import `ai_inference` |
| `services/evals-core/src/evals_core/runner/_query_helper.py` | L42-L43 | 直接 import `angineer_core.dispatcher` |

### 修改步骤

1. **新建 `angineer_core/contracts.py`**
   - 定义 `KnowledgeProvider(Protocol)` 契约，声明 `list_nodes(library_id)` 方法
   - 定义 `SopProvider(Protocol)` 契约，声明 `load_all()` 方法
   - 定义 `LLMProvider(Protocol)` 契约，声明 `chat()` 方法

2. **修改 `Dispatcher.__init__`**
   - 新增 `knowledge_provider: KnowledgeProvider | None = None` 参数
   - 新增 `sop_provider: SopProvider | None = None` 参数
   - 删除内部的 `from docs_core...` import

3. **修改 `Dispatcher.dispatch`**
   - 将 `from docs_core.knowledge_service import knowledge_service` 替换为 `self._knowledge_provider`
   - 将 `sop_loader` 参数改为从 `self._sop_provider` 获取

4. **修改 `Dispatcher._dispatch_sql`**
   - 将内部的 `from docs_core...` import 改为通过 `self._knowledge_provider` 调用

5. **修改 `main.py` 启动组装**
   - 在创建 `Dispatcher` 时注入 `knowledge_service` 和 `sop_loader` 实例
   - 删除 `sys.path.append`，改用 `pyproject.toml` 的本地包安装

6. **修改 `_query_helper.py`**
   - 创建 `Dispatcher` 时注入依赖

### 验收标准

- [ ] `angineer-core` 模块内无 `from docs_core` / `from sop_core` 直接 import
- [ ] `main.py` 中无 `sys.path.append`
- [ ] 所有现有测试通过
- [ ] `pnpm harness` 通过

---

## 1.2 全局单例滥用

### 问题描述

多个核心服务使用模块级全局单例，缺乏生命周期管理，测试隔离困难。

### 涉及文件

| 文件 | 行号 | 问题 |
|------|------|------|
| `services/ai-inference/src/ai_inference/llm_client.py` | L527-L534 | 模块加载时立即初始化 |
| `services/angineer-core/src/angineer_core/base_config.py` | L117-L123 | `_config` 全局单例 |
| `services/docs-core/src/docs_core/knowledge_service.py` | 模块级 | `knowledge_service = KnowledgeService()` |

### 修改步骤

1. **修改 `llm_client.py` 底部**
   - 删除模块加载时的 `llm_client = get_llm_client()` 自动初始化
   - 保留 `get_llm_client()` 懒加载单例

2. **修改 `classifier.py` L10**
   - 将 `from ai_inference.llm_client import llm_client` 改为 `from ai_inference.llm_client import get_llm_client`
   - 使用时调用 `get_llm_client()`

3. **修改 `dispatcher.py` L30**
   - 将 `from ai_inference.llm_client import llm_client as default_llm_client` 改为 `from ai_inference.llm_client import get_llm_client`
   - 在 `__init__` 中使用 `self._llm_client = llm_client or get_llm_client()`

4. **修改 `knowledge_service.py`**
   - 将模块级 `knowledge_service = KnowledgeService()` 改为懒加载函数：
   ```python
   _instance: Optional[KnowledgeService] = None
   
   def get_knowledge_service() -> KnowledgeService:
       global _instance
       if _instance is None:
           _instance = KnowledgeService()
       return _instance
   ```

5. **修改所有引用**
   - `from docs_core.knowledge_service import knowledge_service` → `from docs_core.knowledge_service import get_knowledge_service`
   - 调用处改为 `get_knowledge_service()`

### 验收标准

- [ ] 无模块级立即初始化的单例
- [ ] 所有单例通过 `get_xxx()` 懒加载
- [ ] 现有测试通过

---

## 2.1 会话池并发安全问题

### 问题描述

`_SESSION_POOL` 是普通字典，在 FastAPI 异步环境下存在竞态条件。

### 涉及文件

| 文件 | 行号 | 问题 |
|------|------|------|
| `services/api-server/main.py` | L127-L148 | 会话池无锁保护 |

### 修改步骤

1. **新增线程锁**
   ```python
   _SESSION_POOL: Dict[str, SessionEntry] = {}
   _SESSION_POOL_MAX_SIZE = 200
   _SESSION_POOL_TTL_SECONDS = 3600 * 2
   _session_lock = threading.Lock()  # 新增
   ```

2. **修改 `_get_or_create_session`**
   ```python
   def _get_or_create_session(scene: str, session_id: Optional[str]) -> SessionEntry:
       with _session_lock:
           key = f"{scene}:{session_id or 'default'}"
           entry = _SESSION_POOL.get(key)
           if entry:
               entry.last_active_at = time.time()
               return entry
           if len(_SESSION_POOL) >= _SESSION_POOL_MAX_SIZE:
               _evict_expired_sessions()
           entry = SessionEntry(session_key=key, scene=scene, last_active_at=time.time())
           _SESSION_POOL[key] = entry
           return entry
   ```

3. **修改 `_evict_expired_sessions`**
   ```python
   def _evict_expired_sessions() -> None:
       with _session_lock:
           now = time.time()
           expired = [k for k, v in _SESSION_POOL.items() if now - v.last_active_at > _SESSION_POOL_TTL_SECONDS]
           for k in expired:
               del _SESSION_POOL[k]
           if len(_SESSION_POOL) >= _SESSION_POOL_MAX_SIZE:
               sorted_keys = sorted(_SESSION_POOL, key=lambda k: _SESSION_POOL[k].last_active_at)
               for k in sorted_keys[: len(sorted_keys) // 4]:
                   del _SESSION_POOL[k]
   ```

### 验收标准

- [ ] 会话池所有操作在锁保护下
- [ ] 并发压力测试无数据竞争

---

## 2.2 评测并发控制锁 — 改为任务队列

### 问题描述

使用 `threading.Lock` 做全局评测并发控制，长时间任务持有锁，新请求直接被拒绝。

### 涉及文件

| 文件 | 行号 | 问题 |
|------|------|------|
| `services/evals-core/src/evals_core/runner/suite_runner.py` | L17-L19, L175-L250 | 互斥锁阻塞 |

### 修改步骤

1. **新增队列和 worker**
   ```python
   import queue
   from dataclasses import dataclass
   from typing import Callable
   
   @dataclass
   class EvalTask:
       run_id: str
       dataset_id: str
       questions: List[Dict[str, Any]]
       override_doc_ids: Optional[List[str]] = None
   
   _eval_queue: queue.Queue[EvalTask] = queue.Queue()
   _current_task: Optional[EvalTask] = None
   _worker_thread: Optional[threading.Thread] = None
   ```

2. **新增 `_eval_worker()` 函数**
   ```python
   def _eval_worker():
       while True:
           task = _eval_queue.get()
           if task is None:  # 哨兵，退出
               break
           global _current_task
           _current_task = task
           try:
               _run_suite_impl(task.run_id, task.dataset_id, task.questions, task.override_doc_ids)
           finally:
               _current_task = None
               _eval_queue.task_done()
   ```

3. **修改 `start_eval_run`**
   - 将任务放入队列而非检查锁
   - 返回队列位置信息

4. **新增状态查询**
   ```python
   def get_eval_queue_status() -> Dict[str, Any]:
       return {
           "queue_size": _eval_queue.qsize(),
           "current_run_id": _current_task.run_id if _current_task else None,
           "is_running": _current_task is not None,
       }
   ```

5. **新增 API 端点**
   - `GET /api/evals/queue/status` 返回队列状态

### 验收标准

- [ ] 多个评测请求可排队执行
- [ ] 前端可查询队列状态
- [ ] 无死锁风险

---

## 2.3 意图分类 L0 闲聊误判

### 问题描述

L0 闲聊检测使用简单关键词匹配，优先级最高，导致混合查询被误判。

### 涉及文件

| 文件 | 行号 | 问题 |
|------|------|------|
| `services/angineer-core/src/angineer_core/classifier.py` | L117-L130 | L0 关键词误判 |

### 修改步骤

1. **新增实质性内容检测函数**
   ```python
   def _has_substantive_content(query: str) -> bool:
       """检测查询是否包含实质性业务内容。"""
       # 规范编号
       if STANDARD_CODE_PATTERN.search(query):
           return True
       # 条款编号
       if CLAUSE_ID_PATTERN.search(query):
           return True
       # 参数赋值
       if PARAM_PATTERN.search(query):
           return True
       # 多个数值
       if len(NUM_VALUE_PATTERN.findall(query)) >= 2:
           return True
       # L1-L4 关键词
       if any(kw in query for kw in L1_KEYWORDS + L2_KEYWORDS + L3_KEYWORDS + L4_KEYWORDS):
           return True
       # 长句（>15字且非纯闲聊）
       if len(query) > 15:
           return True
       return False
   ```

2. **拆分 L0 关键词**
   ```python
   L0_PURE_CHAT_KEYWORDS = ["你好", "您好", "嗨", "hi", "hello", "再见", "拜拜", "谢谢", "感谢"]
   L0_AMBIGUOUS_KEYWORDS = ["帮我", "怎么用", "能做什么", "有什么功能", "你是谁", "你叫什么"]
   ```

3. **修改 `_rule_based_classify` L0 检测**
   ```python
   # L0: 闲聊检测
   has_pure_chat = any(kw in query for kw in L0_PURE_CHAT_KEYWORDS)
   has_ambiguous = any(kw in query for kw in L0_AMBIGUOUS_KEYWORDS)
   has_substantive = _has_substantive_content(query)
   
   if has_pure_chat and not has_substantive:
       return IntentResult(
           intent_level="L0",
           intent_type="casual_chat",
           service_mode="casual_chat",
           reason="纯闲聊，无业务内容",
       )
   
   # 有歧义关键词但包含实质性内容，继续后续分类
   ```

### 验收标准

- [ ] "你好，请问 GB 50010 中混凝土强度如何确定？" 不被误判为 L0
- [ ] "谢谢，请帮我计算..." 不被误判为 L0
- [ ] 纯 "你好" 仍正确识别为 L0

---

## 3.1 重复代码 — 前端入口抽取

### 问题描述

`web-console` 和 `admin-console` 的入口文件几乎完全相同。

### 涉及文件

| 文件 | 问题 |
|------|------|
| `apps/admin-console/src/main.ts` | 与 web-console 重复 |
| `apps/web-console/src/main.ts` | 与 admin-console 重复 |
| `apps/admin-console/vite.config.ts` | 结构相似 |
| `apps/web-console/vite.config.ts` | 结构相似 |

### 修改步骤

1. **新建 `packages/ui-kit/src/bootstrap.ts`**
   ```typescript
   import { App } from 'vue'
   import { Router } from 'vue-router'
   import { useThemeStore } from '../stores/theme'
   
   export function bootstrapApp(app: App, router: Router): void {
     app.use(createPinia())
     app.use(router)
     app.use(Antd)
     
     const themeStore = useThemeStore()
     themeStore.initTheme()
     
     app.mount('#app')
   }
   ```

2. **修改两个 `main.ts`**
   ```typescript
   import { createApp } from 'vue'
   import App from './App.vue'
   import router from './router'
   import { bootstrapApp } from '@angineer/ui-kit/bootstrap'
   import 'ant-design-vue/dist/reset.css'
   import './styles/index.less'
   
   const app = createApp(App)
   bootstrapApp(app, router)
   ```

3. **新建 `apps/shared/vite.base.ts`**
   ```typescript
   import { defineConfig } from 'vite'
   import vue from '@vitejs/plugin-vue'
   import { resolve } from 'path'
   
   export function createBaseConfig(port: number, extraAliases: Record<string, string> = {}) {
     return defineConfig({
       plugins: [vue()],
       resolve: {
         alias: {
           '@': resolve(__dirname, 'src'),
           ...extraAliases,
         },
       },
       css: {
         preprocessorOptions: {
           less: {
             javascriptEnabled: true,
             additionalData: `@import "${resolve(__dirname, '../../packages/evals-ui/src/styles/variables.less')}";\n`,
           },
         },
       },
       server: {
         port,
         proxy: {
           '/api': {
             target: `http://localhost:${process.env.API_SERVER_PORT || 8000}`,
             changeOrigin: true,
           },
         },
       },
     })
   }
   ```

4. **修改两个 `vite.config.ts`**
   ```typescript
   import { createBaseConfig } from '../shared/vite.base'
   import { resolve } from 'path'
   
   export default createBaseConfig(5173, {
     '@angineer/ui-kit': resolve(__dirname, '../../packages/ui-kit/src'),
     // ... 其他 alias
   })
   ```

### 验收标准

- [ ] 两个应用正常启动
- [ ] 无重复代码

---

## 3.2 LLM 客户端 base_url 处理逻辑重复

### 问题描述

`_call_openai` 和 `_call_openai_stream` 中重复了相同的 URL 清理逻辑。

### 涉及文件

| 文件 | 行号 | 问题 |
|------|------|------|
| `services/ai-inference/src/ai_inference/llm_client.py` | L260-L262, L306-L308 | 重复代码 |

### 修改步骤

1. **新增私有方法**
   ```python
   @staticmethod
   def _normalize_base_url(base_url: str) -> str:
       """标准化 base_url，移除 /chat/completions 后缀。"""
       if base_url.endswith("/chat/completions"):
           base_url = base_url.replace("/chat/completions", "")
       return base_url
   ```

2. **修改 `_call_openai`**
   ```python
   def _call_openai(self, config: LLMModelConfig, ...):
       base_url = self._normalize_base_url(config.base_url)
       # ...
   ```

3. **修改 `_call_openai_stream`**
   ```python
   def _call_openai_stream(self, config: LLMModelConfig, ...):
       base_url = self._normalize_base_url(config.base_url)
       # ...
   ```

### 验收标准

- [ ] 无重复代码
- [ ] LLM 调用正常

---

## 3.4 异常处理过于宽泛

### 问题描述

多处使用裸 `except Exception` 捕获所有异常，可能掩盖真正的 bug。

### 涉及文件

| 文件 | 行号 | 问题 |
|------|------|------|
| `services/angineer-core/src/angineer_core/dispatcher.py` | L108-L110, L172-L175 | 裸 except |
| `services/evals-core/src/evals_core/runner/answer_eval.py` | L131-L138 | 裸 except |
| `services/evals-core/src/evals_core/runner/suite_runner.py` | L230-L233 | 裸 except |
| `services/api-server/main.py` | L49-L63 | 全局异常处理器 |

### 修改步骤

1. **新建 `angineer_core/base_utils.py`**
   ```python
   FATAL_EXCEPTIONS = (KeyboardInterrupt, SystemExit, MemoryError, GeneratorExit)
   
   def is_fatal_exception(exc: BaseException) -> bool:
       """判断是否为致命异常，不应被捕获。"""
       return isinstance(exc, FATAL_EXCEPTIONS)
   ```

2. **修改各处 except 块**
   ```python
   try:
       # ...
   except Exception as e:
       if is_fatal_exception(e):
           raise
       # 原有处理逻辑
   ```

3. **修改全局异常处理器**
   ```python
   @app.exception_handler(Exception)
   async def global_exception_handler(request, exc):
       if is_fatal_exception(exc):
           raise
       # 原有处理逻辑
   ```

### 验收标准

- [ ] `KeyboardInterrupt` 可正常终止程序
- [ ] 正常异常仍被捕获处理

---

## 4.2 AIChat 组件直接使用 fetch

### 问题描述

`AIChat.vue` 和 `useAIChat.ts` 直接使用原生 `fetch`，未统一封装。

### 涉及文件

| 文件 | 行号 | 问题 |
|------|------|------|
| `packages/ui-kit/src/components/common/AIChat.vue` | L111-L124 | 直接 fetch |
| `packages/ui-kit/src/composables/useAIChat.ts` | L291 | 直接 fetch |
| `apps/admin-console/src/views/EvalManage.vue` | L544 | 直接 fetch |

### 修改步骤

1. **新建 `packages/ui-kit/src/api/client.ts`**
   ```typescript
   const API_BASE = ''
   
   export const apiClient = {
     async get<T>(path: string): Promise<T> {
       const resp = await fetch(`${API_BASE}${path}`)
       if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
       return resp.json()
     },
     
     async post<T>(path: string, body: unknown): Promise<T> {
       const resp = await fetch(`${API_BASE}${path}`, {
         method: 'POST',
         headers: { 'Content-Type': 'application/json' },
         body: JSON.stringify(body),
       })
       if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
       return resp.json()
     },
   }
   ```

2. **新增具体 API 方法**
   ```typescript
   export const llmApi = {
     getConfigs: () => apiClient.get<LLMConfig[]>('/api/llm_configs'),
   }
   
   export const queryApi = {
     query: (payload: QueryRequest) => apiClient.post<QueryResponse>('/api/query', payload),
   }
   ```

3. **修改 `AIChat.vue`**
   ```typescript
   import { llmApi } from '../../api/client'
   
   const fetchModels = async () => {
     loadingModels.value = true
     try {
       const data = await llmApi.getConfigs()
       models.value = data.filter(m => m.configured).map(m => ({ value: m.name, label: m.name }))
     } catch (error) {
       console.error('获取模型列表失败:', error)
       models.value = [{ value: 'default', label: '默认模型' }]
     } finally {
       loadingModels.value = false
     }
   }
   ```

4. **修改 `useAIChat.ts`**
   ```typescript
   import { queryApi } from '../api/client'
   
   const queryData = await queryApi.query(queryRequest)
   ```

5. **修改 `EvalManage.vue`**
   - 同样替换为 `apiClient` 调用

### 验收标准

- [ ] 无直接 `fetch('/api/...')` 调用
- [ ] AI 对话功能正常
- [ ] 错误处理统一

---

## 执行计划

### 第1批（低风险，可并行）

| 任务 | 预计工时 | 依赖 |
|------|---------|------|
| 3.2 LLM base_url 重复 | 5min | 无 |
| 3.4 异常处理过于宽泛 | 15min | 无 |
| 4.2 AIChat fetch 封装 | 20min | 无 |
| 3.1 前端入口抽取 | 20min | 无 |

### 第2批（中风险，顺序执行）

| 任务 | 预计工时 | 依赖 |
|------|---------|------|
| 1.2 全局单例 → 工厂函数 | 30min | 第1批完成 |
| 2.1 会话池加锁 | 15min | 无 |
| 2.3 L0 闲聊误判修复 | 30min | 无 |

### 第3批（高风险，需集中测试）

| 任务 | 预计工时 | 依赖 |
|------|---------|------|
| 1.1 模块解耦 Protocol + DI | 2h | 第2批完成 |
| 2.2 评测队列化 | 1h | 无 |

---

## 验收清单

- [ ] 所有修改完成后运行 `pnpm lint`
- [ ] 运行 `pnpm harness` 确保后端测试通过
- [ ] 运行 `pnpm build` 确保前端构建成功
- [ ] 手动测试核心功能：
  - [ ] AI 对话正常
  - [ ] 知识库检索正常
  - [ ] 评测任务正常执行
  - [ ] 意图分类正确

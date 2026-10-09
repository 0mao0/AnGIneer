// 2026-10-09（设计稿 design-user-kb-access-scope.md §4 R4/B1 定版）：原 MAX_LIBRARY_SELECTION = 5 已移除——
// 多库勾选无硬顶（「选了 N 个组 M 个库就应该是 M 个库去检索」业主口径）；
// 服务端 ANGINEER_MAX_CHAT_LIBRARIES 截断同批移除，>20 库仅记 warning（FANOUT_WARN_THRESHOLD）。
export {}

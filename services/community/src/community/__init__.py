"""AnGIneer Community — 公开内容分类树 + 公开绑定 + 用户投稿池。

设计见 `docs/design-public-eval-sop-pages.md`。三句话边界：

- 本包是 `data/platform/community.sqlite`（分类树 / 公开绑定 / 投稿池）的**唯一写者**；
- 对上游 `evals.sqlite`（测试集与题目）与 `data/platform/sops/`（SOP）**只读**，
  用户投稿永不写进正式库——「先不做审核」意味着投稿必须先落在可分离的池子里；
- 路由不自己解身份：`resolve_principal(request) -> (owner_key, user_id|None)` 由宿主注入
  （与 chat-history 同一契约）。
"""

__version__ = "0.1.0"

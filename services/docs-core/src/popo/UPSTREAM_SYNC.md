# PoPo 已内化（2026-09-09）

本目录原为 git submodule（双 remote：origin=官方 opendatalab/MinerU-Popo 只读追踪，fork=0mao0/MinerU-Popo
实际部署源头）。2026-09-09 起**内化为 AnGIneer 主仓库的普通目录**，不再是 submodule。

## 内化理由

- 我们的 POPO_CONFIGS 定制（model_utils.py 多端点+超时+MAX_TOKENS）官方 PR 从未被合并，fork 是唯一部署源头
- 官方上游活跃度低（内化时最后提交 2026-07-31）
- submodule 增加部署/打包复杂度（不进 wheel、deploy 需 submodule update、库化障碍）

## 上游同步点记录（备查）

- 内化时对齐的上游 commit：`97d560172361e772b3d079ce9eac35796b998782`（2026-07-31，origin/master HEAD）
- 内化时本目录内容 = fork master `e03a99f`（含全部本地定制）
- 若上游未来复活需要同步：对照上述 hash cherry-pick 官方变更，注意保留 `post_processing/model_utils.py`
  的 POPO_CONFIGS 定制（连接失败/超时自动切下一端点；未配置不打请求；POPO_API_TIMEOUT / POPO_MAX_TOKENS）

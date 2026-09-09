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

## 同步操作 runbook（vendor 模式，看 diff 手工移植）

内化后本目录与上游无 git 关联，同步 = 定期 diff 评审 + 手工移植（类似发行版维护上游包）：

```bash
# 1. 上游官方仓库的独立 clone（一次性，放主仓库外）
git clone https://github.com/opendatalab/MinerU-Popo <主仓库外路径>/MinerU-Popo
cd <主仓库外路径>/MinerU-Popo && git fetch origin

# 2. 看上游自同步点以来的变更（同步点 hash 见上一节，每次同步后更新它）
git log --oneline <上次同步点>..origin/master
git diff <上次同步点>..origin/master --stat

# 3. 逐文件看 diff 并移植到本目录对应文件；跳过：
#    - post_processing/model_utils.py 中与 POPO_CONFIGS 定制冲突的部分（保留我方版本，
#      仅移植其逻辑改进，如新 prompt/解析修复）
#    - eval/、output_cases/ 等产物目录（不入库，popo 自带 .gitignore 已排除）

# 4. 验证：本地解析一篇文档跑通 popo 阶段；更新本文档的同步点 hash 并随代码提交
```

**注意**：`model_utils.py` 是唯一的我方定制文件，上游对它的任何改动都需手工 reconcile；
其余文件未定制，上游修复可直接覆盖。

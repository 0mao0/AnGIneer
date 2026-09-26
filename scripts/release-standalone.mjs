// 独立包发版：对齐 release.mjs 的思路，把「人肉约定」固化成脚本闸门。
//
// 用法：
//   pnpm release:standalone aichat-ui 0.2.1              # 完整发版（含推送）
//   pnpm release:standalone aichat-ui 0.2.1 --no-push    # 到 tag 为止，打印推送命令
//   pnpm release:standalone aichat-ui 0.2.1 --dry-run    # 只检查并打印计划
//
// 为什么要有这个脚本（2026-09-26 aichat-ui 0.2.0 实踩三连坑）：
//   1. 裸 `git tag <pkg>@x.y.z` 在主仓库上下文执行——worktree 与主仓库共享对象库，
//      tag 静默打到主仓库 HEAD（甚至是并行会话刚提交的无关 commit），推上远端后
//      publish workflow 检出一棵没有包布局的树，零报错地不发版。
//      → 本脚本打 tag 一律显式指定 worktree HEAD sha，并在推送后校验远端 sha。
//   2. 发版验证只跑了改动相关的测试文件，全量 `pnpm test` 漏网（queue 测试挂死
//      直到 CI 挂满 6h 才发现）。
//      → 前置检查强制跑完 package.json 里的 typecheck 与 test 脚本。
//   3. 步骤散在 AGENTS.md 里靠人记（sync → bump → CHANGELOG → tag → 映射推送 →
//      README 登记），顺序错了没有反馈。
//      → 全部固化为顺序执行 + 逐步校验。
//
// 手写只剩一处：worktree 的 CHANGELOG.md 里 `## x.y.z` 段落（脚本校验存在）。
// 版本号仍须用户事先确认（本脚本不决定版本号，只执行）。
import { execSync, spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(__dirname, '..');
const argv = process.argv.slice(2);
const DRY_RUN = argv.includes('--dry-run');
const NO_PUSH = argv.includes('--no-push');

// 与 sync-standalone.ps1 保持一致的映射（改一处必须同步另一处）
const REPO_NAME_OVERRIDES = { smartree: 'angineer-smartree-ui' };
const SOURCE_PATH_OVERRIDES = { 'ai-inference': 'services/ai-inference' };
const SUPPORTED = ['docs-ui', 'aichat-ui', 'smartree', 'table-ui'];

function sh(cmd, { cwd = ROOT, inherit = false } = {}) {
  if (inherit) {
    execSync(cmd, { cwd, stdio: 'inherit', shell: true });
    return '';
  }
  return execSync(cmd, { cwd, encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'], shell: true }).trim();
}

function trySh(cmd, opts = {}) {
  try {
    return sh(cmd, opts);
  } catch {
    return null;
  }
}

function fail(msg) {
  console.error(`[release-standalone] 中止：${msg}`);
  process.exit(1);
}

const args = argv.filter((a) => !a.startsWith('--'));
if (args.length !== 2 || !/^\d+\.\d+\.\d+$/.test(args[1])) {
  fail('用法：pnpm release:standalone <pkg> <x.y.z> [--no-push] [--dry-run]（版本号不带 v）');
}
const [pkg, bare] = args;
if (!SUPPORTED.includes(pkg)) {
  fail(
    `不支持的包「${pkg}」。本脚本覆盖 ${SUPPORTED.join('/')}；` +
      'ai-inference 是 Python 包走另一套（tag 全名 angineer-ai-inference@x.y.z + PyPI OIDC）'
  );
}
const repo = REPO_NAME_OVERRIDES[pkg] || `angineer-${pkg}`;
const srcPath = SOURCE_PATH_OVERRIDES[pkg] || `packages/${pkg}`;
const worktree = resolve(ROOT, '.worktrees', repo);
const remoteUrl = `git@github.com:0mao0/${repo}.git`;
const splitBranch = `split/${pkg}`;
const localTag = `${pkg}@${bare}`;
const remoteTag = `v${bare}`;

function checkPreconditions() {
  // 1) 主仓库在 main 且工作区干净（sync 同样要求；发版动作不应夹带无关改动）
  const branch = sh('git rev-parse --abbrev-ref HEAD');
  if (branch !== 'main') fail(`主仓库当前分支是 ${branch}，发版只允许在 main 上`);
  const dirty = trySh('git status --porcelain --untracked-files=no');
  if (dirty) fail(`主仓库工作区有未提交改动，先处理：\n${dirty}`);

  // 2) worktree 存在、在 split 分支、干净
  const wtBranch = trySh(`git -C "${worktree}" rev-parse --abbrev-ref HEAD`);
  if (!wtBranch) fail(`worktree 不存在：${worktree}（先跑 scripts/sync-standalone.ps1）`);
  if (wtBranch !== splitBranch) fail(`worktree 分支是 ${wtBranch}，应为 ${splitBranch}`);
  const wtDirty = trySh(`git -C "${worktree}" status --porcelain --untracked-files=no`);
  if (wtDirty) fail(`worktree 有未提交改动，先处理：\n${wtDirty}`);

  // 3) 主仓库源码树与 split 分支树一致（除受保护文件）——不一致说明 sync 没跑
  //    diff-filter=d 排除删除类（独立仓库独有文件不算差异），受保护文件有意分叉
  const treeDiff = trySh(
    `git diff --name-only --diff-filter=d ${splitBranch} "HEAD:${srcPath}" -- ` +
      `"." ":(exclude)package.json" ":(exclude)CHANGELOG.md" ":(exclude)LICENSE"`
  );
  if (treeDiff) {
    fail(`主仓库 ${srcPath} 与 ${splitBranch} 树不一致，先跑 sync-standalone：\n${treeDiff}`);
  }

  // 4) worktree HEAD 不落后于远端 main（领先可以，发版 commit 会一起推）
  const remoteMain = trySh(`git ls-remote ${remoteUrl} refs/heads/main`);
  const wtHead = sh(`git -C "${worktree}" rev-parse HEAD`);
  if (remoteMain) {
    const remoteSha = remoteMain.split(/\s/)[0];
    if (remoteSha && !trySh(`git merge-base --is-ancestor ${remoteSha} ${wtHead}`) && remoteSha !== wtHead) {
      fail(`worktree HEAD 落后于远端 main（远端 ${remoteSha.slice(0, 7)} 不在本地历史里），先同步`);
    }
  }

  // 5) 版本未占用：本地 tag、远端 tag、npm（npm 查询失败只警告）
  if (trySh(`git rev-parse -q --verify "refs/tags/${localTag}"`)) {
    fail(`本地已存在 tag ${localTag}（重发请先明确删除并说明理由）`);
  }
  if (trySh(`git ls-remote --tags ${remoteUrl} "${remoteTag}"`)) {
    fail(`远端已存在 tag ${remoteTag}（重用已推 tag 必须人工确认后手动删远端 tag）`);
  }
  const pkgName = JSON.parse(readFileSync(resolve(worktree, 'package.json'), 'utf-8')).name;
  const npmExisting = trySh(`npm view "${pkgName}@${bare}" version 2>nul`);
  if (npmExisting) fail(`npm 上已存在 ${pkgName}@${bare}，不能再发同版本`);

  // 6) CHANGELOG 已手写当版段落
  const changelog = readFileSync(resolve(worktree, 'CHANGELOG.md'), 'utf-8');
  const sectionRe = new RegExp(`^## ${bare.replace(/\./g, '\\.')}\\s*$`, 'm');
  if (!sectionRe.test(changelog)) {
    fail(`worktree CHANGELOG.md 缺少「## ${bare}」段落——先发版手写，再跑本脚本`);
  }

  // 7) 全量验证（0.2.0 实踩：只跑改动相关文件，queue 测试挂死漏网）：
  //    在主仓库包目录跑（worktree 无 node_modules；上一步已证明两边 src 树一致）
  const pkgJson = JSON.parse(readFileSync(resolve(ROOT, srcPath, 'package.json'), 'utf-8'));
  const scripts = pkgJson.scripts || {};
  const pkgCwd = resolve(ROOT, srcPath);
  const pnpm = process.platform === 'win32' ? 'pnpm.CMD' : 'pnpm';
  for (const name of ['typecheck', 'test']) {
    if (!scripts[name]) continue;
    console.log(`[release-standalone] 跑 ${name}（${srcPath}，全量）…`);
    const r = spawnSync(pnpm, ['run', name], { cwd: pkgCwd, stdio: 'inherit' });
    if (r.status !== 0) fail(`${name} 未通过，修复后重跑`);
  }

  return { wtHead };
}

function main() {
  console.log(`[release-standalone] 目标: ${pkg} ${bare}（${repo}，远端 tag ${remoteTag}）${DRY_RUN ? '（dry-run）' : ''}`);
  const { wtHead } = checkPreconditions();
  console.log('[release-standalone] 前置检查通过');

  const plan = [
    `worktree package.json version → ${bare}（如需要）`,
    `worktree commit: chore: ${localTag} 发版`,
    `git tag ${localTag} <worktree-HEAD-sha>   ← 显式 sha，不打裸 tag（09-26 实踩）`,
    NO_PUSH ? '(--no-push：跳过推送)' : `push ${splitBranch}:main 与 ${localTag}:refs/tags/${remoteTag}`,
    '校验远端 tag sha == worktree HEAD',
    'README 版本表登记（改文件不 commit，由用户提交）',
  ];
  if (DRY_RUN) {
    plan.forEach((s, i) => console.log(`  ${i + 1}. ${s}`));
    return;
  }

  // 1) bump version（保留文件原有格式，只换 version 行；断言无 BOM）
  const pkgJsonPath = resolve(worktree, 'package.json');
  const pkgRaw = readFileSync(pkgJsonPath, 'utf-8');
  if (pkgRaw.charCodeAt(0) === 0xfeff) fail('worktree package.json 带 BOM，先去掉');
  const bumped = pkgRaw.replace(/"version":\s*"[^"]*"/, `"version": "${bare}"`);
  if (bumped !== pkgRaw) {
    writeFileSync(pkgJsonPath, bumped, 'utf-8');
    console.log(`[release-standalone] package.json version → ${bare}`);
  }

  // 2) worktree commit（可能只有 CHANGELOG 或还有 version bump）
  sh('git add package.json CHANGELOG.md', { cwd: worktree });
  const staged = trySh('git diff --cached --name-only', { cwd: worktree });
  if (staged) {
    sh(`git commit -m "chore: ${localTag} 发版"`, { cwd: worktree, inherit: true });
  } else {
    console.log('[release-standalone] worktree 无待提交内容（version 已是目标值），跳过 commit');
  }

  // 3) 显式 sha 打 tag（核心防线：绝不依赖当前上下文 HEAD）
  const releaseSha = sh('git rev-parse HEAD', { cwd: worktree });
  sh(`git tag ${localTag} ${releaseSha}`);
  console.log(`[release-standalone] 已打 tag ${localTag} → ${releaseSha.slice(0, 7)}（worktree HEAD）`);

  if (NO_PUSH) {
    console.log('[release-standalone] --no-push：请手动推送：');
    console.log(`  git -C "${worktree}" push ${remoteUrl} ${splitBranch}:main`);
    console.log(`  git push ${remoteUrl} ${localTag}:refs/tags/${remoteTag}`);
    return;
  }

  // 4) 推送：分支与 tag 分别走 worktree/主仓库上下文，但 refspec 全部显式
  sh(`git push ${remoteUrl} ${splitBranch}:main`, { cwd: worktree, inherit: true });
  sh(`git push ${remoteUrl} ${localTag}:refs/tags/${remoteTag}`, { inherit: true });

  // 5) 远端校验：tag 必须指向发版 commit 本身（09-26 错推主仓库 commit 的事后闸门）
  const remoteTagSha = (sh(`git ls-remote ${remoteUrl} "refs/tags/${remoteTag}"`) || '').split(/\s/)[0];
  if (remoteTagSha !== releaseSha) {
    fail(`远端 tag sha ${remoteTagSha} != 发版 commit ${releaseSha}——请立即人工核查（不得静默放过）`);
  }
  console.log(`[release-standalone] 远端校验通过：${remoteTag} == ${releaseSha.slice(0, 7)}`);

  // 6) README 版本表登记（只改文件，commit/push 由用户决定）
  const readmePath = resolve(ROOT, 'README.md');
  const readme = readFileSync(readmePath, 'utf-8');
  const rowRe = new RegExp(`(\\| \\[${repo}\\][^|]*\\|) \`v[0-9.]+\` \\|`);
  if (rowRe.test(readme)) {
    writeFileSync(readmePath, readme.replace(rowRe, `$1 \`v${bare}\` |`), 'utf-8');
    console.log(`[release-standalone] README 版本表已登记 v${bare}（未 commit，由你提交）`);
  } else {
    console.warn('[release-standalone] 提醒：README 版本表未找到该包行，请手工登记');
  }
  console.log('[release-standalone] 完成。publish workflow 将随 tag 推送自动执行 npm publish；');
  console.log('[release-standalone] 若数分钟内无 Publish run，检查 tag 推送事件是否被吞（09-26 实踩过一次）。');
}

main();

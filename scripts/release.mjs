// 主仓库发版：一条命令完成「tag → sync:version → release commit → 一条命令推分支与 tag」。
//
// 用法：
//   pnpm release v0.2.61              # 完整发版（含推送分支与 tag）
//   pnpm release v0.2.61 --no-push    # 跑到 release commit 为止，打印待执行的推送命令
//   pnpm release v0.2.61 --dry-run    # 只做前置检查并打印计划，不改动任何东西
//
// 为什么要有这个脚本：deploy.yml 的「Version consistency check」比对 git tag / README / package.json，
// 而它依赖 tag 与分支**同批推送**——分两条命令推会有竞态（部署可能在 tag 落地之前 fetch，
// 于是校验看到"README 是新版、tag 还没到"而失败）。脚本把顺序固化，不靠人记。
//
// 需要人手写的只有两处，脚本会检查它们已按当版更新：
//   README 第 5 行：> **当前版本：X.Y.Z** —— <摘要>。详见 [CHANGELOG.md](CHANGELOG.md)。
//   CHANGELOG.md 的 `## vX.Y.Z` 段落（- 列表，条目与摘要一一对应）
import { execSync, spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(__dirname, '..');
const argv = process.argv.slice(2);
const DRY_RUN = argv.includes('--dry-run');
const NO_PUSH = argv.includes('--no-push');
const CHANGELOG_TAIL = '。详见 [CHANGELOG.md](CHANGELOG.md)。';

// 条目边界（与 AppBrand splitReleaseNotes / CHANGELOG 拆分共用）：括号、引号、反引号内的 。； 不算分隔
const OPENERS = '「『【《（';
const CLOSERS = '」』】》）';

function sh(cmd, { inherit = false } = {}) {
  if (inherit) {
    execSync(cmd, { cwd: ROOT, stdio: 'inherit' });
    return '';
  }
  return execSync(cmd, { cwd: ROOT, encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}

function trySh(cmd) {
  try {
    return sh(cmd);
  } catch {
    return null;
  }
}

function spawn(args, { quiet = false } = {}) {
  const r = spawnSync('git', args, { cwd: ROOT, stdio: quiet ? 'pipe' : 'inherit', encoding: 'utf-8' });
  return r.status === 0;
}

function splitTopLevel(text, separators) {
  const parts = [];
  let cur = '';
  let depth = 0;
  for (const ch of text) {
    if (OPENERS.includes(ch)) depth += 1;
    else if (CLOSERS.includes(ch)) depth = Math.max(0, depth - 1);
    else if (ch === '`') depth = depth ? 0 : 1;
    if (depth === 0 && separators.includes(ch)) {
      parts.push(cur);
      cur = '';
      continue;
    }
    cur += ch;
  }
  parts.push(cur);
  return parts.map((s) => s.trim()).filter(Boolean);
}

// 从 README 内容里取出「当前版本」行的摘要正文（—— 之后、「。详见 …」之前）
function extractSummary(readmeText) {
  const line = readmeText.split(/\r?\n/).find((l) => l.includes('当前版本：'));
  if (!line) throw new Error('README.md 未找到「当前版本」行');
  const dash = line.indexOf('——');
  if (dash < 0) throw new Error('README.md「当前版本」行缺少「—— 摘要」结构');
  const tail = line.slice(dash + 2);
  const cut = tail.lastIndexOf(CHANGELOG_TAIL);
  if (cut < 0) throw new Error(`README.md 摘要未以「${CHANGELOG_TAIL}」结尾`);
  return tail.slice(0, cut).trim();
}

function fail(msg) {
  console.error(`[release] 中止：${msg}`);
  process.exit(1);
}

function checkPreconditions(version, bare) {
  // 1) 分支
  const branch = sh('git rev-parse --abbrev-ref HEAD');
  if (branch !== 'main') fail(`当前分支是 ${branch}，发版只允许在 main 上`);

  // 2) 只允许 README.md / CHANGELOG.md 未提交（当版摘要与 CHANGELOG 条目是手写的，先改再发版）；
  //    其它已跟踪文件的改动一律拒绝——避免它们混进 release commit
  const dirty = sh('git status --porcelain --untracked-files=no')
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .filter((l) => {
      const path = l.slice(2).trim().split(' -> ').pop();
      return path !== 'README.md' && path !== 'CHANGELOG.md';
    });
  if (dirty.length) fail(`工作区有与本次发版无关的未提交改动，先处理：\n${dirty.join('\n')}`);

  // 3) tag 在本地与远端都必须不存在
  if (trySh(`git rev-parse -q --verify refs/tags/${version}`)) fail(`本地已存在 tag ${version}`);
  if (trySh(`git ls-remote --tags origin ${version}`)) fail(`远端已存在 tag ${version}`);

  // 4) README 摘要必须已按当版更新（与 HEAD 里的摘要逐字不同）
  const summary = extractSummary(readFileSync(resolve(ROOT, 'README.md'), 'utf-8'));
  const headReadme = trySh('git show HEAD:README.md');
  if (headReadme) {
    let headSummary = '';
    try {
      headSummary = extractSummary(headReadme);
    } catch {
      headSummary = '';
    }
    if (headSummary && headSummary === summary) {
      fail('README 第 5 行摘要与上一版逐字相同——请先手写当版摘要（版本号由本脚本的 sync:version 替换）');
    }
  }

  // 5) CHANGELOG 必须有当版段落；条目数与摘要条目数不一致只提醒
  const changelog = readFileSync(resolve(ROOT, 'CHANGELOG.md'), 'utf-8');
  const sectionRe = new RegExp(`^## v?${bare.replace(/\./g, '\\.')}\\s*$`, 'm');
  if (!sectionRe.test(changelog)) fail(`CHANGELOG.md 缺少「## v${bare}」段落`);
  const sectionBody = changelog.split(sectionRe)[1].split(/^## /m)[0];
  const bullets = sectionBody.split(/\r?\n/).filter((l) => l.trim().startsWith('- '));
  const summaryItems = splitTopLevel(summary, '；');
  const note =
    bullets.length === summaryItems.length
      ? ''
      : `提醒：README 摘要 ${summaryItems.length} 条 vs CHANGELOG ${bullets.length} 条，按约定应一一对应`;
  return { summary, bullets: bullets.length, summaryItems: summaryItems.length, note };
}

function main() {
  const args = argv.filter((a) => !a.startsWith('--'));
  if (args.length !== 1 || !/^v?\d+\.\d+\.\d+$/.test(args[0])) {
    fail('用法：pnpm release vX.Y.Z [--no-push] [--dry-run]');
  }
  const version = args[0].startsWith('v') ? args[0] : `v${args[0]}`;
  const bare = version.slice(1);

  console.log(`[release] 目标版本: ${version}${DRY_RUN ? '（dry-run）' : ''}`);
  const info = checkPreconditions(version, bare);
  if (info.note) console.warn(`[release] ${info.note}`);
  console.log(`[release] 前置检查通过：摘要 ${info.summaryItems} 条 / CHANGELOG 条目 ${info.bullets} 条`);

  const subject = `release: ${version}（${info.summary.length > 400 ? `${info.summary.slice(0, 400)}…` : info.summary}）`;

  if (DRY_RUN) {
    console.log('[release] 计划如下（未执行）：');
    [
      `git tag ${version}`,
      `node scripts/sync-version.mjs ${version}`,
      'git add CHANGELOG.md README.md package.json',
      `git commit -m "release: ${version}（<摘要，见 README 第 5 行>）"`,
      NO_PUSH ? '(--no-push：跳过推送)' : `git push origin main ${version}   ← 分支与 tag 同批推送`,
    ].forEach((s, i) => console.log(`  ${i + 1}. ${s}`));
    return;
  }

  if (!spawn(['tag', version])) fail(`打 tag 失败：${version}`);
  console.log(`[release] 已打 tag ${version}`);

  try {
    sh(`node scripts/sync-version.mjs ${version}`, { inherit: true });
    sh('git add CHANGELOG.md README.md package.json');
    if (!spawn(['commit', '-m', subject])) throw new Error('git commit 失败');
    console.log('[release] release commit 已提交');

    if (NO_PUSH) {
      console.log('[release] --no-push：请手动推送（务必一条命令、分支与 tag 同批）：');
      console.log(`  git push origin main ${version}`);
      return;
    }
    if (!spawn(['push', 'origin', 'main', version])) throw new Error('git push 失败');
    console.log(`[release] 已推送 main 与 ${version}`);
    console.log('[release] deploy.yml 将开始部署；其「Version consistency check」现在会真的比对 tag / README / package.json');
  } catch (err) {
    console.error(`[release] 失败：${err.message || err}`);
    console.error('[release] 回滚本地 tag（尚未推送则远端无痕）；工作区改动保留，修好后重跑本命令');
    spawn(['tag', '-d', version], { quiet: true });
    process.exit(1);
  }
}

main();

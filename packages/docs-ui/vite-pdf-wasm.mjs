/**
 * docs-ui: pdf.js wasm 资源插件
 *
 * pdf.js 6.x 的 JPEG2000 / JBIG2 / ICC 解码需要从 wasmUrl 目录按固定文件名加载
 * wasm 文件（openjpeg.wasm / jbig2.wasm / qcms_bg.wasm），加载失败时还会动态
 * import 同目录下的 JS 回退文件（*_nowasm_fallback.js）。
 *
 * 该插件在 dev / build 启动时把 pdfjs-dist 的 cmaps / standard_fonts / wasm 三个
 * 运行必需目录复制到应用自身的 public 目录，配合组件默认的 `${BASE_URL}` 即可
 * 开箱即用（v6 只有三个资源 URL 齐备时才会启用 worker fetch + wasm 解码），无需
 * 提交二进制资源，也不会依赖外部 CDN。接入方只需在 vite.config.ts 引入：
 *
 *   import pdfWasmPlugin from '@angineer/docs-ui/vite-pdf-wasm'
 *   plugins: [vue(), pdfWasmPlugin()]
 */
import { copyFileSync, existsSync, mkdirSync, readdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'

const require = createRequire(import.meta.url)

const REQUIRED_FILES = [
  'openjpeg.wasm',
  'openjpeg_nowasm_fallback.js',
  'jbig2.wasm',
  'jbig2_nowasm_fallback.js',
  'qcms_bg.wasm',
  'LICENSE_JBIG2',
  'LICENSE_OPENJPEG',
  'LICENSE_PDFJS_JBIG2',
  'LICENSE_PDFJS_OPENJPEG',
  'LICENSE_QCMS'
]

function copyDir(sourceDir, targetDir) {
  mkdirSync(targetDir, { recursive: true })
  for (const file of readdirSync(sourceDir)) {
    const source = join(sourceDir, file)
    if (!existsSync(source)) continue
    copyFileSync(source, join(targetDir, file))
  }
}

function copyPdfAssets(publicDir) {
  if (!publicDir) return
  let sourceDir
  try {
    sourceDir = join(dirname(require.resolve('pdfjs-dist/package.json')), 'wasm')
  } catch (error) {
    console.warn('[docs-ui:pdf-wasm] 找不到 pdfjs-dist，跳过 wasm 资源复制。', error)
    return
  }
  const pdfjsRoot = dirname(sourceDir)
  copyDir(join(pdfjsRoot, 'cmaps'), join(publicDir, 'cmaps'))
  copyDir(join(pdfjsRoot, 'standard_fonts'), join(publicDir, 'standard_fonts'))
  const targetDir = join(publicDir, 'wasm')
  mkdirSync(targetDir, { recursive: true })
  for (const file of REQUIRED_FILES) {
    const source = join(sourceDir, file)
    if (!existsSync(source)) continue
    copyFileSync(source, join(targetDir, file))
  }
}

export function pdfWasmPlugin() {
  let publicDir = ''
  return {
    name: 'docs-ui:pdf-wasm',
    enforce: 'pre',
    configResolved(config) {
      publicDir = config.publicDir
    },
    buildStart() {
      copyPdfAssets(publicDir)
    },
    configureServer() {
      copyPdfAssets(publicDir)
    }
  }
}

export default pdfWasmPlugin

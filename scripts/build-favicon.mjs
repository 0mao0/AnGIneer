// AnGIneer favicon 全套生成：SVG → PNG(16/32/180) → ICO(16+32)
// 幂等：重复执行覆盖写。真相源 = apps/user-web/public/favicon.svg
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { Resvg } from '@resvg/resvg-js'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const svg = readFileSync(join(root, 'apps/user-web/public/favicon.svg'), 'utf8')

function renderPng(size, background) {
  const opts = { fitTo: { mode: 'width', value: size } }
  if (background) opts.background = background
  return Buffer.from(new Resvg(svg, opts).render().asPng())
}

// ICO：6 字节头 + 每帧 16 字节目录 + PNG 数据（PNG 压缩帧，Vista+）
function packIco(frames) {
  const header = Buffer.alloc(6)
  header.writeUInt16LE(0, 0)          // reserved
  header.writeUInt16LE(1, 2)          // type = icon
  header.writeUInt16LE(frames.length, 4)
  let offset = 6 + frames.length * 16
  const dirs = frames.map(({ png, size }) => {
    const e = Buffer.alloc(16)
    e.writeUInt8(size >= 256 ? 0 : size, 0)   // width
    e.writeUInt8(size >= 256 ? 0 : size, 1)   // height
    e.writeUInt8(0, 2)                        // palette
    e.writeUInt8(0, 3)                        // reserved
    e.writeUInt16LE(1, 4)                     // planes
    e.writeUInt16LE(32, 6)                    // bpp
    e.writeUInt32LE(png.length, 8)            // data size
    e.writeUInt32LE(offset, 10)               // data offset
    offset += png.length
    return e
  })
  return Buffer.concat([header, ...dirs, ...frames.map(f => f.png)])
}

const png16 = renderPng(16)
const png32 = renderPng(32)
const png180 = renderPng(180, '#ffffff')   // apple-touch-icon 不透明白底
const ico = packIco([{ png: png16, size: 16 }, { png: png32, size: 32 }])

for (const app of ['user-web', 'admin-web']) {
  const pub = join(root, 'apps', app, 'public')
  mkdirSync(pub, { recursive: true })
  writeFileSync(join(pub, 'favicon.svg'), svg)
  writeFileSync(join(pub, 'favicon.ico'), ico)
  writeFileSync(join(pub, 'apple-touch-icon.png'), png180)
  console.log(`written: apps/${app}/public/{favicon.svg, favicon.ico, apple-touch-icon.png}`)
}

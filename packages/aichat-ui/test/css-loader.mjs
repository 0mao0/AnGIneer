// tsx --test 下 katex ESM 会 import './katex.min.css'，node 无 css 加载器。
// 本 loader 把 .css 短路为空模块，仅供单测使用（vite 构建不受影响）。
export async function load(url, context, next) {
  if (url.endsWith('.css')) {
    return { format: 'module', source: 'export default {}', shortCircuit: true }
  }
  return next(url, context)
}

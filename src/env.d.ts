/// <reference types="vite/client" />

declare module 'pdfjs-dist/build/pdf.worker.min.mjs?url' {
  const workerUrl: string
  export default workerUrl
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

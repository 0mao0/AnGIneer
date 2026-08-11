interface PdfWasmPlugin {
  name: string
  enforce: 'pre'
  configResolved(config: unknown): void
  buildStart(): void
  configureServer(): void
}

declare function pdfWasmPlugin(): PdfWasmPlugin

export default pdfWasmPlugin

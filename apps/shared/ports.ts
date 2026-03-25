import portContract from './ports.json'

export const LOCAL_HOST = portContract.localHost

export const API_SERVER_PORT = portContract.apiServerPort
export const ADMIN_CONSOLE_PORT = portContract.adminConsolePort
export const WEB_CONSOLE_PORT = portContract.webConsolePort

export const createLocalOrigin = (port: number) => `http://${LOCAL_HOST}:${port}`

export const API_PROXY_TARGET = createLocalOrigin(API_SERVER_PORT)
export const ADMIN_CONSOLE_ORIGIN = createLocalOrigin(ADMIN_CONSOLE_PORT)
export const WEB_CONSOLE_ORIGIN = createLocalOrigin(WEB_CONSOLE_PORT)

export const getWebDocumentUrl = (docId: string) =>
  `${WEB_CONSOLE_ORIGIN}/document/${encodeURIComponent(docId)}`

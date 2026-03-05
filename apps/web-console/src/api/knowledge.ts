const baseURL = '/api'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${baseURL}${url}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers
    }
  })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }
  return response.json()
}

export const knowledgeApi = {
  getNodes: (libraryId: string = 'default', visible: boolean = false) =>
    request(`/knowledge/nodes?library_id=${encodeURIComponent(libraryId)}&visible=${visible}`, {
      method: 'GET'
    }),

  getDocument: (libraryId: string, docId: string) =>
    request(`/knowledge/document/${libraryId}/${docId}`)
}

export default knowledgeApi

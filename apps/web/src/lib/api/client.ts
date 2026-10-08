import type { ModelCatalog, ModelProvider } from './types'
import type {
  ArtifactView,
  AssetAdmission,
  AssetView,
  AuthMe,
  Conversation,
  DateWindow,
  DocumentView,
  Evidence,
  IngestionView,
  MediaStoryboardView,
  RunMode,
  SegmentView,
  TableView,
  RunQuality,
  RunSnapshot,
  SourceScope,
  SystemStatus,
  WorkspaceView,
  VisualizationView,
} from './types'
import { parseAuthMe, parseRunSnapshot, parseVisualizationViews } from './runtime'

const jsonHeaders = { 'Content-Type': 'application/json' }
const csrfCookieName = import.meta.env.VITE_CSRF_COOKIE_NAME || 'ares_csrf'

export class ApiError extends Error {
  constructor(public status: number, public code: string | undefined, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

function cookie(name: string): string | undefined {
  if (typeof document === 'undefined') return undefined
  const prefix = `${encodeURIComponent(name)}=`
  return document.cookie.split(';').map((value) => value.trim()).find((value) => value.startsWith(prefix))
    ?.slice(prefix.length).split(';')[0]
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    if (response.status === 401 && typeof window !== 'undefined') {
      window.dispatchEvent(new Event('ares:auth-expired'))
    }
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    const code = typeof detail?.code === 'string' ? detail.code : undefined
    const message = detail?.message ?? code ?? `Request failed (${response.status})`
    throw new ApiError(response.status, code, message)
  }
  return response.json() as Promise<T>
}

async function download(url: string): Promise<{ blob: Blob; filename: string | undefined }> {
  const response = await fetch(url, { credentials: 'same-origin' })
  if (!response.ok) await parse<never>(response)
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const filenameMatch = disposition.match(/filename="?([^";]+)"?/i)
  return { blob: await response.blob(), filename: filenameMatch?.[1] }
}

async function request<T>(url: string, init: RequestInit = {}, validate?: (value: unknown) => T): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    const token = cookie(csrfCookieName)
    if (token) headers.set('X-CSRF-Token', decodeURIComponent(token))
  }
  const value = await fetch(url, { ...init, headers, credentials: 'same-origin' }).then(parse<unknown>)
  return validate ? validate(value) : value as T
}

export interface RunInput {
  modelProvider?: ModelProvider

  conversationId: string
  query: string
  mode: RunMode
  sourceScope: SourceScope[]
  documentIds: string[]
  plugins: string[]
  dateWindow?: DateWindow | null
  idempotencyKey: string
}

export const api = {
  me: () => request<AuthMe>('/api/v1/auth/me', {}, parseAuthMe),
  listWorkspaces: () => request<WorkspaceView[]>('/api/v1/workspaces'),
  switchWorkspace: (workspaceId: string) =>
    request<AuthMe>('/api/v1/auth/workspace', {
      method: 'POST', headers: jsonHeaders, body: JSON.stringify({ workspace_id: workspaceId }),
    }, parseAuthMe),
  logout: async () => {
    const response = await fetch('/api/v1/auth/logout', {
      method: 'POST',
      headers: (() => {
        const headers = new Headers()
        const token = cookie(csrfCookieName)
        if (token) headers.set('X-CSRF-Token', decodeURIComponent(token))
        return headers
      })(),
      credentials: 'same-origin',
    })
    if (!response.ok) await parse<never>(response)
  },
  models: () => request<ModelCatalog>('/api/v1/models'),
  systemStatus: () => request<SystemStatus>('/api/v1/system/status'),
  deleteConversation: async (id: string) => {
    const headers = new Headers()
    const token = cookie(csrfCookieName)
    if (token) headers.set('X-CSRF-Token', decodeURIComponent(token))
    const response = await fetch(`/api/v1/conversations/${id}`, { method: 'DELETE', headers, credentials: 'same-origin' })
    if (!response.ok) await parse<never>(response)
  },
  listConversations: () => request<Conversation[]>('/api/v1/conversations'),
  createConversation: (title?: string) =>
    request<Conversation>('/api/v1/conversations', {
      method: 'POST', headers: jsonHeaders, body: JSON.stringify({ title: title ?? null })
    }),
  listRuns: async (conversationId: string) => {
    const values = await request<unknown[]>(`/api/v1/conversations/${conversationId}/runs`)
    return values.map(parseRunSnapshot)
  },
  createRun: ({ conversationId, query, modelProvider, mode, sourceScope, documentIds, plugins, dateWindow, idempotencyKey }: RunInput) =>
    request<RunSnapshot>('/api/v1/runs', {
      method: 'POST',
      headers: { ...jsonHeaders, 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({
        model_provider: modelProvider,
        conversation_id: conversationId,
        query,
        mode,
        source_scope: sourceScope,
        document_ids: documentIds,
        plugins,
        date_window: dateWindow ?? null
      })
    }, parseRunSnapshot),
  getRun: (runId: string) => request<RunSnapshot>(`/api/v1/runs/${runId}`, {}, parseRunSnapshot),
  getRunQuality: (runId: string) => request<RunQuality>(`/api/v1/runs/${runId}/quality`),
  listRunEvidence: (runId: string) => request<Evidence[]>(`/api/v1/runs/${runId}/evidence`),
  getRunVisualizations: (runId: string) => request<VisualizationView[]>(`/api/v2/runs/${runId}/visualizations`, {}, parseVisualizationViews),
  downloadVisualizationCsv: (runId: string, visualizationId: string) => download(`/api/v2/runs/${runId}/visualizations/${visualizationId}/export.csv`),
  cancelRun: (runId: string) => request<RunSnapshot>(`/api/v1/runs/${runId}/cancel`, { method: 'POST' }, parseRunSnapshot),
  getEvidence: (evidenceId: string) => request<Evidence>(`/api/v1/evidence/${evidenceId}`),

  listAssets: () => request<AssetView[]>('/api/v2/assets'),
  listIngestions: () => request<IngestionView[]>('/api/v2/ingestions'),
  uploadAsset: (file: File) => {
    const form = new FormData()
    form.append('file', file, file.name)
    return request<AssetAdmission>('/api/v2/assets', { method: 'POST', body: form })
  },
  deleteAsset: async (assetId: string) => {
    const headers = new Headers()
    const token = cookie(csrfCookieName)
    if (token) headers.set('X-CSRF-Token', decodeURIComponent(token))
    const response = await fetch(`/api/v2/assets/${assetId}`, {
      method: 'DELETE', headers, credentials: 'same-origin'
    })
    if (!response.ok) await parse<never>(response)
  },
  cancelIngestion: (ingestionId: string) =>
    request<IngestionView>(`/api/v2/ingestions/${ingestionId}/cancel`, { method: 'POST' }),
  retryIngestion: (ingestionId: string) =>
    request<IngestionView>(`/api/v2/ingestions/${ingestionId}/retry`, { method: 'POST' }),
  getSegment: (segmentId: string) => request<SegmentView>(`/api/v2/segments/${segmentId}`),
  getMediaStoryboard: (assetId: string) => request<MediaStoryboardView>(`/api/v2/assets/${assetId}/storyboard`),
  getSegmentTable: (segmentId: string) => request<TableView>(`/api/v2/segments/${segmentId}/table`),
  getTable: (tableId: string) => request<TableView>(`/api/v2/tables/${tableId}`),

  listDocuments: () => request<DocumentView[]>('/api/v1/documents'),
  createTextDocument: (name: string, text: string, mimeType: 'text/plain' | 'text/markdown') =>
    request<DocumentView>('/api/v1/documents/text', {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ name, text, mime_type: mimeType })
    }),
  uploadPdf: (file: File) => {
    const form = new FormData()
    form.append('file', file, file.name)
    return request<DocumentView>('/api/v1/documents/pdf', { method: 'POST', body: form })
  },
  deleteDocument: async (documentId: string) => {
    const headers = new Headers()
    const token = cookie(csrfCookieName)
    if (token) headers.set('X-CSRF-Token', decodeURIComponent(token))
    const response = await fetch(`/api/v1/documents/${documentId}`, {
      method: 'DELETE', headers, credentials: 'same-origin'
    })
    if (!response.ok) await parse<never>(response)
  },

  createExport: (runId: string, format: 'markdown' | 'json') =>
    request<ArtifactView>(`/api/v1/runs/${runId}/exports`, {
      method: 'POST', headers: jsonHeaders, body: JSON.stringify({ format })
    }),
}

import { afterEach, expect, it, vi } from 'vitest'
import { api, ApiError } from './client'
afterEach(() => vi.unstubAllGlobals())

it('propagates the decoded CSRF cookie on mutations', async () => {
  vi.stubGlobal('document', { cookie: 'ares_csrf=token%2Bvalue' })
  const fetcher = vi.fn().mockResolvedValue(new Response('{}'))
  vi.stubGlobal('fetch', fetcher)
  await api.createConversation('Test')
  expect(new Headers(fetcher.mock.calls[0][1].headers).get('X-CSRF-Token')).toBe('token+value')
  expect(fetcher.mock.calls[0][1].credentials).toBe('same-origin')
})

it('reports stale CSRF authentication and preserves the API error', async () => {
  const dispatchEvent = vi.fn()
  vi.stubGlobal('window', { dispatchEvent })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { code: 'CSRF_TOKEN', message: 'expired' } }), { status: 403 })))
  await expect(api.createConversation('Test')).rejects.toBeInstanceOf(ApiError)
  expect(dispatchEvent).toHaveBeenCalledOnce()
})

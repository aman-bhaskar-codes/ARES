import { describe, expect, it } from 'vitest'
import type { AssetView, DocumentView, IngestionView } from '../../lib/api/types'
import { buildLibraryFiles } from './libraryFiles'

const document = { id: 'document-1', name: 'paper.pdf', byte_count: 2048 } as DocumentView
const asset = { id: 'asset-1', name: 'paper.pdf', byte_count: 2048 } as AssetView
const ingestion = { id: 'ingestion-1', asset_id: asset.id, document_id: document.id, created_at: '2026-10-17T10:00:00Z' } as IngestionView

describe('uploaded file library', () => {
  it('shows one uploaded file rather than duplicate asset and extracted document rows', () => {
    const files = buildLibraryFiles([document], [asset], [ingestion])
    expect(files).toHaveLength(1)
    expect(files[0].asset?.id).toBe(asset.id)
    expect(files[0].document?.id).toBe(document.id)
  })
  it('keeps standalone text/PDF uploads even when an asset is absent', () => {
    const files = buildLibraryFiles([document], [], [ingestion])
    expect(files).toHaveLength(1)
    expect(files[0].document?.id).toBe(document.id)
  })
  it('keeps processing and failed uploads and selects the latest ingestion on retry', () => {
    const retry = { ...ingestion, id: 'retry', document_id: undefined, created_at: '2026-10-17T11:00:00Z' } as IngestionView
    const files = buildLibraryFiles([document], [asset], [ingestion, retry])
    expect(files).toHaveLength(1)
    expect(files[0].ingestion?.id).toBe('retry')
    expect(files[0].document?.id).toBe(document.id)
    expect(buildLibraryFiles([], [asset], [retry])[0].asset?.id).toBe(asset.id)
  })
})

import type { AssetView, DocumentView, IngestionView } from '../../lib/api/types'

export function buildLibraryFiles(documents: DocumentView[], assets: AssetView[], ingestions: IngestionView[]) {
  const assetIds = new Set(assets.map(item => item.id))
  const linkedDocuments = new Set(ingestions.filter(item => assetIds.has(item.asset_id)).map(item => item.document_id).filter(Boolean))
  const byDocument = new Map(documents.map(item => [item.id, item]))
  return [
    ...assets.map(asset => {
      const history = ingestions.filter(item => item.asset_id === asset.id).sort((a, b) => b.created_at.localeCompare(a.created_at))
      const ingestion = history[0]
      const document = history.map(item => item.document_id ? byDocument.get(item.document_id) : undefined).find(Boolean)
      return { id: `asset-${asset.id}`, name: asset.name, bytes: asset.byte_count, asset, document, ingestion }
    }),
    ...documents.filter(document => !linkedDocuments.has(document.id)).map(document => ({ id: `document-${document.id}`, name: document.name, bytes: document.byte_count, document, asset: undefined, ingestion: undefined })),
  ]
}

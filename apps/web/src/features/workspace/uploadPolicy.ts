import type { SystemStatus } from '../../lib/api/types'

export function uploadAccept(system?: SystemStatus, richIngestionReady = false) {
  const values = new Set(['text/plain', 'text/markdown', '.txt', '.md'])
  if (!richIngestionReady) {
    values.add('application/pdf'); values.add('.pdf')
    return Array.from(values).join(',')
  }
  const accepted = new Set(system?.ingestion?.accepted_mime_types ?? [])
  const extensionMap: Record<string, string[]> = {
    'application/pdf': ['.pdf'],
    'text/csv': ['.csv'],
    'image/png': ['.png'],
    'image/jpeg': ['.jpg', '.jpeg'],
    'image/webp': ['.webp'],
    'audio/wav': ['.wav'],
    'audio/mpeg': ['.mp3'],
    'audio/mp4': ['.m4a'],
    'audio/ogg': ['.ogg'],
    'audio/webm': ['.webm'],
    'video/mp4': ['.mp4'],
    'video/webm': ['.webm'],
  }
  for (const mime of accepted) {
    if (mime.startsWith('audio/') && !system?.ingestion?.audio_ready) continue
    if (mime.startsWith('video/') && !system?.ingestion?.video_ready) continue
    values.add(mime)
    for (const extension of extensionMap[mime] ?? []) values.add(extension)
  }
  return Array.from(values).join(',')
}


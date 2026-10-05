import type { components } from './generated'

type Schema<Name extends keyof components['schemas']> = components['schemas'][Name]

export type RunStatus = Schema<'RunStatus'>
export type RunMode = Schema<'RunMode'>
export type SupportStatus = Schema<'SupportStatus'>
export type DocumentStatus = Schema<'DocumentStatus'>
export type AssessmentState = Schema<'AssessmentState'>
export type SourceScope = 'web' | 'academic' | 'software' | 'documents'

export type Conversation = Schema<'ConversationView'>
export type CitationRef = Schema<'CitationRef'>
export interface AnswerClaim extends Omit<Schema<'AnswerClaim'>, 'support_status'> {
  support_status: SupportStatus
  checker_method: string
  checker_version: string
  assessment_state: AssessmentState
  assessment_rationale: string
}
export interface AnswerBlock extends Omit<Schema<'AnswerBlock'>, 'citations' | 'claims' | 'finalized'> {
  citations: CitationRef[]
  claims: AnswerClaim[]
  finalized: boolean
}
export interface DateWindow { start: string | null; end: string | null; timezone: string }
export interface RunSnapshot extends Omit<Schema<'RunSnapshot'>, 'source_scope' | 'document_ids' | 'date_window' | 'answer_blocks' | 'gaps' | 'cancellation_requested' | 'budget_version' | 'usage_ledger' | 'last_seq'> {
  source_scope: SourceScope[]
  document_ids: string[]
  date_window: DateWindow | null
  answer_blocks: AnswerBlock[]
  gaps: string[]
  cancellation_requested: boolean
  budget_version: string
  usage_ledger: Record<string, number>
  last_seq: number
}
export interface DocumentView extends Omit<Schema<'DocumentView'>, 'status' | 'warnings'> {
  status: DocumentStatus
  warnings: string[]
}
export type AssetStatus = Schema<'AssetStatus'>
export type IngestionStatus = Schema<'IngestionStatus'>
export type IngestionStage = Schema<'IngestionStage'>
export interface AssetView extends Omit<Schema<'AssetView'>, 'duration_ms'> {
  duration_ms: number | null
}
export type AssetAdmission = Schema<'AssetAdmission'>
export interface IngestionView extends Omit<Schema<'IngestionView'>, 'warnings' | 'lexical_ready' | 'semantic_ready' | 'cancellation_requested' | 'last_seq'> {
  warnings: string[]
  lexical_ready: boolean
  semantic_ready: boolean
  cancellation_requested: boolean
  last_seq: number
}
export type TextEvidenceLocator = { kind: 'text'; char_start: number; char_end: number }
export type PageRegionEvidenceLocator = {
  kind: 'page_region'
  page: number
  bbox: [number, number, number, number]
  coordinate_space: 'normalized_top_left'
  rotation_degrees: number
}
export type TableCellsEvidenceLocator = {
  kind: 'table_cells'
  table_id: string
  rows: number[]
  columns: number[]
  page: number | null
}
export type TimeRangeEvidenceLocator = {
  kind: 'time_range'
  start_ms: number
  end_ms: number
  track: 'audio' | 'video'
}
export type FrameRegionEvidenceLocator = {
  kind: 'frame_region'
  presentation_time_ms: number
  bbox: [number, number, number, number]
  coordinate_space: 'normalized_top_left'
  frame_id: string | null
}
export type EvidenceLocator = TextEvidenceLocator | PageRegionEvidenceLocator | TableCellsEvidenceLocator | TimeRangeEvidenceLocator | FrameRegionEvidenceLocator
export interface Evidence extends Omit<Schema<'EvidenceView'>, 'locator_data'> { locator_data: EvidenceLocator | null }
export interface SegmentView extends Omit<Schema<'SegmentView'>, 'locator' | 'modality'> {
  locator: EvidenceLocator
  modality: 'text' | 'image' | 'table_cell' | 'audio' | 'video_frame'
}
export interface MediaTrackView {
  id: string
  asset_id: string
  extraction_version_id: string | null
  track_type: 'audio' | 'video'
  stream_index: number
  codec_name: string | null
  language: string | null
  duration_ms: number | null
  sample_rate: number | null
  channels: number | null
  width: number | null
  height: number | null
  average_frame_rate: string | null
  metadata: Record<string, unknown>
  created_at: string
}
export interface MediaFrameView {
  id: string
  asset_id: string
  extraction_version_id: string | null
  rendition_id: string
  presentation_time_ms: number
  source_kind: 'periodic' | 'scene'
  width: number
  height: number
  content_hash: string
  content_url: string
  created_at: string
}
export interface MediaStoryboardView {
  asset_id: string
  duration_ms: number | null
  sampling_strategy: string
  sampled_times_ms: number[]
  waveform_peaks: number[]
  visual_coverage_warning: string | null
  tracks: MediaTrackView[]
  frames: MediaFrameView[]
}
export type TableCellView = Schema<'TableCellView'>
export interface TableView extends Omit<Schema<'TableView'>, 'locator' | 'cells'> {
  locator: EvidenceLocator | null
  cells: TableCellView[]
}
export type ArtifactView = Schema<'ArtifactView'>
export interface ToolStatus {
  configured: boolean
  ready?: boolean
  degraded?: boolean
  authenticated?: boolean
  polite_pool?: boolean
  metered: boolean
}
export interface RunQuality extends Omit<Schema<'RunQualityView'>,
  'support_counts' | 'evidence_relation_counts' | 'evidence_relations' | 'facets' |
  'source_kind_counts' | 'provider_counts' | 'risky_source_events' |
  'duplicate_sources_removed' | 'stage_timings_ms' | 'queue_wait_ms' |
  'run_elapsed_ms' | 'gaps_count'> {
  support_counts: Record<string, number>
  evidence_relation_counts: Record<string, number>
  evidence_relations: Array<Schema<'ClaimEvidenceRelationView'>>
  facets: Array<Schema<'RunFacetView'>>
  source_kind_counts: Record<string, number>
  provider_counts: Record<string, number>
  risky_source_events: number
  duplicate_sources_removed: number
  stage_timings_ms: Record<string, number>
  queue_wait_ms: number | null
  run_elapsed_ms: number | null
  gaps_count: number
}
export interface RunEvent {
  schema_version: number
  run_id: string
  seq: number
  event_type: string
  at: string
  payload: Record<string, unknown>
}
export interface SystemStatus {
  mode: 'demo' | 'local_live'
  deployment_environment: 'local' | 'production'
  auth_mode: 'disabled' | 'oidc'
  worker_fleet: { total: number; active: number; draining: number; stale: number }
  worker_profiles?: { research: number; media: number; combined: number }
  ingestion?: {
    enabled: boolean
    ready: boolean
    accepted_mime_types: string[]
    max_upload_bytes: number
    max_image_bytes: number
    max_audio_bytes: number
    max_video_bytes: number
    max_audio_duration_seconds: number
    max_video_duration_seconds: number
    max_video_frames: number
    audio_ready: boolean
    video_ready: boolean
    microphone_enabled: boolean
    max_image_pixels: number
    max_pdf_pages: number
    max_csv_rows: number
    max_table_cells: number
  }
  telemetry_export: { configured: boolean; ready: boolean; degraded: boolean }
  strict_free_mode: boolean
  billable_fallback_allowed: boolean
  gemini_model: string | null
  retrieval_backend: string
  visualizations?: { enabled: boolean; ready: boolean; max_graph_nodes: number; max_graph_edges: number }
  tools: Record<string, ToolStatus>
}
export interface AuthMe extends Omit<Schema<'AuthMeView'>, 'role' | 'auth_mode'> {
  role: 'viewer' | 'editor' | 'owner'
  auth_mode: 'disabled' | 'oidc'
}
export interface WorkspaceView extends Omit<Schema<'WorkspaceView'>, 'role'> {
  role: 'viewer' | 'editor' | 'owner'
}

export type VisualizationKind = Schema<'VisualizationKind'>
export interface VisualizationLineageRef extends Omit<Schema<'VisualizationLineageRef'>, 'segment_id' | 'locator'> {
  segment_id: string | null
  locator: string
}
export interface VisualizationSpec extends Omit<Schema<'VisualizationSpec'>, 'kind' | 'x_field' | 'y_field' | 'series_field' | 'unit' | 'renderer' | 'max_points' | 'allow_download_csv' | 'accessible_table'> {
  kind: VisualizationKind
  x_field: string | null
  y_field: string | null
  series_field: string | null
  unit: string | null
  renderer: 'svg' | 'canvas'
  max_points: number
  allow_download_csv: boolean
  accessible_table: boolean
}
export interface ComparisonMatrixRow {
  facet: string
  status: 'supported' | 'conflicting' | 'missing'
  supporting_count: number
  conflicting_count: number
  independent_origin_count: number
  supporting_evidence_ids: string[]
  conflicting_evidence_ids: string[]
  rationale: string
}
export interface ChartPoint {
  id: string
  label: string
  value: number
  unit: string | null
  series: string | null
  evidence_ids: string[]
  transform: 'direct' | 'aggregate' | 'difference' | 'ratio' | 'unit_conversion'
  transform_note: string
}
export interface TimelineEvent {
  id: string
  label: string
  event_at: string
  source_id: string
  evidence_ids: string[]
  uncertainty: string
}
export interface EvidenceGraphNode {
  id: string
  kind: 'claim' | 'evidence' | 'source'
  label: string
  evidence_id: string | null
  source_id: string | null
  support_status: string | null
}
export interface EvidenceGraphEdge {
  id: string
  source: string
  target: string
  relation: 'supports' | 'contradicts' | 'contextualizes' | 'originates_from'
  evidence_id: string | null
  rationale: string
}
export interface VisualizationView extends Omit<Schema<'VisualizationView'>, 'kind' | 'dataset' | 'approved_spec' | 'data_lineage' | 'export_metadata' | 'description' | 'schema_version'> {
  kind: VisualizationKind
  dataset: Record<string, unknown>
  approved_spec: VisualizationSpec
  data_lineage: VisualizationLineageRef[]
  export_metadata: Record<string, unknown>
  description: string
  schema_version: number
}

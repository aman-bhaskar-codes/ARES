import type {
  AnswerBlock,
  AnswerClaim,
  AssessmentState,
  AuthMe,
  CitationRef,
  DateWindow,
  RunEvent,
  RunMode,
  RunSnapshot,
  RunStatus,
  SourceScope,
  SupportStatus,
  VisualizationKind,
  VisualizationView,
} from './types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function requiredString(record: Record<string, unknown>, key: string): string {
  const value = record[key]
  if (typeof value !== 'string' || value.length === 0) throw new TypeError(`Invalid API payload: ${key}`)
  return value
}

function optionalString(value: unknown): string | null {
  if (value === undefined || value === null) return null
  if (typeof value !== 'string') throw new TypeError('Invalid API payload: expected string or null')
  return value
}

function dateString(value: unknown, key: string): string {
  if (typeof value !== 'string' || Number.isNaN(Date.parse(value))) throw new TypeError(`Invalid API payload: ${key}`)
  return value
}

function optionalDateString(value: unknown, key: string): string | null {
  if (value === undefined || value === null) return null
  return dateString(value, key)
}

function stringArray(value: unknown, key: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    throw new TypeError(`Invalid API payload: ${key}`)
  }
  return [...value]
}

function numberRecord(value: unknown, key: string): Record<string, number> {
  if (value === undefined) return {}
  if (!isRecord(value)) throw new TypeError(`Invalid API payload: ${key}`)
  const output: Record<string, number> = {}
  for (const [name, item] of Object.entries(value)) {
    if (typeof item !== 'number' || !Number.isFinite(item)) throw new TypeError(`Invalid API payload: ${key}.${name}`)
    output[name] = item
  }
  return output
}

const runModes = new Set<RunMode>(['quick', 'research'])
const runStatuses = new Set<RunStatus>(['queued', 'planning', 'discovering', 'reading', 'extracting', 'checking', 'synthesizing', 'completed', 'partial', 'failed', 'cancelled'])
const sourceScopes = new Set<SourceScope>(['web', 'academic', 'software', 'documents'])
const supportStatuses = new Set<SupportStatus>(['supported', 'partially_supported', 'conflicting', 'insufficient_evidence'])
const assessmentStates = new Set<AssessmentState>(['legacy', 'deterministic_exact', 'heuristic_screened', 'semantic_assessed', 'unassessed'])

function enumValue<T extends string>(value: unknown, values: Set<T>, key: string): T {
  if (typeof value !== 'string' || !values.has(value as T)) throw new TypeError(`Invalid API payload: ${key}`)
  return value as T
}

function parseCitation(value: unknown): CitationRef {
  if (!isRecord(value)) throw new TypeError('Invalid API payload: citation')
  const label = value.label
  if (!Number.isInteger(label) || Number(label) < 1) throw new TypeError('Invalid API payload: citation.label')
  return { evidence_id: requiredString(value, 'evidence_id'), label: Number(label) }
}

function parseClaim(value: unknown): AnswerClaim {
  if (!isRecord(value)) throw new TypeError('Invalid API payload: claim')
  const labels = value.citation_labels
  if (!Array.isArray(labels) || labels.length === 0 || labels.some((item) => !Number.isInteger(item) || Number(item) < 1)) {
    throw new TypeError('Invalid API payload: claim.citation_labels')
  }
  return {
    text: requiredString(value, 'text'),
    citation_labels: labels.map(Number),
    support_status: enumValue(value.support_status ?? 'supported', supportStatuses, 'claim.support_status'),
    checker_method: typeof value.checker_method === 'string' ? value.checker_method : 'legacy',
    checker_version: typeof value.checker_version === 'string' ? value.checker_version : 'legacy',
    assessment_state: enumValue(value.assessment_state ?? 'legacy', assessmentStates, 'claim.assessment_state'),
    assessment_rationale: typeof value.assessment_rationale === 'string' ? value.assessment_rationale : '',
  }
}

function parseAnswerBlock(value: unknown): AnswerBlock {
  if (!isRecord(value)) throw new TypeError('Invalid API payload: answer block')
  const citations = value.citations ?? []
  const claims = value.claims ?? []
  if (!Array.isArray(citations) || !Array.isArray(claims)) throw new TypeError('Invalid API payload: answer block arrays')
  const finalized = value.finalized ?? true
  if (typeof finalized !== 'boolean') throw new TypeError('Invalid API payload: answer block.finalized')
  return {
    id: requiredString(value, 'id'),
    markdown: requiredString(value, 'markdown'),
    citations: citations.map(parseCitation),
    claims: claims.map(parseClaim),
    finalized,
  }
}

function parseDateWindow(value: unknown): DateWindow | null {
  if (value === undefined || value === null) return null
  if (!isRecord(value)) throw new TypeError('Invalid API payload: date_window')
  return {
    start: optionalDateString(value.start, 'date_window.start'),
    end: optionalDateString(value.end, 'date_window.end'),
    timezone: typeof value.timezone === 'string' && value.timezone.length > 0 ? value.timezone : 'UTC',
  }
}

export function parseAuthMe(value: unknown): AuthMe {
  if (!isRecord(value)) throw new TypeError('Invalid API payload: auth')
  const role = enumValue(value.role, new Set<AuthMe['role']>(['viewer', 'editor', 'owner']), 'auth.role')
  const authMode = enumValue(value.auth_mode, new Set<AuthMe['auth_mode']>(['disabled', 'oidc']), 'auth.auth_mode')
  if (typeof value.csrf_required !== 'boolean') throw new TypeError('Invalid API payload: auth.csrf_required')
  return {
    user_id: requiredString(value, 'user_id'),
    workspace_id: requiredString(value, 'workspace_id'),
    subject: requiredString(value, 'subject'),
    email: optionalString(value.email),
    display_name: optionalString(value.display_name),
    role,
    auth_mode: authMode,
    csrf_required: value.csrf_required,
  }
}

export function parseRunSnapshot(value: unknown): RunSnapshot {
  if (!isRecord(value)) throw new TypeError('Invalid API payload: run snapshot')
  const mode = enumValue(value.mode, runModes, 'run.mode')
  const status = enumValue(value.status, runStatuses, 'run.status')
  const scopeRaw = value.source_scope ?? []
  const scope = stringArray(scopeRaw, 'run.source_scope').map((item) => enumValue(item, sourceScopes, 'run.source_scope'))
  const blocksRaw = value.answer_blocks ?? []
  if (!Array.isArray(blocksRaw)) throw new TypeError('Invalid API payload: run.answer_blocks')
  const lastSeq = value.last_seq ?? 0
  if (!Number.isInteger(lastSeq) || Number(lastSeq) < 0) throw new TypeError('Invalid API payload: run.last_seq')
  const cancellationRequested = value.cancellation_requested ?? false
  if (typeof cancellationRequested !== 'boolean') throw new TypeError('Invalid API payload: run.cancellation_requested')

  return {
    model_provider: value.model_provider == null ? null : enumValue(value.model_provider, new Set<import('./types').ModelProvider>(['gemini', 'qwen']), 'run.model_provider'),
    id: requiredString(value, 'id'),
    conversation_id: requiredString(value, 'conversation_id'),
    query: requiredString(value, 'query'),
    mode,
    source_scope: scope,
    document_ids: stringArray(value.document_ids ?? [], 'run.document_ids'),
    date_window: parseDateWindow(value.date_window),
    deadline_at: optionalDateString(value.deadline_at, 'run.deadline_at'),
    budget_version: typeof value.budget_version === 'string' ? value.budget_version : 'legacy',
    usage_ledger: numberRecord(value.usage_ledger, 'run.usage_ledger'),
    last_seq: Number(lastSeq),
    status,
    answer_blocks: blocksRaw.map(parseAnswerBlock),
    gaps: stringArray(value.gaps ?? [], 'run.gaps'),
    plugins: stringArray(value.plugins ?? [], 'run.plugins'),
    related_questions: stringArray(value.related_questions ?? [], 'run.related_questions'),
    error_code: optionalString(value.error_code),
    error_message: optionalString(value.error_message),
    cancellation_requested: cancellationRequested,
    created_at: dateString(value.created_at, 'run.created_at'),
    updated_at: dateString(value.updated_at, 'run.updated_at'),
  }
}

export function parseRunEventJson(raw: string, expectedRunId?: string): RunEvent | null {
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return null
  }
  if (!isRecord(value)) return null
  if (!Number.isInteger(value.schema_version) || Number(value.schema_version) < 1 || Number(value.schema_version) > 2) return null
  if (typeof value.run_id !== 'string' || (expectedRunId && value.run_id !== expectedRunId)) return null
  if (!Number.isInteger(value.seq) || Number(value.seq) < 0) return null
  if (typeof value.event_type !== 'string' || value.event_type.length === 0 || value.event_type.length > 96) return null
  if (typeof value.at !== 'string' || Number.isNaN(Date.parse(value.at))) return null
  if (!isRecord(value.payload)) return null
  return {
    schema_version: Number(value.schema_version),
    run_id: value.run_id,
    seq: Number(value.seq),
    event_type: value.event_type,
    at: value.at,
    payload: value.payload,
  }
}

export function reduceRunEvents(current: RunEvent[], incoming: RunEvent, limit = 200): RunEvent[] {
  const bySequence = new Map<number, RunEvent>()
  for (const event of current) bySequence.set(event.seq, event)
  bySequence.set(incoming.seq, incoming)
  return [...bySequence.values()]
    .sort((left, right) => left.seq - right.seq)
    .slice(-Math.max(1, limit))
}


const visualizationKinds = new Set<VisualizationKind>(['comparison_matrix', 'bar', 'line', 'scatter', 'timeline', 'evidence_map'])

export function parseVisualizationViews(value: unknown): VisualizationView[] {
  if (!Array.isArray(value)) throw new TypeError('Invalid API payload: visualizations')
  return value.map((item) => {
    if (!isRecord(item)) throw new TypeError('Invalid API payload: visualization')
    const kind = enumValue(item.kind, visualizationKinds, 'visualization.kind')
    if (!isRecord(item.dataset) || !isRecord(item.approved_spec)) throw new TypeError('Invalid API payload: visualization dataset/spec')
    const spec = item.approved_spec
    const specKind = enumValue(spec.kind, visualizationKinds, 'visualization.spec.kind')
    if (specKind !== kind) throw new TypeError('Invalid API payload: visualization spec kind mismatch')
    const renderer = enumValue(spec.renderer ?? 'svg', new Set<'svg' | 'canvas'>(['svg', 'canvas']), 'visualization.spec.renderer')
    const maxPoints = spec.max_points ?? 200
    if (!Number.isInteger(maxPoints) || Number(maxPoints) < 1 || Number(maxPoints) > 200) throw new TypeError('Invalid API payload: visualization.spec.max_points')
    if (spec.accessible_table !== true) throw new TypeError('Invalid API payload: visualization must retain accessible table')
    const lineageRaw = item.data_lineage ?? []
    if (!Array.isArray(lineageRaw)) throw new TypeError('Invalid API payload: visualization.data_lineage')
    const data_lineage = lineageRaw.map((ref) => {
      if (!isRecord(ref)) throw new TypeError('Invalid API payload: visualization lineage')
      return {
        evidence_id: requiredString(ref, 'evidence_id'),
        source_id: requiredString(ref, 'source_id'),
        segment_id: optionalString(ref.segment_id),
        locator: typeof ref.locator === 'string' ? ref.locator : '',
      }
    })
    return {
      id: requiredString(item, 'id'),
      run_id: requiredString(item, 'run_id'),
      dataset_id: requiredString(item, 'dataset_id'),
      kind,
      title: requiredString(item, 'title'),
      description: typeof item.description === 'string' ? item.description : '',
      schema_version: Number.isInteger(item.schema_version) ? Number(item.schema_version) : 1,
      dataset: item.dataset,
      approved_spec: {
        kind,
        x_field: optionalString(spec.x_field),
        y_field: optionalString(spec.y_field),
        series_field: optionalString(spec.series_field),
        unit: optionalString(spec.unit),
        renderer,
        max_points: Number(maxPoints),
        allow_download_csv: spec.allow_download_csv !== false,
        accessible_table: true,
      },
      data_lineage,
      export_metadata: isRecord(item.export_metadata) ? item.export_metadata : {},
      created_at: dateString(item.created_at, 'visualization.created_at'),
    }
  })
}

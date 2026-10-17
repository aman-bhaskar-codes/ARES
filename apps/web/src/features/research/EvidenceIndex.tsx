import { CalendarDays, FileSearch, Filter, Search, ArrowUpRight } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { Evidence, SourceScope } from '../../lib/api/types'
import { groupEvidenceBySource } from './sourcePresentation'

const sourceKinds: Array<'all' | SourceScope> = ['all', 'web', 'academic', 'software', 'documents']
const readStates = ['all', 'full', 'snippet_only', 'blocked'] as const

function kindOf(item: Evidence): 'web' | 'academic' | 'software' | 'documents' {
  return item.source.source_kind === 'document' ? 'documents' : (item.source.source_kind ?? 'web')
}

export function EvidenceIndex({ evidence, onEvidence }: { evidence: Evidence[]; onEvidence: (id: string) => void }) {
  const [kind, setKind] = useState<(typeof sourceKinds)[number]>('all')
  const [readState, setReadState] = useState<(typeof readStates)[number]>('all')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => evidence.filter((item) => {
    if (kind !== 'all' && kindOf(item) !== kind) return false
    if (readState !== 'all' && (item.source.read_state ?? 'full') !== readState) return false
    const published = item.source.published_at ? new Date(item.source.published_at) : null
    if (from && (!published || published < new Date(`${from}T00:00:00`))) return false
    if (to && (!published || published > new Date(`${to}T23:59:59.999`))) return false
    if (query.trim()) {
      const haystack = `${item.source.title} ${item.source.domain} ${item.text} ${item.locator}`.toLowerCase()
      if (!haystack.includes(query.trim().toLowerCase())) return false
    }
    return true
  }), [evidence, from, kind, query, readState, to])

  const groups = useMemo(() => groupEvidenceBySource(filtered), [filtered])

  return (
    <section className="evidence-index" aria-labelledby="evidence-index-title">
      <div className="workspace-section-head">
        <div><span className="eyebrow">Sources</span><h2 id="evidence-index-title">Explore the evidence</h2></div>
        <span className="workspace-count">{filtered.length} passages</span>
      </div>
      <div className="source-search-row"><label className="source-search"><Search size={16}/><span className="sr-only">Search evidence</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a source or passage…"/></label></div>
      <details className="source-filter-disclosure"><summary><Filter size={15}/> Filter sources{(kind !== 'all' || readState !== 'all' || from || to) ? ' · Active' : ''}</summary>
      <div className="evidence-filters" aria-label="Evidence filters">
        <label><Filter size={13}/><span>Source</span><select value={kind} onChange={(event) => setKind(event.target.value as (typeof sourceKinds)[number])}>{sourceKinds.map((value) => <option key={value} value={value}>{value === 'all' ? 'All sources' : value}</option>)}</select></label>
        <label><FileSearch size={13}/><span>Read state</span><select value={readState} onChange={(event) => setReadState(event.target.value as (typeof readStates)[number])}>{readStates.map((value) => <option key={value} value={value}>{value === 'all' ? 'All extraction states' : value.replaceAll('_', ' ')}</option>)}</select></label>
        <label><CalendarDays size={13}/><span>Published from</span><input type="date" value={from} onChange={(event) => setFrom(event.target.value)}/></label>
        <label><CalendarDays size={13}/><span>Published to</span><input type="date" value={to} onChange={(event) => setTo(event.target.value)}/></label>
      </div></details>
      {groups.length > 0 ? (
        <div className="evidence-index-list">
          {groups.map((group) => (
            <div key={group.sourceId} className="evidence-source-group">
              <div className="source-group-head">
                <h3>{group.title}</h3>
                <div>
                  {group.domain} · {group.kind} {group.publishedAt ? `· ${new Date(group.publishedAt).toLocaleDateString()}` : ''}
                </div>
              </div>
              <div className="source-group-evidence">
                {group.evidence.map((item) => (
                  <button key={item.id} aria-label={`Open passage from ${group.title}, ${item.locator}`} data-evidence-id={item.id} onClick={() => onEvidence(item.id)} className="evidence-index-row">
                    <span className="evidence-index-main">
                      <span className="passage-preview">{item.text}</span>
                      <small>{item.locator} <span className="passage-open">Open passage <ArrowUpRight size={12}/></span></small>
                    </span>
                    <span className={`read-state read-${item.source.read_state ?? 'full'}`} style={{ whiteSpace: 'nowrap' }}>{(item.source.read_state ?? 'full').replaceAll('_', ' ')}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : <div className="workspace-empty">No passages match these filters. Try another search or clear your filters.<button className="quiet-button" onClick={() => { setKind('all'); setReadState('all'); setFrom(''); setTo(''); setQuery('') }}>Clear filters</button></div>}
    </section>
  )
}

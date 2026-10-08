import { Activity, Info, CheckCircle2, Clock3, CopyMinus, Files, GitCompareArrows, ShieldAlert } from 'lucide-react'
import type { RunQuality } from '../../lib/api/types'

function percent(value: number) {
  return `${Math.round(value * 100)}%`
}

function label(value: string) {
  return value.replaceAll('_', ' ')
}

export function RunQualityPanel({ quality, onEvidence }: { quality: RunQuality; onEvidence?: (id: string) => void }) {
  const timingEntries = Object.entries(quality.stage_timings_ms)
    .filter(([, duration]) => Number.isFinite(duration))
    .sort((a, b) => b[1] - a[1])
  const missingFacets = quality.facets.filter((facet) => facet.status === 'missing')
  const conflictingFacets = quality.facets.filter((facet) => facet.status === 'conflicting')

  return (
    <section className="quality-panel" aria-labelledby="quality-title">
      <div className="quality-head">
        <div>
          <span className="eyebrow">Run diagnostics</span>
          <h2 id="quality-title">Evidence quality signals</h2>
        </div>
        <span className="quality-note">Descriptive signals, not a benchmark score</span>
      </div>

      <div className="quality-grid">
        <div className="quality-metric"><CheckCircle2 size={16} /><span>Citation resolution</span><strong>{percent(quality.citation_resolution_rate)}</strong></div>
        <div className="quality-metric"><CheckCircle2 size={16} /><span>Claims with citations</span><strong>{percent(quality.claim_citation_rate)}</strong></div>
        <div className="quality-metric"><CheckCircle2 size={16} /><span>Fully supported claims</span><strong>{percent(quality.supported_claim_rate)}</strong></div>
        <div className="quality-metric"><Files size={16} /><span>Source groups</span><strong>{quality.distinct_source_group_count}</strong></div>
        <div className="quality-metric"><CopyMinus size={16} /><span>Duplicates removed</span><strong>{quality.duplicate_sources_removed}</strong></div>
        <div className={`quality-metric ${quality.risky_source_events > 0 ? 'warn' : ''}`}>
          {quality.risky_source_events > 0 ? <ShieldAlert size={16} /> : <CheckCircle2 size={16} />}
          <span>Risk signals</span><strong>{quality.risky_source_events}</strong>
        </div>
      </div>

      <div className="quality-columns">
        <div>
          <h3>Claim support</h3>
          <div className="quality-list">
            {Object.entries(quality.support_counts).length === 0 && <span className="quality-empty">No finalized claims.</span>}
            {Object.entries(quality.support_counts).map(([status, count]) => <div key={status}><span>{label(status)}</span><strong>{count}</strong></div>)}
          </div>
          {Object.keys(quality.evidence_relation_counts).length > 0 && (
            <>
              <h3 className="quality-subhead"><GitCompareArrows size={14} /> Evidence relations</h3>
              <div className="quality-list">
                {Object.entries(quality.evidence_relation_counts).map(([relation, count]) => <div key={relation}><span>{label(relation)}</span><strong>{count}</strong></div>)}
              </div>
            </>
          )}
          {(quality.confidence_extraction !== undefined || quality.confidence_relevance !== undefined) && (
            <>
              <h3 className="quality-subhead">Model Confidence</h3>
              <div className="quality-list">
                {quality.confidence_extraction !== undefined && quality.confidence_extraction !== null && <div><span>Extraction</span><strong>{percent(quality.confidence_extraction)}</strong></div>}
                {quality.confidence_relevance !== undefined && quality.confidence_relevance !== null && <div><span>Relevance</span><strong>{percent(quality.confidence_relevance)}</strong></div>}
                {quality.confidence_support !== undefined && quality.confidence_support !== null && <div><span>Support</span><strong>{percent(quality.confidence_support)}</strong></div>}
              </div>
            </>
          )}
        </div>
        <div>
          <h3>Source mix</h3>
          <div className="quality-list">
            {Object.entries(quality.source_kind_counts).length === 0 && <span className="quality-empty">No persisted sources.</span>}
            {Object.entries(quality.source_kind_counts).map(([kind, count]) => <div key={kind}><span>{label(kind)}</span><strong>{count}</strong></div>)}
          </div>
        </div>
        <div>
          <h3><Activity size={14} /> Stage time</h3>
          <div className="quality-list">
            {quality.queue_wait_ms !== null && <div><span><Clock3 size={12} /> queue wait</span><strong>{Math.round(quality.queue_wait_ms)} ms</strong></div>}
            {quality.run_elapsed_ms !== null && <div><span><Clock3 size={12} /> end-to-end</span><strong>{Math.round(quality.run_elapsed_ms)} ms</strong></div>}
            {timingEntries.length === 0 && <span className="quality-empty">Timing data unavailable.</span>}
            {timingEntries.slice(0, 6).map(([stage, duration]) => <div key={stage}><span>{label(stage)}</span><strong>{Math.round(duration)} ms</strong></div>)}
          </div>
        </div>
      </div>

      {quality.evidence_relations.length > 0 && (
        <div className="quality-relations" aria-label="Claim evidence relations">
          <h3>Evidence relations</h3>
          <div className="quality-relation-list">
            {quality.evidence_relations.filter((edge) => edge.relation !== 'supports').slice(0, 8).map((edge) => (
              <div key={`${edge.claim_id}-${edge.evidence_id}`} className={`quality-relation ${edge.relation}`}>
                <div><strong>{label(edge.relation)}</strong><span>{edge.claim_text}</span></div>
                {edge.rationale && <small>{edge.rationale}</small>}
                <button type="button" onClick={() => onEvidence?.(edge.evidence_id)} disabled={!onEvidence}>Inspect evidence</button>
              </div>
            ))}
            {quality.evidence_relations.every((edge) => edge.relation === 'supports') && <span className="quality-empty">No conflicting or contextual evidence edges.</span>}
          </div>
        </div>
      )}

      {quality.facets.length > 0 && (
        <div className="quality-facets" aria-label="Research facet coverage">
          <h3>Question coverage</h3>
          <div className="quality-facet-grid">
            {quality.facets.map((facet) => {
              const conflictingEvidenceIds = facet.conflicting_evidence_ids ?? []
              const supportingEvidenceIds = facet.supporting_evidence_ids ?? []
              return <div key={facet.facet_key} className={`quality-facet ${facet.status}`}>
                <span>{facet.facet_key}</span>
                <strong>{label(facet.status)}</strong>
                <small>{facet.independent_origin_count} independent origin{facet.independent_origin_count === 1 ? '' : 's'}</small>
                {facet.rationale && <small>{facet.rationale}</small>}
                {(conflictingEvidenceIds.length > 0 || supportingEvidenceIds.length > 0) && onEvidence && (
                  <div className="quality-facet-actions">
                    {conflictingEvidenceIds.slice(0, 2).map((id) => <button type="button" key={`c-${id}`} onClick={() => onEvidence(id)}>Inspect conflict</button>)}
                    {conflictingEvidenceIds.length === 0 && supportingEvidenceIds.slice(0, 1).map((id) => <button type="button" key={`s-${id}`} onClick={() => onEvidence(id)}>Inspect evidence</button>)}
                  </div>
                )}
              </div>
            })}
          </div>
        </div>
      )}

      {(quality.gaps_count > 0 || quality.risky_source_events > 0 || missingFacets.length > 0 || conflictingFacets.length > 0) && (
        <div className="quality-caution">
          <Info size={15} />
          <span>
            {quality.gaps_count > 0 ? `${quality.gaps_count} unresolved evidence gap${quality.gaps_count === 1 ? '' : 's'}. ` : ''}
            {missingFacets.length > 0 ? `${missingFacets.length} requested facet${missingFacets.length === 1 ? '' : 's'} still lack evidence. ` : ''}
            {conflictingFacets.length > 0 ? `${conflictingFacets.length} facet${conflictingFacets.length === 1 ? '' : 's'} contain conflicting evidence. ` : ''}
            {quality.risky_source_events > 0 ? `${quality.risky_source_events} retrieved source${quality.risky_source_events === 1 ? '' : 's'} contained instruction-like or obfuscated content; all remained untrusted data.` : ''}
          </span>
        </div>
      )}
    </section>
  )
}

import {
  Brain,
  CheckCircle2,
  Download,
  Filter,
  Layers,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../../lib/api/client'
import type { MemoryEpisode, MemoryFact, MemoryPreference } from '../../lib/api/types'

interface MemoryPanelProps {
  readOnly?: boolean
  onClose: () => void
}

export function MemoryPanel({ readOnly = false, onClose }: MemoryPanelProps) {
  const [activeTab, setActiveTab] = useState<'episodes' | 'facts' | 'preferences'>('episodes')
  const [episodes, setEpisodes] = useState<MemoryEpisode[]>([])
  const [facts, setFacts] = useState<MemoryFact[]>([])
  const [preferences, setPreferences] = useState<MemoryPreference | null>(null)
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [factStatus, setFactStatus] = useState<string>('active')
  const [busyConsolidate, setBusyConsolidate] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)

  // Form states for preferences
  const [prefDepth, setPrefDepth] = useState<'quick' | 'standard' | 'deep'>('standard')
  const [prefTone, setPrefTone] = useState<'academic' | 'brief' | 'technical' | 'general'>('academic')
  const [preferredDomainsInput, setPreferredDomainsInput] = useState('')
  const [excludedDomainsInput, setExcludedDomainsInput] = useState('')
  const [customInstructions, setCustomInstructions] = useState('')

  const loadAll = async () => {
    setLoading(true)
    try {
      const [eps, fcts, prefs] = await Promise.all([
        api.listMemoryEpisodes(100),
        api.listMemoryFacts(undefined, factStatus),
        api.getMemoryPreferences(),
      ])
      setEpisodes(eps)
      setFacts(fcts)
      setPreferences(prefs)
      setPrefDepth(prefs.depth)
      setPrefTone(prefs.tone)
      setPreferredDomainsInput(prefs.preferred_domains.join(', '))
      setExcludedDomainsInput(prefs.excluded_domains.join(', '))
      setCustomInstructions(prefs.custom_instructions ?? '')
    } catch (err) {
      console.error('Failed to load memory:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
  }, [factStatus])

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!searchQuery.trim()) {
      return loadAll()
    }
    setLoading(true)
    try {
      if (activeTab === 'episodes') {
        const results = await api.searchMemoryEpisodes(searchQuery)
        setEpisodes(results.map((r) => r.episode))
      } else if (activeTab === 'facts') {
        const results = await api.searchMemoryFacts(searchQuery)
        setFacts(results.map((r) => r.fact))
      }
    } catch (err) {
      console.error('Search failed:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleDeleteEpisode = async (id: string) => {
    if (readOnly) return
    try {
      await api.deleteMemoryEpisode(id)
      setEpisodes((prev) => prev.filter((ep) => ep.id !== id))
    } catch (err) {
      console.error('Failed to delete episode:', err)
    }
  }

  const handleDeleteFact = async (id: string) => {
    if (readOnly) return
    try {
      await api.deleteMemoryFact(id)
      setFacts((prev) => prev.filter((f) => f.id !== id))
    } catch (err) {
      console.error('Failed to delete fact:', err)
    }
  }

  const handleConsolidate = async () => {
    if (readOnly) return
    setBusyConsolidate(true)
    try {
      await api.consolidateMemoryFacts()
      await loadAll()
    } catch (err) {
      console.error('Consolidation failed:', err)
    } finally {
      setBusyConsolidate(false)
    }
  }

  const handleSavePreferences = async (e: React.FormEvent) => {
    e.preventDefault()
    if (readOnly) return
    try {
      const preferred = preferredDomainsInput
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
      const excluded = excludedDomainsInput
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)

      const updated = await api.updateMemoryPreferences({
        depth: prefDepth,
        tone: prefTone,
        preferred_domains: preferred,
        excluded_domains: excluded,
        custom_instructions: customInstructions.trim() || null,
      })
      setPreferences(updated)
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 3000)
    } catch (err) {
      console.error('Failed to update preferences:', err)
    }
  }

  const exportMemoryJson = () => {
    const data = {
      exported_at: new Date().toISOString(),
      episodes,
      facts,
      preferences,
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `ares-workspace-memory-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="workspace-overlay" role="dialog" aria-modal="true" aria-labelledby="memory-title">
      <div className="workspace-panel memory-panel-modal">
        <header className="workspace-header">
          <div className="workspace-title">
            <Brain size={20} className="icon-highlight" />
            <div>
              <h2 id="memory-title">Workspace Memory</h2>
              <p>4-tier persistent memory: Working, Episodic, Semantic, and Preferences</p>
            </div>
          </div>
          <div className="workspace-actions">
            <button
              className="secondary-button"
              onClick={exportMemoryJson}
              title="Export memory as JSON"
            >
              <Download size={15} /> Export
            </button>
            <button className="icon-button" onClick={onClose} aria-label="Close memory panel">
              <X size={18} />
            </button>
          </div>
        </header>

        <div className="workspace-tab-nav">
          <button
            className={activeTab === 'episodes' ? 'active' : ''}
            onClick={() => setActiveTab('episodes')}
          >
            <Layers size={15} /> Episodic Memory ({episodes.length})
          </button>
          <button
            className={activeTab === 'facts' ? 'active' : ''}
            onClick={() => setActiveTab('facts')}
          >
            <CheckCircle2 size={15} /> Verified Facts ({facts.length})
          </button>
          <button
            className={activeTab === 'preferences' ? 'active' : ''}
            onClick={() => setActiveTab('preferences')}
          >
            <Sparkles size={15} /> Research Preferences
          </button>
        </div>

        {activeTab !== 'preferences' && (
          <div className="memory-filter-bar">
            <form onSubmit={handleSearch} className="memory-search-form">
              <Search size={16} />
              <input
                type="text"
                placeholder={
                  activeTab === 'episodes'
                    ? 'Search run episodes with recency decay...'
                    : 'Search verified facts and entities...'
                }
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              <button type="submit" className="search-submit">Search</button>
              {searchQuery && (
                <button
                  type="button"
                  className="clear-search"
                  onClick={() => {
                    setSearchQuery('')
                    loadAll()
                  }}
                >
                  Clear
                </button>
              )}
            </form>

            {activeTab === 'facts' && (
              <div className="fact-controls">
                <select
                  value={factStatus}
                  onChange={(e) => setFactStatus(e.target.value)}
                  className="filter-select"
                >
                  <option value="active">Active facts</option>
                  <option value="superseded">Superseded facts</option>
                  <option value="all">All facts</option>
                </select>
                <button
                  className="secondary-button"
                  onClick={handleConsolidate}
                  disabled={busyConsolidate || readOnly}
                  title="Dedupe and resolve contradictory facts by recency"
                >
                  <RefreshCw size={14} className={busyConsolidate ? 'spinning' : ''} />
                  Consolidate
                </button>
              </div>
            )}
          </div>
        )}

        <div className="memory-content-area">
          {loading ? (
            <div className="loading-state">Loading workspace memory...</div>
          ) : activeTab === 'episodes' ? (
            <div className="episode-list">
              {episodes.length === 0 ? (
                <div className="empty-memory-state">
                  <p>No episodic memories recorded yet. Completed research runs will appear here.</p>
                </div>
              ) : (
                episodes.map((ep) => (
                  <div key={ep.id} className="memory-card">
                    <div className="memory-card-header">
                      <div>
                        <h4>{ep.title}</h4>
                        <span className="memory-date">
                          {new Date(ep.created_at).toLocaleDateString()} · Importance: {Math.round(ep.importance * 100)}%
                        </span>
                      </div>
                      {!readOnly && (
                        <button
                          className="icon-button delete-button"
                          onClick={() => handleDeleteEpisode(ep.id)}
                          aria-label={`Delete episode: ${ep.title}`}
                        >
                          <Trash2 size={15} />
                        </button>
                      )}
                    </div>
                    <p className="memory-summary">{ep.summary}</p>
                    {ep.key_findings && ep.key_findings.length > 0 && (
                      <div className="findings-tags">
                        {ep.key_findings.map((finding, idx) => (
                          <span key={idx} className="finding-chip">
                            {finding}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          ) : activeTab === 'facts' ? (
            <div className="fact-list">
              {facts.length === 0 ? (
                <div className="empty-memory-state">
                  <p>No verified facts stored yet. Facts from research runs passing citation integrity will appear here.</p>
                </div>
              ) : (
                facts.map((fact) => (
                  <div key={fact.id} className={`memory-card fact-card status-${fact.status}`}>
                    <div className="memory-card-header">
                      <div className="fact-badges">
                        <span className="badge-subject">{fact.subject}</span>
                        <span className="badge-predicate">{fact.predicate}</span>
                        <span className={`badge-status status-${fact.status}`}>
                          {fact.status}
                        </span>
                        <span className="badge-confidence">
                          {Math.round(fact.confidence * 100)}% confidence
                        </span>
                      </div>
                      {!readOnly && (
                        <button
                          className="icon-button delete-button"
                          onClick={() => handleDeleteFact(fact.id)}
                          aria-label="Delete fact"
                        >
                          <Trash2 size={15} />
                        </button>
                      )}
                    </div>
                    <div className="fact-body">{fact.fact}</div>
                    {fact.evidence_source && (
                      <div className="fact-source">
                        <strong>Source:</strong> <span>{fact.evidence_source}</span>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          ) : (
            <form onSubmit={handleSavePreferences} className="preferences-form">
              <div className="form-group">
                <label>Default Research Depth</label>
                <div className="radio-pill-group">
                  {(['quick', 'standard', 'deep'] as const).map((d) => (
                    <button
                      key={d}
                      type="button"
                      className={`pill-option ${prefDepth === d ? 'active' : ''}`}
                      onClick={() => setPrefDepth(d)}
                      disabled={readOnly}
                    >
                      {d.charAt(0).toUpperCase() + d.slice(1)}
                    </button>
                  ))}
                </div>
                <small className="form-help">
                  Controls the search breadth, evidence verification waves, and token limits.
                </small>
              </div>

              <div className="form-group">
                <label>Synthesis Tone</label>
                <div className="radio-pill-group">
                  {(['academic', 'brief', 'technical', 'general'] as const).map((t) => (
                    <button
                      key={t}
                      type="button"
                      className={`pill-option ${prefTone === t ? 'active' : ''}`}
                      onClick={() => setPrefTone(t)}
                      disabled={readOnly}
                    >
                      {t.charAt(0).toUpperCase() + t.slice(1)}
                    </button>
                  ))}
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="pref-domains">Preferred Domains</label>
                <input
                  id="pref-domains"
                  type="text"
                  placeholder="arxiv.org, nature.com, github.com"
                  value={preferredDomainsInput}
                  onChange={(e) => setPreferredDomainsInput(e.target.value)}
                  disabled={readOnly}
                />
                <small className="form-help">Comma-separated list of prioritized research sources.</small>
              </div>

              <div className="form-group">
                <label htmlFor="excl-domains">Excluded Domains</label>
                <input
                  id="excl-domains"
                  type="text"
                  placeholder="pinterest.com, medium.com"
                  value={excludedDomainsInput}
                  onChange={(e) => setExcludedDomainsInput(e.target.value)}
                  disabled={readOnly}
                />
                <small className="form-help">Domains to automatically filter out of search hits.</small>
              </div>

              <div className="form-group">
                <label htmlFor="custom-inst">Custom Research Instructions</label>
                <textarea
                  id="custom-inst"
                  rows={4}
                  placeholder="e.g. Always highlight empirical benchmarks and reproducibility details."
                  value={customInstructions}
                  onChange={(e) => setCustomInstructions(e.target.value)}
                  disabled={readOnly}
                />
                <small className="form-help">Persistent prompt guidance applied to all research runs in this workspace.</small>
              </div>

              <div className="form-footer">
                <button
                  type="submit"
                  className="primary-button"
                  disabled={readOnly}
                >
                  Save Preferences
                </button>
                {saveSuccess && (
                  <span className="save-indicator">
                    <CheckCircle2 size={16} /> Saved!
                  </span>
                )}
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}

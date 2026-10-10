import type { ModelProvider } from '../../lib/api/types'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Info,
  AlertTriangle,
  BookOpenText,
  Download,
  GitCompareArrows,
  FileStack,
  ListTree,
  Menu,
  Moon,
  Plus,
  RotateCcw,
  Check,
  Settings2,
  Sparkles,
  Sun,
  LogOut,
  UserRound,
  Trash2,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ApiError, api } from '../../lib/api/client'
import { parseResearchLocation, researchConversationUrl, researchRunUrl, type ResearchView } from '../../lib/researchRoutes'
import type { Evidence, RunMode, RunSnapshot, SourceScope } from '../../lib/api/types'
import { Answer } from '../research/Answer'
import { Composer } from '../research/Composer'
import { FollowUpComposer } from '../research/FollowUpComposer'
import { EvidenceDrawer } from '../research/EvidenceDrawer'
import { EvidenceIndex } from '../research/EvidenceIndex'
import { ResearchActivity } from '../research/ResearchActivity'
import { ResearchGaps } from '../research/ResearchGaps'
import { RelatedQuestions } from '../research/RelatedQuestions'
import { CompactResearchProgress } from '../research/CompactResearchProgress'
import { RunQualityPanel } from '../research/RunQualityPanel'
import { VisualizationWorkspace } from '../research/VisualizationWorkspace'
import { useRunStream } from '../research/useRunStream'
import { WorkspacePanel } from '../workspace/WorkspacePanel'
import { RunHeader } from '../research/RunHeader'
import { ResearchViewNav } from '../research/ResearchViewNav'

const terminal = new Set(['completed', 'partial', 'failed', 'cancelled'])
const idempotencyKey = () => crypto.randomUUID()

export function WorkspaceShell({ authData }: { authData: import('../../lib/api/types').AuthMe }) {
  const queryClient = useQueryClient()
  const location = useLocation()
  const navigate = useNavigate()
  const researchLocation = parseResearchLocation(location.pathname, location.search)
  const routeConversationId = researchLocation.conversationId
  const routeRunId = researchLocation.runId
  const routeEvidenceId = researchLocation.evidenceId
  const activeView = researchLocation.view
  const [conversationId, setConversationId] = useState<string>()
  const [run, setRun] = useState<RunSnapshot>()
  const [modelProvider, setModelProvider] = useState<ModelProvider>(() => window.localStorage.getItem('ares-model') === 'gemini' ? 'gemini' : 'qwen')
  const modelCatalog = useQuery({ queryKey: ['models'], queryFn: api.models })
  useEffect(() => {
    const catalog = modelCatalog.data
    if (catalog && !catalog.models.some((item) => item.id === modelProvider && item.available)) setModelProvider(catalog.default)
  }, [modelCatalog.data, modelProvider])
  useEffect(() => { window.localStorage.setItem('ares-model', modelProvider) }, [modelProvider])
  const [mode, setMode] = useState<RunMode>('quick')
  const [sourceScope, setSourceScope] = useState<SourceScope[]>(['web'])
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([])
  const [evidence, setEvidence] = useState<Evidence>()
  const [navOpen, setNavOpen] = useState(false)
  const [workspace, setWorkspace] = useState<'documents' | 'system'>()
  const [uiError, setUiError] = useState<string>()
  const [exporting, setExporting] = useState<'markdown' | 'json'>()
  const [uploading, setUploading] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = window.localStorage.getItem('ares-theme')
    if (saved === 'light' || saved === 'dark') return saved
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  })
  const { events, connected, snapshotRequiredSeq } = useRunStream(run?.id, Math.max(0, (run?.last_seq ?? 0) - 200))
  const [activePlugins, setActivePlugins] = useState<string[]>(['speed'])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    window.localStorage.setItem('ares-theme', theme)
  }, [theme])
  const authenticated = true
  const canWrite = authData.role !== 'viewer'
  const conversations = useQuery({ queryKey: ['conversations'], queryFn: api.listConversations, enabled: authenticated })
  const system = useQuery({ queryKey: ['system-status'], queryFn: api.systemStatus, enabled: authenticated, staleTime: 60_000 })
  const documents = useQuery({ queryKey: ['documents'], queryFn: api.listDocuments, enabled: authenticated, refetchInterval: workspace === 'documents' ? 2000 : false })
  const assets = useQuery({ queryKey: ['assets'], queryFn: api.listAssets, enabled: authenticated, refetchInterval: workspace === 'documents' ? 2000 : false })
  const ingestions = useQuery({ queryKey: ['ingestions'], queryFn: api.listIngestions, enabled: authenticated, refetchInterval: workspace === 'documents' ? 1200 : false })
  const workspaces = useQuery({ queryKey: ['workspaces'], queryFn: api.listWorkspaces, enabled: authenticated })
  const quality = useQuery({
    queryKey: ['run-quality', run?.id],
    queryFn: () => api.getRunQuality(run!.id),
    enabled: Boolean(authenticated && run?.id && terminal.has(run.status)),
    staleTime: Infinity,
  })
  const runEvidence = useQuery({
    queryKey: ['run-evidence', run?.id],
    queryFn: () => api.listRunEvidence(run!.id),
    enabled: Boolean(authenticated && run?.id),
    refetchInterval: run && !terminal.has(run.status) ? 2000 : false,
    staleTime: run && terminal.has(run.status) ? Infinity : 1000,
  })
  const visualizations = useQuery({
    queryKey: ['run-visualizations', run?.id],
    queryFn: () => api.getRunVisualizations(run!.id),
    enabled: Boolean(authenticated && run?.id && terminal.has(run.status) && system.data?.visualizations?.ready),
    staleTime: Infinity,
    // The research engine publishes its terminal state before the worker derives optional
    // M11 visual artifacts. Poll only a few times to bridge that bounded handoff; legacy
    // runs with no visualization-ready provenance must not create an endless request loop.
    refetchInterval: (query) => {
      const data = query.state.data as unknown[] | undefined
      return (data?.length ?? 0) === 0 && query.state.dataUpdateCount < 5 ? 1200 : false
    },
    refetchIntervalInBackground: false,
  })

  const { data: freshRun } = useQuery({
    queryKey: ['run', run?.id, events.at(-1)?.seq, snapshotRequiredSeq],
    queryFn: () => api.getRun(run!.id),
    enabled: Boolean(authenticated && run?.id),
    refetchInterval: run && !terminal.has(run.status) ? 1000 : false,
  })

  useEffect(() => {
    if (freshRun) setRun(freshRun)
  }, [freshRun])

  const cancel = useMutation({ mutationFn: () => api.cancelRun(run!.id), onSuccess: setRun })
  const switchWorkspace = useMutation({
    mutationFn: api.switchWorkspace,
    onSuccess: async (next) => {
      // A workspace switch is a tenant-boundary transition: stop in-flight reads and remove
      // all cached data from the previous workspace before exposing the new principal.
      await queryClient.cancelQueries()
      queryClient.clear()
      setConversationId(undefined); setRun(undefined); setEvidence(undefined); setWorkspace(undefined); setSelectedDocuments([]); setUiError(undefined)
      navigate('/', { replace: true })
      queryClient.setQueryData(['auth-me'], next)
      await queryClient.invalidateQueries()
    },
    onError: (error) => setUiError(error instanceof Error ? error.message : 'Could not switch workspace'),
  })
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: () => { queryClient.clear(); window.location.assign('/') },
    onError: (error) => setUiError(error instanceof Error ? error.message : 'Could not sign out'),
  })
  const deleteChat = useMutation({
    mutationFn: api.deleteConversation,
    onSuccess: async (_, id) => {
      if (id === conversationId || id === routeConversationId) {
        setConversationId(undefined)
        setRun(undefined)
        setEvidence(undefined)
        navigate('/', { replace: true })
      }
      setUiError(undefined)
      await queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
    onError: (error) => setUiError(error instanceof Error ? error.message : 'Could not delete chat'),
  })
  const busy = Boolean(run && !terminal.has(run.status))

  const adoptRun = useCallback((snapshot: RunSnapshot | undefined) => {
    if (!snapshot) return
    setConversationId(snapshot.conversation_id)
    setRun(snapshot)
    setMode(snapshot.mode)
    setSourceScope(snapshot.source_scope.length ? snapshot.source_scope : ['web'])
    setSelectedDocuments(snapshot.document_ids)
  }, [])

  useEffect(() => {
    if (!authenticated) return
    let cancelled = false
    const restore = async () => {
      if (routeRunId) {
        if (run?.id === routeRunId) return
        try {
          const snapshot = await api.getRun(routeRunId)
          if (!cancelled) adoptRun(snapshot)
        } catch (error) {
          if (!cancelled) setUiError(error instanceof Error ? error.message : 'Could not restore this research run')
        }
        return
      }
      if (routeConversationId) {
        if (conversationId === routeConversationId && run) return
        try {
          const runs = await api.listRuns(routeConversationId)
          if (cancelled) return
          setConversationId(routeConversationId)
          if (runs[0]) {
            adoptRun(runs[0])
            navigate(researchRunUrl(routeConversationId, runs[0].id, activeView), { replace: true })
          } else {
            setRun(undefined)
          }
        } catch (error) {
          if (!cancelled) setUiError(error instanceof Error ? error.message : 'Could not restore this research thread')
        }
        return
      }
      if (location.pathname === '/') {
        setConversationId(undefined)
        setRun(undefined)
        setEvidence(undefined)
      }
    }
    void restore()
    return () => { cancelled = true }
  }, [activeView, adoptRun, authenticated, conversationId, location.pathname, navigate, routeConversationId, routeRunId, run])

  useEffect(() => {
    if (!authenticated) return
    if (!routeEvidenceId) {
      setEvidence(undefined)
      return
    }
    if (evidence?.id === routeEvidenceId) return
    let cancelled = false
    void api.getEvidence(routeEvidenceId).then((item) => { if (!cancelled) setEvidence(item) }).catch((error) => {
      if (!cancelled) setUiError(error instanceof Error ? error.message : 'Could not load evidence')
    })
    return () => { cancelled = true }
  }, [authenticated, evidence?.id, routeEvidenceId])

  const runUrl = useCallback((view: ResearchView = activeView, evidenceId?: string) => {
    if (!run) return '/'
    return researchRunUrl(run.conversation_id, run.id, view, evidenceId)
  }, [activeView, run])

  const openEvidence = async (id: string) => {
    try {
      const item = await api.getEvidence(id)
      setEvidence(item)
      if (run) navigate(runUrl(activeView, id))
    } catch (error) {
      setUiError(error instanceof Error ? error.message : 'Could not load evidence')
    }
  }

  const closeEvidence = () => {
    setEvidence(undefined)
    if (run) navigate(runUrl(activeView), { replace: true })
  }

  const selectView = (view: ResearchView) => {
    if (run) navigate(runUrl(view, routeEvidenceId))
  }

  const submit = async (text: string) => {
    if (!canWrite) { setUiError('Your workspace role is read-only.'); return }
    setUiError(undefined)
    if (sourceScope.includes('documents') && selectedDocuments.length === 0) {
      setUiError('Select at least one ready document, or turn off the Documents source.')
      setWorkspace('documents')
      return
    }
    try {
      let activeConversation = conversationId
      if (!activeConversation) {
        const conversation = await api.createConversation(text.slice(0, 80))
        activeConversation = conversation.id
        setConversationId(conversation.id)
        await queryClient.invalidateQueries({ queryKey: ['conversations'] })
      }
      const snapshot = await api.createRun({
        conversationId: activeConversation,
        query: text,
        modelProvider,
        mode,
        sourceScope,
        plugins: activePlugins,
        documentIds: sourceScope.includes('documents') ? selectedDocuments : [],
        idempotencyKey: idempotencyKey(),
      })
      adoptRun(snapshot)
      navigate(researchRunUrl(snapshot.conversation_id, snapshot.id, 'answer'))
    } catch (error) {
      setUiError(error instanceof Error ? error.message : 'Could not start research')
    }
  }

  const retry = async () => {
    if (!run || !canWrite) return
    setUiError(undefined)
    try {
      const snapshot = await api.createRun({
        conversationId: run.conversation_id,
        query: run.query,
        modelProvider,
        mode: run.mode,
        sourceScope: run.source_scope,
        documentIds: run.document_ids,
        plugins: run.plugins,
        dateWindow: run.date_window,
        idempotencyKey: idempotencyKey(),
      })
      adoptRun(snapshot)
      navigate(researchRunUrl(snapshot.conversation_id, snapshot.id, 'answer'))
    } catch (error) {
      setUiError(error instanceof Error ? error.message : 'Could not retry research')
    }
  }

  const richIngestionReady = Boolean(system.data?.ingestion?.ready)

  const uploadDocument = async (file: File) => {
    if (!canWrite) throw new Error('Your workspace role is read-only.')
    setUploading(true)
    try {
      const lower = file.name.toLowerCase()
      const isPdf = lower.endsWith('.pdf') || file.type === 'application/pdf'
      const isMarkdown = lower.endsWith('.md') || file.type === 'text/markdown'
      const isText = lower.endsWith('.txt') || file.type === 'text/plain'
      const isCsv = lower.endsWith('.csv') || file.type === 'text/csv'
      const isImage = ['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || /\.(png|jpe?g|webp)$/i.test(lower)
      const isAudio = file.type.startsWith('audio/') || /\.(wav|mp3|m4a|ogg)$/i.test(lower)
      const isVideo = file.type.startsWith('video/') || /\.(mp4|webm)$/i.test(lower)
      if (!isPdf && !isMarkdown && !isText && !isCsv && !isImage && !isAudio && !isVideo) {
        throw new Error('ARES accepts PDF, images, CSV, Markdown, text, supported audio, MP4, or WebM research files.')
      }
      if (isAudio && !system.data?.ingestion?.audio_ready) {
        throw new Error('Audio ingestion is not ready. Check the media worker, FFmpeg, faster-whisper runtime, and provisioned model.')
      }
      if (isVideo && !system.data?.ingestion?.video_ready) {
        throw new Error('Video ingestion is not ready. Check the media worker, FFmpeg, faster-whisper runtime, and provisioned model.')
      }
      if ((isPdf || isCsv || isImage || isAudio || isVideo) && richIngestionReady) {
        await api.uploadAsset(file)
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ['assets'] }),
          queryClient.invalidateQueries({ queryKey: ['ingestions'] }),
        ])
      } else if (isPdf) {
        await api.uploadPdf(file)
      } else if (isCsv || isImage || isAudio || isVideo) {
        throw new Error('Rich ingestion is not ready on the current media-worker profile. PDF/text compatibility upload is still available.')
      } else {
        const text = await file.text()
        const mime = isMarkdown ? 'text/markdown' : 'text/plain'
        await api.createTextDocument(file.name, text, mime)
      }
      await queryClient.invalidateQueries({ queryKey: ['documents'] })
    } finally {
      setUploading(false)
    }
  }

  const cancelIngestion = async (ingestionId: string) => {
    if (!canWrite) throw new Error('Your workspace role is read-only.')
    await api.cancelIngestion(ingestionId)
    await queryClient.invalidateQueries({ queryKey: ['ingestions'] })
  }

  const retryIngestion = async (ingestionId: string) => {
    if (!canWrite) throw new Error('Your workspace role is read-only.')
    await api.retryIngestion(ingestionId)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['ingestions'] }),
      queryClient.invalidateQueries({ queryKey: ['assets'] }),
    ])
  }

  const deleteAsset = async (assetId: string) => {
    if (!canWrite) throw new Error('Your workspace role is read-only.')
    const linkedDocumentIds = (ingestions.data ?? [])
      .filter((item) => item.asset_id === assetId && item.document_id)
      .map((item) => item.document_id as string)
    await api.deleteAsset(assetId)
    if (linkedDocumentIds.length > 0) {
      setSelectedDocuments((current) => current.filter((id) => !linkedDocumentIds.includes(id)))
    }
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['assets'] }),
      queryClient.invalidateQueries({ queryKey: ['ingestions'] }),
      queryClient.invalidateQueries({ queryKey: ['documents'] }),
    ])
  }

  const deleteDocument = async (documentId: string) => {
    if (!canWrite) throw new Error('Your workspace role is read-only.')
    await api.deleteDocument(documentId)
    setSelectedDocuments((current) => current.filter((id) => id !== documentId))
    await queryClient.invalidateQueries({ queryKey: ['documents'] })
  }

  const exportRun = async (format: 'markdown' | 'json') => {
    if (!canWrite || !run || !['completed', 'partial'].includes(run.status)) return
    setExporting(format)
    setUiError(undefined)
    try {
      const artifact = await api.createExport(run.id, format)
      window.location.assign(artifact.download_url)
    } catch (error) {
      setUiError(error instanceof Error ? error.message : 'Export failed')
    } finally {
      setExporting(undefined)
    }
  }

  return (
    <div className={`app-shell ${evidence || workspace ? 'with-drawer' : ''}`}>
      <aside className={`nav-rail ${navOpen ? 'open' : ''}`}>
        <div className="brand-row">
          <div className="brand-mark">A</div>
          <div><strong>ARES</strong><span>Research & evidence</span></div>
          <button className="icon-button mobile-close" onClick={() => setNavOpen(false)} aria-label="Close navigation"><X size={18} /></button>
        </div>
        <button className="new-research" disabled={!canWrite} onClick={() => { setConversationId(undefined); setRun(undefined); setUiError(undefined); setNavOpen(false); navigate('/') }}>
          <Plus size={17} /> New research
        </button>
        <div className="nav-section-label">Recent</div>
        <nav className="thread-list" aria-label="Conversation history">
          {conversations.data?.map((conversation) => (
            <div className="thread-row" key={conversation.id}>
            <button
              className={conversation.id === conversationId ? 'active' : ''}
              onClick={() => {
                setConversationId(conversation.id)
                setRun(undefined)
                setEvidence(undefined)
                setNavOpen(false)
                navigate(researchConversationUrl(conversation.id, 'answer'))
              }}
            >
              <span>{conversation.title}</span><small>{new Date(conversation.updated_at).toLocaleDateString()}</small>
            </button>
            {canWrite && <button
              className="thread-delete"
              aria-label={`Delete chat: ${conversation.title}`}
              title="Delete chat"
              disabled={deleteChat.isPending}
              onClick={() => deleteChat.mutate(conversation.id)}
            ><Trash2 size={16} aria-hidden="true" /></button>}
            </div>
          ))}
          {!conversations.data?.length && <div className="empty-nav">Your research threads will appear here.</div>}
        </nav>
        <div className="nav-bottom">
          <button onClick={() => { setWorkspace('documents'); setNavOpen(false) }}><FileStack size={16} /> Documents {selectedDocuments.length > 0 && <span className="nav-count">{selectedDocuments.length}</span>}</button>
          <button onClick={() => { setWorkspace('system'); setNavOpen(false) }}><Settings2 size={16} /> System</button>
        </div>
      </aside>

      <main className="main-view">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setNavOpen(true)} aria-label="Open navigation"><Menu size={20} /></button>
          <div className="demo-pill"><span />{system.data?.mode === 'local_live' ? 'Live · strict free' : 'Recorded demo · keyless'}</div>
          <div className="stream-state">{busy ? (connected ? 'Live progress' : 'Reconnecting…') : canWrite ? 'Ready' : 'Read only'}</div>
          <button className="icon-button theme-toggle" onClick={() => setTheme((value) => value === 'dark' ? 'light' : 'dark')} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>{theme === 'dark' ? <Sun size={17}/> : <Moon size={17}/>}</button>
          <div className="account-area">
            <button className="account-chip" onClick={() => setAccountOpen((value) => !value)} aria-expanded={accountOpen}>
              <UserRound size={15}/><span>{authData.display_name || authData.email || 'Researcher'}</span><small>{authData.role}</small>
            </button>
            {accountOpen && <div className="account-menu">
              <div className="account-identity"><strong>{authData.display_name || authData.email || authData.subject}</strong>{authData.email && <span>{authData.email}</span>}<small>{authData.role} · {authData.auth_mode}</small></div>
              {(workspaces.data?.length ?? 0) > 1 && <label>Workspace<select value={authData.workspace_id} disabled={switchWorkspace.isPending} onChange={(event) => switchWorkspace.mutate(event.target.value)}>{workspaces.data?.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.role}</option>)}</select></label>}
              {authData.auth_mode === 'oidc' && <button disabled={logout.isPending} onClick={() => logout.mutate()}><LogOut size={14}/>{logout.isPending ? 'Signing out…' : 'Sign out'}</button>}
            </div>}
          </div>
        </header>

        {!canWrite && <div className="readonly-banner">Viewer access · research, uploads, exports, cancellation, and other mutations are disabled.</div>}
        {uiError && <div className="global-error" role="alert"><AlertTriangle size={16} /><span>{uiError}</span><button onClick={() => setUiError(undefined)} aria-label="Dismiss error"><X size={15} /></button></div>}

        {!run ? (
          <div className="home-state">
            <div className="hero-badge"><Sparkles size={16} /> evidence-first research</div>
            <h1>Research you can<br /><em>trace back.</em></h1>
            <Composer
              busy={false}
              readOnly={!canWrite}
              modelProvider={modelProvider}
              onModelProvider={setModelProvider}
              models={modelCatalog.data}
              mode={mode}
              onMode={setMode}
              sourceScope={sourceScope}
              onSourceScope={setSourceScope}
              selectedDocuments={selectedDocuments.length}
              onSubmit={submit}
              onStop={() => undefined}
            />
            <div className="example-grid">
              {[
                { id: 'speed', label: 'Speed Boost', desc: 'Accelerates retrieval and reduces token overhead.' },
                { id: 'accuracy', label: 'Deep Verification', desc: 'Cross-checks every claim against multiple sources.' },
                { id: 'code', label: 'Code Interpreter', desc: 'Executes Python for technical math and logic.' }
              ].map(p => (
                <button 
                  key={p.id} 
                  disabled={!canWrite}
                  className={activePlugins.includes(p.id) ? 'active-plugin' : ''}
                  onClick={() => setActivePlugins(prev => prev.includes(p.id) ? prev.filter(id => id !== p.id) : [...prev, p.id])}
                  style={{ 
                    textAlign: 'left', 
                    border: activePlugins.includes(p.id) ? '1px solid var(--brand)' : '1px solid var(--border)',
                    background: activePlugins.includes(p.id) ? 'var(--brand-surface)' : 'var(--bg)'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <span style={{ fontWeight: 600, color: activePlugins.includes(p.id) ? 'var(--brand)' : 'var(--text)' }}>{p.label}</span>
                    {activePlugins.includes(p.id) && <Check size={14} color="var(--brand)" />}
                  </div>
                  <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>{p.desc}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="thread-view">
            <RunHeader run={run} />
            <CompactResearchProgress status={run.status} events={events} onViewActivity={() => navigate(runUrl('activity'))} />
            <ResearchViewNav 
              activeView={activeView} 
              onSelectView={selectView} 
              evidenceCount={runEvidence.data?.length} 
            />

            {activeView === 'answer' && <>
              {run.answer_blocks.map((block) => <Answer key={block.id} block={block} runEvidence={runEvidence.data} onReviewSources={() => navigate(runUrl('sources'))} onEvidence={openEvidence} />)}

              <ResearchGaps gaps={run.gaps} runStatus={run.status} />
              <RelatedQuestions questions={run.related_questions} onAsk={submit} />
              {run.status === 'failed' && <section className="failure-card"><div><AlertTriangle size={18} /><strong>{run.error_code ?? 'Research failed'}</strong><p>{run.error_message}</p></div><button disabled={!canWrite} onClick={() => void retry()}><RotateCcw size={16} /> Retry as new run</button></section>}
              {run.status === 'cancelled' && <section className="failure-card calm"><div><strong>Research stopped</strong><p>Completed work was preserved. Retry starts a new run with the same source policy.</p></div><button disabled={!canWrite} onClick={() => void retry()}><RotateCcw size={16} /> Retry</button></section>}
              <div className="followup">
                <FollowUpComposer
                  busy={busy}
                  readOnly={!canWrite}
                  modelProvider={modelProvider}
                  onModelProvider={setModelProvider}
                  models={modelCatalog.data}
                  mode={mode}
                  onMode={setMode}
                  sourceScope={sourceScope}
                  onSourceScope={setSourceScope}
                  selectedDocuments={selectedDocuments.length}
                  onSubmit={submit}
                  onStop={() => cancel.mutate()}
                />
              </div>
            </>}
            {activeView === 'sources' && (runEvidence.isError ? <div className="workspace-empty">Could not load run evidence: {runEvidence.error instanceof Error ? runEvidence.error.message : 'unknown error'}</div> : <EvidenceIndex evidence={runEvidence.data ?? []} onEvidence={openEvidence}/>)}
            {activeView === 'compare' && (system.data?.visualizations?.ready ? <VisualizationWorkspace visualizations={visualizations.data ?? []} loading={visualizations.isLoading} error={visualizations.error instanceof Error ? visualizations.error.message : undefined} onEvidence={openEvidence}/> : <div className="workspace-empty"><GitCompareArrows size={20}/><strong>Evidence-linked visualizations are unavailable on this profile.</strong><span>The answer and evidence remain usable; enable the M11 visualization capability only when migration 0012 is ready.</span></div>)}
            {activeView === 'diagnostics' && (quality.data ? <RunQualityPanel quality={quality.data} onEvidence={openEvidence} /> : <div className="workspace-empty">{quality.isError ? 'Could not load run diagnostics.' : terminal.has(run.status) ? 'Loading run diagnostics…' : 'Diagnostics will be available when this research finishes.'}</div>)}
            {activeView === 'activity' && <ResearchActivity status={run.status} events={events} detailed/>}
          </div>
        )}
      </main>

      {evidence && <EvidenceDrawer evidence={evidence} onClose={closeEvidence} />}
      {workspace && (
        <WorkspacePanel
          view={workspace}
          documents={documents.data ?? []}
          assets={assets.data ?? []}
          ingestions={ingestions.data ?? []}
          system={system.data}
          selected={selectedDocuments}
          busyUpload={uploading}
          richIngestionReady={richIngestionReady}
          readOnly={!canWrite}
          onClose={() => setWorkspace(undefined)}
          onSelect={(ids) => { setSelectedDocuments(ids); if (ids.length > 0 && !sourceScope.includes('documents')) setSourceScope([...sourceScope, 'documents']) }}
          onUpload={uploadDocument}
          onDelete={deleteDocument}
          onCancelIngestion={cancelIngestion}
          onRetryIngestion={retryIngestion}
          onDeleteAsset={deleteAsset}
        />
      )}
      {navOpen && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setNavOpen(false)} />}
    </div>
  )
}

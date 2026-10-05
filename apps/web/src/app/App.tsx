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
  Settings2,
  Sparkles,
  Sun,
  LogOut,
  UserRound,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ApiError, api } from '../lib/api/client'
import { parseResearchLocation, researchConversationUrl, researchRunUrl, type ResearchView } from '../lib/researchRoutes'
import type { Evidence, RunMode, RunSnapshot, SourceScope } from '../lib/api/types'
import { Answer } from '../features/research/Answer'
import { Composer } from '../features/research/Composer'
import { EvidenceDrawer } from '../features/research/EvidenceDrawer'
import { EvidenceIndex } from '../features/research/EvidenceIndex'
import { ResearchActivity } from '../features/research/ResearchActivity'
import { RunQualityPanel } from '../features/research/RunQualityPanel'
import { VisualizationWorkspace } from '../features/research/VisualizationWorkspace'
import { useRunStream } from '../features/research/useRunStream'
import { WorkspacePanel } from '../features/workspace/WorkspacePanel'

const terminal = new Set(['completed', 'partial', 'failed', 'cancelled'])
const idempotencyKey = () => crypto.randomUUID()

export default function App() {
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
  const [sessionExpired, setSessionExpired] = useState(false)
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = window.localStorage.getItem('ares-theme')
    if (saved === 'light' || saved === 'dark') return saved
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  })
  const { events, connected, snapshotRequiredSeq } = useRunStream(run?.id, Math.max(0, (run?.last_seq ?? 0) - 200))

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    window.localStorage.setItem('ares-theme', theme)
  }, [theme])

  useEffect(() => {
    const expire = () => setSessionExpired(true)
    window.addEventListener('ares:auth-expired', expire)
    return () => window.removeEventListener('ares:auth-expired', expire)
  }, [])

  const auth = useQuery({ queryKey: ['auth-me'], queryFn: api.me, retry: false, staleTime: 30_000 })
  const authenticated = Boolean(auth.data)
  const canWrite = auth.data?.role !== 'viewer'
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

  useQuery({
    queryKey: ['run', run?.id, events.at(-1)?.seq, snapshotRequiredSeq],
    queryFn: () => api.getRun(run!.id),
    enabled: Boolean(authenticated && run?.id),
    refetchInterval: run && !terminal.has(run.status) ? 1000 : false,
    select: (fresh) => { setRun(fresh); return fresh }
  })

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
        mode,
        sourceScope,
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
        mode: run.mode,
        sourceScope: run.source_scope,
        documentIds: run.document_ids,
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

  if (auth.isPending) {
    return <main className="auth-gate"><div className="auth-card"><div className="brand-mark">A</div><h1>ARES</h1><p>Loading your research workspace…</p></div></main>
  }

  if (sessionExpired || (auth.error instanceof ApiError && auth.error.status === 401)) {
    const returnPath = `${window.location.pathname}${window.location.search}`
    return (
      <main className="auth-gate">
        <section className="auth-card">
          <div className="brand-mark">A</div>
          <div className="eyebrow">Autonomous Research & Evidence System</div>
          <h1>Research you can trace back.</h1>
          <p>Your session is missing or expired. Sign in again through the configured identity provider to continue. Unsaved local composer text is not sent anywhere.</p>
          <a className="auth-signin" href={`/api/v1/auth/login?return_path=${encodeURIComponent(returnPath)}`}>Sign in to ARES</a>
        </section>
      </main>
    )
  }

  if (auth.isError || !auth.data) {
    return <main className="auth-gate"><section className="auth-card"><AlertTriangle size={22}/><h1>ARES could not start</h1><p>{auth.error instanceof Error ? auth.error.message : 'Authentication bootstrap failed.'}</p><button className="auth-signin" onClick={() => void auth.refetch()}>Retry</button></section></main>
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
            <button
              key={conversation.id}
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
              <UserRound size={15}/><span>{auth.data.display_name || auth.data.email || 'Researcher'}</span><small>{auth.data.role}</small>
            </button>
            {accountOpen && <div className="account-menu">
              <div className="account-identity"><strong>{auth.data.display_name || auth.data.email || auth.data.subject}</strong>{auth.data.email && <span>{auth.data.email}</span>}<small>{auth.data.role} · {auth.data.auth_mode}</small></div>
              {(workspaces.data?.length ?? 0) > 1 && <label>Workspace<select value={auth.data.workspace_id} disabled={switchWorkspace.isPending} onChange={(event) => switchWorkspace.mutate(event.target.value)}>{workspaces.data?.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.role}</option>)}</select></label>}
              {auth.data.auth_mode === 'oidc' && <button disabled={logout.isPending} onClick={() => logout.mutate()}><LogOut size={14}/>{logout.isPending ? 'Signing out…' : 'Sign out'}</button>}
            </div>}
          </div>
        </header>

        {!canWrite && <div className="readonly-banner">Viewer access · research, uploads, exports, cancellation, and other mutations are disabled.</div>}
        {uiError && <div className="global-error" role="alert"><AlertTriangle size={16} /><span>{uiError}</span><button onClick={() => setUiError(undefined)} aria-label="Dismiss error"><X size={15} /></button></div>}

        {!run ? (
          <div className="home-state">
            <div className="hero-badge"><Sparkles size={16} /> evidence-first research</div>
            <h1>Research you can<br /><em>trace back.</em></h1>
            <p>ARES finds sources, preserves evidence, and gives you an answer you can inspect—not just trust.</p>
            <Composer
              busy={false}
              readOnly={!canWrite}
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
                ['Compare', 'How do current agent-memory approaches differ in evaluation?'],
                ['Trace', 'Trace a software claim back to its official documentation.'],
                ['Challenge', 'Find where two sources disagree and explain the scope difference.']
              ].map(([label, text]) => (
                <button key={label} disabled={!canWrite} onClick={() => void submit(text)}><span>{label}</span>{text}</button>
              ))}
            </div>
          </div>
        ) : (
          <div className="thread-view">
            <div className="query-heading">
              <span>You asked</span><h1>{run.query}</h1>
              <div className="run-meta">
                <span>{run.mode}</span>
                {run.source_scope.map((scope) => <span key={scope}>{scope}</span>)}
                {run.document_ids.length > 0 && <span>{run.document_ids.length} document{run.document_ids.length === 1 ? '' : 's'}</span>}
              </div>
            </div>
            <ResearchActivity status={run.status} events={events} />
            <nav className="research-tabs" aria-label="Research workspace views">
              <button className={activeView === 'answer' ? 'active' : ''} onClick={() => selectView('answer')}><BookOpenText size={15}/> Answer</button>
              <button className={activeView === 'sources' ? 'active' : ''} onClick={() => selectView('sources')}><ListTree size={15}/> Sources {runEvidence.data?.length ? <span>{runEvidence.data.length}</span> : null}</button>
              <button className={activeView === 'compare' ? 'active' : ''} onClick={() => selectView('compare')}><GitCompareArrows size={15}/> Compare</button>
              <button className={activeView === 'activity' ? 'active' : ''} onClick={() => selectView('activity')}><Sparkles size={15}/> Activity</button>
            </nav>

            {activeView === 'answer' && <>
              {run.answer_blocks.map((block) => <Answer key={block.id} block={block} onEvidence={openEvidence} />)}
              {['completed', 'partial'].includes(run.status) && run.answer_blocks.length > 0 && (
                <div className="export-bar" aria-label="Export research">
                  <span><Download size={15} /> Export finalized evidence</span>
                  <button disabled={!canWrite || Boolean(exporting)} onClick={() => void exportRun('markdown')}>{exporting === 'markdown' ? 'Preparing…' : 'Markdown'}</button>
                  <button disabled={!canWrite || Boolean(exporting)} onClick={() => void exportRun('json')}>{exporting === 'json' ? 'Preparing…' : 'JSON manifest'}</button>
                </div>
              )}
              {terminal.has(run.status) && quality.data && <RunQualityPanel quality={quality.data} onEvidence={openEvidence} />}
              {run.gaps.length > 0 && <section className="gap-card"><Info size={18} /><div><strong>What remains unclear</strong>{run.gaps.map((gap) => <p key={gap}>{gap}</p>)}</div></section>}
              {run.status === 'failed' && <section className="failure-card"><div><AlertTriangle size={18} /><strong>{run.error_code ?? 'Research failed'}</strong><p>{run.error_message}</p></div><button disabled={!canWrite} onClick={() => void retry()}><RotateCcw size={16} /> Retry as new run</button></section>}
              {run.status === 'cancelled' && <section className="failure-card calm"><div><strong>Research stopped</strong><p>Completed work was preserved. Retry starts a new run with the same source policy.</p></div><button disabled={!canWrite} onClick={() => void retry()}><RotateCcw size={16} /> Retry</button></section>}
              <div className="followup">
                <Composer
                  busy={busy}
                  readOnly={!canWrite}
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

import type { ModelProvider } from '../../lib/api/types'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Compass,
  Search,
  ChevronRight,
  MessageSquare,
  AlertTriangle,
  Brain,
  Download,
  GitCompareArrows,
  FileStack,
  Menu,
  Moon,
  Plus,
  RotateCcw,
  Check,
  Settings2,
  Sun,
  LogOut,
  UserRound,
  Trash2,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../../lib/api/client'
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
import { uploadAccept } from './uploadPolicy'
import { WorkspacePanel } from '../workspace/WorkspacePanel'
import { MemoryPanel } from '../workspace/MemoryPanel'
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
  const [draftVersion, setDraftVersion] = useState(0)
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
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 900px)').matches)
  const navigation = useRef<HTMLElement>(null)
  const memoryButton = useRef<HTMLButtonElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const media = window.matchMedia('(max-width: 900px)')
    const update = () => setNarrow(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  useEffect(() => {
    if (!navOpen || !narrow) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    navigation.current?.querySelector<HTMLButtonElement>('.mobile-close')?.focus()
    return () => { document.body.style.overflow = previousOverflow; menuButton.current?.focus() }
  }, [navOpen, narrow])
  const [workspace, setWorkspace] = useState<'documents' | 'memory' | 'system'>()
  const [uiError, setUiError] = useState<string>()
  const [exporting, setExporting] = useState<'markdown' | 'json'>()
  const [uploading, setUploading] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
  const accountArea = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const dismiss = (event: PointerEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key !== 'Escape') return
        setNavOpen(false)
        setAccountOpen(false)
        if (accountArea.current?.contains(event.target as Node)) accountArea.current.querySelector('button')?.focus()
      } else if (!accountArea.current?.contains(event.target as Node)) setAccountOpen(false)
    }
    document.addEventListener('keydown', dismiss)
    document.addEventListener('pointerdown', dismiss)
    return () => { document.removeEventListener('keydown', dismiss); document.removeEventListener('pointerdown', dismiss) }
  }, [])
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = window.localStorage.getItem('ares-theme')
    if (saved === 'light' || saved === 'dark') return saved
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  })
  const { events, connected, snapshotRequiredSeq } = useRunStream(run?.id, Math.max(0, (run?.last_seq ?? 0) - 200))
  const [activePlugins, setActivePlugins] = useState<string[]>([])

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
      setConversationId(undefined); setRun(undefined); setEvidence(undefined); setWorkspace(undefined); setSelectedDocuments([]); setSourceScope(['web']); setUiError(undefined)
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
    if (snapshot.plugins && snapshot.plugins.length > 0) {
      setActivePlugins(snapshot.plugins)
    }
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
    if (!canWrite) { setUiError('Your workspace role is read-only.'); throw new Error('Read only') }
    setUiError(undefined)
    if (sourceScope.includes('documents') && selectedDocuments.length === 0) {
      setUiError('Select at least one ready document, or turn off the Documents source.')
      setWorkspace('documents')
      throw new Error('Select a document first')
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
      throw error
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
        const document = await api.uploadPdf(file)
        if (['ready', 'partial'].includes(document.status)) { setSelectedDocuments(ids => [...new Set([...ids, document.id])]); setSourceScope(scopes => [...new Set([...scopes, 'documents' as const])]) }
      } else if (isCsv || isImage || isAudio || isVideo) {
        throw new Error('Rich ingestion is not ready on the current media-worker profile. PDF/text compatibility upload is still available.')
      } else {
        const text = await file.text()
        const mime = isMarkdown ? 'text/markdown' : 'text/plain'
        const document = await api.createTextDocument(file.name, text, mime)
        if (['ready', 'partial'].includes(document.status)) { setSelectedDocuments(ids => [...new Set([...ids, document.id])]); setSourceScope(scopes => [...new Set([...scopes, 'documents' as const])]) }
      }
      await queryClient.invalidateQueries({ queryKey: ['documents'] })
    } finally {
      setUploading(false)
    }
  }

  const uploadFiles = async (files: File[]) => {
    setUiError(undefined)
    setWorkspace('documents')
    try { for (const file of files) await uploadDocument(file) }
    catch (error) { setUiError(error instanceof Error ? error.message : 'Upload failed') }
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
      <aside ref={navigation} role={narrow && navOpen ? 'dialog' : undefined} aria-modal={narrow && navOpen ? true : undefined} aria-label="Workspace navigation" onKeyDown={(event) => {
        if (!narrow || !navOpen || event.key !== 'Tab') return
        const controls = Array.from(navigation.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [])
        const first = controls[0], last = controls[controls.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }} inert={narrow && !navOpen} className={`nav-rail ${navOpen ? 'open' : ''}`}>
        <div className="brand-row">
          <div className="brand-mark"><Compass size={26} strokeWidth={1.6} aria-hidden="true" /></div>
          <div><strong>ARES</strong><span>Follow your curiosity</span></div>
          <button className="icon-button mobile-close" onClick={() => setNavOpen(false)} aria-label="Close navigation"><X size={18} /></button>
        </div>
        <button className="new-research" disabled={!canWrite} onClick={() => { setConversationId(undefined); setRun(undefined); setUiError(undefined); setEvidence(undefined); setWorkspace(undefined); setSelectedDocuments([]); setSourceScope(['web']); setDraftVersion((value) => value + 1); setNavOpen(false); navigate('/') }}>
          <Plus size={19} /> New search
        </button>
        <nav className="primary-nav" aria-label="Workspace"><button className={workspace === 'documents' ? 'active' : ''} onClick={() => { setWorkspace('documents'); setNavOpen(false) }}><FileStack size={18} /> Library {selectedDocuments.length > 0 && <span className="nav-count">{selectedDocuments.length}</span>}</button></nav>
        <div className="nav-section-label"><MessageSquare size={14} /> Your threads</div>
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
          {conversations.isLoading && <div className="empty-nav">Loading your threads…</div>}
          {conversations.isError && <div className="empty-nav">Couldn't load your threads.<button onClick={() => void conversations.refetch()}>Try again</button></div>}
          {conversations.isSuccess && !conversations.data.length && <div className="empty-nav">Start a search.<br />Pick it up here anytime.</div>}
        </nav>
        <div className="nav-bottom">
          <button ref={memoryButton} onClick={() => { setWorkspace('memory'); setNavOpen(false) }}><Brain size={18} /> Memory</button>
          <button onClick={() => { setWorkspace('system'); setNavOpen(false) }}><Settings2 size={18} /> Settings</button>
        </div>
      </aside>

      <main className="main-view" inert={narrow && navOpen}>
        <header className="topbar">
          <button ref={menuButton} aria-expanded={navOpen} className="icon-button mobile-menu" onClick={() => setNavOpen(true)} aria-label="Open navigation"><Menu size={20} /></button>
          <div className="workspace-breadcrumb"><Compass size={17} /><span>{run ? 'Research' : 'Search'}</span>{run && <><ChevronRight size={13} /><span className="breadcrumb-title">{run.query}</span></>}</div>
          <div className="stream-state">{busy ? (connected ? 'Researching…' : 'Reconnecting…') : !canWrite ? 'Read only' : system.data?.mode === 'demo' ? 'Demo workspace' : ''}</div>
          <button className="icon-button theme-toggle" onClick={() => setTheme((value) => value === 'dark' ? 'light' : 'dark')} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>{theme === 'dark' ? <Sun size={17}/> : <Moon size={17}/>}</button>
          <div className="account-area" ref={accountArea}>
            <button className="account-chip" aria-label="Account and workspace" onClick={() => setAccountOpen((value) => !value)} aria-expanded={accountOpen}>
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
        {uiError && workspace !== 'documents' && <div className="global-error" role="alert"><AlertTriangle size={16} /><span>{uiError}</span><button onClick={() => setUiError(undefined)} aria-label="Dismiss error"><X size={15} /></button></div>}

        {!run ? (
          <div className="home-state">
            <div className="home-compass" aria-hidden="true"><Compass size={34} strokeWidth={1.4} /></div>
            <h1>Where will curiosity take you?</h1>
            <p>Ask a question. Get an answer with sources you can explore.</p>
            <Composer
              key={draftVersion}
              busy={false}
              showSuggestions
              onUpload={uploadFiles}
              uploadAccept={uploadAccept(system.data, richIngestionReady)}
              uploading={uploading}
              readOnly={!canWrite}
              modelProvider={modelProvider}
              onModelProvider={setModelProvider}
              models={modelCatalog.data}
              mode={mode}
              onMode={setMode}
              sourceScope={sourceScope}
              onSourceScope={setSourceScope}
              selectedDocuments={selectedDocuments.length}
              plugins={activePlugins}
              onPlugins={setActivePlugins}
              onSubmit={submit}
              onStop={() => undefined}
            />

          </div>
        ) : (
          <div className="thread-view">
            <RunHeader run={run} />
            <CompactResearchProgress status={run.status} events={events} onViewActivity={() => navigate(runUrl('activity'))} />
            <ResearchViewNav 
              activeView={activeView} 
              onSelectView={selectView} 
              evidenceCount={runEvidence.data ? new Set(runEvidence.data.map((item) => item.source.id || item.id)).size : undefined}
            />

            {activeView === 'answer' && <>
              {run.answer_blocks.map((block) => <Answer key={block.id} block={block} runEvidence={runEvidence.data} onReviewSources={() => navigate(runUrl('sources'))} onEvidence={openEvidence} />)}

              {['completed', 'partial'].includes(run.status) && <div className="answer-actions"><button className="quiet-button" disabled={!canWrite || Boolean(exporting)} onClick={() => void exportRun('markdown')}><Download size={16} />{exporting ? 'Exporting…' : 'Export answer'}</button></div>}
              <ResearchGaps gaps={run.gaps} runStatus={run.status} />
              <RelatedQuestions disabled={!canWrite || busy} questions={run.related_questions} onAsk={(question) => { void submit(question).catch(() => undefined) }} />
              {run.status === 'failed' && <section className="failure-card"><div><AlertTriangle size={18} /><strong>{run.error_code ?? 'Research failed'}</strong><p>{run.error_message}</p></div><button disabled={!canWrite} onClick={() => void retry()}><RotateCcw size={16} /> Retry as new run</button></section>}
              {run.status === 'cancelled' && <section className="failure-card calm"><div><strong>Research stopped</strong><p>Completed work was preserved. Retry starts a new run with the same source policy.</p></div><button disabled={!canWrite} onClick={() => void retry()}><RotateCcw size={16} /> Retry</button></section>}
              <div className="followup">
                <FollowUpComposer
                  onUpload={uploadFiles}
                  uploadAccept={uploadAccept(system.data, richIngestionReady)}
                  uploading={uploading}
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
                  plugins={activePlugins}
                  onPlugins={setActivePlugins}
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
      {workspace === 'memory' ? (
        <MemoryPanel readOnly={!canWrite} onClose={() => { setWorkspace(undefined); requestAnimationFrame(() => (narrow ? menuButton.current : memoryButton.current)?.focus()) }} />
      ) : workspace ? (
        <WorkspacePanel
          view={workspace}
          uploading={uploading}
          uploadError={uiError}
          documents={documents.data ?? []}
          assets={assets.data ?? []}
          ingestions={ingestions.data ?? []}
          system={system.data}
          selected={selectedDocuments}
          readOnly={!canWrite}
          onClose={() => setWorkspace(undefined)}
          onSelect={(ids) => { setSelectedDocuments(ids); if (ids.length > 0 && !sourceScope.includes('documents')) setSourceScope([...sourceScope, 'documents']) }}
          onDelete={deleteDocument}
          onCancelIngestion={cancelIngestion}
          onRetryIngestion={retryIngestion}
          onDeleteAsset={deleteAsset}
        />
      ) : null}
      {navOpen && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setNavOpen(false)} />}
    </div>
  )
}

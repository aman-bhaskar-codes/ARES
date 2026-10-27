import {
  AlertCircle,
  ArrowUpRight,
  Brain,
  Check,
  Download,
  FileText,
  History,
  LoaderCircle,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  X,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../../lib/api/client";
import { SafeMarkdown } from "../research/SafeMarkdown";
import type {
  MemoryEpisode,
  MemoryFact,
  MemoryPreference,
} from "../../lib/api/types";

type Tab = "episodes" | "facts" | "preferences";
type Confirmation =
  | { kind: "episode" | "fact"; id: string; title: string }
  | { kind: "consolidate" }
  | { kind: "discard"; href?: string };
const tabs = [
  { id: "episodes" as const, label: "Research history", icon: History },
  { id: "facts" as const, label: "Saved facts", icon: ShieldCheck },
  { id: "preferences" as const, label: "Preferences", icon: Settings2 },
];
const date = (value: string) =>
  new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
const message = (error: unknown) => {
  if (error instanceof ApiError && error.status >= 500)
    return "Memory is temporarily unavailable. Please try again.";
  if (error instanceof ApiError && error.status === 403)
    return "You do not have permission to change this workspace memory.";
  if (error instanceof TypeError)
    return "Could not connect to memory. Check your connection and try again.";
  return error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
};
const domains = (value: string) =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

export function MemoryPanel({
  readOnly = false,
  onClose,
}: {
  readOnly?: boolean;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const dialog = useRef<HTMLDialogElement>(null);
  const loadVersion = useRef(0);
  const searchInput = useRef<HTMLInputElement>(null);
  const confirmCancel = useRef<HTMLButtonElement>(null);
  const errorBox = useRef<HTMLDivElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const requestId = useRef(0);
  const [tab, setTab] = useState<Tab>("episodes");
  const [episodes, setEpisodes] = useState<MemoryEpisode[]>([]);
  const [facts, setFacts] = useState<MemoryFact[]>([]);
  const [preferences, setPreferences] = useState<MemoryPreference | null>(null);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchedEpisodes, setSearchedEpisodes] = useState<
    MemoryEpisode[] | null
  >(null);
  const [searchedFacts, setSearchedFacts] = useState<MemoryFact[] | null>(null);
  const [status, setStatus] = useState("active");
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [depth, setDepth] = useState<MemoryPreference["depth"]>("standard");
  const [tone, setTone] = useState<MemoryPreference["tone"]>("academic");
  const [preferred, setPreferred] = useState("");
  const [excluded, setExcluded] = useState("");
  const [instructions, setInstructions] = useState("");
  const hydrate = (value: MemoryPreference) => {
    setDepth(value.depth);
    setTone(value.tone);
    setPreferred(value.preferred_domains.join(", "));
    setExcluded(value.excluded_domains.join(", "));
    setInstructions(value.custom_instructions ?? "");
  };
  const dirty = Boolean(
    preferences &&
      (depth !== preferences.depth ||
        tone !== preferences.tone ||
        JSON.stringify(domains(preferred)) !==
          JSON.stringify(preferences.preferred_domains) ||
        JSON.stringify(domains(excluded)) !==
          JSON.stringify(preferences.excluded_domains) ||
        instructions.trim() !== (preferences.custom_instructions ?? "")),
  );
  const load = async () => {
    const version = ++loadVersion.current;
    setLoading(true);
    setError("");
    try {
      const [history, saved, prefs] = await Promise.all([
        api.listMemoryEpisodes(100),
        api.listMemoryFacts(undefined, "all"),
        api.getMemoryPreferences(),
      ]);
      if (version !== loadVersion.current) return;
      setEpisodes(history);
      setFacts(saved);
      setPreferences(prefs);
      hydrate(prefs);
      setLoaded(true);
    } catch (error) {
      if (version === loadVersion.current) setError(message(error));
    } finally {
      if (version === loadVersion.current) setLoading(false);
    }
  };
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    void load();
    return () => {
      requestId.current++;
      loadVersion.current++;
      element?.close();
    };
  }, []);
  useEffect(() => {
    if (confirmation) confirmCancel.current?.focus();
  }, [confirmation]);
  useEffect(() => {
    if (error) {
      errorBox.current?.focus({ preventScroll: true });
      errorBox.current?.scrollIntoView({ block: "nearest" });
    }
  }, [error]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const ask = (value: Confirmation) => {
    returnFocus.current = document.activeElement as HTMLElement;
    setConfirmation(value);
  };
  const cancelConfirmation = () => {
    setConfirmation(null);
    requestAnimationFrame(() => returnFocus.current?.focus());
  };
  const close = () => {
    if (!busy) {
      if (confirmation) cancelConfirmation();
      else if (dirty) ask({ kind: "discard" });
      else onClose();
    }
  };
  const trapFocus = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (event.key !== "Tab") return;
    const items = Array.from(
      dialog.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]',
      ) ?? [],
    ).filter(
      (element) =>
        element.tabIndex >= 0 &&
        !element.closest("[inert]") &&
        element.getClientRects().length > 0,
    );
    const first = items[0],
      last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  };
  const clearSearch = () => {
    requestId.current++;
    setQuery("");
    setSearchedEpisodes(null);
    setSearchedFacts(null);
    setSearching(false);
    setError("");
  };
  const changeTab = (value: Tab) => {
    clearSearch();
    setTab(value);
    setNotice("");
  };
  const navigateTabs = (
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? 2
          : (index + (event.key === "ArrowRight" ? 1 : -1) + 3) % 3;
    changeTab(tabs[next].id);
    document.getElementById(`memory-tab-${tabs[next].id}`)?.focus();
  };
  const search = async (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim()) {
      clearSearch();
      searchInput.current?.focus();
      return;
    }
    const id = ++requestId.current;
    setSearching(true);
    setError("");
    try {
      if (tab === "episodes") {
        const rows = await api.searchMemoryEpisodes(query.trim());
        if (id === requestId.current)
          setSearchedEpisodes(rows.map((row) => row.episode));
      } else {
        const rows = await api.searchMemoryFacts(query.trim());
        if (id === requestId.current)
          setSearchedFacts(rows.map((row) => row.fact));
      }
    } catch (error) {
      if (id === requestId.current) setError(message(error));
    } finally {
      if (id === requestId.current) setSearching(false);
    }
  };
  const applyConfirmation = async () => {
    if (!confirmation || busy) return;
    if (confirmation.kind === "discard") {
      onClose();
      if (confirmation.href) navigate(confirmation.href);
      return;
    }
    if (readOnly) return;
    setBusy(true);
    setError("");
    try {
      if (confirmation.kind === "episode") {
        await api.deleteMemoryEpisode(confirmation.id);
        setEpisodes((rows) => rows.filter((row) => row.id !== confirmation.id));
        setSearchedEpisodes(
          (rows) => rows?.filter((row) => row.id !== confirmation.id) ?? null,
        );
        setNotice(
          "Research memory deleted. Your original research is unchanged.",
        );
      } else if (confirmation.kind === "fact") {
        await api.deleteMemoryFact(confirmation.id);
        setFacts((rows) => rows.filter((row) => row.id !== confirmation.id));
        setSearchedFacts(
          (rows) => rows?.filter((row) => row.id !== confirmation.id) ?? null,
        );
        setNotice("Saved fact deleted.");
      } else {
        await api.consolidateMemoryFacts();
        setFacts(await api.listMemoryFacts(undefined, "all"));
        clearSearch();
        setNotice(
          "Saved facts organized. Check Replaced for older duplicate or conflicting entries.",
        );
      }
      setConfirmation(null);
      requestAnimationFrame(() =>
        document.getElementById(`memory-tab-${tab}`)?.focus(),
      );
    } catch (error) {
      setError(message(error));
      setConfirmation(null);
    } finally {
      setBusy(false);
    }
  };
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (readOnly || busy || !dirty) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const prefs = await api.updateMemoryPreferences({
        depth,
        tone,
        preferred_domains: domains(preferred),
        excluded_domains: domains(excluded),
        custom_instructions: instructions.trim() || null,
      });
      setPreferences(prefs);
      hydrate(prefs);
      setNotice("Preferences saved.");
    } catch (error) {
      setError(message(error));
    } finally {
      setBusy(false);
    }
  };
  const exportJson = () => {
    const url = URL.createObjectURL(
      new Blob(
        [
          JSON.stringify(
            {
              exported_at: new Date().toISOString(),
              scope: "loaded_recent_entries",
              episodes,
              facts,
              preferences,
            },
            null,
            2,
          ),
        ],
        { type: "application/json" },
      ),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `ares-memory-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const visibleEpisodes = searchedEpisodes ?? episodes;
  const visibleFacts = (searchedFacts ?? facts).filter(
    (fact) => status === "all" || fact.status === status,
  );
  const isSearch =
    tab === "episodes" ? searchedEpisodes !== null : searchedFacts !== null;
  return (
    <dialog
      ref={dialog}
      className="memory-dialog"
      aria-labelledby="memory-title"
      aria-describedby="memory-description"
      onKeyDown={trapFocus}
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
    >
      <div className="memory-layout" inert={confirmation !== null}>
        <header className="memory-header">
          <span className="memory-brand-icon">
            <Brain size={23} />
          </span>
          <div className="memory-heading">
            <span className="memory-eyebrow">YOUR RESEARCH, REMEMBERED</span>
            <h2 id="memory-title">Workspace memory</h2>
            <p id="memory-description">
              Revisit discoveries, inspect saved facts, and shape your research
              preferences.
            </p>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="Close memory panel"
            onClick={close}
            disabled={busy}
            autoFocus
          >
            <X size={20} />
          </button>
        </header>
        <div
          className="memory-navigation"
          role="tablist"
          aria-label="Memory sections"
        >
          {tabs.map(({ id, label, icon: Icon }, index) => (
            <button
              type="button"
              key={id}
              id={`memory-tab-${id}`}
              role="tab"
              aria-selected={tab === id}
              aria-controls={`memory-panel-${id}`}
              tabIndex={tab === id ? 0 : -1}
              onKeyDown={(event) => navigateTabs(event, index)}
              onClick={() => changeTab(id)}
              disabled={busy}
            >
              <Icon size={17} />
              <span>{label}</span>
              {id !== "preferences" && (
                <small>
                  {loaded
                    ? id === "episodes"
                      ? episodes.length
                      : facts.length
                    : "—"}
                </small>
              )}
            </button>
          ))}
        </div>
        <div
          className="memory-body"
          role="tabpanel"
          id={`memory-panel-${tab}`}
          aria-labelledby={`memory-tab-${tab}`}
          tabIndex={0}
          aria-busy={loading || searching}
        >
          {readOnly && (
            <p className="memory-readonly">
              <ShieldCheck size={15} />
              You have view-only access to this workspace.
            </p>
          )}
          {error && (
            <div
              className="memory-alert"
              role="alert"
              ref={errorBox}
              tabIndex={-1}
            >
              <AlertCircle size={18} />
              <span>{error}</span>
              {!loaded && (
                <button type="button" onClick={() => void load()}>
                  Retry
                </button>
              )}
            </div>
          )}
          {notice && (
            <p className="memory-notice" role="status">
              <Check size={16} />
              {notice}
              {tab === "preferences" && dirty
                ? " You have new unsaved changes."
                : ""}
            </p>
          )}
          {loading ? (
            <div className="memory-empty" role="status">
              <LoaderCircle className="spin" size={25} />
              <h3>Loading your memory</h3>
              <p>Gathering recent research and saved facts.</p>
            </div>
          ) : !loaded ? (
            <div className="memory-empty">
              <Brain size={28} />
              <h3>Memory couldn’t be loaded</h3>
              <p>
                Retry to reconnect. Your saved entries have not been changed.
              </p>
            </div>
          ) : tab === "preferences" ? (
            <form noValidate onSubmit={save} className="memory-preferences">
              <div className="memory-section-intro">
                <h3>Make research feel like you</h3>
                <p>
                  Keep your preferred research settings and guidance in one
                  place.
                </p>
              </div>
              <section className="memory-settings-card">
                <div className="memory-settings-heading">
                  <SlidersHorizontal size={18} />
                  <div>
                    <h4>Research style</h4>
                    <p>Choose your preferred depth and writing tone.</p>
                  </div>
                </div>
                <fieldset disabled={readOnly || busy}>
                  <legend>Research depth</legend>
                  <div className="memory-choice-grid">
                    {(
                      [
                        {
                          id: "quick",
                          title: "Quick",
                          text: "A focused starting point",
                        },
                        {
                          id: "standard",
                          title: "Balanced",
                          text: "Breadth with useful detail",
                        },
                        {
                          id: "deep",
                          title: "Deep",
                          text: "A more thorough exploration",
                        },
                      ] as const
                    ).map((item) => (
                      <label className="memory-choice" key={item.id}>
                        <input
                          type="radio"
                          name="memory-depth"
                          checked={depth === item.id}
                          onChange={() => setDepth(item.id)}
                        />
                        <span>
                          <b>{item.title}</b>
                          <small>{item.text}</small>
                        </span>
                      </label>
                    ))}
                  </div>
                </fieldset>
                <fieldset disabled={readOnly || busy}>
                  <legend>Writing tone</legend>
                  <div className="memory-tone-choices">
                    {(
                      ["academic", "brief", "technical", "general"] as const
                    ).map((value) => (
                      <label className="memory-choice" key={value}>
                        <input
                          type="radio"
                          name="memory-tone"
                          checked={tone === value}
                          onChange={() => setTone(value)}
                        />
                        <span>
                          {value === "general"
                            ? "Conversational"
                            : value.charAt(0).toUpperCase() + value.slice(1)}
                        </span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              </section>
              <section className="memory-settings-card">
                <div className="memory-settings-heading">
                  <ShieldCheck size={18} />
                  <div>
                    <h4>Source preferences</h4>
                    <p>
                      Store the domains you prefer and those you want to
                      exclude.
                    </p>
                  </div>
                </div>
                <div className="memory-field-grid">
                  <div className="memory-field">
                    <label htmlFor="memory-preferred">Preferred domains</label>
                    <input
                      id="memory-preferred"
                      value={preferred}
                      onChange={(event) => setPreferred(event.target.value)}
                      placeholder="nature.com, arxiv.org"
                      disabled={readOnly || busy}
                      aria-describedby="memory-domains-help"
                    />
                  </div>
                  <div className="memory-field">
                    <label htmlFor="memory-excluded">Excluded domains</label>
                    <input
                      id="memory-excluded"
                      value={excluded}
                      onChange={(event) => setExcluded(event.target.value)}
                      placeholder="example.com"
                      disabled={readOnly || busy}
                      aria-describedby="memory-domains-help"
                    />
                  </div>
                </div>
                <p id="memory-domains-help" className="memory-help">
                  Separate domains with commas. Leave blank for no domain
                  preference.
                </p>
              </section>
              <section className="memory-settings-card">
                <div className="memory-settings-heading">
                  <FileText size={18} />
                  <div>
                    <h4>Personal guidance</h4>
                    <p>Note what matters to you in a research answer.</p>
                  </div>
                </div>
                <div className="memory-field">
                  <label htmlFor="memory-instructions">
                    Research instructions
                  </label>
                  <textarea
                    id="memory-instructions"
                    className="resize-none"
                    rows={5}
                    value={instructions}
                    onChange={(event) => setInstructions(event.target.value)}
                    placeholder="For example: explain technical terms and highlight the limitations of each study."
                    disabled={readOnly || busy}
                  />
                </div>
              </section>
              <footer className="memory-save-bar">
                <span>
                  {readOnly
                    ? "View-only access"
                    : dirty
                      ? "Unsaved changes"
                      : "Your preferences are up to date"}
                </span>
                <div>
                  <button
                    type="button"
                    className="quiet-button"
                    disabled={!dirty || busy || readOnly}
                    onClick={() => {
                      if (preferences) hydrate(preferences);
                      setNotice("");
                    }}
                  >
                    Reset changes
                  </button>
                  <button
                    type="submit"
                    className="memory-primary"
                    disabled={!dirty || busy || readOnly}
                  >
                    {busy ? (
                      <LoaderCircle size={16} className="spin" />
                    ) : (
                      <Check size={16} />
                    )}
                    Save preferences
                  </button>
                </div>
              </footer>
            </form>
          ) : (
            <>
              <div className="memory-section-intro">
                <div>
                  <h3>
                    {tab === "episodes"
                      ? "Your research trail"
                      : "Knowledge worth keeping"}
                  </h3>
                  <p>
                    {tab === "episodes"
                      ? "Summaries and key findings from previous research."
                      : "Saved assertions and their provenance. A saved fact is not an independent guarantee of truth."}
                  </p>
                </div>
                <span className="memory-result-count">
                  {isSearch
                    ? `${tab === "episodes" ? visibleEpisodes.length : visibleFacts.length} matches`
                    : "Recent entries"}
                </span>
              </div>
              <div className="memory-toolbar">
                <form
                  noValidate
                  className="memory-search"
                  role="search"
                  onSubmit={search}
                >
                  <Search size={17} />
                  <label className="sr-only" htmlFor="memory-search">
                    Search{" "}
                    {tab === "episodes" ? "research history" : "saved facts"}
                  </label>
                  <input
                    id="memory-search"
                    ref={searchInput}
                    value={query}
                    onChange={(event) => {
                      setQuery(event.target.value);
                      if (!event.target.value) clearSearch();
                    }}
                    placeholder={
                      tab === "episodes"
                        ? "Find a topic or past discovery…"
                        : "Find a fact, topic, or entity…"
                    }
                  />
                  {query && (
                    <button
                      type="button"
                      className="icon-button"
                      aria-label="Clear memory search"
                      onClick={() => {
                        clearSearch();
                        searchInput.current?.focus();
                      }}
                    >
                      <X size={15} />
                    </button>
                  )}
                  <button
                    type="submit"
                    className="memory-search-submit"
                    disabled={searching}
                  >
                    {searching ? (
                      <LoaderCircle size={15} className="spin" />
                    ) : (
                      "Search"
                    )}
                  </button>
                </form>
                {tab === "facts" && (
                  <fieldset className="memory-status-filter">
                    <legend className="sr-only">Fact status</legend>
                    {[
                      { value: "active", label: "Active" },
                      { value: "superseded", label: "Replaced" },
                      { value: "contradiction", label: "Conflicts" },
                      { value: "all", label: "All" },
                    ].map((item) => (
                      <label key={item.value}>
                        <input
                          type="radio"
                          name="memory-status"
                          checked={status === item.value}
                          onChange={() => setStatus(item.value)}
                        />
                        <span>{item.label}</span>
                      </label>
                    ))}
                  </fieldset>
                )}
              </div>
              {(tab === "episodes"
                ? visibleEpisodes.length
                : visibleFacts.length) === 0 ? (
                <div className="memory-empty">
                  <Search size={28} />
                  <h3>
                    {isSearch
                      ? "No matching memories"
                      : tab === "episodes"
                        ? "Your next discovery starts here"
                        : "No saved facts in this view"}
                  </h3>
                  <p>
                    {isSearch
                      ? "Try another phrase or clear the search to see recent entries."
                      : tab === "episodes"
                        ? "Research summaries will appear here as your workspace builds its memory."
                        : "Choose another status, or complete research to build your saved knowledge."}
                  </p>
                  {isSearch && (
                    <button
                      type="button"
                      className="quiet-button"
                      onClick={clearSearch}
                    >
                      Clear search
                    </button>
                  )}
                </div>
              ) : tab === "episodes" ? (
                <div className="memory-entry-list">
                  {visibleEpisodes.map((episode) => (
                    <article className="memory-entry" key={episode.id}>
                      <div className="memory-entry-top">
                        <span className="memory-entry-icon">
                          <History size={17} />
                        </span>
                        <div>
                          <h4>{episode.title}</h4>
                          <p className="memory-meta">
                            {date(episode.created_at)}
                            <span>
                              {episode.importance >= 0.75
                                ? "High priority"
                                : episode.importance >= 0.4
                                  ? "Standard priority"
                                  : "Low priority"}
                            </span>
                          </p>
                        </div>
                        {!readOnly && (
                          <button
                            type="button"
                            className="icon-button memory-delete"
                            disabled={busy}
                            aria-label={`Delete research memory: ${episode.title}`}
                            onClick={() =>
                              ask({
                                kind: "episode",
                                id: episode.id,
                                title: episode.title,
                              })
                            }
                          >
                            <Trash2 size={16} />
                          </button>
                        )}
                      </div>
                      <div className="memory-summary">
                        <SafeMarkdown
                          markdown={episode.summary.replace(
                            /^#{1,6}\s+Evidence-checked answer\s*/i,
                            "",
                          )}
                        />
                      </div>
                      {episode.key_findings.length > 0 && (
                        <details className="memory-findings">
                          <summary>
                            {episode.key_findings.length} key{" "}
                            {episode.key_findings.length === 1
                              ? "finding"
                              : "findings"}
                          </summary>
                          <ul>
                            {episode.key_findings.map((finding, index) => (
                              <li key={index}>{finding}</li>
                            ))}
                          </ul>
                        </details>
                      )}
                      {episode.run_id && episode.conversation_id && (
                        <Link
                          className="memory-research-link"
                          to={`/research/${episode.conversation_id}/runs/${episode.run_id}`}
                          onClick={(event) => {
                            if (dirty) {
                              event.preventDefault();
                              ask({
                                kind: "discard",
                                href:
                                  event.currentTarget.getAttribute("href") ??
                                  undefined,
                              });
                            } else onClose();
                          }}
                        >
                          Open research
                          <ArrowUpRight size={14} />
                        </Link>
                      )}
                    </article>
                  ))}
                </div>
              ) : (
                <div className="memory-entry-list">
                  {visibleFacts.map((fact) => (
                    <article className="memory-entry" key={fact.id}>
                      <div className="memory-entry-top">
                        <span className="memory-entry-icon">
                          <ShieldCheck size={17} />
                        </span>
                        <div>
                          <h4>{fact.subject}</h4>
                          <p className="memory-meta">
                            {date(fact.created_at)}
                            <span>
                              {Math.round(fact.confidence * 100)}% recorded
                              confidence
                            </span>
                          </p>
                        </div>
                        <span className={`memory-status ${fact.status}`}>
                          {fact.status === "contradiction"
                            ? "Conflicting"
                            : fact.status === "superseded"
                              ? "Replaced"
                              : "Active"}
                        </span>
                        {!readOnly && (
                          <button
                            type="button"
                            className="icon-button memory-delete"
                            disabled={busy}
                            aria-label={`Delete fact: ${fact.subject}`}
                            onClick={() =>
                              ask({
                                kind: "fact",
                                id: fact.id,
                                title: fact.subject,
                              })
                            }
                          >
                            <Trash2 size={16} />
                          </button>
                        )}
                      </div>
                      <p className="memory-predicate">
                        {fact.predicate.replaceAll("_", " ")}
                      </p>
                      <div className="memory-summary">
                        <SafeMarkdown markdown={fact.fact} />
                      </div>
                      {fact.evidence_source && (
                        <div className="memory-provenance">
                          <span>SOURCE &amp; CONTEXT</span>
                          <p>{fact.evidence_source}</p>
                        </div>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
        {tab !== "preferences" && (
          <footer className="memory-footer">
            <span>
              <ShieldCheck size={14} />
              {readOnly
                ? "Workspace access · View only"
                : "Saved in this workspace"}
            </span>
            <div>
              {tab === "facts" && (
                <button
                  type="button"
                  className="quiet-button"
                  disabled={busy || readOnly || !loaded || !facts.length}
                  onClick={() => ask({ kind: "consolidate" })}
                >
                  <RefreshCw size={15} />
                  Organize facts
                </button>
              )}
              <button
                type="button"
                className="quiet-button"
                disabled={!loaded || busy}
                onClick={exportJson}
                title="Export loaded recent entries as JSON"
              >
                <Download size={15} />
                Export entries
              </button>
            </div>
          </footer>
        )}
      </div>
      {confirmation && (
        <section
          className="memory-confirm"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="memory-confirm-title"
          aria-describedby="memory-confirm-description"
        >
          <span className="memory-brand-icon">
            {confirmation.kind === "consolidate" ? (
              <RefreshCw size={24} />
            ) : (
              <AlertCircle size={24} />
            )}
          </span>
          <h3 id="memory-confirm-title">
            {confirmation.kind === "discard"
              ? "Discard unsaved changes?"
              : confirmation.kind === "consolidate"
                ? "Organize saved facts?"
                : "Delete this memory?"}
          </h3>
          <p id="memory-confirm-description">
            {confirmation.kind === "discard"
              ? "Your preference edits will be lost. Previously saved preferences will stay unchanged."
              : confirmation.kind === "consolidate"
                ? "Duplicate entries may be merged and older conflicting facts marked as superseded."
                : `“${confirmation.title}” will be permanently removed from memory. Your original research will remain available.`}
          </p>
          <div>
            <button
              type="button"
              className="quiet-button"
              ref={confirmCancel}
              disabled={busy}
              onClick={cancelConfirmation}
            >
              {confirmation.kind === "discard" ? "Keep editing" : "Cancel"}
            </button>
            <button
              type="button"
              className={
                confirmation.kind === "consolidate"
                  ? "memory-primary"
                  : "memory-danger"
              }
              disabled={busy}
              onClick={() => void applyConfirmation()}
            >
              {busy ? <LoaderCircle size={16} className="spin" /> : null}
              {confirmation.kind === "discard"
                ? "Discard changes"
                : confirmation.kind === "consolidate"
                  ? "Organize facts"
                  : "Delete memory"}
            </button>
          </div>
        </section>
      )}
    </dialog>
  );
}

"use client";

import {
  Activity,
  BookOpen,
  Database,
  HelpCircle,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Send,
  SquarePen,
  TerminalSquare,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { CorpusLab } from "@/components/corpus-lab";
import { MarkdownMessage } from "@/components/markdown-message";
import { Onboarding } from "@/components/onboarding";
import { Operations } from "@/components/operations";
import { ServiceHealthModal } from "@/components/service-health-modal";
import { SystemStatus } from "@/components/system-status";
import {
  ApiError,
  streamReview,
} from "@/lib/api";
import { operatorAvailable } from "@/lib/operator-api";
import { loadConversations, newConversation, ONBOARDING_KEY, saveConversations } from "@/lib/storage";
import type { ChatMessage, Conversation, EvidenceHit, RetrievalProfile, ReviewSessionProfile } from "@/lib/types";
import { DEFAULT_PROFILE, DEFAULT_SESSION_PROFILE, resolvedRetrievalProfile } from "@/lib/types";
import { useRuntimeHealth } from "@/lib/use-runtime-health";

type View = "review" | "lab" | "status" | "operations";

export function ServiceShell() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState("");
  const [view, setView] = useState<View>("review");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [tourOpen, setTourOpen] = useState(false);
  const [profile, setProfile] = useState<ReviewSessionProfile>(DEFAULT_SESSION_PROFILE);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [progress, setProgress] = useState("");
  const reviewAbort = useRef<AbortController | null>(null);
  const adminLive = process.env.NEXT_PUBLIC_ADMIN_MODE === "live";
  const operationsAvailable = operatorAvailable();
  const runtimeHealth = useRuntimeHealth();

  useEffect(() => {
    const restored = loadConversations();
    const initial = restored.length ? restored : [newConversation()];
    const shouldOpenTour = window.localStorage.getItem(ONBOARDING_KEY) !== "done";
    setConversations(initial);
    setActiveId(initial[0].id);
    setTourOpen(shouldOpenTour);
    if (window.innerWidth <= 560) setSidebarOpen(shouldOpenTour);
  }, []);

  useEffect(() => () => reviewAbort.current?.abort(), []);

  const active = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId) ?? conversations[0],
    [activeId, conversations],
  );

  function persist(next: Conversation[]) {
    setConversations(saveConversations(next));
  }

  function createReview() {
    const conversation = newConversation();
    persist([conversation, ...conversations]);
    setActiveId(conversation.id);
    setProfile(DEFAULT_SESSION_PROFILE);
    setView("review");
  }

  function removeReview(id: string) {
    const remaining = conversations.filter((conversation) => conversation.id !== id);
    const next = remaining.length ? remaining : [newConversation()];
    persist(next);
    if (activeId === id) setActiveId(next[0].id);
  }

  function clearReviews() {
    const conversation = newConversation();
    persist([conversation]);
    setActiveId(conversation.id);
  }

  function updateActive(messages: ChatMessage[], selectedProfile = active?.profile ?? null) {
    if (!active) return;
    const firstQuestion = messages.find((message) => message.role === "user")?.text ?? "New review";
    const next = conversations.map((conversation) =>
      conversation.id === active.id
        ? {
            ...conversation,
            title: firstQuestion.slice(0, 52),
            updatedAt: new Date().toISOString(),
            messages,
            profile: selectedProfile,
          }
        : conversation,
    );
    persist(next);
  }

  async function submit() {
    const question = query.trim();
    if (!question || busy || !active) return;
    setQuery("");
    setBusy(true);
    setProgress("Retrieving evidence");
    reviewAbort.current?.abort();
    const controller = new AbortController();
    reviewAbort.current = controller;
    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: "user", text: question };
    const pending = [...active.messages, userMessage];
    let preparedEvidence: EvidenceHit[] = [];
    updateActive(pending);
    try {
      const selectedProfile = active.profile ?? profile;
      let evidence: EvidenceHit[] = [];
      let candidateToken: string | undefined;
      const history = pending
        .slice(0, -1)
        .filter((message) => message.role === "user" || message.role === "assistant")
        .slice(-6)
        .map((message) => ({ role: message.role, text: message.text }));
      const response = await streamReview(
        question,
        selectedProfile,
        null,
        history,
        (event) => setProgress(`${event.node} · ${event.evidence_count} evidence · ${event.step_count} model steps`),
        controller.signal,
        (payload) => {
          evidence = payload.candidates.length ? payload.candidates : payload.results;
          preparedEvidence = evidence;
          candidateToken = payload.candidate_token ?? undefined;
          setProgress(`${payload.candidates.length} candidates retrieved`);
        },
      );
      const answer = terminalAnswer(response);
      const assistant: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        text: answer,
        evidence,
        evidenceLabel: terminalEvidenceLabel(response),
        trace: extractTrace(response),
        question,
        candidateToken,
        pinnedChunkIds: [],
        excludedChunkIds: [],
      };
      updateActive([...pending, assistant]);
    } catch (reason) {
      if (isInfrastructureFailure(reason)) {
        setQuery(question);
        await runtimeHealth.check();
        return;
      }
      const evidence = preparedEvidence;
      const message =
        reason instanceof ApiError && reason.code === "daily_cost_limit"
          ? "The daily answer budget is exhausted. Retrieved evidence is shown without an LLM answer."
          : reason instanceof Error
            ? reason.message
            : "The review could not be completed.";
      updateActive([
        ...pending,
        { id: crypto.randomUUID(), role: "assistant", text: message, evidence },
      ]);
    } finally {
      setBusy(false);
      setProgress("");
      if (reviewAbort.current === controller) reviewAbort.current = null;
    }
  }

  function applyProfile(nextProfile: RetrievalProfile, source?: string) {
    const [suite] = source?.split(":") ?? [];
    const corpusScope = suite?.startsWith("dart") ? "dart" : suite?.startsWith("sec") ? "sec" : (active?.profile ?? profile).corpus_scope;
    const languages = suite?.endsWith("-ko") ? ["ko" as const] : suite?.endsWith("-en") ? ["en" as const] : (active?.profile ?? profile).languages;
    const sessionProfile: ReviewSessionProfile = {
      ...(active?.profile ?? profile),
      corpus_scope: corpusScope,
      languages,
      retrieval_preset: "custom",
      custom_retrieval: nextProfile,
      applied_from_evaluation: source ?? null,
    };
    setProfile(sessionProfile);
    if (active) updateActive(active.messages, sessionProfile);
    setView("review");
  }

  function updateSessionProfile(update: Partial<ReviewSessionProfile>) {
    const next = { ...(active?.profile ?? profile), ...update };
    setProfile(next);
    if (active) updateActive(active.messages, next);
  }

  function updateLabProfile(nextProfile: RetrievalProfile) {
    updateSessionProfile({ retrieval_preset: "custom", custom_retrieval: nextProfile });
  }

  function markEvidence(messageId: string, chunkId: number, mode: "pin" | "exclude") {
    if (!active) return;
    const messages = active.messages.map((message) => {
      if (message.id !== messageId) return message;
      const pins = new Set(message.pinnedChunkIds ?? []);
      const excludes = new Set(message.excludedChunkIds ?? []);
      if (mode === "pin") {
        excludes.delete(chunkId);
        pins.has(chunkId) ? pins.delete(chunkId) : pins.add(chunkId);
      } else {
        pins.delete(chunkId);
        excludes.has(chunkId) ? excludes.delete(chunkId) : excludes.add(chunkId);
      }
      return { ...message, pinnedChunkIds: [...pins], excludedChunkIds: [...excludes] };
    });
    updateActive(messages);
  }

  async function useSelectedEvidence(message: ChatMessage) {
    if (!active || !message.question || !message.candidateToken || busy) return;
    setBusy(true);
    setProgress("Revalidating selected evidence");
    try {
      const response = await streamReview(
        message.question,
        active.profile ?? profile,
        {
          candidateToken: message.candidateToken,
          pinned: message.pinnedChunkIds ?? [],
          excluded: message.excludedChunkIds ?? [],
        },
        active.messages.slice(-6).map((item) => ({ role: item.role, text: item.text })),
        (event) => setProgress(`${event.node} · ${event.evidence_count} evidence`),
      );
      updateActive([...active.messages, {
        id: crypto.randomUUID(),
        role: "assistant",
        text: terminalAnswer(response),
        evidence: message.evidence?.filter((hit) => !(message.excludedChunkIds ?? []).includes(hit.chunk_id)),
        evidenceLabel: terminalEvidenceLabel(response),
        trace: extractTrace(response),
      }]);
    } catch (reason) {
      setProgress(reason instanceof Error ? reason.message : "Selected evidence review failed.");
    } finally {
      setBusy(false);
      window.setTimeout(() => setProgress(""), 2500);
    }
  }

  function closeTour() {
    window.localStorage.setItem(ONBOARDING_KEY, "done");
    setTourOpen(false);
  }

  function openTour() {
    setSidebarOpen(true);
    setTourOpen(true);
  }

  return (
    <main className={`service-shell ${sidebarOpen ? "" : "sidebar-collapsed"}`}>
      <aside className="sidebar">
        <div className="brand"><span>D</span><strong>DocReview</strong></div>
        <button className="new-review" data-tour="new-review" type="button" onClick={createReview}><SquarePen size={17} /><span>New review</span></button>
        <p className="sidebar-label">Recent reviews</p>
        <div className="conversation-list" data-tour="recent-reviews">
          {conversations.map((conversation) => (
            <div className="conversation-row" key={conversation.id}>
              <button type="button" aria-pressed={conversation.id === activeId && view === "review"} onClick={() => { setActiveId(conversation.id); setProfile(conversation.profile ?? DEFAULT_SESSION_PROFILE); setView("review"); }}>
                <MessageSquare size={15} /><span>{conversation.title}</span>
              </button>
              <button className="delete-review" type="button" aria-label={`Delete ${conversation.title}`} onClick={() => removeReview(conversation.id)}><Trash2 size={14} /></button>
            </div>
          ))}
        </div>
        <div className="sidebar-nav">
          <button data-tour="corpus-lab" type="button" aria-pressed={view === "lab"} onClick={() => setView("lab")}><Database size={17} /><span>Corpus Lab</span></button>
          {operationsAvailable && <button data-tour="operations" type="button" aria-pressed={view === "operations"} onClick={() => setView("operations")}><TerminalSquare size={17} /><span>Operations</span></button>}
          <a data-tour="documentation" href="/docreview-rag-agent/docs/" target="_blank" rel="noreferrer"><BookOpen size={17} /><span>Documentation</span></a>
          <button data-tour="system-status" type="button" aria-pressed={view === "status"} onClick={() => setView("status")}><Activity size={17} /><span>System status</span></button>
          <button type="button" onClick={openTour}><HelpCircle size={17} /><span>Show tutorial</span></button>
          <button type="button" onClick={clearReviews}><Trash2 size={17} /><span>Clear conversations</span></button>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <button className="icon-button" type="button" aria-label="Toggle sidebar" onClick={() => setSidebarOpen((value) => !value)}>{sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}</button>
          <div><strong>{view === "review" ? active?.title ?? "New review" : view === "lab" ? "Corpus Lab" : view === "operations" ? "Operations" : "System status"}</strong><span>Evidence-first SEC and DART filing review</span></div>
          <span className={`health ${healthBadge(runtimeHealth.kind)}`}><i />{healthLabel(runtimeHealth.kind)}</span>
        </header>

        {view === "review" && <section className="review-workspace">
          <div className="messages">
            <div className="messages-inner">
              {!active?.messages.length && <div className="welcome"><p className="eyebrow">Grounded by design</p><h1>Review filings with verifiable evidence.</h1><p>Ask across SEC 10-K and DART reports. Unsupported answers terminate as NOT_IN_DOCS.</p><div className="suggestions" data-tour="evidence-fallback"><button type="button" onClick={() => setQuery("What drove NVIDIA data center revenue growth?")}>NVIDIA growth drivers</button><button type="button" onClick={() => setQuery("삼성전자 메모리 사업의 주요 위험은 무엇인가요?")}>삼성전자 메모리 위험</button></div></div>}
              {active?.messages.map((message) => <article className={`message ${message.role}`} key={message.id}><div className="message-role">{message.role === "user" ? "You" : "DocReview"}</div><div className="message-body">{message.role === "assistant" ? <MarkdownMessage>{message.text}</MarkdownMessage> : <p>{message.text}</p>}{message.evidence?.length ? <details className="evidence"><summary data-tour="evidence-toggle">{message.evidenceLabel ?? "Retrieved candidates"} · {message.evidence.length}</summary>{message.evidence.map((hit) => <div className="evidence-hit" key={hit.chunk_id}><div className="evidence-actions"><button type="button" aria-pressed={(message.pinnedChunkIds ?? []).includes(hit.chunk_id)} onClick={() => markEvidence(message.id, hit.chunk_id, "pin")}>Pin</button><button type="button" aria-pressed={(message.excludedChunkIds ?? []).includes(hit.chunk_id)} onClick={() => markEvidence(message.id, hit.chunk_id, "exclude")}>Exclude</button></div><strong>{hit.citation}</strong><span>{hit.doc_id} · chars {hit.start_char}–{hit.end_char}</span><p>{hit.body}</p></div>)}{message.candidateToken && <button className="button primary use-evidence" type="button" onClick={() => void useSelectedEvidence(message)}>Use selected evidence</button>}</details> : null}{message.trace && <pre className="trace">{message.trace}</pre>}</div></article>)}
              {busy && <div className="thinking">{progress || "Retrieving and checking evidence…"}</div>}
            </div>
          </div>
          <div className="composer-wrap" data-tour="composer"><button className="profile-chip" type="button" onClick={() => setSettingsOpen(true)}>Session profile · {(active?.profile ?? profile).engine} · {(active?.profile ?? profile).corpus_scope} · {(active?.profile ?? profile).retrieval_preset}</button><label className="composer"><textarea value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); } }} placeholder="Ask a question about the filing corpus" rows={1} /><button data-tour="send" type="button" aria-label="Send question" disabled={busy || runtimeHealth.kind !== "healthy" || !query.trim()} onClick={() => void submit()}><Send size={17} /></button></label><p>Answers must cite retrieved filing evidence. Provider calls are rate- and cost-limited.</p></div>
        </section>}

        {view === "lab" && <CorpusLab live={adminLive} ready={runtimeHealth.kind === "healthy"} profile={resolvedRetrievalProfile(profile)} onProfileChange={updateLabProfile} onApplyProfile={applyProfile} />}
        {view === "operations" && operationsAvailable && <Operations />}
        {view === "status" && <SystemStatus readiness={runtimeHealth.readiness} loading={runtimeHealth.checking} error="" onRefresh={() => void runtimeHealth.check()} />}
      </section>
      {settingsOpen && <aside className="settings-drawer" aria-label="Review Settings"><div className="drawer-heading"><div><p className="eyebrow">Conversation</p><h2>Review Settings</h2></div><button className="icon-button" type="button" aria-label="Close Review Settings" onClick={() => setSettingsOpen(false)}>×</button></div><label>Answer engine<select value={profile.engine} onChange={(event) => updateSessionProfile({ engine: event.target.value as ReviewSessionProfile["engine"] })}><option value="openai">OpenAI API</option><option value="local" disabled={!runtimeHealth.readiness?.review_engines?.local?.enabled}>Local LLM</option></select></label><label>Corpus<select value={profile.corpus_scope} onChange={(event) => updateSessionProfile({ corpus_scope: event.target.value as ReviewSessionProfile["corpus_scope"] })}><option value="auto">Auto</option><option value="sec">SEC</option><option value="dart">DART</option></select></label><label>Companies<input value={profile.issuers.join(" ")} placeholder="005930 NVDA" onChange={(event) => updateSessionProfile({ issuers: event.target.value.split(/[\s,]+/).filter(Boolean) })} /></label><label>Retrieval<select value={profile.retrieval_preset} onChange={(event) => updateSessionProfile({ retrieval_preset: event.target.value as ReviewSessionProfile["retrieval_preset"], custom_retrieval: event.target.value === "custom" ? profile.custom_retrieval ?? DEFAULT_PROFILE : null })}><option value="balanced">Balanced</option><option value="korean">Korean</option><option value="accuracy">Accuracy</option><option value="custom">Custom</option></select></label>{!runtimeHealth.readiness?.review_engines?.local?.enabled && <p className="helper">Set LOCAL_LLM_BASE_URL and LOCAL_LLM_MODEL on the server to enable Local LLM.</p>}</aside>}
      {tourOpen && <Onboarding onClose={closeTour} includeOperations={operationsAvailable} />}
      <ServiceHealthModal
        kind={runtimeHealth.kind}
        visible={runtimeHealth.modalVisible}
        checking={runtimeHealth.checking}
        onRetry={() => void runtimeHealth.check()}
        onReload={() => window.location.reload()}
        onDismiss={runtimeHealth.dismissWarning}
        onOpenStatus={() => { runtimeHealth.dismissWarning(); setView("status"); }}
      />
    </main>
  );
}

function isInfrastructureFailure(reason: unknown): boolean {
  return reason instanceof TypeError || (
    reason instanceof ApiError
    && ["database_unavailable", "service_unavailable"].includes(reason.code)
  );
}

function healthBadge(kind: ReturnType<typeof useRuntimeHealth>["kind"]): string {
  if (kind === "healthy") return "ready";
  if (kind === "checking") return "unknown";
  return "degraded";
}

function healthLabel(kind: ReturnType<typeof useRuntimeHealth>["kind"]): string {
  return kind === "api_down" ? "API down" : kind.replace("_", " ");
}

export function terminalAnswer(payload: Record<string, unknown>): string {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const report = root.report as Record<string, unknown> | null;
  if (report?.report_kind === "conversation" && typeof report.answer === "string") return report.answer;
  if (report?.label === "SUPPORTED" && typeof report.answer === "string") return report.answer;
  if (report?.label === "NOT_IN_DOCS") {
    const rationale = typeof report.rationale === "string" ? report.rationale : "The filings do not contain direct support for this question.";
    return `${rationale}\n\nRelated filing evidence is available below, but it should not be treated as direct support.`;
  }
  const failure = root.failure as Record<string, unknown> | null;
  if (failure) {
    const detail = JSON.stringify(failure);
    if (/AuthenticationError|token_invalidated|invalidated/i.test(detail)) {
      return "OpenAI API authentication failed. Update the server-side API key and retry.";
    }
    return `The answer could not be generated (${String(failure.status ?? failure.code ?? "provider failure")}).`;
  }
  throw new Error("Review completed without a valid terminal report or failure.");
}

function terminalEvidenceLabel(payload: Record<string, unknown>): ChatMessage["evidenceLabel"] {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const report = root.report as Record<string, unknown> | null;
  if (report?.label === "SUPPORTED") return "Cited evidence";
  if (report?.label === "NOT_IN_DOCS") return "Related evidence — not direct support";
  return "Retrieved candidates — answer not generated";
}

function extractTrace(payload: Record<string, unknown>): string {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const values = ["status", "total_requests", "total_input_tokens", "total_output_tokens", "total_time_seconds"];
  return values.filter((key) => root[key] !== undefined).map((key) => `${key}=${String(root[key])}`).join(" · ");
}

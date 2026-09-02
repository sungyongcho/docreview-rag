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
  Settings,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { CorpusLab } from "@/components/corpus-lab";
import { MarkdownMessage } from "@/components/markdown-message";
import { Onboarding } from "@/components/onboarding";
import { Operations } from "@/components/operations";
import { ServiceHealthModal } from "@/components/service-health-modal";
import { SystemStatus } from "@/components/system-status";
import { SettingsModal } from "@/components/settings-modal";
import { useNotifications } from "@/components/notifications";
import {
  ApiError,
  getCapabilities,
  retrieveEvidence,
  streamReview,
} from "@/lib/api";
import { operatorAvailable } from "@/lib/operator-api";
import { loadConversations, newConversation, ONBOARDING_KEY, saveConversations } from "@/lib/storage";
import type { Capabilities, ChatMessage, Conversation, EvidenceHit, PublishedSnapshot, RetrievalProfile, ReviewSessionProfile } from "@/lib/types";
import { DEFAULT_PROFILE, DEFAULT_SESSION_PROFILE, resolvedRetrievalProfile } from "@/lib/types";
import { useRuntimeHealth } from "@/lib/use-runtime-health";
import { useOperatorJobs } from "@/lib/use-operator-jobs";

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
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [progress, setProgress] = useState("");
  const reviewAbort = useRef<AbortController | null>(null);
  const adminLive = process.env.NEXT_PUBLIC_ADMIN_MODE === "live";
  const operationsAvailable = operatorAvailable();
  const runtimeHealth = useRuntimeHealth();
  const { notify } = useNotifications();
  const operatorJobs = useOperatorJobs(adminLive, runtimeHealth.check);

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
  useEffect(() => {
    void getCapabilities().then((value) => setCapabilities(adminLive ? value : {
      ...value,
      can_edit_prompt_policy: false,
      can_edit_run_limits: false,
      can_edit_golden: false,
      can_build_snapshot: false,
      can_run_evaluation: false,
      can_change_custom_retrieval: false,
      can_query_snapshot: false,
      can_use_operations: false,
      can_compare_published_snapshots: true,
    })).catch(() => setCapabilities(null));
  }, [adminLive]);

  const active = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId) ?? conversations[0],
    [activeId, conversations],
  );
  const activeSessionProfile = active?.profile ?? profile;
  const vectorOnlyUnavailable = resolvedRetrievalProfile(activeSessionProfile).strategy === "vector"
    && (runtimeHealth.readiness?.corpus?.pending_embeddings ?? 0) > 0;

  function persist(next: Conversation[]) {
    setConversations(saveConversations(next));
  }

  function createReview() {
    const conversation = newConversation();
    persist([conversation, ...conversations]);
    setActiveId(conversation.id);
    setProfile(conversation.profile ?? DEFAULT_SESSION_PROFILE);
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
    const selectedProfile = active.profile ?? profile;
    updateActive(pending);
    try {
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
      let evidence = preparedEvidence;
      if (reason instanceof ApiError && reason.code === "provider_unavailable") {
        try {
          const retrieved = await retrieveEvidence(question, selectedProfile);
          evidence = retrieved.candidates.length ? retrieved.candidates : retrieved.results;
        } catch {
          // Preserve the original provider error when retrieval is also unavailable.
        }
      }
      const message =
        reason instanceof ApiError && reason.code === "daily_cost_limit"
          ? "The daily answer budget is exhausted. Retrieved evidence is shown without an LLM answer."
          : reason instanceof ApiError && reason.code === "provider_unavailable" && evidence.length
            ? "No answer model is configured. Retrieved filing evidence is shown below without a generated answer."
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

  function applySnapshot(snapshot: PublishedSnapshot) {
    const storedProfile = snapshot.profile.retrieval_profile;
    const retrieval = storedProfile && typeof storedProfile === "object"
      ? storedProfile as RetrievalProfile
      : resolvedRetrievalProfile(active?.profile ?? profile);
    const next = {
      ...(active?.profile ?? profile),
      snapshot_id: snapshot.snapshot_id,
      applied_from_evaluation: `snapshot:${snapshot.snapshot_id}`,
      retrieval_preset: "custom" as const,
      custom_retrieval: retrieval,
    };
    setProfile(next);
    if (active) updateActive(active.messages, next);
    setView("review");
    notify(`Snapshot ${snapshot.label} applied to this review.`, "success", "snapshot-review");
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
        active.messages.slice(-(active.profile ?? profile).prompt_policy.history_turns).map((item) => ({ role: item.role, text: item.text })),
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
      notify(reason instanceof Error ? reason.message : "Selected evidence review failed.", "error", "evidence-review");
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
          <button type="button" onClick={() => setSettingsOpen(true)}><Settings size={17} /><span>Settings</span></button>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <button className="icon-button" type="button" aria-label="Toggle sidebar" onClick={() => setSidebarOpen((value) => !value)}>{sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}</button>
          <div><strong>{view === "review" ? active?.title ?? "New review" : view === "lab" ? "Corpus Lab" : view === "operations" ? "Operations" : "System status"}</strong><span>Evidence-first SEC and DART filing review</span></div>
          <div className="topbar-status">{adminLive && (operatorJobs.board.active_count > 0 || operatorJobs.board.queued_count > 0) && <button className="job-health" type="button" onClick={() => setView("lab")}>{operatorJobs.board.active_count} running · {operatorJobs.board.queued_count} queued</button>}<button type="button" className={`health ${healthBadge(runtimeHealth.kind)}`} onClick={() => setView("status")}><i />{healthLabel(runtimeHealth.kind)}</button></div>
        </header>

        {view === "review" && <section className="review-workspace">
          <div className="messages">
            <div className="messages-inner">
              {!active?.messages.length && <div className="welcome"><p className="eyebrow">Grounded by design</p><h1>Review filings with verifiable evidence.</h1><p>Ask across SEC 10-K and DART reports. Unsupported answers terminate as NOT_IN_DOCS.</p><div className="suggestions" data-tour="evidence-fallback"><button type="button" onClick={() => setQuery("What drove NVIDIA data center revenue growth?")}>NVIDIA growth drivers</button><button type="button" onClick={() => setQuery("삼성전자 메모리 사업의 주요 위험은 무엇인가요?")}>삼성전자 메모리 위험</button></div></div>}
              {active?.messages.map((message) => <article className={`message ${message.role}`} key={message.id}><div className="message-role">{message.role === "user" ? "You" : "DocReview"}</div><div className="message-body">{message.role === "assistant" ? <MarkdownMessage>{message.text}</MarkdownMessage> : <p>{message.text}</p>}{message.evidence?.length ? <details className="evidence"><summary data-tour="evidence-toggle">{message.evidenceLabel ?? "Retrieved candidates"} · {message.evidence.length}</summary>{message.evidence.map((hit) => <div className="evidence-hit" key={hit.chunk_id}><div className="evidence-actions"><button type="button" aria-pressed={(message.pinnedChunkIds ?? []).includes(hit.chunk_id)} onClick={() => markEvidence(message.id, hit.chunk_id, "pin")}>Pin</button><button type="button" aria-pressed={(message.excludedChunkIds ?? []).includes(hit.chunk_id)} onClick={() => markEvidence(message.id, hit.chunk_id, "exclude")}>Exclude</button></div><strong>{hit.citation}</strong><span>{hit.doc_id} · chars {hit.start_char}–{hit.end_char}</span><p>{hit.body}</p></div>)}{message.candidateToken && <button className="button primary use-evidence" type="button" onClick={() => void useSelectedEvidence(message)}>Use selected evidence</button>}</details> : null}{message.trace && <pre className="trace">{message.trace}</pre>}</div></article>)}
              {busy && <div className="thinking">{progress || "Retrieving and checking evidence…"}</div>}
            </div>
          </div>
          <div className="composer-wrap" data-tour="composer"><button className="profile-chip" type="button" onClick={() => setSettingsOpen(true)}>Session profile · {activeSessionProfile.engine} · {activeSessionProfile.corpus_scope} · {activeSessionProfile.retrieval_preset}</button><label className="composer"><textarea value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); } }} placeholder="Ask a question about the filing corpus" rows={1} /><button data-tour="send" type="button" aria-label="Send question" disabled={busy || runtimeHealth.kind === "api_down" || runtimeHealth.kind === "checking" || vectorOnlyUnavailable || !query.trim()} onClick={() => void submit()}><Send size={17} /></button></label>{vectorOnlyUnavailable ? <p className="danger">Vector-only retrieval is unavailable until embeddings are ready. <button className="inline-link" type="button" onClick={() => setView("lab")}>Open Corpus Lab</button></p> : <p>Answers must cite retrieved filing evidence. Provider calls are rate- and cost-limited.</p>}</div>
        </section>}

        {view === "lab" && <CorpusLab live={adminLive} ready={runtimeHealth.kind === "healthy"} profile={resolvedRetrievalProfile(profile)} onProfileChange={updateLabProfile} onApplyProfile={applyProfile} onApplySnapshot={applySnapshot} jobBoard={operatorJobs.board} jobsLoading={operatorJobs.loading} onRetryJob={(jobId) => void operatorJobs.retry(jobId)} onCancelJob={(jobId) => void operatorJobs.cancel(jobId)} onRefreshJobs={() => void operatorJobs.refresh()} readiness={runtimeHealth.readiness} healthKind={runtimeHealth.kind} onNavigate={(target) => setView(target)} onRecheck={() => void runtimeHealth.check()} />}
        {view === "operations" && operationsAvailable && <Operations />}
        {view === "status" && <SystemStatus readiness={runtimeHealth.readiness} loading={runtimeHealth.checking} error="" onRefresh={() => void runtimeHealth.check()} />}
      </section>
      <SettingsModal open={settingsOpen} profile={active?.profile ?? profile} capabilities={capabilities ?? { can_edit_prompt_policy: adminLive, can_edit_run_limits: adminLive, can_edit_golden: adminLive, can_build_snapshot: adminLive, can_run_evaluation: adminLive, can_change_custom_retrieval: adminLive, can_query_snapshot: adminLive, can_use_operations: operationsAvailable, can_compare_published_snapshots: true }} readiness={runtimeHealth.readiness} onChange={(next) => { setProfile(next); if (active) updateActive(active.messages, next); }} onClose={() => setSettingsOpen(false)} onOpenLab={() => { setSettingsOpen(false); setView("lab"); }} onOpenOperations={() => { setSettingsOpen(false); setView("operations"); }} onOpenStatus={() => { setSettingsOpen(false); setView("status"); }} onOpenTour={() => { setSettingsOpen(false); openTour(); }} onClear={() => { clearReviews(); notify("Local conversations cleared.", "success"); }} />
      {tourOpen && <Onboarding onClose={closeTour} includeOperations={operationsAvailable} />}
      <ServiceHealthModal
        kind={runtimeHealth.kind}
        visible={runtimeHealth.modalVisible}
        checking={runtimeHealth.checking}
        onRetry={() => void runtimeHealth.check()}
        onReload={() => window.location.reload()}
        onDismiss={runtimeHealth.dismissWarning}
        onOpenStatus={() => { runtimeHealth.dismissWarning(); setView("status"); }}
        onOpenCorpusLab={() => { runtimeHealth.dismissWarning(); setView("lab"); }}
        degradedMessage={runtimeHealth.readiness?.corpus?.pending_embeddings
          ? `${runtimeHealth.readiness.corpus.pending_embeddings.toLocaleString()} chunks still need embeddings. Open Corpus Lab and run Backfill embeddings.`
          : runtimeHealth.readiness?.corpus?.schema_message || undefined}
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

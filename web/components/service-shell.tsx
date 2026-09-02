"use client";

import {
  Activity,
  CircleHelp,
  FlaskConical,
  Hammer,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Send,
  SquarePen,
  Trash2,
  Settings,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { BuildWorkspace, type BuildTab } from "@/components/build-workspace";
import { ComposerBanner, ComposerToolbar, composerBanner } from "@/components/composer-toolbar";
import { HelpOverlay } from "@/components/help-overlay";
import { MarkdownMessage } from "@/components/markdown-message";
import { MeasureWorkspace, type MeasureTab } from "@/components/measure-workspace";
import { Onboarding, type TourView } from "@/components/onboarding";
import { ReviewProgressSteps, reviewProgressFromEvent, type ReviewProgressState } from "@/components/review-progress";
import { ServiceHealthModal } from "@/components/service-health-modal";
import { PROD_LOCKED_MESSAGE, SettingsModal, type SettingsCategory } from "@/components/settings-modal";
import { SystemWorkspace, type SystemTab } from "@/components/system-workspace";
import { useNotifications } from "@/components/notifications";
import {
  ApiError,
  getCapabilities,
  getReleaseLimits,
  retrieveEvidence,
  streamReview,
} from "@/lib/api";
import { helpScreen } from "@/lib/help-content";
import { getOperatorCommands, operatorAvailable, startOperatorJob } from "@/lib/operator-api";
import { loadConversations, loadHelpOpen, newConversation, ONBOARDING_KEY, saveConversations, saveHelpOpen } from "@/lib/storage";
import type { Capabilities, ChatMessage, Conversation, EvidenceHit, PublishedSnapshot, RetrievalProfile, ReviewSessionProfile } from "@/lib/types";
import { DEFAULT_SESSION_PROFILE, resolvedRetrievalProfile } from "@/lib/types";
import { useRuntimeHealth } from "@/lib/use-runtime-health";
import { useOperatorJobs } from "@/lib/use-operator-jobs";

type View = "review" | "build" | "measure" | "system";

/** One deep-link target for every navigation call site: sidebar, topbar, modals, and workspaces. */
export type NavigationTarget =
  | { view: "review" }
  | { view: "build"; tab?: BuildTab; stage?: number }
  | { view: "measure"; tab?: MeasureTab; resultId?: number }
  | { view: "system"; tab?: SystemTab };

export function ServiceShell() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState("");
  const [view, setView] = useState<View>("review");
  const [buildTab, setBuildTab] = useState<BuildTab>("pipeline");
  const [measureTab, setMeasureTab] = useState<MeasureTab>("playground");
  const [systemTab, setSystemTab] = useState<SystemTab>("status");
  const [measureResultId, setMeasureResultId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [tourOpen, setTourOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [profile, setProfile] = useState<ReviewSessionProfile>(DEFAULT_SESSION_PROFILE);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsCategory, setSettingsCategory] = useState<SettingsCategory | undefined>(undefined);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [progress, setProgress] = useState<ReviewProgressState | null>(null);
  /** `ReleaseLimits.daily_cost_reset_at_utc` captured after a `daily_cost_limit` error; cleared by the next successful review. */
  const [resetAt, setResetAt] = useState<string | null>(null);
  /** Build stage card to scroll into view once the Build workspace has rendered. */
  const [pendingStage, setPendingStage] = useState<number | null>(null);
  const reviewAbort = useRef<AbortController | null>(null);
  /** First-run routing fires once per page load and is cancelled by any explicit navigation before it. */
  const firstRunRouted = useRef(false);
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
    // The tour owns the screen on a first visit; a persisted open Help state waits until it is dismissed.
    setHelpOpen(!shouldOpenTour && loadHelpOpen());
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
  const latestEvidenceId = active?.messages.filter((message) => message.evidence?.length).at(-1)?.id ?? null;
  const banner = composerBanner({ readiness: runtimeHealth.readiness, live: adminLive, profile: activeSessionProfile, resetAt });
  const sendBlocked = banner?.kind === "empty" || banner?.kind === "vector";

  useEffect(() => {
    if (pendingStage === null || view !== "build" || buildTab !== "pipeline") return;
    document.getElementById(`stage-${pendingStage}`)?.scrollIntoView({ block: "start" });
    setPendingStage(null);
  }, [pendingStage, view, buildTab]);

  function persist(next: Conversation[]) {
    setConversations(saveConversations(next));
  }

  function navigate(target: NavigationTarget) {
    firstRunRouted.current = true;
    if (target.view === "build" && target.tab) setBuildTab(target.tab);
    if (target.view === "build" && target.stage !== undefined) setPendingStage(target.stage);
    if (target.view === "measure") {
      if (target.tab) setMeasureTab(target.tab);
      setMeasureResultId(target.resultId ?? null);
    }
    if (target.view === "system" && target.tab) setSystemTab(target.tab);
    setView(target.view);
  }

  function openSettings(category?: SettingsCategory) {
    setSettingsCategory(category);
    setSettingsOpen(true);
  }

  function createReview() {
    const conversation = newConversation();
    persist([conversation, ...conversations]);
    setActiveId(conversation.id);
    setProfile(conversation.profile ?? DEFAULT_SESSION_PROFILE);
    navigate({ view: "review" });
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

  function conversationTitle(messages: ChatMessage[]): string {
    return (messages.find((message) => message.role === "user")?.text ?? "New review").slice(0, 52);
  }

  /**
   * Replace the active conversation's messages. Reads the current list at update time
   * so a change made while a review streams (a toolbar edit, a pin) is not reverted.
   */
  function updateActive(messages: ChatMessage[], selectedProfile?: ReviewSessionProfile | null) {
    const targetId = activeId;
    setConversations((current) => saveConversations(current.map((conversation) =>
      conversation.id === targetId
        ? {
            ...conversation,
            title: conversationTitle(messages),
            updatedAt: new Date().toISOString(),
            messages,
            profile: selectedProfile === undefined ? conversation.profile : selectedProfile,
          }
        : conversation,
    )));
  }

  /** Append one message to the conversation a review started in, even if the user moved on. */
  function appendMessage(conversationId: string, message: ChatMessage) {
    setConversations((current) => saveConversations(current.map((conversation) => {
      if (conversation.id !== conversationId) return conversation;
      const messages = [...conversation.messages, message];
      return { ...conversation, title: conversationTitle(messages), updatedAt: new Date().toISOString(), messages };
    })));
  }

  /** One-off read of the reset time after a `daily_cost_limit` error so the banner can say when answers resume. */
  function noteDailyBudget(reason: unknown) {
    if (reason instanceof ApiError && reason.code === "daily_cost_limit") {
      void getReleaseLimits().then((limits) => setResetAt(limits.daily_cost_reset_at_utc)).catch(() => undefined);
    }
  }

  async function submit() {
    const question = query.trim();
    if (!question || busy || !active || sendBlocked) return;
    setQuery("");
    setBusy(true);
    setProgress(null);
    reviewAbort.current?.abort();
    const controller = new AbortController();
    reviewAbort.current = controller;
    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: "user", text: question };
    const conversationId = active.id;
    const pending = [...active.messages, userMessage];
    let preparedEvidence: EvidenceHit[] = [];
    const selectedProfile = active.profile ?? profile;
    appendMessage(conversationId, userMessage);
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
        (event) => setProgress(reviewProgressFromEvent(event)),
        controller.signal,
        (payload) => {
          evidence = payload.candidates.length ? payload.candidates : payload.results;
          preparedEvidence = evidence;
          candidateToken = payload.candidate_token ?? undefined;
          setProgress({ node: "candidates", evidence: payload.candidates.length, relevant: 0, steps: 0 });
        },
      );
      const answer = terminalAnswer(response);
      setResetAt(null);
      const assistant: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        text: answer,
        evidence,
        evidenceLabel: terminalEvidenceLabel(response),
        citations: terminalCitationCount(response),
        trace: extractTrace(response),
        question,
        candidateToken,
        pinnedChunkIds: [],
        excludedChunkIds: [],
      };
      appendMessage(conversationId, assistant);
    } catch (reason) {
      if (isInfrastructureFailure(reason)) {
        setQuery(question);
        await runtimeHealth.check();
        return;
      }
      let evidence = preparedEvidence;
      // The provider gate and the daily cost limiter both reject before retrieval runs,
      // so fetch the evidence separately for the evidence-only reply.
      if (reason instanceof ApiError && ["provider_unavailable", "daily_cost_limit"].includes(reason.code) && !evidence.length) {
        try {
          const retrieved = await retrieveEvidence(question, selectedProfile);
          evidence = retrieved.candidates.length ? retrieved.candidates : retrieved.results;
        } catch {
          // Preserve the original provider error when retrieval is also unavailable.
        }
      }
      noteDailyBudget(reason);
      const message =
        reason instanceof ApiError && reason.code === "daily_cost_limit"
          ? "The daily answer budget is exhausted. Retrieved evidence is shown without an LLM answer."
          : reason instanceof ApiError && reason.code === "provider_unavailable" && evidence.length
            ? "No answer model is configured. Retrieved filing evidence is shown below without a generated answer. See Build › step 6."
          : reason instanceof Error
            ? reason.message
            : "The review could not be completed.";
      appendMessage(conversationId, {
        id: crypto.randomUUID(),
        role: "assistant",
        text: message,
        evidence,
        evidenceLabel: "Retrieved candidates — answer not generated",
      });
    } finally {
      setBusy(false);
      setProgress(null);
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
    navigate({ view: "review" });
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
    navigate({ view: "review" });
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
    const conversationId = active.id;
    const selected = (message.evidence ?? []).filter((hit) => !(message.excludedChunkIds ?? []).includes(hit.chunk_id)).length;
    setProgress({ node: "retrieve", evidence: selected, relevant: 0, steps: 0, revalidating: true });
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
        (event) => setProgress({ ...reviewProgressFromEvent(event), revalidating: true }),
      );
      setResetAt(null);
      appendMessage(conversationId, {
        id: crypto.randomUUID(),
        role: "assistant",
        text: terminalAnswer(response),
        evidence: message.evidence?.filter((hit) => !(message.excludedChunkIds ?? []).includes(hit.chunk_id)),
        evidenceLabel: terminalEvidenceLabel(response),
        citations: terminalCitationCount(response),
        trace: extractTrace(response),
      });
    } catch (reason) {
      noteDailyBudget(reason);
      notify(reason instanceof Error ? reason.message : "Selected evidence review failed.", "error", "evidence-review");
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  function closeTour() {
    window.localStorage.setItem(ONBOARDING_KEY, "done");
    setTourOpen(false);
  }

  function openTour() {
    setSidebarOpen(true);
    setHelp(false);
    setTourOpen(true);
  }

  function setHelp(open: boolean) {
    saveHelpOpen(open);
    setHelpOpen(open);
  }

  /** `?` toggles Help anywhere except inside a text control, and never behind the tour or a modal. */
  const modalOpen = settingsOpen || runtimeHealth.modalVisible;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "?" || tourOpen || modalOpen) return;
      const target = event.target;
      if (target instanceof HTMLElement && (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable || target.hasAttribute("contenteditable"))) return;
      event.preventDefault();
      setHelp(!helpOpen);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [helpOpen, tourOpen, modalOpen]);
  const currentTab = view === "build" ? buildTab : view === "measure" ? measureTab : view === "system" ? systemTab : "";
  const location = `${view}/${buildTab}/${measureTab}/${systemTab}`;
  /** The workspace reserves room for the panel only while it is actually on screen. */
  const helpVisible = helpOpen && !tourOpen;

  const readiness = runtimeHealth.readiness;
  /** First-run routing: an empty live corpus with nothing asked yet opens on Build, unless the user already went somewhere. */
  useEffect(() => {
    if (firstRunRouted.current || !adminLive || readiness === null || !conversations.length) return;
    firstRunRouted.current = true;
    if (readiness.corpus.documents === 0 && conversations.every((conversation) => !conversation.messages.length)) setView("build");
  }, [adminLive, readiness, conversations]);

  /** Tour steps name a workspace; the shell switches there before the step's target is spotlighted. */
  function openTourStep(step: { view: TourView; tab?: string }) {
    if (step.view === "build") navigate({ view: "build", tab: "pipeline" });
    else if (step.view === "measure") navigate({ view: "measure" });
    else if (step.view === "system") navigate({ view: "system", tab: operationsAvailable ? "operations" : "status" });
    else navigate({ view: "review" });
  }
  /**
   * Build needs the operator: a degraded runtime, a switched-off answer model, or a
   * failed job. Corpus-level "action" states live behind `/admin/corpus`, which only
   * Build fetches, so readiness stands in for them here.
   */
  const buildNeedsAttention = adminLive && (
    (readiness !== null && (readiness.status === "degraded" || readiness.review_enabled === false))
    || operatorJobs.board.jobs.some((job) => job.status === "failed" || job.status === "interrupted")
  );

  async function runOperation(commandId: string) {
    try {
      const command = (await getOperatorCommands()).find((item) => item.command_id === commandId);
      if (!command) throw new Error(`Operations does not offer ${commandId}.`);
      if (command.confirmation && !window.confirm(command.confirmation)) return;
      await startOperatorJob(command.command_id);
      notify(`${command.label} started. Follow it under System › Operations.`, "success", "operations-run");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Command could not start.", "error", "operations-run");
    }
  }
  const topbarTitle = view === "review"
    ? active?.title ?? "New review"
    : view === "build" ? "Build" : view === "measure" ? "Measure" : "System";

  return (
    <main className={`service-shell ${sidebarOpen ? "" : "sidebar-collapsed"}${helpVisible ? " help-open" : ""}`}>
      <aside className="sidebar">
        <div className="brand"><span>D</span><strong>DocReview</strong></div>
        <button className="new-review" data-tour="new-review" type="button" onClick={createReview}><SquarePen size={17} /><span>New review</span></button>
        <p className="sidebar-label">Recent reviews</p>
        <div className="conversation-list" data-tour="recent-reviews">
          {conversations.map((conversation) => (
            <div className="conversation-row" key={conversation.id}>
              <button type="button" aria-pressed={conversation.id === activeId && view === "review"} onClick={() => { setActiveId(conversation.id); setProfile(conversation.profile ?? DEFAULT_SESSION_PROFILE); navigate({ view: "review" }); }}>
                <MessageSquare size={15} /><span>{conversation.title}</span>
              </button>
              <button className="delete-review" type="button" aria-label={`Delete ${conversation.title}`} onClick={() => removeReview(conversation.id)}><Trash2 size={14} /></button>
            </div>
          ))}
        </div>
        <div className="sidebar-nav">
          <button data-tour="build" type="button" aria-pressed={view === "build"} onClick={() => navigate({ view: "build" })}><Hammer size={17} /><span>Build</span>{buildNeedsAttention && <><i className="nav-dot" aria-hidden="true" /><span className="sr-only">, needs attention</span></>}</button>
          <button data-tour="measure" type="button" aria-pressed={view === "measure"} onClick={() => navigate({ view: "measure" })}><FlaskConical size={17} /><span>Measure</span></button>
          <button data-tour="system" className="nav-secondary" type="button" aria-pressed={view === "system"} onClick={() => navigate({ view: "system" })}><Activity size={17} /><span>System</span></button>
          <button data-tour="settings" type="button" onClick={() => openSettings()}><Settings size={17} /><span>Settings</span></button>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <button className="icon-button" type="button" aria-label="Toggle sidebar" onClick={() => setSidebarOpen((value) => !value)}>{sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}</button>
          <div><strong>{topbarTitle}</strong><span>Evidence-first SEC and DART filing review</span></div>
          <div className="topbar-status">{adminLive && (operatorJobs.board.active_count > 0 || operatorJobs.board.queued_count > 0) && <button className="job-health" type="button" onClick={() => navigate({ view: "build", tab: "jobs" })}>{operatorJobs.board.active_count} running · {operatorJobs.board.queued_count} queued</button>}<button type="button" className="icon-button help-toggle" aria-label="Toggle help" aria-pressed={helpOpen} onClick={() => setHelp(!helpOpen)}><CircleHelp size={18} /></button><button type="button" className={`health ${healthBadge(runtimeHealth.kind)}`} onClick={() => navigate({ view: "system", tab: "status" })}><i />{healthLabel(runtimeHealth.kind)}</button></div>
        </header>

        {view === "review" && <section className="review-workspace">
          <div className="messages">
            <div className="messages-inner">
              {!active?.messages.length && (
                <div className="welcome">
                  <p className="eyebrow">Grounded by design</p>
                  <h1>Review filings with verifiable evidence.</h1>
                  <p>Ask across SEC 10-K and DART reports. Unsupported answers terminate as NOT_IN_DOCS.</p>
                  {adminLive && readiness?.corpus?.documents === 0 ? (
                    <div className="next-step" data-tour="evidence-fallback">
                      <h2>Corpus is empty</h2>
                      <p>Download and ingest filings first.</p>
                      <div className="action-row"><button className="button primary" type="button" onClick={() => navigate({ view: "build", tab: "pipeline" })}>Open Build</button></div>
                    </div>
                  ) : (
                    <div className="suggestions" data-tour="evidence-fallback">
                      <button type="button" onClick={() => setQuery("What drove NVIDIA data center revenue growth?")}>NVIDIA growth drivers</button>
                      <button type="button" onClick={() => setQuery("삼성전자 메모리 사업의 주요 위험은 무엇인가요?")}>삼성전자 메모리 위험</button>
                    </div>
                  )}
                </div>
              )}
              {active?.messages.map((message) => (
                <ReviewMessage
                  key={message.id}
                  message={message}
                  latestEvidence={message.id === latestEvidenceId}
                  busy={busy}
                  onMark={(chunkId, mode) => markEvidence(message.id, chunkId, mode)}
                  onUseSelected={() => void useSelectedEvidence(message)}
                />
              ))}
              {busy && <div className="thinking">{progress ? <ReviewProgressSteps state={progress} /> : "Retrieving and checking evidence…"}</div>}
            </div>
          </div>
          <div className="composer-wrap" data-tour="composer">
            <ComposerToolbar
              profile={activeSessionProfile}
              onChange={updateSessionProfile}
              canUseCustom={capabilities?.can_change_custom_retrieval ?? adminLive}
              onLocked={() => notify(PROD_LOCKED_MESSAGE, "warning", "prod-locked")}
              onOpenFilters={() => openSettings("review")}
              readiness={readiness}
              live={adminLive}
              onOpenBuild={() => navigate({ view: "build", tab: "pipeline" })}
            />
            <label className="composer">
              <textarea data-help="review.composer" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); } }} placeholder="Ask a question about the filing corpus" rows={1} />
              <button data-tour="send" data-help="review.send" type="button" aria-label="Send question" disabled={busy || runtimeHealth.kind === "api_down" || runtimeHealth.kind === "checking" || sendBlocked || !query.trim()} onClick={() => void submit()}><Send size={17} /></button>
            </label>
            {banner
              ? <ComposerBanner banner={banner} onOpenBuild={() => navigate({ view: "build", tab: "pipeline" })} onOpenAnswerModel={() => navigate({ view: "build", tab: "pipeline", stage: 6 })} />
              : <p>Answers must cite retrieved filing evidence. Provider calls are rate- and cost-limited.</p>}
          </div>
        </section>}

        {view === "build" && <BuildWorkspace
          live={adminLive}
          ready={runtimeHealth.kind === "healthy"}
          readiness={runtimeHealth.readiness}
          healthKind={runtimeHealth.kind}
          profile={resolvedRetrievalProfile(activeSessionProfile)}
          jobBoard={operatorJobs.board}
          jobsLoading={operatorJobs.loading}
          onRetryJob={(jobId) => void operatorJobs.retry(jobId)}
          onCancelJob={(jobId) => void operatorJobs.cancel(jobId)}
          onRefreshJobs={() => void operatorJobs.refresh()}
          onRecheck={() => void runtimeHealth.check()}
          operationsAvailable={operationsAvailable}
          onRunOperation={(commandId) => void runOperation(commandId)}
          tab={buildTab}
          onTabChange={setBuildTab}
          onNavigate={navigate}
        />}
        {view === "measure" && <MeasureWorkspace
          live={adminLive}
          ready={runtimeHealth.kind === "healthy"}
          profile={resolvedRetrievalProfile(activeSessionProfile)}
          onProfileChange={updateLabProfile}
          onApplyProfile={applyProfile}
          onApplySnapshot={applySnapshot}
          jobBoard={operatorJobs.board}
          onRefreshJobs={() => void operatorJobs.refresh()}
          tab={measureTab}
          onTabChange={setMeasureTab}
          onOpenSettings={(category) => openSettings(category)}
          focusResultId={measureResultId}
        />}
        {view === "system" && <SystemWorkspace
          live={adminLive}
          ready={runtimeHealth.kind === "healthy"}
          readiness={runtimeHealth.readiness}
          checking={runtimeHealth.checking}
          onRefresh={() => void runtimeHealth.check()}
          operationsAvailable={operationsAvailable}
          tab={systemTab}
          onTabChange={setSystemTab}
        />}
      </section>
      <SettingsModal open={settingsOpen} initialCategory={settingsCategory} profile={active?.profile ?? profile} capabilities={capabilities ?? { can_edit_prompt_policy: adminLive, can_edit_run_limits: adminLive, can_edit_golden: adminLive, can_build_snapshot: adminLive, can_run_evaluation: adminLive, can_change_custom_retrieval: adminLive, can_query_snapshot: adminLive, can_use_operations: operationsAvailable, can_compare_published_snapshots: true }} readiness={runtimeHealth.readiness} onChange={(next) => { setProfile(next); if (active) updateActive(active.messages, next); }} onClose={() => setSettingsOpen(false)} onOpenMeasure={(tab) => { setSettingsOpen(false); navigate({ view: "measure", tab }); }} onOpenSystem={(tab) => { setSettingsOpen(false); navigate({ view: "system", tab }); }} onOpenTour={() => { setSettingsOpen(false); openTour(); }} onClear={() => { clearReviews(); notify("Local conversations cleared.", "success"); }} />
      {tourOpen && <Onboarding onClose={closeTour} includeOperations={operationsAvailable} onStepChange={openTourStep} location={location} />}
      <HelpOverlay screen={helpScreen(view, currentTab)} open={helpVisible} keyboard={!modalOpen} onClose={() => setHelp(false)} location={location} />
      <ServiceHealthModal
        kind={runtimeHealth.kind}
        visible={runtimeHealth.modalVisible}
        checking={runtimeHealth.checking}
        onRetry={() => void runtimeHealth.check()}
        onReload={() => window.location.reload()}
        onDismiss={runtimeHealth.dismissWarning}
        onOpenStatus={() => { runtimeHealth.dismissWarning(); navigate({ view: "system", tab: "status" }); }}
        onOpenBuild={() => { runtimeHealth.dismissWarning(); navigate({ view: "build", tab: "pipeline" }); }}
        degradedMessage={runtimeHealth.readiness?.corpus?.pending_embeddings
          ? `${runtimeHealth.readiness.corpus.pending_embeddings.toLocaleString()} chunks still need embeddings. Open Build and run Backfill embeddings.`
          : runtimeHealth.readiness?.corpus?.schema_message || undefined}
      />
    </main>
  );
}

interface ReviewMessageProps {
  message: ChatMessage;
  /** The newest message carrying evidence; only that one gets the `review.evidence` help hook. */
  latestEvidence: boolean;
  busy: boolean;
  onMark: (chunkId: number, mode: "pin" | "exclude") => void;
  onUseSelected: () => void;
}

/** Verdict pill derived from the terminal label; conversation replies carry no label and get no pill. */
function verdictPill(message: ChatMessage): { className: string; text: string } | null {
  if (message.evidenceLabel === "Cited evidence") {
    const count = message.citations ?? message.evidence?.length ?? 0;
    return { className: "supported", text: `Supported · ${count} citation${count === 1 ? "" : "s"}` };
  }
  if (message.evidenceLabel === "Related evidence — not direct support") return { className: "not-in-docs", text: "Not in documents" };
  if (message.evidenceLabel === "Retrieved candidates — answer not generated") return { className: "failed", text: "Answer not generated" };
  return null;
}

function ReviewMessage({ message, latestEvidence, busy, onMark, onUseSelected }: ReviewMessageProps) {
  const pill = message.role === "assistant" ? verdictPill(message) : null;
  const pinned = message.pinnedChunkIds ?? [];
  const excluded = message.excludedChunkIds ?? [];
  const notInDocs = message.evidenceLabel === "Related evidence — not direct support";
  return (
    <article className={`message ${message.role}`}>
      <div className="message-role">{message.role === "user" ? "You" : "DocReview"}</div>
      <div className="message-body">
        {pill && <span className={`verdict ${pill.className}`}>{pill.text}</span>}
        {message.role === "assistant" ? <MarkdownMessage>{message.text}</MarkdownMessage> : <p>{message.text}</p>}
        {message.evidence?.length ? (
          <>
            {notInDocs && <p className="notice">Related evidence is shown below, but it is not direct support.</p>}
            <details className="evidence" data-help={latestEvidence ? "review.evidence" : undefined}>
              <summary data-tour="evidence-toggle">{message.evidenceLabel ?? "Retrieved candidates"} · {message.evidence.length}</summary>
              {message.evidence.map((hit) => {
                const isPinned = pinned.includes(hit.chunk_id);
                const isExcluded = excluded.includes(hit.chunk_id);
                return (
                  <div className={`evidence-hit${isPinned ? " pinned" : ""}${isExcluded ? " excluded" : ""}`} key={hit.chunk_id}>
                    <div className="evidence-meta">
                      <strong>{hit.citation}</strong>
                      <span aria-hidden="true">·</span>
                      <span className="doc-chip">{hit.doc_id}</span>
                      {hit.kind === "table" && <><span aria-hidden="true">·</span><span className="kind-badge">table</span></>}
                      <span aria-hidden="true">·</span>
                      <span>chars {hit.start_char}–{hit.end_char}</span>
                    </div>
                    <p>{hit.body}</p>
                    <div className="evidence-actions">
                      <button type="button" aria-pressed={isPinned} onClick={() => onMark(hit.chunk_id, "pin")}>Pin</button>
                      <button type="button" aria-pressed={isExcluded} onClick={() => onMark(hit.chunk_id, "exclude")}>Exclude</button>
                    </div>
                  </div>
                );
              })}
              {message.candidateToken && pinned.length + excluded.length > 0 && (
                <button className="button primary use-evidence" type="button" disabled={busy} onClick={onUseSelected}>
                  Use selected evidence · {pinned.length} pinned · {excluded.length} excluded
                </button>
              )}
            </details>
          </>
        ) : null}
        {message.trace && <details className="trace-details"><summary>Run trace</summary><pre className="trace">{message.trace}</pre></details>}
      </div>
    </article>
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
    // The card adds the "related evidence" notice itself, so the text carries only the rationale.
    return typeof report.rationale === "string" ? report.rationale : "The filings do not contain direct support for this question.";
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

/** Evidence label for a terminal report; conversation replies and other unlabelled reports get none. */
function terminalEvidenceLabel(payload: Record<string, unknown>): ChatMessage["evidenceLabel"] {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const report = root.report as Record<string, unknown> | null;
  if (report?.label === "SUPPORTED") return "Cited evidence";
  if (report?.label === "NOT_IN_DOCS") return "Related evidence — not direct support";
  if (report) return undefined;
  return "Retrieved candidates — answer not generated";
}

/** Citations the report made, as opposed to the candidate pool the stream sent earlier. */
function terminalCitationCount(payload: Record<string, unknown>): number | undefined {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const report = root.report as Record<string, unknown> | null;
  return Array.isArray(report?.citations) ? report.citations.length : undefined;
}

function extractTrace(payload: Record<string, unknown>): string {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const values = ["status", "total_requests", "total_input_tokens", "total_output_tokens", "total_time_seconds"];
  return values.filter((key) => root[key] !== undefined).map((key) => `${key}=${String(root[key])}`).join(" · ");
}

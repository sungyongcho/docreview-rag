"use client";
import { BrowserStorageSupport } from "@/components/browser-storage";
import { browserStorage, configureBrowserStorage, loadDefaultProfile, loadActiveConversation, saveActiveConversation, subscribeStorageRestored, productionBrowserStorageEnabled } from "@/lib/storage";
import { useI18n } from "@/lib/i18n";


import { conversationSettingsError } from "@/lib/saved-presets";
import { SlowCpuNotice } from "./slow-cpu-notice";
import { ProductBrand } from "@/components/product-brand";
import { CreatorSignature } from "@/components/creator-signature";
import { GuidesNavigation } from "@/components/guides-navigation";
import type { DisclosureStage } from "@/components/review-stage-details";
import { RunDetailsPanel } from "@/components/run-details-panel";
import { EvidenceCandidates } from "@/components/evidence-candidates";
import { LanguageSwitch } from "@/lib/i18n";
import { localCpuWarning, localModelIssue, selectedLocalModel, SLOW_LOCAL_CPU_TOKENS_PER_SECOND } from "@/lib/local-models";

import {
  Activity,
  CircleHelp,
  FlaskConical,
  Hammer,
  MessageSquare,
  Monitor,
  PanelLeftClose,
  PanelLeftOpen,
  Send,
  SquarePen,
  Trash2,
  Settings,
  TriangleAlert,
  X,
} from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { RetainedPanel } from "@/components/retained-panel";
import "./workspace-navigation.css";
import { WorkspaceHistory } from "@/components/workspace-history";
import { navigationLabel, navigationUrl, parseNavigationUrl, type NavigationTarget } from "@/lib/navigation";

import { BuildWorkspace, type BuildTab } from "@/components/build-workspace";
import { ConversationSettings, type ConversationSettingsTab } from "@/components/conversation-settings";
import { LocalEngineSettings } from "@/components/local-engine-settings";
import { ComposerBanner, ComposerToolbar, composerBanner } from "@/components/composer-toolbar";
import { HelpOverlay } from "@/components/help-overlay";
import { MarkdownMessage } from "@/components/markdown-message";
import { MeasureWorkspace, type MeasureTab } from "@/components/measure-workspace";
import { Onboarding, type TourView } from "@/components/onboarding";
import { PathDecisionBadge, ReviewProgressSteps, WaitingGlyph, reviewProgressFromEvent, initialReviewProgress, candidateProgress, finishReviewProgress, resolvedScopeFromServer, type ReviewProgressState } from "@/components/review-progress";
import { ServiceHealthModal } from "@/components/service-health-modal";
import { PROD_LOCKED_MESSAGE, SettingsModal, type SettingsCategory } from "@/components/settings-modal";
import { SystemWorkspace, type SystemTab } from "@/components/system-workspace";
import { NotificationProvider, NotificationOutlet, useNotifications } from "@/components/notifications";
import { ProductionPreviewFrame } from "@/components/production-preview-frame";
import { ThemeSwitch } from "@/components/theme-switch";
import { enterProductionPreview, exitProductionPreview, previewState } from "@/lib/production-preview";
import { useProductionPreview } from "@/lib/use-production-preview";
import {
  ApiError,
  getCapabilities,
  getReleaseLimits,
  retrieveEvidence,
  streamReview,
} from "@/lib/api";
import { LOCAL_ENGINE_VISIBLE } from "@/lib/build-mode";
import { profileCompatibilityIssue } from "@/lib/profile-compatibility";
import { failureMessage, failureReport } from "@/lib/pipeline";
import { helpScreen } from "@/lib/help-content";
import { helpTopicScreen } from "@/lib/help-search";
import { getOperatorCommands, operatorAvailable, startOperatorJob } from "@/lib/operator-api";
import { loadConversations, loadHelpOpen, newConversation, ONBOARDING_KEY, saveConversations, saveHelpOpen } from "@/lib/storage";
import type { Capabilities, ChatMessage, Conversation, EvidenceHit, PublishedSnapshot, RetrievalProfile, ReviewSessionDraft } from "@/lib/types";
import { DEFAULT_SESSION_PROFILE, resolvedRetrievalProfile } from "@/lib/types";
import { useRuntimeHealth } from "@/lib/use-runtime-health";
import { useOperatorJobs } from "@/lib/use-operator-jobs";

type View = "review" | "build" | "measure" | "system";

interface NavigationEntry {
  position: number;
  target: NavigationTarget;
  conversationId: string;
  query: string;
  conversationTab: ConversationSettingsTab | null;
  scroll: Array<{ element: HTMLElement; top: number; left: number }>;
  focus: HTMLElement | null;
}

/** Preserve the complete DEV tree while a separate public document is being inspected. */
export function ServiceShell({ publicPreview = false }: { publicPreview?: boolean } = {}) {
  const preview = useProductionPreview();
  const frame = useRef<HTMLIFrameElement>(null);
  const dev = useRef<HTMLDivElement>(null);
  const restore = useRef<{ focus: HTMLElement | null; scroll: Array<{ element: HTMLElement; top: number; left: number }> } | null>(null);
  function openPreview() {
    const captured = { focus: document.activeElement instanceof HTMLElement ? document.activeElement : null, scroll: Array.from(dev.current?.querySelectorAll<HTMLElement>("*") ?? []).filter((element) => element.scrollTop || element.scrollLeft).map((element) => ({ element, top: element.scrollTop, left: element.scrollLeft })) };
    if (enterProductionPreview()) restore.current = captured;
  }
  function closePreview() {
    exitProductionPreview();
    requestAnimationFrame(() => {
      for (const item of restore.current?.scroll ?? []) { item.element.scrollTop = item.top; item.element.scrollLeft = item.left; }
      restore.current?.focus?.focus({ preventScroll: true });
      restore.current = null;
    });
  }
  useEffect(() => {
    const changed = (event: MessageEvent) => {
      if (event.origin === window.location.origin && event.source === frame.current?.contentWindow && event.data?.type === "docreview-preview-unavailable") closePreview();
    };
    window.addEventListener("message", changed);
    return () => { window.removeEventListener("message", changed); if (previewState().mode === "host") exitProductionPreview(); };
  }, []);
  if (publicPreview || preview.mode === "document") return <NotificationProvider><ServiceSession publicPreview /></NotificationProvider>;
  return <>
    <div ref={dev}><RetainedPanel active={preview.mode !== "host"}><NotificationProvider><ServiceSession sessionActive={preview.mode !== "host"} onPreview={openPreview} previewBlocked={preview.pendingMutations > 0} /></NotificationProvider></RetainedPanel></div>
    {preview.mode === "host" && <ProductionPreviewFrame frameRef={frame} onExit={closePreview} />}
  </>;
}

/** Restored requests cannot resume themselves after a reload or browser import. */
function restoreInterruptedConversations(saved: Conversation[], t: (key: string) => string): Conversation[] {
  return saved.map((conversation) => ({ ...conversation, messages: conversation.messages.map((message) => message.pending ? { ...message, pending: false, text: t("The request was interrupted. Send the question again."), execution: message.execution ? finishReviewProgress(message.execution, "failed", Math.max(0, Date.now() - (message.execution.startedAt ?? Date.now()))) : undefined } : message) }));
}

function ServiceSession({ publicPreview = false, sessionActive = true, onPreview, previewBlocked = false }: { publicPreview?: boolean; sessionActive?: boolean; onPreview?: () => void; previewBlocked?: boolean }) {
  const { t, locale } = useI18n();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState("");
  const [view, setView] = useState<View>("review");
  const [navigationHistory, setNavigationHistory] = useState<NavigationEntry[]>([]);
  const [navigationForward, setNavigationForward] = useState<NavigationEntry[]>([]);
  const navigationPosition = useRef(0);
  const revertingPosition = useRef<number | null>(null);
  const [buildStage, setBuildStage] = useState<number | "setup" | undefined>(undefined);
  const pendingReturn = useRef<NavigationEntry | null>(null);
  const [unsavedGolden, setUnsavedGolden] = useState(false);
  const [buildTab, setBuildTab] = useState<BuildTab>("pipeline");
  const [measureTab, setMeasureTab] = useState<MeasureTab>("playground");
  const [systemTab, setSystemTab] = useState<SystemTab>("status");
  const [measureResultId, setMeasureResultId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const sidebarToggle = useRef<HTMLButtonElement>(null);
  const [tourOpen, setTourOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [runDetailsMessageId, setRunDetailsMessageId] = useState<string | null>(null);
  const [runDetailsStage, setRunDetailsStage] = useState<{ stage: DisclosureStage | null } | undefined>();
  const [pendingHelpTarget, setPendingHelpTarget] = useState<string | null>(null);
  const [profile, setProfile] = useState<ReviewSessionDraft>(DEFAULT_SESSION_PROFILE);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [conversationTab, setConversationTab] = useState<ConversationSettingsTab | null>(null);
  const [conversationInputsValid, setConversationInputsValid] = useState(true);
  const ragTrigger = useRef<HTMLButtonElement>(null);
  const [settingsCategory, setSettingsCategory] = useState<SettingsCategory | undefined>(undefined);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [activeReview, setActiveReview] = useState<{ conversationId: string; messageId: string } | null>(null);
  const currentConversationId = useRef(activeId);
  currentConversationId.current = activeId;
  const messagesViewport = useRef<HTMLDivElement>(null);
  const followReview = useRef(true);
  const lastReview = useRef<{ conversationId: string; messageId: string } | null>(null);
  const lastScrolledMessage = useRef<ChatMessage | null>(null);
  /** `ReleaseLimits.daily_cost_reset_at_utc` captured after a `daily_cost_limit` error; cleared by the next successful review. */
  const [resetAt, setResetAt] = useState<string | null>(null);
  /** Build stage card to scroll into view once the Build workspace has rendered. */
  const [pendingStage, setPendingStage] = useState<number | "setup" | null>(null);
  const reviewAbort = useRef<AbortController | null>(null);
  /** First-run routing fires once per page load and is cancelled by any explicit navigation before it. */
  const firstRunRouted = useRef(false);
  const recoveryRouted = useRef(false);
  useEffect(() => {
    if (publicPreview || !sessionActive || recoveryRouted.current) return;
    recoveryRouted.current = true;
    const stage = new URLSearchParams(window.location.search).get("recovery_stage");
    const stages: Record<string, number> = { filings: 1, index: 2, embeddings: 3, lexical: 4, ask: 5, answer_model: 6, evaluate: 7 };
    if (!stage || !stages[stage]) return;
    firstRunRouted.current = true;
    setView("build"); setBuildTab("pipeline"); setBuildStage(stages[stage]); setPendingStage(stages[stage]);
  }, [publicPreview, sessionActive]);
  const adminBuild = process.env.NEXT_PUBLIC_ADMIN_MODE === "live" && !publicPreview;
  const runtimeHealth = useRuntimeHealth({ active: sessionActive, publicPreview });
  const permissions = capabilities && (!runtimeHealth.readiness?.environment || capabilities.environment === runtimeHealth.readiness.environment) ? capabilities : null;
  const environment = permissions?.environment ?? runtimeHealth.readiness?.environment;
  const modeLabel = environment ? `${environment.toUpperCase()} MODE` : null;
  const adminLive = adminBuild && permissions?.can_edit_prompt_policy === true;
  const localAllowed = LOCAL_ENGINE_VISIBLE && permissions?.environment === "dev" && permissions.can_configure_local_llm;
  const operationsAvailable = adminBuild && permissions?.environment === "dev" && permissions.can_use_operations && operatorAvailable();
  const helpCapabilities = useMemo(() => permissions ? { ...permissions, can_use_operations: Boolean(operationsAvailable), can_configure_local_llm: Boolean(localAllowed), can_change_custom_retrieval: Boolean(adminLive && permissions.can_change_custom_retrieval), can_edit_run_limits: Boolean(adminLive && permissions.can_edit_run_limits) } : null, [permissions, operationsAvailable, localAllowed, adminLive]);
  const initialized = useRef(false);
  const tourInitialized = useRef(false);
  const { notify, dismissNotice } = useNotifications();
  const operatorJobs = useOperatorJobs(adminBuild && permissions?.can_build_snapshot === true, runtimeHealth.check, sessionActive);
  const workPending = operatorJobs.board.active_count > 0 || operatorJobs.board.queued_count > 0;



  useEffect(() => {
    if (tourInitialized.current || (!environment && !publicPreview) || (environment === "prod" && !publicPreview && !productionBrowserStorageEnabled())) return;
    tourInitialized.current = true;
    let savedTour: string | null = null;
    try { savedTour = browserStorage().getItem(ONBOARDING_KEY); } catch { /* PROD recovery starts after capabilities identify the environment. */ }
    const shouldOpenTour = !publicPreview && savedTour !== "done";
    setTourOpen(shouldOpenTour);
    // The tour owns the screen on a first visit; a persisted open Help state waits until it is dismissed.
    setHelpOpen(!shouldOpenTour && loadHelpOpen());
    if (window.innerWidth <= 560) setSidebarOpen(shouldOpenTour);
  }, [environment, capabilities, publicPreview]);

  useEffect(() => () => reviewAbort.current?.abort(), []);
  useEffect(() => {
    if (!sessionActive) return;
    let cancelled = false;
    void getCapabilities().then((value) => {
      if (cancelled) return;
      if (!["dev", "prod"].includes(value.environment)) { setCapabilities(null); return; }
      configureBrowserStorage(publicPreview ? undefined : value.environment);
      if (!initialized.current) {
        initialized.current = true;
        const saved = loadConversations();
        const restored = restoreInterruptedConversations(saved, t);
        const initial = restored.length ? restored : [newConversation(value.environment === "prod" && !publicPreview || adminBuild && value.environment === "dev" && value.can_edit_prompt_policy ? undefined : DEFAULT_SESSION_PROFILE)];
        setConversations(saved.some((conversation) => conversation.messages.some((message) => message.pending)) ? saveConversations(initial) : initial);
        const remembered = initial.find(item => item.id === loadActiveConversation()) ?? initial[0];
        const target = parseNavigationUrl(window.location.href, initial.map((item) => item.id), remembered.id);
        const selected = target?.view === "review" ? initial.find((item) => item.id === target.conversationId) ?? remembered : remembered;
        setActiveId(selected.id);
        setProfile(selected.profile ?? DEFAULT_SESSION_PROFILE);
        const position = window.history.state?.docreviewNavigation?.position;
        navigationPosition.current = Number.isSafeInteger(position) ? position : 0;
        if (target) {
          firstRunRouted.current = true;
          setView(target.view);
          if (target.view === "build") { setBuildTab(target.tab ?? "pipeline"); setBuildStage(target.stage); if (target.stage !== undefined) setPendingStage(target.stage); }
          if (target.view === "measure") { setMeasureTab(target.tab ?? "playground"); setMeasureResultId(target.resultId ?? null); }
          if (target.view === "system") setSystemTab(!adminBuild || publicPreview ? "status" : target.tab ?? "status");
        }
      }
      setCapabilities(adminBuild ? value : {
        ...value,
        can_edit_prompt_policy: false,
        can_edit_run_limits: false,
        can_edit_golden: false,
        can_build_snapshot: false,
        can_run_evaluation: false,
        can_change_custom_retrieval: false,
        can_query_snapshot: false,
        can_use_operations: false,
        can_configure_local_llm: false,
      });
    }).catch(() => { if (!cancelled) setCapabilities(null); });
    return () => { cancelled = true; };
  }, [adminBuild, runtimeHealth.checkedAt, sessionActive]);

  useEffect(() => {
    if (publicPreview && capabilities && capabilities.environment !== "dev") window.parent.postMessage({ type: "docreview-preview-unavailable" }, window.location.origin);
  }, [publicPreview, capabilities]);

  useEffect(() => { if (initialized.current && sessionActive && !publicPreview) saveActiveConversation(activeId); }, [activeId, sessionActive, publicPreview]);
  useEffect(() => subscribeStorageRestored(() => {
    if (!initialized.current || !productionBrowserStorageEnabled()) return;
    const loaded = restoreInterruptedConversations(loadConversations(), t);
    const next = loaded.length ? loaded : [newConversation(loadDefaultProfile())];
    const selected = next.find(item => item.id === loadActiveConversation()) ?? next[0];
    setConversations(next); setActiveId(selected.id); setProfile(selected.profile ?? DEFAULT_SESSION_PROFILE);
  }), []);

  const active = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId) ?? conversations[0],
    [activeId, conversations],
  );
  useLayoutEffect(() => {
    const target = lastReview.current;
    if (view !== "review" || !target || target.conversationId !== active?.id) return;
    const message = active.messages.find((item) => item.id === target.messageId);
    if (!message || lastScrolledMessage.current === message) return;
    lastScrolledMessage.current = message;
    const element = messagesViewport.current;
    if (element && followReview.current) element.scrollTop = element.scrollHeight;
  }, [active?.messages, active?.id, view]);

  const activeSessionProfile = active?.profile ?? profile;
  const latestEvidenceId = active?.messages.filter((message) => message.evidence?.length).at(-1)?.id ?? null;
  const banner = composerBanner({ readiness: runtimeHealth.readiness, live: adminLive, profile: activeSessionProfile, resetAt, jobs: operatorJobs.board.jobs });
  const compatibilityIssue = profileCompatibilityIssue(activeSessionProfile, permissions);
  const localIssue = localAllowed ? localModelIssue(activeSessionProfile, runtimeHealth.readiness) : null;
  const localModel = selectedLocalModel(activeSessionProfile, runtimeHealth.readiness?.review_engines?.local);
  const localCpuSpeed = localAllowed && !localIssue && !compatibilityIssue ? localCpuWarning(activeSessionProfile, runtimeHealth.readiness?.review_engines?.local) : null;
  const settingsValidationError = conversationSettingsError(activeSessionProfile);
  const sendBlocked = settingsValidationError !== null || publicPreview || !conversationInputsValid || banner?.kind === "empty" || banner?.kind === "preparation" || localIssue !== null || compatibilityIssue !== null;

  useEffect(() => {
    if (!localAllowed || compatibilityIssue || !active || activeSessionProfile.local_model || !localModel) return;
    const targetId = active.id;
    setConversations((current) => saveConversations(current.map((conversation) => {
      if (conversation.id !== targetId || conversation.profile?.local_model) return conversation;
      return { ...conversation, profile: { ...(conversation.profile ?? DEFAULT_SESSION_PROFILE), local_model: localModel } };
    })));
  }, [active?.id, activeSessionProfile.engine, activeSessionProfile.local_model, localModel, localAllowed, compatibilityIssue]);

  useEffect(() => {
    if (pendingStage === null || view !== "build" || buildTab !== "pipeline") return;
    document.getElementById(`stage-${pendingStage}`)?.scrollIntoView({ block: "start" });
    setPendingStage(null);
  }, [pendingStage, view, buildTab]);

  function persist(next: Conversation[]) {
    setConversations(saveConversations(next));
  }

  /** Return the explicit location represented by the retained workspace controls. */
  function currentTarget(): NavigationTarget {
    return view === "build" ? { view, tab: buildTab, ...(buildTab === "pipeline" && buildStage !== undefined ? { stage: buildStage } : {}) }
      : view === "measure" ? { view, tab: measureTab, resultId: measureResultId }
      : view === "system" ? { view, tab: systemTab } : { view, conversationId: active?.id ?? activeId };
  }

  /** Save only the visible origin; retained panels own their existing control state. */
  function currentNavigation(): NavigationEntry {
    const panel = document.querySelector<HTMLElement>(`[data-workspace="${view}"]`);
    const scroll = Array.from(panel?.querySelectorAll<HTMLElement>("*") ?? [])
      .filter((element) => !element.closest("[hidden]") && (element.scrollTop !== 0 || element.scrollLeft !== 0 || element.matches(".messages, .lab-shell")))
      .map((element) => ({ element, top: element.scrollTop, left: element.scrollLeft }));
    return { position: navigationPosition.current, target: currentTarget(), conversationId: active?.id ?? activeId, query, conversationTab, scroll, focus: document.activeElement instanceof HTMLElement ? document.activeElement : null };
  }

  /** Keep navigation metadata local and preserve unrelated URL/Next history state. */
  function writeNavigation(target: NavigationTarget, replace: boolean) {
    const state = { ...window.history.state, docreviewNavigation: { position: navigationPosition.current } };
    window.history[replace ? "replaceState" : "pushState"](state, "", navigationUrl(target, window.location.href));
  }

  function navigate(target: NavigationTarget, confirmed = false, returning = false) {
    const normalized: NavigationTarget = target.view === "build" ? { ...target, tab: target.tab ?? buildTab }
      : target.view === "measure" ? { ...target, tab: target.tab ?? measureTab, resultId: target.resultId === undefined ? measureResultId : target.resultId }
      : target.view === "system" ? { ...target, tab: (!adminBuild || publicPreview) && target.tab !== undefined && target.tab !== "status" ? "status" : target.tab ?? systemTab }
      : { ...target, conversationId: target.conversationId ?? active?.id ?? activeId };
    const changed = normalized.view !== view
      || (normalized.view === "build" && (normalized.tab !== buildTab || (normalized.stage !== undefined && normalized.stage !== buildStage)))
      || (normalized.view === "measure" && (normalized.tab !== measureTab || normalized.resultId !== measureResultId))
      || (normalized.view === "system" && normalized.tab !== systemTab)
      || (normalized.view === "review" && normalized.conversationId !== activeId);
    if (!confirmed && changed && view === "measure" && unsavedGolden && !window.confirm(t("Discard unsaved question changes?"))) return false;
    if (changed && !returning) {
      const origin = currentNavigation();
      setNavigationHistory((history) => [...history.slice(-29), origin]);
      setNavigationForward([]);
      navigationPosition.current += 1;
      writeNavigation(normalized, false);
    }
    firstRunRouted.current = true;
    if (normalized.view !== "review") setRunDetailsMessageId(null);
    if (normalized.view === "build") {
      if (normalized.tab) setBuildTab(normalized.tab);
      setBuildStage(normalized.stage);
      if (normalized.stage !== undefined) setPendingStage(normalized.stage);
    }
    if (normalized.view === "measure") {
      if (normalized.tab) setMeasureTab(normalized.tab);
      if (normalized.resultId !== undefined) setMeasureResultId(normalized.resultId);
    }
    if (normalized.view === "system" && normalized.tab) setSystemTab(normalized.tab);
    if (normalized.view === "review" && normalized.conversationId) {
      setActiveId(normalized.conversationId);
      const selected = conversations.find((conversation) => conversation.id === normalized.conversationId);
      if (selected) setProfile(selected.profile ?? DEFAULT_SESSION_PROFILE);
    }
    setView(normalized.view);
    return true;
  }

  /** The native traversal generates the same popstate path as browser back/forward. */
  function jumpNavigation(position: number) {
    const distance = position - navigationPosition.current;
    if (distance) window.history.go(distance);
  }

  useEffect(() => {
    if (!initialized.current || !sessionActive || !active?.id) return;
    writeNavigation(currentTarget(), true);
  }, [view, buildTab, buildStage, measureTab, measureResultId, systemTab, active?.id, sessionActive]);

  useEffect(() => {
    if (!initialized.current || !sessionActive || !active?.id) return;
    /** Restore a visited entry, or a valid URL whose in-memory scroll snapshot expired. */
    const pop = (event: PopStateEvent) => {
      const requested = event.state?.docreviewNavigation?.position;
      const nextPosition = Number.isSafeInteger(requested) ? requested : navigationPosition.current - 1;
      if (revertingPosition.current === nextPosition) { revertingPosition.current = null; return; }
      const target = parseNavigationUrl(window.location.href, conversations.map((item) => item.id), active.id) ?? { view: "review" as const, conversationId: active.id };
      const origin = currentNavigation();
      const all = [...navigationHistory, origin, ...navigationForward];
      const index = all.findIndex((entry) => entry.position === nextPosition);
      const entry = index >= 0 ? all[index] : null;
      if (!navigate(target, false, true)) {
        const distance = origin.position - nextPosition;
        if (distance) { revertingPosition.current = origin.position; window.history.go(distance); }
        else writeNavigation(origin.target, true);
        return;
      }
      navigationPosition.current = nextPosition;
      if (entry) {
        setNavigationHistory(all.slice(0, index).slice(-30));
        setNavigationForward(all.slice(index + 1, index + 31));
        pendingReturn.current = entry;
        const restored = conversations.find((item) => item.id === entry.conversationId);
        if (restored) {
          setActiveId(restored.id);
          setProfile(restored.profile ?? DEFAULT_SESSION_PROFILE);
          if (restored.id !== activeId) setQuery(entry.query);
        }
        setConversationTab(entry.conversationTab);
      } else if (nextPosition < origin.position) {
        setNavigationHistory([]);
        setNavigationForward([origin, ...navigationForward].slice(0, 30));
      } else {
        setNavigationHistory([...navigationHistory, origin].slice(-30));
        setNavigationForward([]);
      }
    };
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, [view, buildTab, buildStage, measureTab, measureResultId, systemTab, activeId, active, conversations, query, conversationTab, navigationHistory, navigationForward, unsavedGolden, sessionActive, adminBuild, publicPreview]);

  useLayoutEffect(() => {
    const entry = pendingReturn.current;
    if (!entry) return;
    pendingReturn.current = null;
    if (entry.focus?.isConnected && !entry.focus.closest("[hidden], [inert]")) entry.focus.focus({ preventScroll: true });
    for (const { element, top, left } of entry.scroll) if (element.isConnected) { element.scrollTop = top; element.scrollLeft = left; }
  }, [view, buildTab, measureTab, systemTab, activeId, navigationHistory, navigationForward]);

  function openConversationSettings(tab: ConversationSettingsTab) {
    if (!navigate({ view: "review" })) return;
    setSettingsOpen(false);
    setConversationTab(tab);
  }

  function navigateHelpTopic(id: string) {
    if (!adminLive && (id === "review.evidence-policy" || id === "review.run-limits" || id.startsWith("review.retrieval"))) {
      notify(t(PROD_LOCKED_MESSAGE), "warning", "help-locked");
      return;
    }
    const owner = helpTopicScreen(id);
    const settingsTab: ConversationSettingsTab | null = id === "review.filters" || id === "review.rag" ? "filters" : id === "review.evidence-policy" ? "evidence" : id === "review.run-limits" ? "limits" : id.startsWith("review.retrieval") ? "retrieval" : null;
    let target: NavigationTarget | null = null;
    if (id === "review.snapshot") target = { view: "measure", tab: "snapshots" };
    else if (settingsTab || owner === "review") target = { view: "review" };
    else if (owner === "build.documents") target = { view: "build", tab: "documents" };
    else if (owner === "build.jobs") target = { view: "build", tab: "jobs" };
    else if (owner === "build") {
      const stages = ["filings", "index", "embeddings", "lexical", "ask", "answer_model", "evaluate"];
      const index = stages.indexOf(id.replace("build.stage.", ""));
      target = { view: "build", tab: "pipeline", ...(index >= 0 ? { stage: index + 1 } : {}) };
    } else if (owner === "system") target = { view: "system", tab: id === "system.operations" && operationsAvailable ? "operations" : id === "system.api" && adminLive ? "api" : id === "system.usage" && adminLive ? "usage" : "status" };
    else if (owner?.startsWith("measure.")) target = { view: "measure", tab: id === "measure.snapshots.freeze" ? "runs" : owner.slice(8) as MeasureTab };
    if (!target || !navigate(target)) return;
    if (settingsTab) { setSettingsOpen(false); setConversationTab(settingsTab); }
    setPendingHelpTarget(id === "review.snapshot" ? "measure.snapshots.list" : id === "measure.runs.chunk_targets" ? "measure.runs.mode" : id.startsWith("review.retrieval.") && activeSessionProfile.retrieval_preset !== "custom" ? "review.retrieval" : id);
  }

  useEffect(() => {
    if (!pendingHelpTarget) return;
    let finished = false;
    const observer = new MutationObserver(revealTarget);
    /** Lazy panels and evaluation dialogs can mount after the workspace navigation commits. */
    function revealTarget() {
      if (finished) return;
      const target = Array.from(document.querySelectorAll<HTMLElement>(`[data-help="${pendingHelpTarget}"]`)).find((element) => !element.closest("[hidden]"));
      if (!target) return;
      finished = true;
      observer.disconnect();
      for (let disclosure = target.closest("details"); disclosure; disclosure = disclosure.parentElement?.closest("details") ?? null) disclosure.open = true;
      target.scrollIntoView?.({ block: "center", inline: "nearest" });
      setPendingHelpTarget(null);
    }
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"] });
    const frame = requestAnimationFrame(revealTarget);
    const timeout = window.setTimeout(() => { finished = true; observer.disconnect(); setPendingHelpTarget(null); }, 2000);
    return () => { finished = true; cancelAnimationFrame(frame); window.clearTimeout(timeout); observer.disconnect(); };
  }, [pendingHelpTarget, view, buildTab, measureTab, systemTab, conversationTab]);

  // Saved error actions keep their old category identifiers but open the current owner.
  function openSettings(category?: SettingsCategory | "review" | "limits" | "runtime" | "experiments" | "snapshot") {
    if (category === "review") return openConversationSettings("filters");
    if (category === "limits") {
      if (adminLive) return openConversationSettings("limits");
      return navigate({ view: "system", tab: "status" });
    }
    if (category === "runtime") return navigate({ view: "system", tab: "status" });
    if (category === "experiments") return navigate({ view: "measure", tab: "defaults" });
    if (category === "snapshot") return navigate({ view: "measure", tab: "snapshots" });
    setSettingsCategory(category);
    setSettingsOpen(true);
  }

  function createReview() {
    if (view === "measure" && unsavedGolden && !window.confirm(t("Discard unsaved question changes?"))) return;
    const conversation = newConversation(adminLive && permissions?.environment === "dev" ? undefined : DEFAULT_SESSION_PROFILE);
    persist([conversation, ...conversations]);
    setActiveId(conversation.id);
    setProfile(conversation.profile ?? DEFAULT_SESSION_PROFILE);
    navigate({ view: "review", conversationId: conversation.id }, true);
  }

  function removeReview(id: string) {
    if (activeReview?.conversationId === id) reviewAbort.current?.abort();
    const remaining = conversations.filter((conversation) => conversation.id !== id);
    const next = remaining.length ? remaining : [newConversation(adminLive && permissions?.environment === "dev" ? undefined : DEFAULT_SESSION_PROFILE)];
    persist(next);
    if (activeId === id) setActiveId(next[0].id);
  }

  function clearReviews() {
    reviewAbort.current?.abort();
    const conversation = newConversation(adminLive && permissions?.environment === "dev" ? undefined : DEFAULT_SESSION_PROFILE);
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
  function updateActive(messages: ChatMessage[], selectedProfile?: ReviewSessionDraft | null) {
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

  /** Append submitted messages atomically to their original conversation. */
  function appendMessage(conversationId: string, added: ChatMessage | ChatMessage[]) {
    setConversations((current) => saveConversations(current.map((conversation) => {
      if (conversation.id !== conversationId) return conversation;
      const messages = [...conversation.messages, ...(Array.isArray(added) ? added : [added])];
      return { ...conversation, title: conversationTitle(messages), updatedAt: new Date().toISOString(), messages };
    })));
  }

  /** Update one reserved assistant identity without overwriting concurrent profile or evidence edits. */
  function updateMessage(conversationId: string, messageId: string, patch: Partial<Omit<ChatMessage, "id" | "role">>) {
    setConversations((current) => saveConversations(current.map((conversation) => conversation.id === conversationId ? { ...conversation, updatedAt: new Date().toISOString(), messages: conversation.messages.map((message) => message.id === messageId ? { ...message, ...patch } : message) } : conversation)));
  }

  /** One-off read of the reset time after a `daily_cost_limit` error so the banner can say when answers resume. */
  function noteDailyBudget(reason: unknown) {
    if (reason instanceof ApiError && reason.code === "daily_cost_limit") {
      void getReleaseLimits().then((limits) => setResetAt(limits.daily_cost_reset_at_utc)).catch(() => undefined);
    }
  }

  async function submit() {
    if (publicPreview || !sessionActive) return;
    const question = query.trim();
    if (!question || busy || !active || sendBlocked) return;
    setQuery("");
    setBusy(true);
    const requestStarted = Date.now();
    let execution = initialReviewProgress(false, 0, (active.profile ?? profile).corpus_scope);

    reviewAbort.current?.abort();
    const controller = new AbortController();
    reviewAbort.current = controller;
    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: "user", text: question };
    const conversationId = active.id;
    const assistantId = crypto.randomUUID();
    const pending = [...active.messages, userMessage];
    lastReview.current = { conversationId, messageId: assistantId };
    setActiveReview(lastReview.current);
    followReview.current = true;
    let preparedEvidence: EvidenceHit[] = [];
    const selectedProfile = { ...(active.profile ?? profile), local_model: localModel };
    appendMessage(conversationId, [userMessage, { id: assistantId, role: "assistant", text: "", pending: true, execution, question }]);
    try {
      let evidence: EvidenceHit[] = [];
      let candidateToken: string | undefined;
      const history = pending
        .slice(0, -1)
        .filter((message) => !message.pending && message.text.trim() && (message.role === "user" || message.role === "assistant"))
        .map((message) => ({ role: message.role, text: message.text }));
      const response = await streamReview(
        question,
        selectedProfile,
        null,
        history,
        (event) => { if (controller.signal.aborted) return; execution = reviewProgressFromEvent(event, execution); updateMessage(conversationId, assistantId, { execution }); },
        controller.signal,
        (payload) => {
          if (controller.signal.aborted) return;
          evidence = payload.candidates.length ? payload.candidates : payload.results;
          preparedEvidence = evidence;
          candidateToken = payload.candidate_token ?? undefined;
          execution = candidateProgress(execution, evidence.length, payload.resolved_scope, payload.path_decision);
          updateMessage(conversationId, assistantId, { execution });
        },
      );
      if (controller.signal.aborted) throw new DOMException("Request cancelled", "AbortError");
      const answer = terminalAnswer(response);
      const terminal = (response.run ?? response) as Record<string, unknown>;
      execution = finishReviewProgress(execution, terminal.failure ? "failed" : "completed", Date.now() - requestStarted, terminal.execution, terminal.report);
      setResetAt(null);
      const assistant: Partial<ChatMessage> = {
        pending: false,
        text: answer,
        execution,
        performance: terminal.execution as Record<string, unknown> | undefined,
        evidence,
        evidenceLabel: terminalEvidenceLabel(response),
        citations: terminalCitationCount(response),
        trace: extractTrace(response),
        diagnostics: runDiagnostics(response),
        failureFix: terminalFailureFix(response),
        question,
        candidateToken,
        pinnedChunkIds: [],
        excludedChunkIds: [],
      };
      updateMessage(conversationId, assistantId, assistant);
    } catch (reason) {
      if (reason instanceof ApiError && reason.pathDecision) execution = { ...execution, pathDecision: reason.pathDecision };
      execution = finishReviewProgress(execution, controller.signal.aborted ? "cancelled" : "failed", Date.now() - requestStarted);
      if (isInfrastructureFailure(reason)) {
        updateMessage(conversationId, assistantId, { pending: false, execution, text: reason instanceof Error ? reason.message : t("The review could not be completed.") });
        if (currentConversationId.current === conversationId) setQuery((current) => current || question);
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
          execution = { ...execution, resolvedScope: resolvedScopeFromServer(retrieved.resolved_scope) ?? execution.resolvedScope };
        } catch {
          // Preserve the original provider error when retrieval is also unavailable.
        }
      }
      noteDailyBudget(reason);
      const message =
        controller.signal.aborted ? t("Request cancelled") :
        reason instanceof ApiError && reason.code === "daily_cost_limit"
          ? "The daily answer budget is exhausted. Retrieved evidence is shown without an LLM answer."
          : reason instanceof ApiError && reason.code === "provider_unavailable" && evidence.length
            ? "No answer model is configured. Retrieved filing evidence is shown below without a generated answer. See Build › step 6."
          : reason instanceof Error
            ? reason.message
            : "The review could not be completed.";
      updateMessage(conversationId, assistantId, {
        pending: false,
        text: message,
        execution,
        evidence,
        evidenceLabel: "Retrieved candidates — answer not generated",
      });
    } finally {
      if ((active.profile ?? profile).engine === "local") void runtimeHealth.check();
      setBusy(false);
      setActiveReview(null);
      if (reviewAbort.current === controller) reviewAbort.current = null;
    }
  }

  function applyProfile(nextProfile: RetrievalProfile, source?: string) {
    const [suite] = source?.split(":") ?? [];
    const corpusScope = suite?.startsWith("dart") ? "dart" : suite?.startsWith("sec") ? "sec" : (active?.profile ?? profile).corpus_scope;
    const languages = suite?.endsWith("-ko") ? ["ko" as const] : suite?.endsWith("-en") ? ["en" as const] : (active?.profile ?? profile).languages;
    const sessionProfile: ReviewSessionDraft = {
      ...(active?.profile ?? profile),
      corpus_scope: corpusScope,
      languages,
      retrieval_preset: "custom",
      custom_retrieval: nextProfile,
      applied_from_evaluation: source ?? null,
    };
    updateSessionProfile(sessionProfile);
    navigate({ view: "review" });
  }

  /** Patch preferences without replacing messages appended by an in-flight response. */
  function updateSessionProfile(update: Partial<ReviewSessionDraft>) {
    const targetId = active?.id;
    setProfile((current) => ({ ...current, ...update }));
    if (targetId) setConversations((current) => saveConversations(current.map((conversation) =>
      conversation.id === targetId
        ? { ...conversation, updatedAt: new Date().toISOString(), profile: { ...(conversation.profile ?? DEFAULT_SESSION_PROFILE), ...update } }
        : conversation,
    )));
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
    updateSessionProfile(next);
    navigate({ view: "review" });
    notify(t("Snapshot {p0} applied to this review.", { p0: snapshot.label }), "success", "snapshot-review");
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
    if (!active || !message.question || !message.candidateToken || busy || sendBlocked) return;
    setBusy(true);
    const conversationId = active.id;
    const selected = (message.evidence ?? []).filter((hit) => !(message.excludedChunkIds ?? []).includes(hit.chunk_id)).length;
    const requestStarted = Date.now();
    let execution = initialReviewProgress(true, selected, (active.profile ?? profile).corpus_scope);
    const assistantId = crypto.randomUUID();
    lastReview.current = { conversationId, messageId: assistantId };
    setActiveReview(lastReview.current);
    followReview.current = true;
    appendMessage(conversationId, { id: assistantId, role: "assistant", text: "", pending: true, execution, question: message.question });
    const controller = new AbortController();
    reviewAbort.current = controller;
    try {
      // Reuse the context that produced this candidate snapshot, excluding its question and later turns.
      const messageIndex = active.messages.findIndex((item) => item.id === message.id);
      const questionIndex = active.messages.slice(0, Math.max(0, messageIndex)).findLastIndex((item) => item.role === "user" && item.text === message.question);
      const historyTurns = (active.profile ?? profile).prompt_policy.history_turns;
      const originalHistory = active.messages.slice(0, Math.max(0, questionIndex))
        .filter((item) => !item.pending && item.text.trim() && (item.role === "user" || item.role === "assistant"))
        .map((item) => ({ role: item.role, text: item.text }));
      const response = await streamReview(
        message.question,
        active.profile ?? profile,
        {
          candidateToken: message.candidateToken,
          pinned: message.pinnedChunkIds ?? [],
          excluded: message.excludedChunkIds ?? [],
        },
        historyTurns > 0 ? originalHistory.slice(-historyTurns) : [],
        (event) => { if (controller.signal.aborted) return; execution = reviewProgressFromEvent(event, execution); updateMessage(conversationId, assistantId, { execution }); },
        controller.signal,
      );
      if (controller.signal.aborted) throw new DOMException("Request cancelled", "AbortError");
      setResetAt(null);
      const terminal = (response.run ?? response) as Record<string, unknown>;
      execution = finishReviewProgress(execution, terminal.failure ? "failed" : "completed", Date.now() - requestStarted, terminal.execution, terminal.report);
      updateMessage(conversationId, assistantId, {
        pending: false,
        execution,
        performance: terminal.execution as Record<string, unknown> | undefined,
        text: terminalAnswer(response),
        evidence: message.evidence?.filter((hit) => !(message.excludedChunkIds ?? []).includes(hit.chunk_id)),
        evidenceLabel: terminalEvidenceLabel(response),
        citations: terminalCitationCount(response),
        trace: extractTrace(response),
        diagnostics: runDiagnostics(response),
        failureFix: terminalFailureFix(response),
      });
    } catch (reason) {
      if (reason instanceof ApiError && reason.pathDecision) execution = { ...execution, pathDecision: reason.pathDecision };
      execution = finishReviewProgress(execution, controller.signal.aborted ? "cancelled" : "failed", Date.now() - requestStarted);
      updateMessage(conversationId, assistantId, { pending: false, text: controller.signal.aborted ? t("Request cancelled") : reason instanceof Error ? reason.message : t("Selected evidence review failed."), execution });
      noteDailyBudget(reason);
      notify(reason instanceof Error ? reason.message : t("Selected evidence review failed."), "error", "evidence-review");
    } finally {
      if ((active.profile ?? profile).engine === "local") void runtimeHealth.check();
      setBusy(false);
      setActiveReview(null);
      if (reviewAbort.current === controller) reviewAbort.current = null;
    }
  }

  function closeTour() {
    browserStorage().setItem(ONBOARDING_KEY, "done");
    setTourOpen(false);
  }

  function openTour() {
    setSidebarOpen(true);
    setHelp(false);
    setTourOpen(true);
  }

  function setHelp(open: boolean) {
    if (open) setRunDetailsMessageId(null);
    saveHelpOpen(open);
    setHelpOpen(open);
  }

  /** `?` toggles Help anywhere except inside a text control, and never behind the tour or a modal. */
  const modalOpen = settingsOpen || runtimeHealth.modalVisible || (view === "review" && conversationTab !== null);
  useEffect(() => {
    if (!sessionActive) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "?" || tourOpen || modalOpen) return;
      const target = event.target;
      if (target instanceof Element && target.closest('[role="dialog"][aria-modal="true"]')) return;
      if (target instanceof HTMLElement && (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable || target.hasAttribute("contenteditable"))) return;
      event.preventDefault();
      setHelp(!helpOpen);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [helpOpen, tourOpen, modalOpen, sessionActive]);
  const currentTab = view === "build" ? buildTab : view === "measure" ? measureTab : view === "system" ? systemTab : "";
  const location = `${view}/${buildTab}/${measureTab}/${systemTab}`;
  /** The workspace reserves room for the panel only while it is actually on screen. */
  const helpVisible = sessionActive && helpOpen && !tourOpen;
  const selectedRunIndex = active?.messages.findIndex((message) => message.id === runDetailsMessageId) ?? -1;
  const selectedRun = selectedRunIndex >= 0 ? active!.messages[selectedRunIndex] : null;
  const runDetailsMessage = selectedRun && sessionActive && view === "review" && !tourOpen && !helpVisible
    ? { ...selectedRun, question: selectedRun.question ?? active!.messages.slice(0, selectedRunIndex).findLast((message) => message.role === "user")?.text }
    : null;

  /** Keep the question visible beside one selected run without changing conversation state. */
  function openRunDetails(messageId: string, stage?: DisclosureStage) {
    setRunDetailsStage({ stage: stage ?? null });
    setHelp(false);
    setRunDetailsMessageId(messageId);
  }

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
    if (!operationsAvailable) return;
    try {
      const command = (await getOperatorCommands()).find((item) => item.command_id === commandId);
      if (!command) throw new Error(`Operations does not offer ${commandId}.`);
      if (command.confirmation && !window.confirm(command.confirmation)) return;
      await startOperatorJob(command.command_id);
      notify(t("{p0} started. Follow it under System › Operations.", { p0: command.label }), "success", "operations-run");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Command could not start."), "error", "operations-run");
    }
  }
  const historyEntries = [...navigationHistory.map(({ position, target }) => ({ position, target })), { position: navigationPosition.current, target: currentTarget() }, ...navigationForward.map(({ position, target }) => ({ position, target }))];
  const conversationTitles = Object.fromEntries(conversations.map((item) => [item.id, item.title]));
  function closeSidebar() {
    setSidebarOpen(false);
    sidebarToggle.current?.focus();
  }

  return (
    <main className={`service-shell ${sidebarOpen ? "" : "sidebar-collapsed"}${helpVisible ? " help-open" : ""}${runDetailsMessage ? " run-details-open" : ""}`}>
      {sidebarOpen && <button className="sidebar-backdrop" type="button" aria-label={t("Close navigation overlay")} onClick={closeSidebar} />}
      <aside id="service-navigation" className="sidebar" inert={!sidebarOpen} onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); closeSidebar(); } }}>
        <div className="brand"><ProductBrand /><button className="icon-button sidebar-close" type="button" aria-label={t("Close sidebar")} onClick={closeSidebar}><X size={18} /></button></div>
        <button className="new-review" data-tour="new-review" type="button" onClick={createReview}><SquarePen size={17} /><span>{t("New review")}</span></button>
        <p className="sidebar-label">{t("Recent reviews")}</p>
        <div className="conversation-list" data-tour="recent-reviews">
          {conversations.map((conversation) => (
            <div className="conversation-row" key={conversation.id}>
              <button type="button" aria-pressed={conversation.id === activeId && view === "review"} onClick={() => navigate({ view: "review", conversationId: conversation.id })}>
                <MessageSquare size={15} /><span>{conversation.title}</span>
              </button>
              <button className="delete-review" type="button" aria-label={t("Delete {p0}", { p0: conversation.title })} onClick={() => removeReview(conversation.id)}><Trash2 size={14} /></button>
            </div>
          ))}
        </div>
        {environment && <div className={`runtime-mode-badge ${environment}`} role="note" aria-label={modeLabel ?? undefined} title={t("Server environment: {p0}", { p0: modeLabel ?? "" })}>
          <strong>{environment.toUpperCase()}</strong><span>{t("MODE")}</span>
        </div>}
        <div className="sidebar-nav">
          <GuidesNavigation />
          <button data-tour="build" type="button" aria-pressed={view === "build"} onClick={() => navigate({ view: "build" })}><Hammer size={17} /><span>{t("Build")}</span>{buildNeedsAttention && <><i className="nav-dot" aria-hidden="true" /><span className="sr-only">{t(", needs attention")}</span></>}</button>
          <button data-tour="measure" type="button" aria-pressed={view === "measure"} onClick={() => navigate({ view: "measure" })}><FlaskConical size={17} /><span>{t("Measure")}</span></button>
          <button data-tour="system" className={`nav-secondary system-status-button ${healthBadge(runtimeHealth.kind)}`} type="button" aria-label={t("System · {p0}", { p0: t(healthLabel(runtimeHealth.kind)) })} aria-pressed={view === "system"} onClick={() => navigate({ view: "system", tab: "status" })}><Activity size={17} /><span>{t("System")}</span><span className="system-health"><i aria-hidden="true" />{t(healthLabel(runtimeHealth.kind))}</span></button>
          <button data-tour="settings" type="button" onClick={() => openSettings()}><Settings size={17} /><span>{t("Settings")}</span></button>
        </div>
        {localAllowed && activeSessionProfile.engine === "local" && (
          <div className="local-mode-badge" role="note">
            <TriangleAlert size={14} aria-hidden="true" />
            <span className="local-mode-label">{t("LOCAL MODEL")}{localModel ? t(" · {p0}", { p0: localModel }) : ""}{localIssue ? t(" · Unavailable") : ""}</span>
            <span className="local-mode-note">{t("Answers use the selected model server. Choose an engine and model above the conversation input. API health and model availability are checked separately.")}{" "}</span>
          </div>
        )}
        <CreatorSignature />
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="topbar-navigation">
            <button ref={sidebarToggle} className="icon-button" type="button" aria-label={t("Toggle sidebar")} aria-expanded={sidebarOpen} aria-controls="service-navigation" title={modeLabel ?? undefined} onClick={() => setSidebarOpen((value) => !value)}>{sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}</button>
            <WorkspaceHistory entries={historyEntries.map((entry) => ({ id: String(entry.position), label: navigationLabel(entry.target, conversationTitles, t) }))} currentIndex={navigationHistory.length} onBack={() => { const previous = navigationHistory.at(-1); if (previous) jumpNavigation(previous.position); }} onForward={() => { const next = navigationForward[0]; if (next) jumpNavigation(next.position); }} onJump={(index) => jumpNavigation(historyEntries[index].position)} />
          </div>
          <div className="topbar-status">{onPreview && adminBuild && environment === "dev" && <button className="button production-preview-trigger" type="button" aria-label={t("Production preview")} disabled={busy || modalOpen || tourOpen || previewBlocked} title={t(busy || modalOpen || tourOpen || previewBlocked ? "Finish the current request or close the dialog before previewing." : "On the deployed screen, settings are stored in this browser's localStorage")} onClick={() => { if (!busy && !modalOpen && !tourOpen && !previewBlocked) onPreview(); }}><Monitor size={16} aria-hidden="true" /><span>{t("Production preview")}</span></button>}<LanguageSwitch /><ThemeSwitch />{adminLive && (operatorJobs.board.active_count > 0 || operatorJobs.board.queued_count > 0) && <button className="job-health" type="button" onClick={() => navigate({ view: "build", tab: "jobs" })}>{operatorJobs.board.active_count}{t("running ·")}{" "}{operatorJobs.board.queued_count}{t("queued")}</button>}<button type="button" className="icon-button help-toggle" aria-label={t("Toggle help")} aria-pressed={helpOpen} onClick={() => setHelp(!helpOpen)}><CircleHelp size={18} /></button></div>
        </header>
        {sessionActive && (runtimeHealth.waiting || runtimeHealth.kind === "checking") && <div className="connection-status" role="status"><span>{t(runtimeHealth.waiting ? workPending ? "A job is in progress. Waiting for the API; retrying status checks." : "Connection check delayed. Retrying before declaring an outage." : "Checking API connection…")}</span><button className="button" type="button" disabled={runtimeHealth.checking} onClick={() => void runtimeHealth.check(true)}>{t("Retry connection")}</button></div>}
        <NotificationOutlet active={sessionActive} />

        <RetainedPanel active={view === "review"} className="review-workspace" workspace="review">
          <div className="messages" ref={messagesViewport} onScroll={(event) => { const element = event.currentTarget; followReview.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80; }}>
            <div className="messages-inner">
              {!active?.messages.length && (
                <div className="welcome">
                  <ProductBrand hero />
                  <p className="eyebrow">{t("Grounded by design")}</p>
                  <h1>{t("Review filings with verifiable evidence.")}</h1>
                  <p>{t("Ask across SEC 10-K and DART reports. Unsupported answers terminate as NOT_IN_DOCS.")}</p>
                  <ol className="first-review-path"><li><strong>01</strong><span>{t("Ask about a filing")}</span></li><li><strong>02</strong><span>{t("Open its original evidence")}</span></li><li><strong>03</strong><span>{t("Inspect execution and compare retrieval")}</span></li></ol>
                  <div className="welcome-links"><button className="button ghost" type="button" onClick={() => navigate({ view: "build", tab: "pipeline" })}>{t("Explore the implementation")}</button><a href={`/docreview-rag-agent/docs/${locale}/`}>{t("Read the walkthrough")}</a></div>
                  {readiness?.mode === "canned" && <p className="notice">{t("Demonstration data — no live provider calls.")}</p>}
                  {adminLive && readiness?.corpus?.documents === 0 ? (
                    <div className="next-step" data-tour="evidence-fallback">
                      <h2>{t("Corpus is empty")}</h2>
                      <p>{t("Download and ingest filings first.")}</p>
                      <div className="action-row"><button className="button primary" type="button" onClick={() => navigate({ view: "build", tab: "pipeline" })}>{t("Open Build")}</button></div>
                    </div>
                  ) : (
                    <div className="suggestions" data-tour="evidence-fallback">
                      <button type="button" onClick={() => setQuery("What drove NVIDIA data center revenue growth?")}>{t("NVIDIA growth drivers")}</button>
                      <button type="button" onClick={() => setQuery("삼성전자 메모리 사업의 주요 위험은 무엇인가요?")}>{t("Samsung memory risks")}</button>
                    </div>
                  )}
                </div>
              )}
              {active?.messages.map((message) => (
                <ReviewMessage
                  key={message.id}
                  message={message}
                  catalogMode={adminLive ? "live" : "published"}
                  latestEvidence={message.id === latestEvidenceId}
                  busy={busy || sendBlocked}
                  onStop={message.pending && activeReview?.conversationId === active?.id && activeReview.messageId === message.id ? () => reviewAbort.current?.abort() : undefined}
                  onSwitchScope={!busy ? () => { updateSessionProfile({ corpus_scope: "auto" }); setQuery(message.question ?? ""); } : undefined}
                  onMark={(chunkId, mode) => markEvidence(message.id, chunkId, mode)}
                  onUseSelected={() => void useSelectedEvidence(message)}
                  onOpenDetails={(stage) => openRunDetails(message.id, stage)}
                />
              ))}

            </div>
          </div>
          <div className="composer-wrap" data-tour="composer">
            {conversationTab && <ConversationSettings speed={localCpuSpeed} query={query} onManagePresets={() => { setConversationTab(null); navigate({ view: "measure", tab: "presets" }); }} key={activeId} tab={conversationTab} profile={activeSessionProfile} editable={adminLive} onValidityChange={setConversationInputsValid} onChange={updateSessionProfile} onTabChange={setConversationTab} onClose={() => setConversationTab(null)} />}
            <ComposerToolbar
              query={query}
              engineControls={localAllowed && <LocalEngineSettings profile={activeSessionProfile} readiness={runtimeHealth.readiness} onChange={updateSessionProfile} />}
              settingsOpen={conversationTab !== null}
              settingsTriggerRef={ragTrigger}
              profile={activeSessionProfile}
              onChange={updateSessionProfile}
              canUseCustom={adminBuild && permissions?.can_change_custom_retrieval === true}
              onLocked={() => notify(PROD_LOCKED_MESSAGE, "warning", "prod-locked")}
              onOpenSettings={() => openConversationSettings("filters")}
              onOpenCustom={() => { setConversationTab(null); navigate({ view: "measure", tab: "presets" }); }}
              readiness={readiness}
              live={adminLive}
              onOpenBuild={() => navigate({ view: "build", tab: "pipeline" })}
            />

            <label className="composer">
              <textarea data-help="review.composer" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); } }} placeholder={t("Ask a question about the filing corpus")} rows={1} />
              <button data-tour="send" data-help="review.send" type="button" aria-label={t("Send question")} disabled={busy || runtimeHealth.kind === "api_down" || runtimeHealth.kind === "checking" || sendBlocked || !query.trim()} onClick={() => void submit()}><Send size={17} /></button>
            </label>
            {localCpuSpeed !== null && !publicPreview && <SlowCpuNotice key={`${activeId}:${localModel}`} profile={activeSessionProfile} model={localModel ?? ""} speed={localCpuSpeed} onOpenLimits={() => openSettings("limits")} onOpenEvidence={() => openConversationSettings("evidence")} />}

            {settingsValidationError && <p role="alert" className="notice error">{t(settingsValidationError)} <button type="button" className="inline-link" onClick={() => openConversationSettings("retrieval")}>{t("Open settings")}</button></p>}
            {compatibilityIssue && <p className="notice error" role="alert">{t(compatibilityIssue)}</p>}
            {localIssue && <p className="helper" role="status">{t(localIssue)} <button className="inline-link" type="button" onClick={() => openSettings("local")}>{t("Open Local LLM settings")}</button></p>}
            {publicPreview ? <p id="production-preview-read-only" role="note">{t("Preview is read-only. Questions and server changes are disabled; your DEV conversation is preserved.")}</p> : banner
              ? <ComposerBanner banner={banner} onOpenBuild={() => navigate({ view: "build", tab: "pipeline", stage: banner.step })} onOpenAnswerModel={() => navigate({ view: "build", tab: "pipeline", stage: 6 })} />
              : <p>{t("Answers must cite retrieved filing evidence. Provider calls are rate- and cost-limited.")}</p>}
          </div>
        </RetainedPanel>

        <RetainedPanel active={view === "build"} className="retained-workspace" workspace="build"><BuildWorkspace
          focusStep={pendingStage}
          live={adminBuild && permissions?.can_build_snapshot === true}
          ready={runtimeHealth.kind === "healthy"}
          readiness={runtimeHealth.readiness}
          healthKind={runtimeHealth.kind}
          connectionPending={runtimeHealth.waiting}
          profile={resolvedRetrievalProfile(activeSessionProfile)}
          jobBoard={operatorJobs.board}
          jobsLoading={operatorJobs.loading}
          jobsStale={operatorJobs.stale}
          onRetryJob={(jobId) => void operatorJobs.retry(jobId)}
          onCancelJob={(jobId) => void operatorJobs.cancel(jobId)}
          onRefreshJobs={() => void operatorJobs.refresh(true)}
          onRecheck={() => void runtimeHealth.check()}
          operationsAvailable={operationsAvailable}
          onRunOperation={(commandId) => void runOperation(commandId)}
          tab={buildTab}
          onTabChange={(tab) => navigate({ view: "build", tab })}
          onNavigate={navigate}
          onOpenLocalSettings={() => openSettings("local")}
        /></RetainedPanel>
        <RetainedPanel active={view === "measure"} className="retained-workspace" workspace="measure"><MeasureWorkspace
          capabilities={helpCapabilities}
          publicPreview={publicPreview}
          active={sessionActive && view === "measure"}
          readiness={runtimeHealth.readiness}
          onOpenPreparation={(stage) => navigate({ view: "build", tab: "pipeline", stage })}
          onDirtyChange={setUnsavedGolden}
          environment={permissions?.environment}
          live={adminBuild && permissions?.can_run_evaluation === true}
          ready={runtimeHealth.kind === "healthy"}
          profile={resolvedRetrievalProfile(activeSessionProfile)}
          onProfileChange={updateLabProfile}
          onApplyProfile={applyProfile}
          onApplySnapshot={applySnapshot}
          jobBoard={operatorJobs.board}
          onRefreshJobs={() => void operatorJobs.refresh(true)}
          tab={measureTab}
          onTabChange={(tab) => navigate({ view: "measure", tab }, true)}
          focusResultId={measureResultId}
          onResultSelectionChange={setMeasureResultId}
          helpTarget={pendingHelpTarget}
        /></RetainedPanel>
        <RetainedPanel active={view === "system"} className="retained-workspace" workspace="system"><SystemWorkspace
          onOpenLimitDefaults={() => openSettings("prompt")}
          live={adminLive}
          ready={runtimeHealth.kind === "healthy"}
          readiness={runtimeHealth.readiness}
          localModel={localModel}
          localAllowed={localAllowed}
          checking={runtimeHealth.checking}
          onRefresh={() => void runtimeHealth.check()}
          operationsAvailable={operationsAvailable}
          tab={systemTab}
          onTabChange={(tab) => navigate({ view: "system", tab })}
        /></RetainedPanel>
      </section>
      <BrowserStorageSupport enabled={!publicPreview && environment === "prod" && productionBrowserStorageEnabled()} />
      <SettingsModal storageImportDisabled={busy} open={sessionActive && settingsOpen} initialCategory={settingsCategory} profile={active?.profile ?? profile} capabilities={permissions} readiness={readiness} onLocalConnectionChanged={runtimeHealth.refreshLocal} onChange={updateSessionProfile} onClose={() => setSettingsOpen(false)} onOpenTour={() => { setSettingsOpen(false); openTour(); }} onClear={() => { clearReviews(); notify(t("Local conversations cleared."), "success"); }} />
      {sessionActive && tourOpen && <Onboarding onClose={closeTour} includeOperations={operationsAvailable} onStepChange={openTourStep} location={location} />}
      <RunDetailsPanel stageRequest={runDetailsStage} draftProfile={activeSessionProfile} draftQuery={query} message={runDetailsMessage} onClose={() => setRunDetailsMessageId(null)} onOpenFix={openSettings} />

      <HelpOverlay screen={helpScreen(view, currentTab)} open={helpVisible} keyboard={!modalOpen} capabilities={helpCapabilities} publicPreview={publicPreview} onClose={() => setHelp(false)} location={location} onNavigateTopic={navigateHelpTopic} />
      <ServiceHealthModal
        kind={runtimeHealth.kind}
        visible={sessionActive && runtimeHealth.modalVisible}
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
  catalogMode?: "live" | "published";
  onStop?: () => void;
  onSwitchScope?: () => void;
  onOpenDetails?: (stage?: DisclosureStage) => void;
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

function ReviewMessage({ message, catalogMode, latestEvidence, busy, onStop, onSwitchScope, onMark, onUseSelected, onOpenDetails }: ReviewMessageProps) {
  const { t, locale } = useI18n();
  const [summaryOpen, setSummaryOpen] = useState(Boolean(message.pending));
  const pill = message.role === "assistant" ? verdictPill(message) : null;
  const notInDocs = message.evidenceLabel === "Related evidence — not direct support";
  const article = useRef<HTMLElement>(null);
  /** Reveal only this message's evidence list when its report stage links to candidates. */
  function showEvidence() {
    const evidence = article.current?.querySelector<HTMLDetailsElement>("details.evidence");
    if (!evidence) return;
    evidence.open = true;
    evidence.querySelector<HTMLElement>("summary")?.focus({ preventScroll: true });
    evidence.scrollIntoView?.({ block: "nearest" });
  }
  return (
    <article ref={article} className={`message ${message.role}${message.pending ? " pending" : ""}`} data-message-id={message.id} aria-busy={message.pending || undefined}>
      <div className="message-role">{message.role === "user" ? t("You") : t("DocReview RAG")}</div>
      <div className="message-body">
        {pill && <span className={`verdict ${pill.className}`}>{t(pill.text)}</span>}
        {message.execution?.pathDecision && <PathDecisionBadge decision={message.execution.pathDecision} />}
        {message.role === "assistant" ? (message.text ? <MarkdownMessage>{message.text}</MarkdownMessage> : null) : <p>{message.text}</p>}
        {message.execution && <><details className="review-execution-summary" open={summaryOpen} onToggle={(event) => setSummaryOpen(event.currentTarget.open)}><summary>{t("Execution summary")}</summary><ReviewProgressSteps catalogMode={catalogMode} state={message.execution} performance={message.performance} finalLabel={message.evidenceLabel === "Cited evidence" ? "Supported" : message.evidenceLabel === "Related evidence — not direct support" ? "Not in documents" : message.evidenceLabel === "Retrieved candidates — answer not generated" ? "Answer not generated" : message.execution.pathDecision?.intent === "casual_chat" ? "Conversation reply" : undefined} onSwitchScope={onSwitchScope} onOpenDetails={onOpenDetails} onShowEvidence={message.evidence?.length ? showEvidence : undefined} />{message.pending && onStop && <button className="button ghost" type="button" onClick={onStop}>{t("Stop request")}</button>}</details></>}
        {message.evidence?.length ? (
          <>
            {notInDocs && <p className="notice">{t("Related evidence is shown below, but it is not direct support.")}</p>}
            <details className="evidence" data-help={latestEvidence ? "review.evidence" : undefined}>
              <summary data-tour="evidence-toggle">{t(message.evidenceLabel === "Cited evidence" ? "Retrieved evidence candidates" : message.evidenceLabel ?? "Retrieved candidates")} · {message.evidence.length}</summary>
              <EvidenceCandidates key={message.id} message={message} busy={busy} onMark={onMark} onUseSelected={onUseSelected} />
            </details>
          </>
        ) : null}
        {message.role === "assistant" && (message.execution || message.performance || message.diagnostics?.length || message.trace) && onOpenDetails && <button className="button ghost" type="button" data-run-details-open data-help="review.run-trace" onClick={() => onOpenDetails()}>{t("Run details")}</button>}
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
  if (failure) return failureMessage(failure);
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

const RUN_FACTS: ReadonlyArray<readonly [string, string]> = [
  ["status", "Status"],
  ["run_id", "Run id"],
  ["iterations", "Iterations"],
  ["total_requests", "Provider requests"],
  ["total_input_tokens", "Input tokens"],
  ["total_output_tokens", "Output tokens"],
  ["total_estimated_cost_usd", "Estimated cost"],
  ["total_time_seconds", "Elapsed seconds"],
];

/** Failure fields worth naming, keyed by the shape that carries them. */
const FAILURE_FACTS: ReadonlyArray<readonly [string, string]> = [
  ["code", "Failure"],
  ["resource", "Exhausted resource"],
  ["limit", "Limit"],
  ["observed", "Observed"],
  ["blocked_node", "Blocked at"],
  ["status", "Provider status"],
  ["node", "Node"],
  ["attempts", "Attempts"],
  ["error_type", "Error type"],
  ["message", "Message"],
];

/**
 * Flatten one terminal response into labelled rows.
 *
 * The run identifier is included deliberately: it is the only handle a reader has for
 * correlating a failure with `/runs/{id}` and its step traces, and the browser was
 * discarding it. Node paths are joined rather than dropped so the route a run took
 * before failing is visible.
 */
/** The settings destination for a terminal failure, when the failure names one. */
function terminalFailureFix(payload: Record<string, unknown>): ChatMessage["failureFix"] {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const failure = root.failure as Record<string, unknown> | null;
  return failure ? failureReport(failure).fix : undefined;
}

function runDiagnostics(payload: Record<string, unknown>): Array<{ label: string; value: string }> {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const rows: Array<{ label: string; value: string }> = [];
  for (const [key, label] of RUN_FACTS) {
    if (root[key] !== undefined && root[key] !== null) rows.push({ label, value: String(root[key]) });
  }
  if (Array.isArray(root.node_path) && root.node_path.length) {
    rows.push({ label: "Node path", value: root.node_path.join(" → ") });
  }
  const failure = root.failure as Record<string, unknown> | null;
  if (failure) {
    for (const [key, label] of FAILURE_FACTS) {
      if (failure[key] !== undefined && failure[key] !== null) rows.push({ label, value: String(failure[key]) });
    }
    if (Array.isArray(failure.details) && failure.details.length) {
      rows.push({ label: "Details", value: failure.details.map(String).join(" · ") });
    }
  }
  return rows;
}

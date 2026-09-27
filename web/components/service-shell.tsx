"use client";
import { useSavedPresets } from "@/lib/use-saved-presets";
import { applyProdPolicy, newProdProfile } from "@/lib/prod-profile";
import { usePublishedCorpus } from "@/lib/use-published-corpus";
import { effectivePublishedProfile, publicTargetIds, pinPublicTargets, createPublicTargets } from "@/lib/published-scope";
import { useConfirmation } from "./use-confirmation";
import { NotificationSignals } from "@/components/notification-signals";
import type { NotificationTarget } from "@/lib/notification-registry";
import { notificationErrorDetail, notificationErrorMessage } from "@/lib/notification-registry";
import { publicScopeFailure } from "@/lib/scope-failure";
import { BrowserStorageSupport } from "@/components/browser-storage";
import { applyFreshStartReset, FRESH_START_RECEIPT_KEY, browserStorage, configureBrowserStorage, loadDefaultProfile, loadActiveConversation, saveActiveConversation, subscribeStorageRestored, productionBrowserStorageEnabled } from "@/lib/storage";
import { useI18n } from "@/lib/i18n";


import { conversationSettingsError } from "@/lib/saved-presets";
import { configurePresetStorage } from "@/lib/preset-storage";
import { ProfileCompatibilityNotice } from "./profile-compatibility-notice";
import { SlowCpuNotice } from "./slow-cpu-notice";
import type { DisclosureStage } from "@/components/review-stage-details";
import { RunDetailsPanel } from "@/components/run-details-panel";
import { localCpuWarning, localModelIssue, selectedLocalModel } from "@/lib/local-models";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { RetainedPanel } from "@/components/retained-panel";
import "./workspace-navigation.css";
import { navigationLabel, type NavigationTarget } from "@/lib/navigation";
import { useWorkspaceNavigation } from "./use-workspace-navigation";

import { BuildWorkspace } from "@/components/build-workspace";
import { ConversationSettings, type ConversationSettingsTab } from "@/components/conversation-settings";
import { LocalEngineSettings } from "@/components/local-engine-settings";
import { ComposerBanner, ComposerToolbar, composerBanner } from "@/components/composer-toolbar";
import { HelpOverlay } from "@/components/help-overlay";
import { QuestionComposer } from "@/components/question-composer";
import { restoreInterruptedConversations } from "@/components/interrupted-reviews";
import { MeasureWorkspace, type MeasureTab } from "@/components/measure-workspace";
import { Onboarding, type TourView } from "@/components/onboarding";
import { ReviewMessage } from "@/components/review-message";
import { ReviewWelcome } from "@/components/review-welcome";
import { ServiceHealthModal } from "@/components/service-health-modal";
import { ServiceSidebar } from "@/components/service-sidebar";
import { ServiceTopbar } from "@/components/service-topbar";
import { SettingsModal, type SettingsCategory } from "@/components/settings-modal";
import { DevPromotionProvider } from "@/components/dev-mode-bubble";
import { DEV_ONLY_REASONS } from "@/lib/dev-mode";
import { SystemWorkspace } from "@/components/system-workspace";
import { NotificationProvider, useNotifications } from "@/components/notifications";
import { getCapabilities } from "@/lib/api";
import { LOCAL_ENGINE_VISIBLE } from "@/lib/build-mode";
import { profileCompatibilityIssue } from "@/lib/profile-compatibility";
import { helpScreen } from "@/lib/help-content";
import { helpTopicScreen } from "@/lib/help-search";
import { getOperatorCommands, operatorAvailable, startOperatorJob } from "@/lib/operator-api";
import { loadConversations, loadHelpOpen, newConversation, ONBOARDING_KEY, saveConversations, saveHelpOpen } from "@/lib/storage";
import type { Capabilities, ChatMessage, Conversation, PublishedSnapshot, RetrievalProfile, ReviewSessionDraft } from "@/lib/types";
import { DEFAULT_SESSION_PROFILE, resolvedRetrievalProfile } from "@/lib/types";
import { useRuntimeHealth } from "@/lib/use-runtime-health";
import { useOperatorJobs } from "@/lib/use-operator-jobs";
import { useConversationDraft } from "./use-conversation-draft";
import { useHelpShortcut } from "./use-help-shortcut";
import { useHelpTargetReveal } from "./use-help-target-reveal";
import { usePublicExecutionPolicy } from "./use-public-execution-policy";
import { useBrowserRequestLimits } from "./use-browser-request-limits";
import { BrowserRequestStatus } from "./browser-request-status";
import { useReviewRequests } from "./use-review-requests";

/** Render the shared interface with the running server's DEV or PROD permissions. */
export function ServiceShell() {
  return <div><div><NotificationProvider><ServiceSession /></NotificationProvider></div></div>;
}

function ServiceSession() {
  const { builtins } = useSavedPresets();
  const { confirm, confirmationDialog } = useConfirmation();
  const { t } = useI18n();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const adminBuild = process.env.NEXT_PUBLIC_ADMIN_MODE === "live";
  const navigation = useWorkspaceNavigation(adminBuild, conversations.map(conversation => conversation.id));
  const { view, activeId, buildTab, buildJobId, measureTab, measureResultId, systemTab, conversationTab, pendingStage,
    navigate, initialize: initializeNavigation, routeFirstRun, deferLeave, setActiveId, setConversationTab, setMeasureResultId,
    setUnsavedGolden, registerGoldenLeave, historyEntries, historyIndex, jumpNavigation } = navigation;
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const sidebarToggle = useRef<HTMLButtonElement>(null);
  const [tourOpen, setTourOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const composerInput = useRef<HTMLTextAreaElement>(null);
  const [runDetailsMessageId, setRunDetailsMessageId] = useState<string | null>(null);
  const [runDetailsStage, setRunDetailsStage] = useState<{ stage: DisclosureStage | null } | undefined>();
  const [pendingHelpTarget, setPendingHelpTarget] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [conversationInputsValid, setConversationInputsValid] = useState(true);
  const ragTrigger = useRef<HTMLButtonElement>(null);
  const [settingsCategory, setSettingsCategory] = useState<SettingsCategory | undefined>(undefined);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const messagesViewport = useRef<HTMLDivElement>(null);
  const followReview = useRef(true);
  const lastReview = useRef<{ conversationId: string; messageId: string } | null>(null);
  const lastScrolledMessage = useRef<ChatMessage | null>(null);
  /** `ReleaseLimits.daily_cost_reset_at_utc` captured after a `daily_cost_limit` error; cleared by the next successful review. */
  const [resetAt, setResetAt] = useState<string | null>(null);
  const reviewAbort = useRef<AbortController | null>(null);
  useEffect(() => { if (view !== "review") setRunDetailsMessageId(null); }, [view]);
  const runtimeHealth = useRuntimeHealth();
  const permissions = capabilities && (!runtimeHealth.readiness?.environment || capabilities.environment === runtimeHealth.readiness.environment) ? capabilities : null;
  const environment = permissions?.environment ?? runtimeHealth.readiness?.environment;
  const modeLabel = environment ? `${environment.toUpperCase()} MODE` : null;
  const adminLive = adminBuild && permissions?.can_edit_prompt_policy === true;
  const localAllowed = LOCAL_ENGINE_VISIBLE && permissions?.environment === "dev" && permissions.can_configure_local_llm;
  useEffect(() => {
    configurePresetStorage(permissions);
    return () => configurePresetStorage(null);
  }, [permissions?.environment, permissions?.can_change_custom_retrieval]);
  const operationsAvailable = adminBuild && permissions?.environment === "dev" && permissions.can_use_operations && operatorAvailable();
  const helpCapabilities = useMemo(() => permissions ? { ...permissions, can_use_operations: Boolean(operationsAvailable), can_configure_local_llm: Boolean(localAllowed), can_change_custom_retrieval: Boolean(adminLive && permissions.can_change_custom_retrieval), can_edit_run_limits: Boolean(adminLive && permissions.can_edit_run_limits) } : null, [permissions, operationsAvailable, localAllowed, adminLive]);
  const initialized = useRef(false);
  const tourInitialized = useRef(false);
  const { notify } = useNotifications();
  const operatorJobs = useOperatorJobs(adminBuild && permissions?.can_build_snapshot === true, runtimeHealth.check);
  const workPending = operatorJobs.board.active_count > 0 || operatorJobs.board.queued_count > 0;



  useEffect(() => {
    if (tourInitialized.current || !environment || (environment === "prod" && !productionBrowserStorageEnabled())) return;
    tourInitialized.current = true;
    let savedTour: string | null = null;
    try { savedTour = browserStorage().getItem(ONBOARDING_KEY); } catch { /* PROD recovery starts after capabilities identify the environment. */ }
    const shouldOpenTour = savedTour !== "done";
    setTourOpen(shouldOpenTour);
    // The tour owns the screen on a first visit; a persisted open Help state waits until it is dismissed.
    setHelpOpen(!shouldOpenTour && loadHelpOpen());
    if (window.innerWidth <= 560) setSidebarOpen(shouldOpenTour);
  }, [environment, capabilities]);

  useEffect(() => () => reviewAbort.current?.abort(), []);
  useEffect(() => {
    function freshStart(event: StorageEvent) {
      if (event.storageArea !== window.localStorage || event.key !== FRESH_START_RECEIPT_KEY || !event.newValue) return;
      if (applyFreshStartReset(event.newValue)) {
        initialized.current = false;
        reviewAbort.current?.abort();
        window.location.replace("/docreview-rag/");
      }
    }
    window.addEventListener("storage", freshStart);
    return () => window.removeEventListener("storage", freshStart);
  }, []);
  useEffect(() => {
    let cancelled = false;
    void getCapabilities().then((value) => {
      if (cancelled) return;
      if (!["dev", "prod"].includes(value.environment)) { setCapabilities(null); return; }
      configureBrowserStorage(value.environment);
      if (value.environment === "dev" && applyFreshStartReset(value.browser_reset_id)) {
        initialized.current = false;
        reviewAbort.current?.abort();
        window.location.replace("/docreview-rag/");
        return;
      }
      if (!initialized.current) {
        initialized.current = true;
        const saved = loadConversations();
        const restored = restoreInterruptedConversations(saved);
        const initial = restored.length ? restored : [newConversation(adminBuild && value.environment === "dev" && value.can_edit_prompt_policy ? undefined : newProdProfile())];
        if (!restored.length && value.environment === "prod") {
          initial[0].publishedTargets = ["AMD", "NVDA"].flatMap(issuer => [2019, 2020, 2021, 2022, 2023, 2024].map(year => ({ registry: "sec" as const, issuer, year })));
          saveConversations(initial);
        }
        setConversations(saved.some((conversation) => conversation.messages.some((message) => message.pending)) ? saveConversations(initial) : initial);
        const remembered = initial.find(item => item.id === loadActiveConversation()) ?? initial[0];
        initializeNavigation(initial.map((item) => item.id), remembered.id);
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
    }).catch(() => {
      if (cancelled) return;
      // A public bundle still needs an environment for the tour and help; assume the deployed shape until the server answers.
      const fallback = runtimeHealth.readiness?.environment;
      setCapabilities(!adminBuild && (fallback === "prod" || fallback === "dev") ? { environment: fallback, browser_reset_id: null, can_configure_local_llm: false, can_edit_prompt_policy: false, can_edit_run_limits: false, can_edit_golden: false, can_build_snapshot: false, can_run_evaluation: false, can_change_custom_retrieval: false, can_query_snapshot: false, can_use_operations: false, can_compare_published_snapshots: true } : null);
    });
    return () => { cancelled = true; };
  }, [adminBuild, runtimeHealth.checkedAt, runtimeHealth.readiness?.environment, initializeNavigation]);



  useEffect(() => { if (initialized.current) saveActiveConversation(activeId); }, [activeId]);
  useEffect(() => subscribeStorageRestored(() => {
    if (!initialized.current || !productionBrowserStorageEnabled()) return;
    const loaded = restoreInterruptedConversations(loadConversations());
    const next = loaded.length ? loaded : [newConversation(loadDefaultProfile())];
    const selected = next.find(item => item.id === loadActiveConversation()) ?? next[0];
    setConversations(next); setActiveId(selected.id);
  }), []);

  const active = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId) ?? conversations[0],
    [activeId, conversations],
  );
  const { query, setQuery } = useConversationDraft(active, conversations, setConversations);
  useLayoutEffect(() => {
    const target = lastReview.current;
    if (view !== "review" || !target || target.conversationId !== active?.id) return;
    const message = active.messages.find((item) => item.id === target.messageId);
    if (!message || lastScrolledMessage.current === message) return;
    lastScrolledMessage.current = message;
    const element = messagesViewport.current;
    if (element && followReview.current) element.scrollTop = element.scrollHeight;
  }, [active?.messages, active?.id, view]);

  const { policy: publicPolicy, failed: publicPolicyFailed, retry: retryPublicPolicy } = usePublicExecutionPolicy(adminLive, permissions);
  const browserAllowance = useBrowserRequestLimits(!adminLive);

  const storedSessionProfile = active?.profile ?? DEFAULT_SESSION_PROFILE;
  const publicCorpus = usePublishedCorpus(!adminLive);
  const publicIds = publicTargetIds(publicCorpus.documents, active?.publishedTargets);
  const activeSessionProfile = adminLive ? storedSessionProfile : effectivePublishedProfile(applyProdPolicy(storedSessionProfile, publicPolicy ?? newProdProfile().prompt_policy), publicCorpus.documents, publicIds);
  useEffect(() => {
    if (adminLive || publicCorpus.status !== "ready" || !active?.publishedTargets) return;
    const pinned = pinPublicTargets(publicCorpus.documents, active.publishedTargets);
    if (pinned === active.publishedTargets) return;
    setConversations((current) => saveConversations(current.map((conversation) => conversation.id === active.id && conversation.publishedTargets === active.publishedTargets ? { ...conversation, publishedTargets: pinned } : conversation)));
  }, [adminLive, publicCorpus.status, publicCorpus.documents, active?.id, active?.publishedTargets]);
  const publicScopeBlocked = !adminLive && (publicCorpus.status !== "ready" || activeSessionProfile.doc_ids.length === 0);
  const unavailableScope = !adminLive && publicCorpus.status === "ready" && publicIds?.some((id) => !publicCorpus.documents.some((doc) => doc.doc_id === id));

  /** Update only this conversation's public selection, preserving messages and DEV drafts. */
  function changePublishedScope(ids: string[], targets?: import("@/lib/types").PublicTarget[]) {
    const targetId = active?.id;
    if (!targetId) return;
    const reset = { doc_ids: [], registries: [], issuers: [], fiscal_years: [] };
    setConversations((current) => saveConversations(current.map((conversation) => conversation.id === targetId
      ? { ...conversation, publishedTargets: createPublicTargets(publicCorpus.documents, targets ?? publicCorpus.documents.filter((doc) => ids.includes(doc.doc_id)).map((doc) => ({ registry: doc.registry as "sec" | "dart", issuer: doc.issuer, year: doc.fiscal_year }))), profile: { ...conversation.profile, ...reset }, updatedAt: new Date().toISOString() }
      : conversation)));
  }
  /** Keep pipeline experiments separate from the committed search scope. */
  function updatePipelineDraft(targets?: import("@/lib/types").PublicTarget[], progress?: { stage: string; checked: string[] }) {
    if (!active) return;
    setConversations(current => saveConversations(current.map(conversation => conversation.id !== active.id ? conversation : {
      ...conversation,
      pipelineDraft: {
        targets: targets ?? conversation.pipelineDraft?.targets ?? conversation.publishedTargets ?? createPublicTargets(publicCorpus.documents, publicCorpus.documents.filter(doc => publicIds?.includes(doc.doc_id) ?? true).map(doc => ({ registry: doc.registry as "sec" | "dart", issuer: doc.issuer, year: doc.fiscal_year }))),
        candidates: [...new Map([...(conversation.pipelineDraft?.candidates ?? conversation.pipelineDraft?.targets ?? conversation.publishedTargets ?? []), ...(targets ?? [])].map(target => [`${target.registry}:${target.issuer}:${target.year}`, target])).values()],
        stage: targets ? conversation.pipelineDraft?.stage ?? "filings" : progress?.stage ?? "filings",
        checked: targets ? (conversation.pipelineDraft?.checked ?? []).filter(step => step !== "index" && (step !== "filings" || conversation.pipelineDraft?.stage === "index")) : progress?.checked ?? [],
      },
    })));
  }

  const latestEvidenceId = active?.messages.filter((message) => message.evidence?.length).at(-1)?.id ?? null;
  const banner = composerBanner({ builtins, readiness: runtimeHealth.readiness, live: adminLive, profile: activeSessionProfile, resetAt, jobs: operatorJobs.board.jobs });
  const compatibilityIssue = adminLive ? profileCompatibilityIssue(activeSessionProfile, permissions) : null;
  const localIssue = localAllowed ? localModelIssue(activeSessionProfile, runtimeHealth.readiness) : null;
  const localModel = selectedLocalModel(activeSessionProfile, runtimeHealth.readiness?.review_engines?.local);
  const localCpuSpeed = localAllowed && !localIssue && !compatibilityIssue ? localCpuWarning(activeSessionProfile, runtimeHealth.readiness?.review_engines?.local) : null;
  const settingsValidationError = conversationSettingsError(activeSessionProfile, builtins);
  const sendBlocked = (!adminLive && (!publicPolicy || (browserAllowance?.retry_after_seconds ?? 0) > 0)) || publicScopeBlocked || settingsValidationError !== null || !conversationInputsValid || banner?.kind === "updating" || banner?.kind === "empty" || banner?.kind === "preparation" || localIssue !== null || compatibilityIssue !== null;
  const { busy, activeReview, submit, reviewSelectedEvidence, markEvidence } = useReviewRequests({
    active, activeId, sessionProfile: activeSessionProfile, localModel, sendBlocked, developer: adminLive, view, query, setQuery,
    setConversations, reviewAbort, onReviewStarted: (target) => { lastReview.current = target; followReview.current = true; },
    setDailyBudgetResetAt: setResetAt, checkRuntimeHealth: runtimeHealth.check,
  });

  useEffect(() => {
    if (!localAllowed || compatibilityIssue || !active || activeSessionProfile.local_model || !localModel) return;
    const targetId = active.id;
    setConversations((current) => saveConversations(current.map((conversation) => {
      if (conversation.id !== targetId || conversation.profile.local_model) return conversation;
      return { ...conversation, profile: { ...conversation.profile, local_model: localModel } };
    })));
  }, [active?.id, activeSessionProfile.engine, activeSessionProfile.local_model, localModel, localAllowed, compatibilityIssue]);

  function persist(next: Conversation[]) {
    setConversations(saveConversations(next));
  }

  function openConversationSettings(tab: ConversationSettingsTab) {
    if (!navigate({ view: "review" })) return;
    setSettingsOpen(false);
    setConversationTab(tab);
  }

  function navigateHelpTopic(id: string) {
    if (!adminLive && (id === "review.evidence-policy" || id === "review.run-limits" || id.startsWith("review.retrieval"))) {
      notify(t(DEV_ONLY_REASONS.settings), "warning", "help-locked", undefined, { event: "help-locked-warning" });
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

  useHelpTargetReveal(pendingHelpTarget, () => setPendingHelpTarget(null), `${view}/${buildTab}/${measureTab}/${systemTab}/${conversationTab}`);

  /** Keep settings callbacks and guarded workspace history as the only notification destinations. */
  function openNotification(target: NotificationTarget) {
    if (target.view === "settings") {
      if (!adminLive && (target.category === "local" || target.category === "limits")) return navigate({ view: "system", tab: "status" });
      openSettings(target.category);return;
    }
    if (target.view === "review" && target.conversationId && !conversations.some(conversation => conversation.id === target.conversationId)) { notify(t("This conversation no longer exists in this browser."), "info", "notification-target", undefined, { event: "notification-target-unavailable" });return; }
    navigate(target);
  }

  /** Route existing failure actions through the history-aware workspace navigator. */
  function openFailureFix(category: NonNullable<ChatMessage["failureFix"]>["category"]) {
    if (category === "documents" || category === "jobs") return navigate({ view: "build", tab: category });
    openSettings(category);
  }

  function openSettings(category?: SettingsCategory | "runtime") {
    if (category === "limits") {
      if (adminLive) { setSettingsCategory("limits"); setSettingsOpen(true); return; }
      return navigate({ view: "system", tab: "status" });
    }
    if (category === "runtime") return navigate({ view: "system", tab: "status" });
    setSettingsCategory(category);
    setSettingsOpen(true);
  }

  function createReview(confirmed = false) {
    if (!confirmed && deferLeave(() => createReview(true))) return;
    const reusable = [active, ...conversations].find(item => item && item.messages.length === 0 && !profileCompatibilityIssue(item.profile, permissions));
    const conversation = reusable ?? newConversation(adminLive && permissions?.environment === "dev" ? undefined : newProdProfile(publicPolicy ?? undefined));
    if (reusable && activeId === reusable.id && view === "review") return;
    if (!reusable) persist([conversation, ...conversations]);
    navigate({ view: "review", conversationId: conversation.id }, { confirmed: true });
  }

  function removeReview(id: string) {
    if (activeReview?.conversationId === id) reviewAbort.current?.abort();
    const remaining = conversations.filter((conversation) => conversation.id !== id);
    const next = remaining.length ? remaining : [newConversation(adminLive && permissions?.environment === "dev" ? undefined : newProdProfile(publicPolicy ?? undefined))];
    persist(next);
    if (activeId === id) setActiveId(next[0].id);
  }

  function clearReviews() {
    reviewAbort.current?.abort();
    const conversation = newConversation(adminLive && permissions?.environment === "dev" ? undefined : newProdProfile(publicPolicy ?? undefined));
    persist([conversation]);
    setActiveId(conversation.id);
  }

  function applyProfile(nextProfile: RetrievalProfile, source?: string) {
    const [suite] = source?.split(":") ?? [];
    const corpusScope = suite?.startsWith("dart") ? "dart" : suite?.startsWith("sec") ? "sec" : storedSessionProfile.corpus_scope;
    const languages = suite?.endsWith("-ko") ? ["ko" as const] : suite?.endsWith("-en") ? ["en" as const] : storedSessionProfile.languages;
    const sessionProfile: ReviewSessionDraft = {
      ...storedSessionProfile,
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
    if (!active) return;
    const targetId = active.id;
    const dimensionsChanged = !adminLive && ["registries", "issuers", "fiscal_years", "doc_ids"].some((key) => key in update);
    const selection = dimensionsChanged ? effectivePublishedProfile({ ...storedSessionProfile, ...update }, publicCorpus.documents, undefined).doc_ids : undefined;
    setConversations((current) => saveConversations(current.map((conversation) =>
      conversation.id === targetId
        ? { ...conversation, ...(dimensionsChanged ? { publishedTargets: createPublicTargets(publicCorpus.documents, publicCorpus.documents.filter((doc) => selection?.includes(doc.doc_id)).map((doc) => ({ registry: doc.registry as "sec" | "dart", issuer: doc.issuer, year: doc.fiscal_year }))) } : {}), updatedAt: new Date().toISOString(), profile: { ...conversation.profile, ...update } }
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
      : resolvedRetrievalProfile(storedSessionProfile, builtins);
    const next = {
      ...storedSessionProfile,
      snapshot_id: snapshot.snapshot_id,
      applied_from_evaluation: `snapshot:${snapshot.snapshot_id}`,
      retrieval_preset: "custom" as const,
      custom_retrieval: retrieval,
    };
    updateSessionProfile(next);
    navigate({ view: "review" });
    notify(t("Snapshot {p0} applied to this review.", { p0: snapshot.label }), "success", "snapshot-review", undefined, { event: "snapshot-review-notice", target: { view: "review", conversationId: activeId } });
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

  const modalOpen = settingsOpen || runtimeHealth.modalVisible || (view === "review" && conversationTab !== null);
  useHelpShortcut({ helpOpen, tourOpen, modalOpen, setHelp });
  const currentTab = view === "build" ? buildTab : view === "measure" ? measureTab : view === "system" ? systemTab : "";
  const location = `${view}/${buildTab}/${measureTab}/${systemTab}`;
  /** The workspace reserves room for the panel only while it is actually on screen. */
  const helpVisible = helpOpen && !tourOpen;
  const selectedRunIndex = active?.messages.findIndex((message) => message.id === runDetailsMessageId) ?? -1;
  const selectedRun = selectedRunIndex >= 0 ? active!.messages[selectedRunIndex] : null;
  const runDetailsMessage = selectedRun && view === "review" && !tourOpen && !helpVisible
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
    if (!adminLive || readiness === null || !conversations.length) return;
    routeFirstRun(readiness.corpus.documents === 0 && conversations.every((conversation) => !conversation.messages.length));
  }, [adminLive, readiness, conversations, routeFirstRun]);

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
      if (command.confirmation && !await confirm(command.confirmation)) return;
      await startOperatorJob(command.command_id);
      notify(t("{p0} started. Follow it under System › Operations.", { p0: command.label }), "success", "operations-run", undefined, { event: "operations-run-notice" });
    } catch (reason) {
      notify(reason instanceof Error ? notificationErrorMessage(reason) : t("Command could not start."), "error", "operations-run", undefined, { event: "operations-run-error", detail: notificationErrorDetail(reason) });
    }
  }
  const conversationTitles = Object.fromEntries(conversations.map((item) => [item.id, item.messages.length > 0 ? item.title : t("New chat")]));
  function closeSidebar() {
    setSidebarOpen(false);
    sidebarToggle.current?.focus();
  }

  return (
    <DevPromotionProvider promote={!adminLive}>
    <main className={`service-shell ${sidebarOpen ? "" : "sidebar-collapsed"}${helpVisible ? " help-open" : ""}${runDetailsMessage ? " run-details-open" : ""}`}>{confirmationDialog}
      <ServiceSidebar
        open={sidebarOpen}
        onClose={closeSidebar}
        view={view}
        newChatActive={view === "review" && !!active && active.messages.length === 0}
        onNewChat={() => createReview()}
        conversations={conversations}
        activeConversationId={activeId}
        conversationTitles={conversationTitles}
        onDeleteConversation={removeReview}
        environment={environment}
        modeLabel={modeLabel}
        buildNeedsAttention={buildNeedsAttention}
        healthKind={runtimeHealth.kind}
        showLocalModel={localAllowed && activeSessionProfile.engine === "local"}
        localModel={localModel}
        localModelUnavailable={Boolean(localIssue)}
        onNavigate={(target) => navigate(target)}
        onOpenSettings={() => openSettings()}
        onOpenAbout={() => openSettings("about")}
      />

      <section className="workspace">
        <ServiceTopbar
          sidebarToggleRef={sidebarToggle}
          sidebarOpen={sidebarOpen}
          onToggleSidebar={() => setSidebarOpen((value) => !value)}
          modeLabel={modeLabel}
          historyEntries={historyEntries.map((entry) => ({ id: String(entry.position), label: navigationLabel(entry.target, conversationTitles, t) }))}
          historyIndex={historyIndex}
          onHistoryBack={() => { const previous = historyEntries[historyIndex - 1]; if (previous) jumpNavigation(previous.position); }}
          onHistoryForward={() => { const next = historyEntries[historyIndex + 1]; if (next) jumpNavigation(next.position); }}
          onHistoryJump={(index) => jumpNavigation(historyEntries[index].position)}
          developer={adminLive}
          searchUpdating={runtimeHealth.readiness?.corpus.updating === true}
          searchPreparation={banner?.kind === "preparation" || banner?.kind === "empty" ? banner.text : null}
          jobBoard={operatorJobs.board}
          jobsStale={operatorJobs.stale}
          searchStatusStale={operatorJobs.stale || runtimeHealth.waiting || !runtimeHealth.readiness || runtimeHealth.kind === "api_down"}
          statusBlocked={settingsOpen || runtimeHealth.modalVisible || tourOpen}
          helpOpen={helpOpen}
          onToggleHelp={() => setHelp(!helpOpen)}
          onNavigate={(target) => navigate(target)}
          onOpenNotification={openNotification}
        />
        {runDetailsMessage && <div className="run-details-backdrop" aria-hidden="true" onClick={() => setRunDetailsMessageId(null)} />}
        {(runtimeHealth.waiting || runtimeHealth.kind === "checking") && <div className="connection-status" role="status"><span>{t(runtimeHealth.waiting ? workPending ? "A job is in progress. Waiting for the API; retrying status checks." : "Connection check delayed. Retrying before declaring an outage." : "Checking API connection…")}</span><button className="button" type="button" disabled={runtimeHealth.checking} onClick={() => void runtimeHealth.check(true)}>{t("Retry connection")}</button></div>}

        <RetainedPanel active={view === "review"} className="review-workspace" workspace="review">
          <div className="messages" ref={messagesViewport} onScroll={(event) => { const element = event.currentTarget; followReview.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80; }}>
            <div className="messages-inner">
              {!active?.messages.length && (
                <ReviewWelcome
                  developer={adminLive}
                  readiness={readiness}
                  onNewChat={() => createReview()}
                  onOpenBuild={() => navigate({ view: "build", tab: "pipeline" })}
                  onChooseExample={(question) => { setQuery(question); composerInput.current?.focus(); }}
                />
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
                  onUseSelected={() => void reviewSelectedEvidence(message)}
                  onOpenDetails={(stage) => openRunDetails(message.id, stage)}
                  onOpenFix={openFailureFix}
                />
              ))}

            </div>
          </div>
          <div className="composer-wrap" data-tour="composer">
            {localCpuSpeed !== null && <SlowCpuNotice key={`${activeId}:${localModel}`} profile={activeSessionProfile} model={localModel ?? ""} speed={localCpuSpeed} onOpenLimits={() => openConversationSettings("limits")} />}
            {conversationTab && <ConversationSettings speed={localCpuSpeed} query={query} onManagePresets={() => { setConversationTab(null); navigate({ view: "measure", tab: "presets" }); }} key={activeId} tab={conversationTab} profile={activeSessionProfile} editable={adminLive} onValidityChange={setConversationInputsValid} onChange={updateSessionProfile} onTabChange={setConversationTab} onClose={() => setConversationTab(null)} />}
            <ComposerToolbar
              requestPending={activeReview !== null}
              publicScopeStatus={adminLive ? null : publicCorpus.status === "loading" ? "Loading published filings…" : publicCorpus.status === "error" ? "Published filings could not be loaded." : !publicCorpus.documents.length ? "No published filings" : activeSessionProfile.doc_ids.length === 0 ? "No filings in scope" : null}
              query={query}
              engineControls={localAllowed && <LocalEngineSettings profile={activeSessionProfile} readiness={runtimeHealth.readiness} onChange={updateSessionProfile} />}
              settingsOpen={conversationTab !== null}
              settingsTriggerRef={ragTrigger}
              profile={activeSessionProfile}
              onChange={updateSessionProfile}
              canUseCustom={adminBuild && permissions?.can_change_custom_retrieval === true}
              onLocked={() => notify(t(DEV_ONLY_REASONS.settings), "warning", "prod-locked", undefined, { event: "prod-locked-warning" })}
              onOpenSettings={() => openConversationSettings("filters")}
              onOpenCustom={() => { setConversationTab(null); navigate({ view: "measure", tab: "presets" }); }}
              readiness={readiness}
              live={adminLive}
              onOpenBuild={() => navigate({ view: "build", tab: "pipeline" })}
            />

            {!adminLive && <p className="helper" role="status">{t(publicCorpus.status === "loading" ? "Loading published filings…" : publicCorpus.status === "error" ? "Published filings could not be loaded." : !publicCorpus.documents.length ? "No portfolio filings have been published yet." : publicScopeBlocked ? "Select at least one published filing to ask a question." : "Questions use the selected published filings.")}{unavailableScope && <> {t("Some saved filings are no longer published. Review your selection.")}</>}{publicCorpus.status === "error" && <button type="button" className="button ghost" onClick={publicCorpus.refresh}>{t("Retry")}</button>}</p>}
            {permissions && compatibilityIssue && <ProfileCompatibilityNotice key={`${activeId}:${compatibilityIssue}`} message={compatibilityIssue} conversationId={activeId} />}
            {!adminLive && !publicPolicy && <p className="helper" role="status">{t(publicPolicyFailed ? "Server execution limits could not be loaded. Browser defaults are not the applied policy." : "Loading server execution limits…")}{publicPolicyFailed && <button type="button" className="button ghost" onClick={retryPublicPolicy}>{t("Retry")}</button>}</p>}
            {!adminLive && <BrowserRequestStatus />}
            <QuestionComposer
              inputRef={composerInput}
              query={query}
              onQueryChange={setQuery}
              onSubmit={() => void submit()}
              sendDisabled={busy || runtimeHealth.kind === "api_down" || runtimeHealth.kind === "checking" || sendBlocked}
            />

            {settingsValidationError && <p role="alert" className="notice error">{t(settingsValidationError)} <button type="button" className="inline-link" onClick={() => openConversationSettings("retrieval")}>{t("Open settings")}</button></p>}
            {localIssue && <p className="helper" role="status">{t(localIssue)} <button className="inline-link" type="button" onClick={() => openSettings("local")}>{t("Open Local LLM settings")}</button></p>}
            {banner
              ? <ComposerBanner banner={banner} onOpenBuild={() => navigate({ view: "build", tab: "pipeline", stage: banner.step })} onOpenAnswerModel={() => navigate({ view: "build", tab: "pipeline", stage: 6 })} />
              : <p>{t("Answers must cite retrieved filing evidence. Provider calls are rate- and cost-limited.")}</p>}
          </div>
        </RetainedPanel>

        <RetainedPanel active={view === "build"} className="retained-workspace" workspace="build"><BuildWorkspace key={active?.id}
          onLocalPrepared={runtimeHealth.refreshLocal}
          localModel={activeSessionProfile.local_model}
          focusStep={pendingStage}
          focusJobId={buildJobId}
          live={adminBuild && permissions?.can_build_snapshot === true}
          publishedCorpus={publicCorpus}
          publicProfile={activeSessionProfile}
          publicTargets={active?.pipelineDraft?.targets ?? active?.publishedTargets}
          publicProgress={active?.pipelineDraft}
          onPublicProgressChange={progress => updatePipelineDraft(undefined, progress)}
          publicSelection={publicIds ?? effectivePublishedProfile({ ...storedSessionProfile, corpus_scope: "auto" }, publicCorpus.documents, undefined).doc_ids}
          onPublicSelectionChange={(_ids, targets) => updatePipelineDraft(targets ?? [])}
          onConfirmScope={() => { if (active?.pipelineDraft) changePublishedScope([], active.pipelineDraft.targets); }}
          onAskScope={() => navigate({ view: "review" })}
          ready={runtimeHealth.kind === "healthy"}
          readiness={runtimeHealth.readiness}
          healthKind={runtimeHealth.kind}
          connectionPending={runtimeHealth.waiting}
          profile={resolvedRetrievalProfile(activeSessionProfile, builtins)}
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
          active={view === "measure"}
          readiness={runtimeHealth.readiness}
          onOpenPreparation={(stage) => navigate({ view: "build", tab: "pipeline", stage })}
          onDirtyChange={setUnsavedGolden}
          onLeaveGuard={registerGoldenLeave}
          environment={permissions?.environment}
          live={adminBuild && permissions?.can_run_evaluation === true}
          ready={runtimeHealth.kind === "healthy"}
          profile={resolvedRetrievalProfile(activeSessionProfile, builtins)}
          publicProfile={activeSessionProfile}
          publicScopeBlocked={publicScopeBlocked || (!adminLive && !publicPolicy)}
          onProfileChange={updateLabProfile}
          onApplyProfile={applyProfile}
          onApplySnapshot={applySnapshot}
          jobBoard={operatorJobs.board}
          onRefreshJobs={() => void operatorJobs.refresh(true)}
          tab={measureTab}
          onTabChange={(tab) => navigate({ view: "measure", tab }, { confirmed: true })}
          focusResultId={measureResultId}
          onResultSelectionChange={setMeasureResultId}
          helpTarget={pendingHelpTarget}
        /></RetainedPanel>
        <RetainedPanel active={view === "system"} className="retained-workspace" workspace="system"><SystemWorkspace
          onOpenLimitDefaults={() => openSettings("limits")}
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
      <BrowserStorageSupport enabled={environment === "prod" && productionBrowserStorageEnabled()} />
      <SettingsModal storageImportDisabled={busy} open={settingsOpen} initialCategory={settingsCategory} profile={storedSessionProfile} capabilities={permissions} readiness={readiness} onLocalConnectionChanged={runtimeHealth.refreshLocal} onOpenModelSelection={() => {
        if (!navigate({ view: "review" })) return;
        setSettingsOpen(false);
        if (window.innerWidth <= 560) setSidebarOpen(false);
        window.requestAnimationFrame(() => document.querySelector<HTMLSelectElement>("[data-answer-engine-select]")?.focus());
      }} onChange={updateSessionProfile} onClose={() => setSettingsOpen(false)} onOpenTour={() => { setSettingsOpen(false); openTour(); }} onClear={() => { clearReviews(); notify(t("Local conversations cleared."), "success", "local-conversations-cleared", undefined, { event: "local-conversations-cleared-notice" }); }} />
      {tourOpen && <Onboarding publicMode={!adminLive} onClose={closeTour} includeOperations={operationsAvailable} onStepChange={openTourStep} location={location} />}
      <RunDetailsPanel editable={adminLive} stageRequest={runDetailsStage} draftProfile={activeSessionProfile} draftQuery={query} message={publicScopeFailure(runDetailsMessage, adminLive)} onClose={() => setRunDetailsMessageId(null)} onOpenFix={openFailureFix} />

      <HelpOverlay screen={helpScreen(view, currentTab)} open={helpVisible} keyboard={!modalOpen} capabilities={helpCapabilities} onClose={() => setHelp(false)} location={location} onNavigateTopic={navigateHelpTopic} />
      <NotificationSignals enabled={environment !== undefined} healthKind={runtimeHealth.kind} healthMessage={runtimeHealth.readiness?.corpus?.schema_message} checkedAt={runtimeHealth.checkedAt} operations={Boolean(operationsAvailable)} local={runtimeHealth.readiness?.review_engines?.local} model={localModel ?? null} cpuSpeed={localCpuSpeed} conversationId={activeId} reviewVisible={view === "review"} jobsVisible={view === "build" && buildTab === "jobs"} systemVisible={view === "system" && systemTab === "status"} />
      <ServiceHealthModal
        kind={runtimeHealth.kind}
        visible={runtimeHealth.modalVisible}
        checking={runtimeHealth.checking}
        onRetry={() => void runtimeHealth.check()}
        onReload={() => window.location.reload()}
        onDismiss={runtimeHealth.dismissWarning}
        onOpenStatus={() => { runtimeHealth.dismissWarning(); navigate({ view: "system", tab: "status" }); }}
        onOpenBuild={() => { runtimeHealth.dismissWarning(); navigate({ view: "build", tab: "pipeline" }); }}
        readOnly={!adminLive}
        degradedMessage={runtimeHealth.readiness?.corpus?.pending_embeddings
          ? `${runtimeHealth.readiness.corpus.pending_embeddings.toLocaleString()} chunks still need embeddings. Open Build and run Backfill embeddings.`
          : runtimeHealth.readiness?.corpus?.schema_message || undefined}
      />
    </main>
    </DevPromotionProvider>
  );
}

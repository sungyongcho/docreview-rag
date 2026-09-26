import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { navigationUrl, parseNavigationUrl, type NavigationTarget } from "@/lib/navigation";
import type { BuildTab } from "./build-workspace";
import type { ConversationSettingsTab } from "./conversation-settings";
import type { MeasureTab } from "./measure-workspace";
import type { SystemTab } from "./system-workspace";

interface WorkspaceLocation {
  view: NavigationTarget["view"];
  activeId: string;
  buildTab: BuildTab;
  buildStage: number | "setup" | undefined;
  buildJobId: string | undefined;
  measureTab: MeasureTab;
  measureResultId: number | null;
  systemTab: SystemTab;
  conversationTab: ConversationSettingsTab | null;
  pendingStage: number | "setup" | null;
}

interface NavigationEntry {
  position: number;
  target: NavigationTarget;
  conversationId: string;
  conversationTab: ConversationSettingsTab | null;
  scroll: Array<{ element: HTMLElement; top: number; left: number }>;
  focus: HTMLElement | null;
}

/** Apply explicit destinations while retaining each inactive workspace's controls. */
function applyTarget(current: WorkspaceLocation, target: NavigationTarget, adminBuild: boolean): WorkspaceLocation {
  const next = { ...current, view: target.view };
  switch (target.view) {
    case "review":
      return { ...next, activeId: target.conversationId ?? current.activeId };
    case "build":
      return {
        ...next,
        buildTab: target.tab ?? current.buildTab,
        buildJobId: target.jobId,
        buildStage: target.stage,
        pendingStage: target.stage ?? current.pendingStage,
      };
    case "measure":
      return {
        ...next,
        measureTab: target.tab ?? current.measureTab,
        measureResultId: target.resultId === undefined ? current.measureResultId : target.resultId,
      };
    case "system":
      return { ...next, systemTab: adminBuild ? target.tab ?? current.systemTab : "status" };
  }
}

/** Project only the visible destination into the URL and navigation labels. */
function currentTarget(location: WorkspaceLocation): NavigationTarget {
  switch (location.view) {
    case "review":
      return { view: "review", conversationId: location.activeId };
    case "build":
      return {
        view: "build",
        tab: location.buildTab,
        ...(location.buildTab === "jobs" && location.buildJobId ? { jobId: location.buildJobId } : {}),
        ...(location.buildTab === "pipeline" && location.buildStage !== undefined ? { stage: location.buildStage } : {}),
      };
    case "measure":
      return { view: "measure", tab: location.measureTab, resultId: location.measureResultId };
    case "system":
      return { view: "system", tab: location.systemTab };
  }
}

/** Own workspace destinations, native history, leave guards and retained-panel restoration. */
export function useWorkspaceNavigation(adminBuild: boolean, conversationIds: string[]) {
  const [location, setLocation] = useState<WorkspaceLocation>({
    view: "review",
    activeId: "",
    buildTab: "pipeline",
    buildStage: undefined,
    buildJobId: undefined,
    measureTab: "playground",
    measureResultId: null,
    systemTab: "status",
    conversationTab: null,
    pendingStage: null,
  });
  const [history, setHistory] = useState<{ back: NavigationEntry[]; forward: NavigationEntry[] }>({ back: [], forward: [] });
  const position = useRef(0);
  const revertingPosition = useRef<number | null>(null);
  const pendingReturn = useRef<NavigationEntry | null>(null);
  const initialized = useRef(false);
  const firstRunRouted = useRef(false);
  const recoveryRouted = useRef(false);
  const [unsavedGolden, setUnsavedGolden] = useState(false);
  const goldenLeaveGuard = useRef<((action: () => void) => void) | null>(null);
  /** Register the active editor confirmation without coupling navigation to its dialog. */
  const registerGoldenLeave = useCallback((guard: ((action: () => void) => void) | null) => {
    goldenLeaveGuard.current = guard;
  }, []);

  /** Resolve the initial URL only after the shell has loaded its permitted conversation store. */
  const initialize = useCallback((ids: string[], rememberedId: string) => {
    const target = parseNavigationUrl(window.location.href, ids, rememberedId);
    const savedPosition = window.history.state?.docreviewNavigation?.position;
    position.current = Number.isSafeInteger(savedPosition) ? savedPosition : 0;
    initialized.current = true;
    if (target) firstRunRouted.current = true;
    setLocation(current => {
      const selected = { ...current, activeId: rememberedId };
      return target ? applyTarget(selected, target, adminBuild) : selected;
    });
  }, [adminBuild]);

  useEffect(() => {
    if (recoveryRouted.current) return;
    recoveryRouted.current = true;
    const stage = new URLSearchParams(window.location.search).get("recovery_stage");
    const stages: Record<string, number> = {
      filings: 1, index: 2, embeddings: 3, lexical: 4, ask: 5, answer_model: 6, evaluate: 7,
    };
    if (!stage || !stages[stage]) return;
    firstRunRouted.current = true;
    setLocation(current => applyTarget(current, { view: "build", tab: "pipeline", stage: stages[stage] }, adminBuild));
  }, [adminBuild]);

  /** Automatic first-run routing never replaces an explicit URL or user navigation. */
  const routeFirstRun = useCallback((openBuild: boolean) => {
    if (firstRunRouted.current) return;
    firstRunRouted.current = true;
    if (openBuild) setLocation(current => applyTarget(current, { view: "build" }, adminBuild));
  }, [adminBuild]);

  /** Capture only the visible panel; retained controls keep their own component state. */
  function captureNavigation(): NavigationEntry {
    const panel = document.querySelector<HTMLElement>(`[data-workspace="${location.view}"]`);
    const scroll = Array.from(panel?.querySelectorAll<HTMLElement>("*") ?? [])
      .filter((element) => !element.closest("[hidden]") && (
        element.scrollTop !== 0 || element.scrollLeft !== 0 || element.matches(".messages, .lab-shell")
      ))
      .map((element) => ({ element, top: element.scrollTop, left: element.scrollLeft }));
    return {
      position: position.current,
      target: currentTarget(location),
      conversationId: location.activeId,
      conversationTab: location.conversationTab,
      scroll,
      focus: document.activeElement instanceof HTMLElement ? document.activeElement : null,
    };
  }

  /** Preserve unrelated URL parameters and Next history metadata. */
  function writeNavigation(target: NavigationTarget, replace: boolean) {
    const state = { ...window.history.state, docreviewNavigation: { position: position.current } };
    window.history[replace ? "replaceState" : "pushState"](state, "", navigationUrl(target, window.location.href));
  }

  /** Return whether an unsaved editor must confirm an action before it can proceed. */
  function deferLeave(action: () => void): boolean {
    if (location.view !== "measure" || !unsavedGolden || !goldenLeaveGuard.current) return false;
    goldenLeaveGuard.current(action);
    return true;
  }

  /** Share destination application across explicit navigation and native traversal. */
  function navigate(
    target: NavigationTarget,
    { confirmed = false, fromHistory = false }: { confirmed?: boolean; fromHistory?: boolean } = {},
  ): boolean {
    const next = applyTarget(location, target, adminBuild);
    const changed = next.view !== location.view
      || (next.view === "build" && (
        next.buildTab !== location.buildTab
        || next.buildJobId !== location.buildJobId
        || (target.view === "build" && target.stage !== undefined && next.buildStage !== location.buildStage)
      ))
      || (next.view === "measure" && (
        next.measureTab !== location.measureTab || next.measureResultId !== location.measureResultId
      ))
      || (next.view === "system" && next.systemTab !== location.systemTab)
      || (next.view === "review" && next.activeId !== location.activeId);
    if (!confirmed && changed && deferLeave(() => navigate(target, { confirmed: true }))) return false;
    if (changed && !fromHistory) {
      const origin = captureNavigation();
      setHistory(current => ({ back: [...current.back.slice(-29), origin], forward: [] }));
      position.current += 1;
      writeNavigation(currentTarget(next), false);
    }
    firstRunRouted.current = true;
    setLocation(current => applyTarget(current, target, adminBuild));
    return true;
  }

  /** Header jumps use the same popstate path as browser back and forward. */
  function jumpNavigation(destination: number) {
    const distance = destination - position.current;
    if (distance) window.history.go(distance);
  }

  const {
    view, activeId, buildTab, buildJobId, buildStage, measureTab, measureResultId, systemTab, pendingStage,
  } = location;
  useEffect(() => {
    if (initialized.current && activeId) writeNavigation(currentTarget(location), true);
  }, [view, activeId, buildTab, buildJobId, buildStage, measureTab, measureResultId, systemTab]);

  useEffect(() => {
    if (!initialized.current || !activeId) return;
    /** Restore a known entry, or a valid URL whose in-memory snapshot has expired. */
    const pop = (event: PopStateEvent) => {
      const requested = event.state?.docreviewNavigation?.position;
      const nextPosition = Number.isSafeInteger(requested) ? requested : position.current - 1;
      if (revertingPosition.current === nextPosition) {
        revertingPosition.current = null;
        return;
      }
      const fallback = conversationIds.includes(activeId) ? activeId : conversationIds[0] ?? activeId;
      const target = parseNavigationUrl(window.location.href, conversationIds, fallback)
        ?? { view: "review" as const, conversationId: fallback };
      const origin = captureNavigation();
      const all = [...history.back, origin, ...history.forward];
      const index = all.findIndex((entry) => entry.position === nextPosition);
      const entry = index >= 0 ? all[index] : null;
      if (!navigate(target, { fromHistory: true })) {
        const distance = origin.position - nextPosition;
        if (distance) {
          revertingPosition.current = origin.position;
          window.history.go(distance);
        } else {
          writeNavigation(origin.target, true);
        }
        return;
      }
      position.current = nextPosition;
      if (entry) {
        setHistory({
          back: all.slice(0, index).slice(-30),
          forward: all.slice(index + 1, index + 31),
        });
        pendingReturn.current = entry;
        setLocation(current => ({
          ...current,
          activeId: conversationIds.includes(entry.conversationId) ? entry.conversationId : current.activeId,
          conversationTab: entry.conversationTab,
        }));
      } else if (nextPosition < origin.position) {
        setHistory({ back: [], forward: [origin, ...history.forward].slice(0, 30) });
      } else {
        setHistory({ back: [...history.back, origin].slice(-30), forward: [] });
      }
    };
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, [location, history, conversationIds, unsavedGolden, adminBuild]);

  useLayoutEffect(() => {
    const entry = pendingReturn.current;
    if (!entry) return;
    pendingReturn.current = null;
    if (entry.focus?.isConnected && !entry.focus.closest("[hidden], [inert]")) {
      entry.focus.focus({ preventScroll: true });
    }
    for (const { element, top, left } of entry.scroll) {
      if (!element.isConnected) continue;
      element.scrollTop = top;
      element.scrollLeft = left;
    }
  }, [location, history]);

  useEffect(() => {
    if (pendingStage === null || view !== "build" || buildTab !== "pipeline") return;
    document.getElementById(`stage-${pendingStage}`)?.scrollIntoView({ block: "start" });
    setLocation(current => ({ ...current, pendingStage: null }));
  }, [pendingStage, view, buildTab]);

  /** Select a loaded conversation without adding a history entry during store updates. */
  const setActiveId = useCallback((activeId: string) => {
    setLocation(current => ({ ...current, activeId }));
  }, []);
  /** Retain review settings independently of the currently visible workspace. */
  const setConversationTab = useCallback((conversationTab: ConversationSettingsTab | null) => {
    setLocation(current => ({ ...current, conversationTab }));
  }, []);
  /** Reflect result selection in the current URL without adding a history entry. */
  const setMeasureResultId = useCallback((measureResultId: number | null) => {
    setLocation(current => ({ ...current, measureResultId }));
  }, []);
  const historyEntries = [
    ...history.back,
    { position: position.current, target: currentTarget(location) },
    ...history.forward,
  ];
  return {
    ...location,
    navigate,
    initialize,
    routeFirstRun,
    deferLeave,
    setActiveId,
    setConversationTab,
    setMeasureResultId,
    setUnsavedGolden,
    registerGoldenLeave,
    historyEntries,
    historyIndex: history.back.length,
    jumpNavigation,
  };
}

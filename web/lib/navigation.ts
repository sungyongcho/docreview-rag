import type { BuildTab } from "@/components/build-workspace";
import type { MeasureTab } from "@/components/measure-workspace";
import type { SystemTab } from "@/components/system-workspace";
import { STAGE_ORDER } from "./pipeline";

export type NavigationTarget =
  | { view: "review"; conversationId?: string }
  | { view: "build"; tab?: BuildTab; stage?: number | "setup"; jobId?: string }
  | { view: "measure"; tab?: MeasureTab; resultId?: number | null }
  | { view: "system"; tab?: SystemTab };

const BUILD_TABS: Record<BuildTab, string> = { pipeline: "Pipeline", documents: "Documents", jobs: "Jobs" };
const MEASURE_TABS: Record<MeasureTab, string> = { playground: "Search trial", golden: "Golden dataset", runs: "Run evaluation", compare: "Compare and save", snapshots: "Snapshots", defaults: "Defaults", presets: "Retrieval presets" };
const SYSTEM_TABS: Record<SystemTab, string> = { status: "Status", operations: "Operations", api: "API", usage: "Usage" };
const NAVIGATION_PARAMETERS = ["view", "tab", "stage", "result", "conversation", "job"];

/** Parse canonical positive integer IDs without accepting exponents, fractions or unsafe values. */
function positiveInteger(value: string | null): number | undefined {
  if (!value || !/^[1-9]\d*$/.test(value)) return undefined;
  const number = Number(value);
  return Number.isSafeInteger(number) ? number : undefined;
}

/** Restore only recognized local workspace destinations, preserving legacy URLs with no view. */
export function parseNavigationUrl(url: string, conversationIds: string[], fallbackConversationId: string): NavigationTarget | null {
  const params = new URL(url, "http://docreview.local").searchParams;
  const view = params.get("view");
  if (view === null) return null;
  const tab = params.get("tab") ?? "";
  if (view === "build") {
    const selected = Object.hasOwn(BUILD_TABS, tab) ? tab as BuildTab : "pipeline";
    const stage = params.get("stage");
    const numeric = positiveInteger(stage);
    const job = params.get("job");
    return { view, tab: selected, ...(selected === "jobs" && job && /^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$/.test(job) ? { jobId: job } : {}), ...(selected === "pipeline" && (stage === "setup" || (numeric !== undefined && numeric <= STAGE_ORDER.length)) ? { stage: stage === "setup" ? "setup" : numeric } : {}) };
  }
  if (view === "measure") {
    const resultId = positiveInteger(params.get("result"));
    return { view, tab: Object.hasOwn(MEASURE_TABS, tab) ? tab as MeasureTab : "playground", ...(resultId !== undefined ? { resultId } : {}) };
  }
  if (view === "system") return { view, tab: Object.hasOwn(SYSTEM_TABS, tab) ? tab as SystemTab : "status" };
  const conversation = params.get("conversation");
  return { view: "review", conversationId: view === "review" && conversation && conversationIds.includes(conversation) ? conversation : fallbackConversationId };
}

/** Replace only app navigation parameters so locale, preview queries, base path and anchors survive. */
export function navigationUrl(target: NavigationTarget, currentUrl: string): string {
  const url = new URL(currentUrl, "http://docreview.local");
  for (const parameter of NAVIGATION_PARAMETERS) url.searchParams.delete(parameter);
  url.searchParams.set("view", target.view);
  if (target.view === "review") {
    if (target.conversationId) url.searchParams.set("conversation", target.conversationId);
  } else {
    url.searchParams.set("tab", target.tab ?? (target.view === "build" ? "pipeline" : target.view === "measure" ? "playground" : "status"));
    if (target.view === "build" && target.stage !== undefined) url.searchParams.set("stage", String(target.stage));
    if (target.view === "build" && target.tab === "jobs" && target.jobId) url.searchParams.set("job", target.jobId);
    if (target.view === "measure" && target.resultId != null) url.searchParams.set("result", String(target.resultId));
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

/** Name the complete destination for the current header, history options and arrow tooltips. */
export function navigationLabel(target: NavigationTarget, titles: Record<string, string>, t: (key: string) => string): string {
  if (target.view === "review") return `${t("Conversation")} · ${titles[target.conversationId ?? ""] || t("New review")}`;
  if (target.view === "build") return [t("Build"), t(BUILD_TABS[target.tab ?? "pipeline"]), ...(target.stage === undefined ? [] : [target.stage === "setup" ? t("Setup") : `${t("Step")} ${target.stage}`])].join(" · ");
  if (target.view === "measure") return [t("Measure"), t(MEASURE_TABS[target.tab ?? "playground"]), ...(target.resultId == null ? [] : [`${t("Result")} ${target.resultId}`])].join(" · ");
  return `${t("System")} · ${t(SYSTEM_TABS[target.tab ?? "status"])}`;
}

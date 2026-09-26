"use client";
import { CircleHelp, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import type { RefObject } from "react";

import { NotificationCenter } from "@/components/notification-center";
import { SEARCH_UPDATE_KINDS, SearchUpdateStatus, searchUpdateProgress } from "@/components/search-update-status";
import { ThemeSwitch } from "@/components/theme-switch";
import { WorkspaceHistory } from "@/components/workspace-history";
import { LanguageSwitch, useI18n } from "@/lib/i18n";
import type { NavigationTarget } from "@/lib/navigation";
import type { NotificationTarget } from "@/lib/notification-registry";
import type { OperatorJobBoard } from "@/lib/types";

interface ServiceTopbarProps {
  sidebarToggleRef: RefObject<HTMLButtonElement | null>;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  modeLabel: string | null;
  historyEntries: Array<{ id: string; label: string }>;
  historyIndex: number;
  onHistoryBack: () => void;
  onHistoryForward: () => void;
  onHistoryJump: (index: number) => void;
  developer: boolean;
  searchUpdating: boolean;
  searchPreparation: string | null;
  jobBoard: OperatorJobBoard;
  jobsStale: boolean;
  /** The search update status cannot trust the job board while the API is unreachable. */
  searchStatusStale: boolean;
  /** Settings, the service-health modal and the tour own the screen, so status popovers stay closed. */
  statusBlocked: boolean;
  helpOpen: boolean;
  onToggleHelp: () => void;
  onNavigate: (target: NavigationTarget) => void;
  onOpenNotification: (target: NotificationTarget) => void;
}

/** Top bar: sidebar toggle and workspace history on the left, status and display controls on the right. */
export function ServiceTopbar({
  sidebarToggleRef, sidebarOpen, onToggleSidebar, modeLabel, historyEntries, historyIndex, onHistoryBack, onHistoryForward, onHistoryJump,
  developer, searchUpdating, searchPreparation, jobBoard, jobsStale, searchStatusStale, statusBlocked, helpOpen, onToggleHelp, onNavigate, onOpenNotification,
}: ServiceTopbarProps) {
  const { t } = useI18n();
  return (
    <header className="topbar">
      <div className="topbar-navigation">
        <button ref={sidebarToggleRef} className="icon-button" type="button" aria-label={t("Toggle sidebar")} aria-expanded={sidebarOpen} aria-controls="service-navigation" title={modeLabel ?? undefined} onClick={onToggleSidebar}>{sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}</button>
        <WorkspaceHistory entries={historyEntries} currentIndex={historyIndex} onBack={onHistoryBack} onForward={onHistoryForward} onJump={onHistoryJump} />
      </div>
      <div className="topbar-status">
        {!developer && <SearchUpdateStatus updating={searchUpdating} preparation={searchPreparation} jobs={jobBoard.jobs} stale={searchStatusStale} blocked={statusBlocked} onOpenJobs={developer ? jobId => onNavigate({ view: "build", tab: "jobs", jobId }) : undefined} />}
        <NotificationCenter jobs={jobBoard.jobs} jobsStale={jobsStale} developer={developer} onNavigate={onOpenNotification} blocked={statusBlocked} />
        <LanguageSwitch />
        <ThemeSwitch />
        {developer && (jobBoard.active_count > 0 || jobBoard.queued_count > 0) && <JobHealthButton jobBoard={jobBoard} stale={jobsStale} onOpenJobs={() => onNavigate({ view: "build", tab: "jobs" })} />}
        <button type="button" className="icon-button help-toggle" aria-label={t("Toggle help")} aria-pressed={helpOpen} onClick={onToggleHelp}><CircleHelp size={18} /></button>
      </div>
    </header>
  );
}

/** Running and queued job counts, plus the progress of the search update that is running or next in line. */
function JobHealthButton({ jobBoard, stale, onOpenJobs }: { jobBoard: OperatorJobBoard; stale: boolean; onOpenJobs: () => void }) {
  const { t } = useI18n();
  const searchJobs = jobBoard.jobs.filter(job => job.domain === "corpus" && SEARCH_UPDATE_KINDS.has(job.kind));
  const activeSearchJob = searchJobs.find(job => job.status === "running") ?? searchJobs.find(job => job.status === "queued");
  const progressLabel = activeSearchJob && !stale ? searchUpdateProgress(activeSearchJob, t) : null;
  return (
    <button className="job-health" data-running={jobBoard.active_count > 0} title={t("View all jobs")} type="button" onClick={onOpenJobs}>
      <span>{jobBoard.active_count}{t("running ·")}{" "}{jobBoard.queued_count}{t("queued")}</span>
      {progressLabel && <span className="job-health-detail">· {progressLabel}</span>}
    </button>
  );
}

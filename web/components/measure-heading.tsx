"use client";
import { DevelopmentBadge } from "@/components/development-badge";
import type { MeasureTab } from "@/components/measure-workspace";
import { PublicQualityAccess } from "@/components/public-quality-access";
import { WorkflowHelp } from "@/components/workflow-help";
import { deploymentLabel } from "@/lib/deployment";
import { useI18n } from "@/lib/i18n";
import type { Capabilities } from "@/lib/types";

interface MeasureHeadingProps {
  tab: MeasureTab;
  /** The golden question editor takes over the page, so the title and section tabs step aside while it is open. */
  goldenEditing: boolean;
  live: boolean;
  active: boolean;
  environment?: "dev" | "prod";
  capabilities?: Capabilities | null;
  onSelectTab: (tab: MeasureTab) => void;
}

/** Measure page title, the section tabs, and the introduction of the selected section. */
export function MeasureHeading({ tab, goldenEditing, live, active, environment, capabilities, onSelectTab }: MeasureHeadingProps) {
  const { t, locale } = useI18n();
  return (
    <>
      <header hidden={goldenEditing} className="page-heading">
        <div><p className="eyebrow">{t("Measure")}</p><h1>{t("Measure retrieval before trusting it.")}</h1></div>
        <div className="page-badges">{environment && <span className="mode-badge">{deploymentLabel(environment)}</span>}<span className={`mode-badge ${live ? "live" : ""}`}>{live ? t("Local operator") : t("Read-only portfolio")}</span></div>
      </header>
      <nav hidden={goldenEditing} className="lab-tabs workflow-tabs measure-tab-strip" aria-label={t("Measure sections")}>
        <div className="measure-tab-group measure-workflow-group" role="group" aria-label={t("Evaluation workflow")}>
          {([["playground", "Search trial"], ["golden", "Golden dataset"], ["runs", "Run evaluation"], ["compare", "Compare & snapshots"]] as const).map(([id, label], index) => <button key={id} type="button" aria-pressed={tab === id || (id === "compare" && tab === "snapshots")} onClick={() => onSelectTab(id)}><span className="measure-step-chip" aria-hidden="true">{index + 1}</span>{t(label)}</button>)}
        </div>
        <div className="measure-tab-group measure-management-group" role="group" aria-label={t("Manage")}>
          <span className="measure-management-caption" aria-hidden="true">{t("Manage")}</span>
          <button type="button" aria-pressed={tab === "presets"} onClick={() => onSelectTab("presets")}>{t("Presets")}</button>
        </div>
      </nav>
      <div className="workflow-section-heading" data-help={tab === "presets" ? "measure.presets.manage" : undefined}><h2>{tab === "presets" ? t("Retrieval presets") : tab === "playground" ? t("Search trial") : tab === "golden" ? t("Prepare a golden dataset") : tab === "runs" ? t("Run evaluation") : tab === "snapshots" ? t(live ? "Snapshot management" : "Published snapshots") : t("Compare evaluation results")}</h2>{live && ["golden", "runs"].includes(tab) && <DevelopmentBadge locale={locale} compact />}<WorkflowHelp active={active} screen={`measure.${tab}`} capabilities={capabilities} /></div>
      {(live || tab === "playground" || tab === "presets") && <p className="data-origin">{t(live ? "Live workspace · results come from recorded runs" : tab === "playground" ? "Live search within the selected published scope" : "Explore published records. Reading and filtering do not run an evaluation.")}</p>}
      {!live && !goldenEditing && (tab === "golden" || tab === "runs" || tab === "compare" || tab === "snapshots") && <PublicQualityAccess section={tab} />}
      {(live || tab === "playground" || tab === "presets") && <p className="workflow-intro">{tab === "presets" ? t("Create reusable search settings, then select them in a conversation.") : tab === "playground" ? t("Try one question and inspect its evidence before evaluating a whole dataset.") : tab === "golden" ? t(live ? "Select a JSON dataset and inspect its questions. Create a separate file to edit, save changes, then check format and sources." : "Inspect published questions and expected evidence. Editing runs in DEV mode.") : tab === "runs" ? t("Choose the questions and search settings to measure. A run records what was tested and how well the evidence was retrieved.") : tab === "snapshots" ? t("A snapshot preserves search data and an evaluation result so you can reuse a known configuration later.") : t("Choose a baseline and a candidate. Compare evidence hits, rank, and latency. Saving a snapshot is optional.")}</p>}
      {(tab === "compare" || tab === "snapshots") && <nav className="result-tabs"><button type="button" aria-pressed={tab === "compare"} onClick={() => onSelectTab("compare")}>{t("Compare results")}</button><button type="button" aria-pressed={tab === "snapshots"} onClick={() => onSelectTab("snapshots")}>{t(live ? "Snapshot management" : "Published snapshots")}</button></nav>}
    </>
  );
}

"use client";

import { useI18n } from "@/lib/i18n";
import { DevelopmentBadge } from "./development-badge";
import "./public-quality-access.css";

type Section = "golden" | "runs" | "compare" | "snapshots";
interface ControlHelp { controls: string[]; description: string; devOnly?: boolean; }
const CONTROLS: Record<Section, ControlHelp[]> = {
  golden: [
    { controls: ["Evaluation dataset", "Search", "Sort by"], description: "Select a published dataset, then narrow or reorder its questions." },
    { controls: ["ID"], description: "Click a question ID to expand its expected documents and evidence." },
    { controls: ["Create draft", "Evaluate this dataset"], description: "These buttons run in DEV only and are disabled on this website.", devOnly: true },
  ],
  runs: [
    { controls: ["Explore evaluation settings"], description: "Opens a form for trying search settings. Changing the form does not run an evaluation." },
    { controls: ["Request preview · not submitted"], description: "Shows the request corresponding to the form without sending it." },
    { controls: ["Save exploration in this browser"], description: "Saves only the trial settings in this browser; it does not save an evaluation result." },
    { controls: ["Queue evaluation", "Save result as snapshot"], description: "These buttons run in DEV only and are disabled on this website.", devOnly: true },
  ],
  compare: [
    { controls: ["Evaluation dataset", "Baseline", "Candidate"], description: "The gray fields are fixed example selections. Explore the example without running an evaluation or model." },
    { controls: ["Explore an example"], description: "Loads the two recorded evaluations and their question-level differences. No evaluation or model is run." },
  ],
  snapshots: [
    { controls: ["Dataset file", "Search", "Sort by"], description: "Filter and sort the published snapshots listed below." },
    { controls: ["Baseline", "Candidate", "Compare stored results"], description: "Select two different snapshots, then compare their saved results without rerunning an evaluation or model." },
    { controls: ["Snapshot details"], description: "Expands the settings and identifiers recorded in that snapshot." },
  ],
};

/** Explain the controls rendered in each public tab using their exact translated labels. */
export function PublicQualityAccess({ section }: { section: Section }) {
  const { t, locale } = useI18n();
  return <section className="public-quality-access" aria-label={t("Available features")}><dl>
    {CONTROLS[section].map(row => <div key={row.controls.join(":")}><dt>{row.controls.map(label => t(label)).join(" · ")}{row.devOnly && <DevelopmentBadge locale={locale} compact />}</dt><dd>{t(row.description)}</dd></div>)}
  </dl></section>;
}

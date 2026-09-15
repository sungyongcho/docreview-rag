"use client";

import { ArrowRight, Ban, Check, CircleHelp, FileSearch } from "lucide-react";
import { useI18n } from "@/lib/i18n";

const PATHS = [
  { intent: "document_review", label: "Document review", description: "Company, financial and filing analysis", destination: "Continue to stage 1", Icon: FileSearch },
  { intent: "service_help", label: "Service guidance", description: "Greetings and help using this service", destination: "Fixed guidance, then stop", Icon: CircleHelp },
  { intent: "out_of_scope", label: "Unsupported request", description: "Unrelated requests and role-play", destination: "Scope notice, then stop", Icon: Ban },
] as const;

/** Show the recorded purpose classification, never infer a route from later scope results. */
export function ReviewPathChoice({ path }: { path: Record<string, unknown> }) {
  const { t } = useI18n();
  const selected = PATHS.find((item) => item.intent === path.intent);
  const legacy = path.intent === "casual_chat";
  return <div className="review-path-choice">
    <p className="review-path-intro">{t("Stage 0 chooses the service path. Company, year and filing availability are checked in stage 1.")}</p>
    <ol className="review-path-options" aria-label={t("Service paths")}>
      {PATHS.map(({ intent, label, description, destination, Icon }) => <li key={intent} className={`review-path-option${selected?.intent === intent ? " selected" : ""}`} aria-current={selected?.intent === intent ? "step" : undefined}>
        <div className="review-path-option-heading"><Icon size={18} aria-hidden="true" /><strong>{t(label)}</strong></div>
        <p>{t(description)}</p>
        <div className="review-path-destination"><ArrowRight size={14} aria-hidden="true" /><span>{t(destination)}</span></div>
        {selected?.intent === intent && <span className="review-path-selected"><Check size={13} aria-hidden="true" />{t("Selected path")}</span>}
      </li>)}
    </ol>
    {!selected && <p className="review-path-unrecorded">{t(legacy ? "This historical run used a conversation route. Its recorded classification is preserved." : "No service path was recorded. A later scope or result does not establish this decision.")}</p>}
    {typeof path.rationale === "string" && path.rationale.length > 0 && <div className="review-path-explanation"><strong>{t("Decision explanation")}</strong><p>{path.rationale}</p></div>}
  </div>;
}

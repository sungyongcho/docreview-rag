"use client";

import { CircleHelp } from "lucide-react";
import { HELP_TOPICS, type HelpScreen } from "@/lib/help-content";
import { useI18n } from "@/lib/i18n";

export function WorkflowHelp({ screen }: { screen: HelpScreen }) {
  const { t, locale } = useI18n();
  return <details className="workflow-help"><summary aria-label={t("How to use this page")} title={t("How to use this page")}><CircleHelp size={18} /></summary><div className="workflow-help-panel"><strong>{t("How to use this page")}</strong>{HELP_TOPICS[screen].slice(0, 3).map((topic) => <section key={topic.id}><h3>{t(topic.title)}</h3>{topic.body.map((text) => <p key={text}>{t(text)}</p>)}</section>)}</div></details>;
}

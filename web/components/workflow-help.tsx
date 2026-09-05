"use client";

import { CircleHelp } from "lucide-react";
import { developmentHelpTopic, type HelpAccess, type HelpScreen } from "@/lib/help-content";
import { helpEntriesForAccess } from "@/lib/help-search";
import { DevelopmentBadge } from "@/components/development-badge";
import { useI18n } from "@/lib/i18n";

export function WorkflowHelp({ screen, capabilities, publicPreview }: { screen: HelpScreen } & HelpAccess) {
  const { t, locale } = useI18n();
  const topics = helpEntriesForAccess({ capabilities, publicPreview }).filter((entry) => entry.screen === screen).slice(0, 3);
  if (!topics.length) return null;
  return <details className="workflow-help"><summary aria-label={t("How to use this page")} title={t("How to use this page")}><CircleHelp size={18} /></summary><div className="workflow-help-panel"><strong>{t("How to use this page")}</strong>{topics.map(({ topic }) => <section key={topic.id}><h3>{t(topic.title)}{developmentHelpTopic(topic) && <DevelopmentBadge locale={locale} compact />}</h3>{topic.body.map((text) => <p key={text}>{t(text)}</p>)}</section>)}</div></details>;
}

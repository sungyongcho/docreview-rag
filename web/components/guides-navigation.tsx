"use client";

import { BookOpen, NotebookPen } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { DOCUMENTATION_BASE } from "@/lib/documentation-registry.mjs";
import "./guides-navigation.css";

/** Keep the user guide and the development draft discoverable in either environment. */
export function GuidesNavigation() {
  const { t, locale } = useI18n();
  return <nav className="guides-navigation" aria-label={t("Guides & development")}>
    <p>{t("Guides & development")}</p>
    <a href={`${DOCUMENTATION_BASE}/docs/${locale}/`}><BookOpen size={16} aria-hidden="true" /><span>{t("User guide")}</span></a>
    <a href={`${DOCUMENTATION_BASE}/docs/${locale}/development/`}><NotebookPen size={16} aria-hidden="true" /><span>{t("Development log")}</span></a>
  </nav>;
}

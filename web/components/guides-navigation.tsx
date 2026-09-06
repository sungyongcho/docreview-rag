"use client";

import { BookOpen, ChevronDown, NotebookPen } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { DOCUMENTATION_BASE } from "@/lib/documentation-registry.mjs";
import "./guides-navigation.css";

/** Keep the user guide and the development draft discoverable in either environment. */
export function GuidesNavigation() {
  const { t, locale } = useI18n();
  return <details className="guides-navigation">
    <summary><BookOpen size={15} aria-hidden="true" /><span>{t("Guides & development")}</span><ChevronDown className="guides-chevron" size={14} aria-hidden="true" /></summary>
    <nav aria-label={t("Guides & development")}>
      <a href={`${DOCUMENTATION_BASE}/docs/${locale}/`}><BookOpen size={15} aria-hidden="true" /><span>{t("User guide")}</span></a>
      <a href={`${DOCUMENTATION_BASE}/docs/${locale}/development/`}><NotebookPen size={15} aria-hidden="true" /><span>{t("Development log")}</span></a>
    </nav>
  </details>;
}

"use client";

import { Monitor, X } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import type { RefObject } from "react";
import "./production-preview.css";

/** The separate document reuses the public renderer without sharing DEV history or DOM IDs. */
export function ProductionPreviewFrame({ frameRef, onExit }: { frameRef: RefObject<HTMLIFrameElement | null>; onExit: () => void }) {
  const { t, locale } = useI18n();
  return <section className="production-preview-frame" aria-label={t("Production preview")}>
    <header><div><strong><Monitor size={17} aria-hidden="true" />{t("Production preview")}</strong><p>{t("The backend is still DEV. This preview reads public data only and cannot run requests or change server settings.")}</p><details><summary>{t("Preview limits")}</summary><p>{t("This uses the shared public interface in the development bundle. Production permissions and compile-time exclusions still require verification in the production image.")}</p></details></div><button className="button" type="button" onClick={onExit}><X size={16} aria-hidden="true" />{t("Exit preview")}</button></header>
    <iframe ref={frameRef} name="docreview-production-preview" src={`/docreview-rag-agent/production-preview/?locale=${locale}`} title={t("Production preview interface")} />
  </section>;
}

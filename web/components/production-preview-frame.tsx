"use client";

import { Monitor, X } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import type { RefObject } from "react";
import "./production-preview.css";

/** The separate document reuses the public renderer without sharing DEV history or DOM IDs.
 *
 * Language and theme are shared browser preferences, so a switch inside the frame reaches this
 * header through the storage event instead of a frame reload.
 */
export function ProductionPreviewFrame({ frameRef, onExit }: { frameRef: RefObject<HTMLIFrameElement | null>; onExit: () => void }) {
  const { t } = useI18n();
  return <section className="production-preview-frame" aria-label={t("Production preview")}>
    <header><div><strong><Monitor size={17} aria-hidden="true" />{t("Production preview")}</strong><p>{t("PROD interface · local DEV backend. Open the PROD badge for request and browser-storage details.")}</p></div><button className="button" type="button" onClick={onExit}><X size={16} aria-hidden="true" />{t("Exit preview")}</button></header>
    <iframe ref={frameRef} name="docreview-production-preview" src="/docreview-rag-agent/production-preview/" title={t("Production preview interface")} />
  </section>;
}

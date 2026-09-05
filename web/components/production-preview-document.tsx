"use client";

import { useEffect, useState } from "react";
import { browserStorage, enterProductionPreview } from "@/lib/production-preview";
import { getCapabilities } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ServiceShell } from "./service-shell";

/** Initialize the no-write boundary before mounting anything that can read browser history. */
export function ProductionPreviewDocument() {
  const { t } = useI18n();
  const [ready, setReady] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    if (process.env.NEXT_PUBLIC_ADMIN_MODE !== "live") { setUnavailable(true); return; }
    enterProductionPreview("document");
    const locale = new URLSearchParams(window.location.search).get("locale");
    if (locale === "en" || locale === "ko") browserStorage().setItem("docreview.locale", locale);
    let current = true;
    void getCapabilities().then((capabilities) => {
      if (!current) return;
      if (capabilities.environment === "dev") setReady(true);
      else setUnavailable(true);
    }).catch(() => { if (current) setUnavailable(true); });
    // The boundary lasts for this document's lifetime, including client-side documentation visits.
    return () => { current = false; };
  }, []);
  if (!ready) return <p role="status">{t(unavailable ? "Production preview is available only from a running DEV environment." : "Preparing production preview…")}</p>;
  return <ServiceShell publicPreview />;
}

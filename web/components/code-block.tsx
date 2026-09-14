"use client";

import { useEffect, useState } from "react";
import { Check, Copy } from "lucide-react";
import { translate, useI18n, type Locale } from "@/lib/i18n";

export function CodeBlock({ code, language, html, locale: documentLocale }: { code: string; language: string; html: string; locale?: Locale }) {
  const { locale: preference } = useI18n();
  const locale = documentLocale ?? preference;
  const t = (source: string) => translate(locale, source);
  const [status, setStatus] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => setStatus("idle"), [code]);
  async function copy() {
    try { await navigator.clipboard.writeText(code); setStatus("copied"); }
    catch { setStatus("failed"); }
  }
  return <figure className="code-card"><header><span>{language || "text"}</span><button type="button" onClick={() => void copy()} aria-label={t("Copy code")}>{status === "copied" ? <Check size={15} /> : <Copy size={15} />}{t(status === "copied" ? "Copied" : "Copy")}</button></header><div dangerouslySetInnerHTML={{ __html: html }} />{status === "failed" && <figcaption role="alert">{t("Copy failed. Select the code and copy it manually.")}</figcaption>}<span className="visually-hidden" role="status">{status === "copied" ? t("Copied") : ""}</span></figure>;
}

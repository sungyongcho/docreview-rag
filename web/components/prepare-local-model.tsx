"use client";

import { useRef, useState } from "react";
import { Play, LoaderCircle } from "lucide-react";
import { prepareLocalLLM } from "@/lib/api";
import type { LocalLLMConnection } from "@/lib/types";
import { useI18n } from "@/lib/i18n";

/** Explicitly warm an installed model and report only verified server residency. */
export function PrepareLocalModel({ model, disabled = false, ready = false, onPrepared, onStatus }: { model: string | null; disabled?: boolean; ready?: boolean; onPrepared?: (connection: LocalLLMConnection) => void; onStatus?: (status: { loading: boolean; error: string }) => void }) {
  const { t } = useI18n();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  async function prepare() {
    if (!model || disabled || ready || inFlight.current) return;
    inFlight.current = true; setLoading(true); setError("");
    onStatus?.({ loading: true, error: "" });
    let failure = "";
    try { const result = await prepareLocalLLM(model); onPrepared?.(result); }
    catch (reason) { failure = reason instanceof Error ? reason.message : "Model preparation failed."; setError(failure); }
    finally { inFlight.current = false; setLoading(false); onStatus?.({ loading: false, error: failure }); }
  }
  return <div className="model-prepare-control"><button type="button" className="button" disabled={!model || disabled || ready || loading} onClick={() => void prepare()}>{loading ? <LoaderCircle size={15} className="preparation-spinner" aria-hidden="true" /> : <Play size={15} aria-hidden="true" />}{t(loading ? "Preparing model…" : ready ? "Model ready" : "Prepare model")}</button>{error && !onStatus && <p role="alert" className="helper">{t(error)}</p>}</div>;
}

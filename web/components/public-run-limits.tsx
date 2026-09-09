"use client";
import { useEffect, useState } from "react";
import { getReleaseLimits } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { ReleaseLimits } from "@/lib/types";

/** Read the applied public policy rather than displaying a browser profile as server policy. */
export function PublicRunLimits() {
  const { t, locale } = useI18n();
  const [policy, setPolicy] = useState<ReleaseLimits | null>(null);
  const [failed, setFailed] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let current = true;
    setPolicy(null); setFailed(false);
    Promise.resolve().then(() => getReleaseLimits()).then(value => {
      if (!value.prompt_policy || !value.per_call) throw new Error("Public policy unavailable");
      if (current) setPolicy(value);
    }).catch(() => { if (current) setFailed(true); });
    return () => { current = false; };
  }, [revision]);
  if (failed) return <div role="status"><p className="helper">{t("Server execution limits could not be loaded. Browser defaults are not the applied policy.")}</p><button type="button" className="button" onClick={() => setRevision(value => value + 1)}>{t("Retry")}</button></div>;
  if (!policy?.prompt_policy || !policy.per_call) return <p className="helper" role="status">{t("Loading server execution limits…")}</p>;
  const budget = policy.prompt_policy.workflow_budget;
  const rows = [["Maximum evidence characters", policy.prompt_policy.max_context_chars], ["Maximum wall clock seconds", budget.max_wall_clock_s], ["Maximum input tokens", budget.max_input_tokens], ["Maximum output tokens", budget.max_output_tokens]] as const;
  return <><p className="helper">{t("Server policy for one question. These limits cannot be changed here.")}</p><dl className="request-facts">{rows.map(([name,value]) => <div key={name}><dt>{t(name)}</dt><dd>{value.toLocaleString(locale)}{name === "Maximum wall clock seconds" ? ` ${t("seconds")}` : ""}</dd></div>)}</dl><h4>{t("Model call limits")}</h4><p className="helper">{t("Each model call also has its own ceiling; the whole-question token budget counts all calls together.")}</p><dl className="request-facts"><div><dt>{t("Maximum input tokens")}</dt><dd>{policy.per_call.max_input_tokens.toLocaleString(locale)}</dd></div><div><dt>{t("Maximum output tokens")}</dt><dd>{policy.per_call.max_output_tokens.toLocaleString(locale)}</dd></div><div><dt>{t("Maximum cost per call (USD)")}</dt><dd>{policy.per_call.max_cost_usd}</dd></div></dl></>;
}

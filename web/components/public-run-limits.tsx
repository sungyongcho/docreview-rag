"use client";
import { useEffect, useState } from "react";
import { getReleaseLimits } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import "./public-run-limits.css";
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
  const number = (value: number) => value.toLocaleString(locale);
  const questionRows = [
    ["Maximum evidence characters", number(policy.prompt_policy.max_context_chars), "Maximum length of retrieved evidence passed to the answer model."],
    ["Maximum wall clock seconds", `${number(budget.max_wall_clock_s)} ${t("seconds")}`, "Time limit for the entire question workflow."],
    ["Maximum input tokens", number(budget.max_input_tokens), "Total input tokens across model calls for one question."],
    ["Maximum output tokens", number(budget.max_output_tokens), "Total output tokens across model calls, not just the final answer."],
    ["Maximum iterations", number(budget.max_iterations), "Maximum workflow iterations; this is not the number of allowed questions."],
  ];
  const callRows = [
    ["Maximum input tokens", number(policy.per_call.max_input_tokens), "Input ceiling for a single model call."],
    ["Maximum output tokens", number(policy.per_call.max_output_tokens), "Output ceiling for a single model call."],
    ["Maximum cost per call (USD)", `$${policy.per_call.max_cost_usd}`, "Spending ceiling per model call, not a fixed charge."],
  ];
  /** Reuse the same compact table structure for the two distinct budget scopes. */
  function table(title: string, rows: string[][]) {
    return <div className="public-limits-table-wrap"><table className="public-limits-table"><caption>{t(title)}</caption><thead><tr><th scope="col">{t("Setting")}</th><th scope="col">{t("Applied value")}</th><th scope="col">{t("Meaning")}</th></tr></thead><tbody>{rows.map(([name, value, explanation]) => <tr key={name}><th scope="row">{t(name)}</th><td>{value}</td><td>{t(explanation)}</td></tr>)}</tbody></table></div>;
  }
  return <section className="public-run-limits">
    <p className="helper">{t("These are the default limits applied by the deployed service, grouped by whole question and individual model call.")}</p>
    {table("Whole question", questionRows)}
    {table("Single model call", callRows)}
  </section>;
}

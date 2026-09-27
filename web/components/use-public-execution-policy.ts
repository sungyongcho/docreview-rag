import { useEffect, useState } from "react";

import { getReleaseLimits } from "@/lib/api";
import { configureBrowserRequestLimits } from "@/lib/browser-request-limits";
import type { Capabilities, ReviewSessionDraft } from "@/lib/types";

/**
 * Load the execution policy the server applies to public reviews.
 *
 * Browser defaults are never used in its place: the policy stays null until the server answers,
 * and `failed` lets the composer offer a retry instead.
 */
export function usePublicExecutionPolicy(developer: boolean, permissions: Capabilities | null) {
  const [policy, setPolicy] = useState<ReviewSessionDraft["prompt_policy"] | null>(null);
  const [failed, setFailed] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    configureBrowserRequestLimits(developer ? undefined : null);
    if (developer || !permissions) return;
    let current = true;
    setPolicy(null); setFailed(false);
    void getReleaseLimits().then(limits => {
      if (!limits.prompt_policy?.workflow_budget) throw new Error("Public execution policy unavailable");
      if (current) { configureBrowserRequestLimits(limits); setPolicy(limits.prompt_policy); }
    }).catch(() => { if (current) setFailed(true); });
    return () => { current = false; configureBrowserRequestLimits(undefined); };
  }, [developer, permissions?.environment, revision]);
  return { policy, failed, retry: () => setRevision(value => value + 1) };
}

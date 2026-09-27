import { useEffect, useState } from "react";
import { getBrowserRequestAllowance, subscribeBrowserRequestLimits } from "@/lib/browser-request-limits";

/** Refresh local balances after dispatch, cross-tab changes and rolling-window recovery. */
export function useBrowserRequestLimits(enabled = true) {
  const [value, setValue] = useState(getBrowserRequestAllowance);
  useEffect(() => {
    if (!enabled) return;
    const refresh = () => {
      const next = getBrowserRequestAllowance();
      setValue(current => current && next && current.per_minute === next.per_minute && current.per_day === next.per_day && current.remaining_minute === next.remaining_minute && current.remaining_day === next.remaining_day && current.retry_after_seconds === next.retry_after_seconds ? current : next);
    };
    refresh();
    const unsubscribe = subscribeBrowserRequestLimits(refresh);
    const timer = window.setInterval(refresh, 1000);
    return () => { unsubscribe(); window.clearInterval(timer); };
  }, [enabled]);
  return enabled ? value : null;
}

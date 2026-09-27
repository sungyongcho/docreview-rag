import { useI18n } from "@/lib/i18n";
import { useBrowserRequestLimits } from "./use-browser-request-limits";

/** Keep browser counters and retry time separate from the server's shared allowance. */
export function BrowserRequestStatus() {
  const { t } = useI18n();
  const limits = useBrowserRequestLimits();
  if (!limits) return null;
  return <div className="helper" role="status" aria-live="polite">
    <span>{t("Execution requests remaining in this browser")}: {t("Minute {remaining}/{limit}", { remaining: limits.remaining_minute, limit: limits.per_minute })} · {t("Rolling 24 hours {remaining}/{limit}", { remaining: limits.remaining_day, limit: limits.per_day })}</span>
    {limits.retry_after_seconds > 0 && <p>{t("This browser has reached its execution request limit. Retry in {seconds} seconds. Your input is preserved.", { seconds: limits.retry_after_seconds })}</p>}
  </div>;
}

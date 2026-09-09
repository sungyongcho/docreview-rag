import { translate, type Locale } from "./i18n";

/** Short relative age for lists; falls back to the locale date for anything older than a day. */
export function relativeTime(iso: string, locale: Locale, now: number = Date.now()): string {
  const time = new Date(iso).getTime();
  if (!Number.isFinite(time)) return "";
  const seconds = Math.max(0, Math.round((now - time) / 1000));
  if (seconds < 60) return translate(locale, "Just now");
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return translate(locale, "{count} min ago", { count: minutes });
  const hours = Math.round(minutes / 60);
  if (hours < 24) return translate(locale, "{count} h ago", { count: hours });
  return new Date(time).toLocaleString(locale === "ko" ? "ko-KR" : "en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

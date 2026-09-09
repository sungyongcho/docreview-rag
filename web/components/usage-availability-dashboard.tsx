"use client";

import { type CSSProperties } from "react";
import { useI18n } from "@/lib/i18n";
import type { Readiness, ReleaseLimits } from "@/lib/types";
import "./usage-availability-dashboard.css";



/** Keep unknown or invalid server allowances distinct from a full allowance. */
export function allowancePercent(remaining: unknown, total: unknown): number | null {
  if (remaining == null || total == null || remaining === "" || total === "") return null;
  const left = Number(remaining), ceiling = Number(total);
  return Number.isFinite(left) && Number.isFinite(ceiling) && left >= 0 && ceiling > 0 ? Math.min(100, Math.max(0, left / ceiling * 100)) : null;
}

/** Display shared OpenAI reservations separately from rolling client request limits. */
export function UsageAvailabilityDashboard({ limits, readiness }: { limits: ReleaseLimits | null; readiness: Readiness | null }) {
  const { locale } = useI18n();
  const ko = locale === "ko";
  const text = (en: string, kr: string) => ko ? kr : en;
  const percent = allowancePercent(limits?.remaining_daily_cost_usd, limits?.daily_cost_usd);
  const percentLabel = percent == null ? "—" : percent > 0 && percent < 1 ? "<1%" : `${Math.floor(percent)}%`;
  const exhausted = percent === 0;
  const ipLimited = limits != null && (limits.remaining_minute <= 0 || limits.remaining_day <= 0);
  const status = percent == null ? text("Status unavailable", "상태 확인 중") : exhausted ? text("Shared allowance exhausted", "공용 한도 소진") : ipLimited ? text("Request limit reached", "접속 요청 한도 도달") : readiness?.review_enabled === false ? text("Answers unavailable", "답변 사용 불가") : text("Allowance available", "한도 내 사용 가능");
  const reset = limits?.daily_cost_reset_at_utc && Number.isFinite(Date.parse(limits.daily_cost_reset_at_utc)) ? new Date(limits.daily_cost_reset_at_utc).toLocaleString(locale, { timeZone: "UTC", timeZoneName: "short" }) : text("Unknown", "확인 중");
  const duration = (seconds: number) => {
    if (seconds <= 0) return text("No recovery pending", "복구 대기 없음");
    const hours = Math.floor(seconds / 3600), minutes = Math.floor(seconds % 3600 / 60), rest = Math.ceil(seconds % 60);
    return hours ? `${hours}${ko ? "시간" : "h"} ${minutes}${ko ? "분" : "m"}` : minutes ? `${minutes}${ko ? "분" : "m"} ${rest}${ko ? "초" : "s"}` : `${rest}${ko ? "초" : "s"}`;
  };
  return <div className="usage-dashboard">
    <div className="usage-shared" data-state={exhausted || ipLimited ? "blocked" : percent != null && percent < 20 ? "low" : "normal"}>
      <div className="usage-ring" role="img" aria-label={`${text("Shared OpenAI allowance remaining", "전체 이용자 공용 AI 잔여 한도")}: ${percent == null ? text("Unknown", "확인 중") : percentLabel}`} style={{ "--usage-remaining": `${percent ?? 0}%` } as CSSProperties}>
        <div><strong>{percent == null ? "—" : percentLabel}</strong><span>{text("remaining", "사용 가능")}</span></div>
      </div>
      <div className="usage-shared-copy"><span className="usage-eyebrow">{text("OPENAI · SHARED DAILY ALLOWANCE", "OPENAI · 전체 이용자 공용 한도")}</span><h3>{status}</h3><p>{text("All visitors share this server's daily OpenAI allowance for answers and query embeddings. This is not a personal spending limit.", "답변 생성과 질문 임베딩에 사용하는 서버의 일일 OpenAI 한도를 모든 이용자가 공유합니다. 개인 비용 한도가 아닙니다.")}</p><div className="usage-reset"><span>{text("Server allowance resets", "서버 공용 한도 초기화")}</span><strong>{reset}</strong></div><small>{text("Remaining allowance is based on reserved usage, not a final invoice. Resets at 00:00 UTC daily.", "잔여량은 사용 예약 기준이며 실제 청구액이 아닙니다. 매일 UTC 00:00에 초기화됩니다.")}</small></div>
    </div>
    <section className="usage-client"><h3>{text("Request allowance · this connection", "요청 가능량 · 현재 접속")}</h3><p>{text("Connections sharing an IP share these limits. Requests recover individually after 60 seconds or 24 hours; they do not reset at midnight.", "같은 IP의 접속자는 요청 한도를 공유합니다. 각 요청 후 60초·24시간이 지나면 순차 복구되며, 자정에 초기화되지 않습니다.")}</p><div className="usage-client-grid">{(["minute", "day"] as const).map(window => {
      const total = limits?.[window === "minute" ? "per_minute" : "per_day"];
      const remaining = limits?.[window === "minute" ? "remaining_minute" : "remaining_day"];
      const recovery = limits?.[window === "minute" ? "minute_reset_seconds" : "day_reset_seconds"];
      const progress = allowancePercent(remaining, total);
      return <div className="usage-window" key={window}><div><span>{window === "minute" ? text("Rolling minute", "최근 1분") : text("Rolling 24 hours", "최근 24시간")}</span><strong>{remaining == null || total == null ? "—" : `${remaining} / ${total}`}</strong></div><div className="usage-bar" aria-hidden="true"><i style={{ width: `${progress ?? 0}%` }} /></div><small>{text("Next recovery", "다음 요청량 복구")}: {recovery == null ? text("Unknown", "확인 중") : duration(recovery)}</small></div>;
    })}</div></section>
    {(exhausted || ipLimited) && <p className="usage-blocked" role="status">{exhausted ? text("OpenAI requests are paused until the server allowance resets. Saved results remain available.", "서버 공용 한도가 초기화될 때까지 OpenAI 요청이 차단됩니다. 저장된 결과는 계속 확인할 수 있습니다.") : text("This connection has reached its request limit. Try again after the next recovery.", "현재 접속의 요청 한도에 도달했습니다. 요청량 복구 후 다시 이용할 수 있습니다.")}</p>}
    <div className="usage-model"><span>{text("Answer model", "답변 모델")}: <strong>{readiness?.active_review_model ?? "—"}</strong></span><span>{text("Input token ceiling", "입력 토큰 한도")}: <strong>{limits?.max_input_tokens.toLocaleString(locale) ?? "—"}</strong></span><span>{text("Output token ceiling", "출력 토큰 한도")}: <strong>{limits?.max_output_tokens.toLocaleString(locale) ?? "—"}</strong></span></div>
  </div>;
}

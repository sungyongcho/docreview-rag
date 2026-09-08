"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { KO } from "./messages-ko";
import { localizedDocumentationRoute } from "./documentation-registry.mjs";
import { browserStorage, subscribeStorageRestored, storageEventValue } from "./storage";

export type Locale = "ko" | "en";
export const LOCALE_KEY = "docreview.locale";
type Values = Record<string, string | number>;

/** An explicit document language wins over a preference saved in another tab. */
export function preferredLocale(pathname: string, saved: string | null): Locale {
  const route = pathname.match(/\/docs\/(ko|en)(?:\/[^/]+)?\/?$/)?.[1];
  return route === "en" || (!route && saved === "en") ? "en" : "ko";
}

/** Keep the current document and deployment prefix when switching languages. */
export function localizedDocumentationPath(pathname: string, locale: Locale, hash = ""): string | null {
  return localizedDocumentationRoute(pathname, locale, hash);
}

/** Language remains usable when the browser blocks optional preference storage. */
export function savedLocale(): string | null {
  try { return browserStorage().getItem(LOCALE_KEY); }
  catch { return null; }
}

function persistLocale(locale: Locale) {
  try { browserStorage().setItem(LOCALE_KEY, locale); }
  catch { /* Keep the current interface usable without persistent browser storage. */ }
}

/** Translate app-generated summaries while keeping identifiers and server details intact. */
function runtimeKorean(source: string): string | undefined {
  const known = (value: string) => KO[value] ?? value;
  if (/^(OpenAI|Local)(: | (?:only )?ready)/.test(source)) {
    return source.split(" · ").map((part) => {
      const match = part.match(/^(OpenAI|Local)(?:: (.+)| (only )?ready)$/);
      if (!match) return part;
      return `${known(match[1])}${match[2] ? `: ${known(match[2])}` : match[3] ? "만 준비" : " 준비"}`;
    }).join(" · ");
  }
  const patterns: Array<[RegExp, (...parts: string[]) => string]> = [
    [/^Open (.+) and inspect its current state\.$/, (stage) => `${translate("ko", stage)} 단계로 이동해 현재 상태를 확인하세요.`],
    [/^Next step · (.+)$/, (stage) => `다음 단계 · ${known(stage)}`],
    [/^Running · (.+)$/, (stage) => `실행 중 · ${known(stage)}`],
    [/^Blocked · (.+)$/, (stage) => `선행 조건 필요 · ${known(stage)}`],
    [/^(?:after )?step (\d+) · (.+)$/, (order, stage) => `${order}단계 · ${known(stage)}${source.startsWith("after ") ? " 이후" : ""}`],
    [/^(\d[\d,]*) \/ (\d[\d,]*) filings on disk$/, (ready, total) => `${ready} / ${total} 원문 준비`],
    [/^(\d[\d,]*) documents?$/, (count) => `${count}개 문서`],
    [/^(\d[\d,]*) chunks?$/, (count) => `${count}개 청크`],
    [/^(\d[\d,]*) embedded$/, (count) => `${count}개 임베딩 완료`],
    [/^(\d[\d,]*) pending( · .+)?$/, (count, provider = "") => `${count}개 미처리${provider}`],
    [/^(\d[\d,]*) filings · hybrid ready$/, (count) => `${count}개 공시 · 하이브리드 검색 준비`],
    [/^(\d[\d,]*) filings (ingested|in the published corpus)$/, (count, state) => `${count}개 공시 · ${state === "ingested" ? "DB 적재 완료" : "공개 문서 범위"}`],
    [/^(\d[\d,]*) results?$/, (count) => `${count}개 평가 결과`],
    [/^(\d[\d,]*) (published )?snapshots?$/, (count, published) => `${count}개 ${published ? "게시된 " : ""}스냅샷`],
    [/^Supported · (\d+) citations?$/, (count) => `근거 확인 · 인용 ${count}개`],
    [/^(\d[\d,]*) chunks searchable$/, (count) => `${count}개 검색 가능 청크`],
    [/^(\d[\d,]*) chunks? still needs? vectors\. Run Backfill embeddings\.$/, (count) => `${count}개 청크의 임베딩이 필요합니다. 누락 임베딩 생성을 실행하세요.`],
    [/^Answer model: (.+)$/, (model) => `답변 모델: ${known(model)}`],
    [/^(\d[\d,]*) listed filings? not ingested yet \((.+)\)$/, (count, registry) => `${count}개 등록 공시 미적재 (${registry})`],
    [/^(\d[\d,]*) listed filings? (?:is|are) not on disk yet\. Run Download missing filings\.$/, (count) => `${count}개 등록 공시의 원문이 없습니다. 누락된 원문 다운로드를 실행하세요.`],
    [/^Queued #(\d+)$/, (position) => `대기 순서 #${position}`],
    [/^Last run (failed|interrupted|cancelled): ([\s\S]*)$/, (status, detail) => `이전 작업 ${known(status)}: ${detail}`],
    [/^Connected over (.+)\. Model information refreshes automatically every 30 seconds while this tab is visible\.$/, (protocol) => `${protocol === "its protocol" ? "서버 프로토콜" : protocol}로 연결했습니다. 이 탭이 보이는 동안 30초마다 모델 정보를 갱신합니다.`],
    [/^Schema (.+)\.$/, (status) => `스키마 상태: ${known(status)}.`],
    [/^openai · (enabled|disabled)$/, (status) => `openai · ${known(status)}`],
    [/^local · (.+)$/, (status) => `로컬 · ${known(status)}`],
    [/^Local · (.+)$/, (model) => `로컬 · ${model === "configured" ? "설정됨" : model}`],
    [/^The run passed its wall-clock limit(?: of ([\d.]+)s)?(?: at the (.+) step)?\.( A local model on CPU usually needs a longer one\.)?$/, (limit, node, advice) => `실행 시간 한도${limit ? `(${limit}초)` : ""}를 초과했습니다.${node ? ` 중단 단계: ${node}.` : ""}${advice ? " CPU에서 실행하는 로컬 모델은 더 긴 시간이 필요할 수 있습니다." : ""}`],
    [/^The run used all of its allowed steps(?: \(([\d.]+) of ([\d.]+)\))?(?: at the (.+) step)?\.$/, (observed, limit, node) => `허용된 실행 단계를 모두 사용했습니다.${limit ? ` 사용량: ${observed} / ${limit}.` : ""}${node ? ` 중단 단계: ${node}.` : ""}`],
    [/^The model call reached its (input token|output token|estimated cost) limit(?: \(([\d.]+) of ([\d.]+)\))?(?: at the (.+) step)?\.$/, (kind, used, limit, node) => `모델 호출의 ${kind === "input token" ? "입력 토큰" : kind === "output token" ? "출력 토큰" : "예상 비용"} 한도에 도달했습니다.${limit ? ` 사용량: ${used} / ${limit}.` : ""}${node ? ` 중단 단계: ${node}.` : ""}`],
    [/^The model call reached a budget limit(?: at the (.+) step)?\.$/, (node) => `모델 호출이 예산 한도에 도달했습니다.${node ? ` 중단 단계: ${node}.` : ""}`],
    [/^The model call was refused before it started: its prompt is about ([\d,]+) input tokens and ([\d,]+) remain of ([\d,]+)(?: at the (.+) step)?\.$/, (projected, remaining, limit, node) => `모델 호출을 시작하기 전에 거절했습니다: 프롬프트가 약 ${projected} 입력 토큰인데 한도 ${limit} 중 ${remaining}만 남아 있습니다.${node ? ` 중단 단계: ${node}.` : ""}`],
    [/^The run exceeded its (input|output) token budget(?: \(([\d.]+) of ([\d.]+)\))?(?: at the (.+) step)?\.$/, (kind, observed, limit, node) => `${kind === "input" ? "입력" : "출력"} 토큰 예산을 초과했습니다.${limit ? ` 사용량: ${observed} / ${limit}.` : ""}${node ? ` 중단 단계: ${node}.` : ""}`],
    [/^The model returned output that did not match the required schema(?: after (\d+) attempts)?\.( Smaller local models often fail structured output; try the OpenAI engine for this question\.)?$/, (attempts, advice) => `모델 응답이 요구된 형식을 충족하지 못했습니다.${attempts ? ` 시도 횟수: ${attempts}.` : ""}${advice ? " 작은 로컬 모델은 구조화된 응답에 실패할 수 있습니다. 이 질문에는 OpenAI 엔진을 시도해 보세요." : ""}`],
    [/^The model did not answer within the time limit(?: after (\d+) attempts)?\. Raise LOCAL_LLM_TIMEOUT_S, or choose a smaller model\.$/, (attempts) => `모델이 제한 시간 안에 답하지 못했습니다.${attempts ? ` 시도 횟수: ${attempts}.` : ""} LOCAL_LLM_TIMEOUT_S를 늘리거나 더 작은 모델을 선택하세요.`],
    [/^A (\S+) stopped the run(?: at the (\S+) step)?(: [\s\S]*)?$/, (kind, node, detail = "") => `${kind}${node ? ` · ${node} 단계` : ""}에서 실행이 중단됐습니다${detail}`],
    [/^The answer could not be generated \(([^)]+)\)(?: at the (\S+) step)?(?: after (\d+) attempts)?\.([\s\S]*)$/, (status, node, attempts, detail) => `답변을 생성하지 못했습니다 (${status}).${node ? ` 중단 단계: ${node}.` : ""}${attempts ? ` 시도 횟수: ${attempts}.` : ""}${detail}`],
  ];
  for (const [pattern, render] of patterns) {
    const match = source.match(pattern);
    if (match) return render(...match.slice(1));
  }
  return undefined;
}
export function translate(locale: Locale, source: string, values: Values = {}) {
  const selected = locale === "ko" ? KO[source] ?? runtimeKorean(source) ?? source : source;
  // Rename only catalog-owned product copy; source excerpts, labels and logs stay intact.
  const template = Object.hasOwn(KO, source) ? selected.replace(/DocReview(?! RAG)/g, "DocReview RAG") : selected;
  return template.replace(/\{(\w+)\}/g, (token, name: string) => values[name] === undefined ? token : String(values[name]));
}
const I18nContext = createContext({ locale: "en" as Locale, setLocale: (_locale: Locale) => {}, t: (source: string, values?: Values) => translate("en", source, values) });

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, update] = useState<Locale>("ko");
  const setLocale = useCallback((value: Locale) => {
    update(value);
    persistLocale(value);
    const destination = localizedDocumentationPath(window.location.pathname, value, window.location.hash);
    if (destination && destination !== window.location.pathname + window.location.hash) window.location.assign(destination);
  }, []);
  useEffect(() => {
    const initial = preferredLocale(window.location.pathname, savedLocale());
    update(initial);
    if (/\/docs\/(ko|en)(?:\/[^/]+)?\/?$/.test(window.location.pathname)) persistLocale(initial);
    function changed(event: StorageEvent) {
      const value = storageEventValue(event, LOCALE_KEY);
      if (value !== undefined) update(preferredLocale(window.location.pathname, value));
    }
    const restored = subscribeStorageRestored(() => update(preferredLocale(window.location.pathname, savedLocale())));
    window.addEventListener("storage", changed);
    return () => { restored(); window.removeEventListener("storage", changed); };
  }, []);
  useEffect(() => { document.documentElement.lang = locale; }, [locale]);
  const t = useCallback((source: string, values?: Values) => translate(locale, source, values), [locale]);
  return <I18nContext.Provider value={{ locale, setLocale, t }}>{children}</I18nContext.Provider>;
}
export function useI18n() { return useContext(I18nContext); }
export function LanguageSwitch({ locale: documentLocale }: { locale?: Locale } = {}) {
  const { locale, setLocale } = useI18n();
  const active = documentLocale ?? locale;
  return <div className="language-switch" role="group" aria-label="Language / 언어"><button type="button" lang="en" aria-pressed={active === "en"} onClick={() => setLocale("en")}>EN</button><button type="button" lang="ko" aria-pressed={active === "ko"} onClick={() => setLocale("ko")}>한국어</button></div>;
}

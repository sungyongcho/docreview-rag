import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { I18nProvider, LanguageSwitch, LOCALE_KEY, localizedDocumentationPath, preferredLocale, translate, useI18n } from "./i18n";
import { KO } from "./messages-ko";
import { HELP_SCREEN_TITLES, HELP_TOPICS } from "./help-content";
import { ANSWER_MODEL_HINT, STAGE_COPY, failureMessage } from "./pipeline";
import { localEngineStatus } from "./local-models";
import { ONBOARDING_KEY } from "./storage";
import { REVIEW_STEPS } from "@/components/review-progress";
import { DocumentationRedirect } from "@/components/documentation-navigation";

const navigation = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));

afterEach(() => { cleanup(); localStorage.clear(); window.history.replaceState({}, "", "/"); vi.clearAllMocks(); });

function TestScreen() {
  const { t } = useI18n();
  return <><LanguageSwitch /><h1>{t("Build")}</h1><textarea aria-label="User question" defaultValue="Keep my original question" /></>;
}

describe("Korean and English UI", () => {
  it("changes interface language without rewriting user content and follows another tab", () => {
    render(<I18nProvider><TestScreen /></I18nProvider>);
    expect(screen.getByRole("heading")).toHaveTextContent("데이터 준비");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Do not translate this question" } });
    fireEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(screen.getByRole("heading")).toHaveTextContent("Build");
    expect(screen.getByRole("textbox")).toHaveValue("Do not translate this question");
    expect(localStorage.getItem(LOCALE_KEY)).toBe("en");
    fireEvent(window, new StorageEvent("storage", { key: LOCALE_KEY, newValue: "ko" }));
    expect(screen.getByRole("heading")).toHaveTextContent("데이터 준비");
  });

  it("covers all literal UI messages and preserves interpolation parameters", () => {
    const missing = new Set<string>();
    for (const name of readdirSync("components").filter((name) => name.endsWith(".tsx") && !name.includes(".test."))) {
      const file = join("components", name);
      const tree = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
      function visit(node: ts.Node) {
        if (ts.isPropertyAssignment(node) && ["label", "title", "description", "mechanism", "tradeoff"].includes(node.name.getText(tree)) && ts.isStringLiteral(node.initializer)) {
          if (!(node.initializer.text in KO)) missing.add(node.initializer.text);
        }
        if (ts.isCallExpression(node) && node.expression.getText(tree) === "t" && node.arguments[0]) {
          function inspect(argument: ts.Node) {
            if (ts.isStringLiteral(argument) || ts.isNoSubstitutionTemplateLiteral(argument)) {
              if (!(argument.text in KO)) missing.add(argument.text);
            } else if (ts.isConditionalExpression(argument)) {
              inspect(argument.whenTrue);
              inspect(argument.whenFalse);
            }
          }
          inspect(node.arguments[0]);
        }
        ts.forEachChild(node, visit);
      }
      visit(tree);
    }
    expect([...missing]).toEqual([]);
    for (const [en, ko] of Object.entries(KO)) {
      const parameters = (text: string) => [...new Set(text.match(/\{\w+\}/g) ?? [])].sort();
      expect(parameters(ko), en).toEqual(parameters(en));
    }
    expect(translate("ko", "Delete {p0}", { p0: "Original title" })).toBe("Original title 삭제");
  });

  it("covers app-owned help, pipeline and progress copy selected through variables", () => {
    const messages = [
      ...Object.values(HELP_SCREEN_TITLES),
      ...Object.values(HELP_TOPICS).flatMap((topics) => topics.flatMap((topic) => [topic.title, ...topic.body, ...(topic.tune ? [topic.tune] : [])])),
      ...Object.values(STAGE_COPY).flatMap((stage) => [stage.title, stage.description, stage.why]),
      ...REVIEW_STEPS.flatMap((phase) => [phase.label, phase.detail]),
      ANSWER_MODEL_HINT,
    ];
    expect([...new Set(messages.filter((message) => !(message in KO)))]).toEqual([]);
  });

  it("translates generated counts, dependencies and model status without changing identifiers", () => {
    expect(translate("ko", "Open Parse & chunk and inspect its current state.")).toBe("파싱·청킹 단계로 이동해 현재 상태를 확인하세요.");
    expect(translate("ko", "1 result")).toBe("1개 평가 결과");
    expect(translate("ko", "2 published snapshots")).toBe("2개 게시된 스냅샷");
    expect(translate("ko", "1,200 pending · text-embedding-3-large")).toBe("1,200개 미처리 · text-embedding-3-large");
    expect(translate("ko", "after step 2 · Parse & chunk")).toBe("2단계 · 파싱·청킹 이후");
    expect(translate("ko", "Next step · Embeddings")).toBe("다음 단계 · 임베딩");
    expect(translate("ko", localEngineStatus({ enabled: true, protocol: "ollama" }))).toBe("ollama로 연결했습니다. 이 탭이 보이는 동안 30초마다 모델 정보를 갱신합니다.");
    expect(translate("ko", "DocReview source excerpt: keep original text")).toBe("DocReview source excerpt: keep original text");
    expect(translate("ko", "Delete {p0}", { p0: "DocReview source {raw}" })).toBe("DocReview source {raw} 삭제");
  });

  it("renders Korean runtime checking and local-engine loading at their display boundaries", async () => {
    vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    vi.resetModules();
    const { I18nProvider: Provider } = await import("./i18n");
    const { ServiceShell } = await import("@/components/service-shell");
    const { LocalEngineSettings } = await import("@/components/local-engine-settings");
    const { DEFAULT_SESSION_PROFILE } = await import("./types");
    try {
      localStorage.setItem(ONBOARDING_KEY, "done");
      render(<Provider><ServiceShell /></Provider>);
      expect(screen.getByRole("button", { name: "시스템 · 확인 중" })).toHaveTextContent("확인 중");
      cleanup();
      render(<Provider><LocalEngineSettings profile={{ ...DEFAULT_SESSION_PROFILE, engine: "local", local_model: "original-model-id" }} readiness={null} onChange={vi.fn()} /></Provider>);
      expect(screen.getByRole("status")).toHaveTextContent("로컬 모델 서버를 확인하는 중…");
      expect(screen.getByRole("option", { name: /original-model-id/ })).toHaveValue("original-model-id");
      fireEvent(window, new StorageEvent("storage", { key: LOCALE_KEY, newValue: "en" }));
      expect(screen.getByRole("status")).toHaveTextContent("Checking the local model server…");
    } finally {
      cleanup();
      vi.unstubAllGlobals();
      vi.unstubAllEnvs();
      vi.resetModules();
    }
  });

  it("translates runtime state labels without changing their raw values", () => {
    for (const [raw, expected] of [["healthy", "정상"], ["checking", "확인 중"], ["API down", "API 연결 끊김"], ["db degraded", "DB 상태 확인 필요"]]) {
      expect(translate("ko", "System · {p0}", { p0: translate("ko", raw) })).toBe(`시스템 · ${expected}`);
      expect(translate("en", raw)).toBe(raw);
    }
  });

  it("localizes operational summaries while preserving raw failure detail", () => {
    const detail = "DocReview provider detail: original text remains";
    expect(translate("ko", failureMessage({ status: "node_error", error_type: "StorageError", node: "retrieve", message: detail }))).toBe(`StorageError · retrieve 단계에서 실행이 중단됐습니다: ${detail}`);
    expect(translate("ko", failureMessage({ status: "budget_exceeded", resource: "wall_clock_s", limit: 120, blocked_node: "check" }))).toContain("실행 시간 한도(120초)를 초과했습니다. 중단 단계: check.");
    expect(translate("ko", failureMessage({ status: "budget_exceeded", resource: "output_tokens", limit: 4000, observed: 4100 }))).toBe("출력 토큰 예산을 초과했습니다. 사용량: 4100 / 4000.");
    expect(translate("ko", failureMessage({ code: "provider_failure", status: "budget_exceeded", node: "grade", budget: { which: "output_tokens", used: 600, limit: 600 } }))).toBe("모델 호출의 출력 토큰 한도에 도달했습니다. 사용량: 600 / 600. 중단 단계: grade.");
    expect(translate("ko", `Last run interrupted: ${detail}`)).toBe(`이전 작업 재시작으로 중단: ${detail}`);
  });

  it.each([
    ["/docreview-rag-agent/docs/", "overview", "/docs/en/"],
    ["/docreview-rag-agent/docs/cli/", "cli", "/docs/en/cli/"],
  ] as const)("resolves saved English for legacy route %s", (path, documentId, destination) => {
    window.history.replaceState({}, "", path);
    localStorage.setItem(LOCALE_KEY, "en");
    render(<DocumentationRedirect documentId={documentId} />);
    expect(navigation.replace).toHaveBeenCalledWith(destination);
  });

  it("keeps explicit document language consistent when another tab changes its preference", () => {
    window.history.replaceState({}, "", "/docreview-rag-agent/docs/en/cli/");
    localStorage.setItem(LOCALE_KEY, "ko");
    render(<I18nProvider><TestScreen /></I18nProvider>);
    expect(screen.getByRole("heading")).toHaveTextContent("Build");
    expect(localStorage.getItem(LOCALE_KEY)).toBe("en");
    fireEvent(window, new StorageEvent("storage", { key: LOCALE_KEY, newValue: "ko" }));
    expect(screen.getByRole("heading")).toHaveTextContent("Build");
    expect(document.documentElement.lang).toBe("en");
  });

  it("keeps document identity and deployment prefix during language changes", () => {
    expect(localizedDocumentationPath("/docreview-rag-agent/docs/en/cli/", "ko")).toBe("/docreview-rag-agent/docs/ko/cli/");
    expect(localizedDocumentationPath("/docs", "en")).toBe("/docs/en/");
    expect(localizedDocumentationPath("/docs/en/settings/", "ko", "#step-10")).toBe("/docs/ko/settings/#step-10");
    expect(preferredLocale("/docs/en/settings/", "ko")).toBe("en");
    expect(localizedDocumentationPath("/documents/", "en")).toBeNull();
    expect(preferredLocale("/docs/ko/", "en")).toBe("ko");
    expect(preferredLocale("/docs/", "en")).toBe("en");
    expect(preferredLocale("/docs/", "invalid")).toBe("ko");
  });
});

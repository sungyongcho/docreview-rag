import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { I18nProvider, LanguageSwitch, LOCALE_KEY, preferredLocale, translate, useI18n } from "./i18n";
import { localizedDocumentationRoute } from "./documentation-registry.mjs";
import { KO } from "./messages-ko";
import { HELP_SCREEN_TITLES, HELP_TOPICS } from "./help-content";
import { ANSWER_MODEL_HINT, STAGE_COPY, failureMessage } from "./pipeline";
import { localEngineStatus } from "./local-models";
import { ONBOARDING_KEY } from "./storage";
import { REVIEW_STEPS } from "@/components/review-progress";
import { FAILURE_FACTS, RUN_FACTS } from "@/components/review-response";
import { DocumentationRedirect } from "@/components/documentation-navigation";

const navigation = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));

afterEach(() => { cleanup(); localStorage.clear(); window.history.replaceState({}, "", "/"); vi.clearAllMocks(); });

function TestScreen() {
  const { t } = useI18n();
  return <><LanguageSwitch /><h1>{t("Build")}</h1><textarea aria-label="User question" defaultValue="Keep my original question" /></>;
}

/** Web directories whose strings can reach `t`. */
const UI_DIRECTORIES = ["app", "components", "lib"];
/**
 * Server code and served data whose messages, identifiers and values the UI displays through `t`,
 * such as golden-case facets and preset labels. Downloaded filings under data/corpus never reach `t`.
 */
const SERVER_DIRECTORIES = ["../app", "../schemas", "../scripts", "../data/golden", "../data/presets"];
/** Stands for a computed value inside a string the UI builds. */
const ANY_TEXT = "(.+)";

function sourceFiles(directories: string[], extension: RegExp): string[] {
  const files: string[] = [];
  for (const directory of directories) {
    for (const name of readdirSync(directory, { recursive: true }) as string[]) {
      if (!extension.test(name)) continue;
      // Tests may quote retired copy, and the catalog itself is what this check audits.
      if (/\.(test|spec)\./.test(name) || name.endsWith("messages-ko.ts")) continue;
      files.push(join(directory, name));
    }
  }
  return files;
}

/** Files the repository ships under the given directories. Local golden drafts, caches and
 * other untracked files stay out, so the result is the same on every checkout. */
function trackedFiles(directories: string[], extension: RegExp): string[] {
  const listed = execFileSync("git", ["ls-files", "-z", "--", ...directories], { encoding: "utf8" });
  return listed.split("\0").filter((name) => name !== "" && extension.test(name));
}

function escapeRegExp(text: string) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function isStringConcatenation(node: ts.Node): node is ts.BinaryExpression {
  return ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken;
}

/** Initializers of the file's named values, so a message composed from other constants can be read in full. */
function fileConstants(tree: ts.SourceFile): Map<string, ts.Expression> {
  const constants = new Map<string, ts.Expression>();
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) constants.set(node.name.text, node.initializer);
    ts.forEachChild(node, visit);
  }
  visit(tree);
  return constants;
}

/**
 * Regular-expression parts for a string-building expression: literal text stays, named constants are
 * read through, and any other computed value matches any text.
 */
function builtStringParts(node: ts.Node, constants: Map<string, ts.Expression>, resolving = new Set<string>()): string[] {
  const parts = (child: ts.Node) => builtStringParts(child, constants, resolving);
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return [escapeRegExp(node.text)];
  if (ts.isParenthesizedExpression(node)) return parts(node.expression);
  if (isStringConcatenation(node)) return [...parts(node.left), ...parts(node.right)];
  if (ts.isTemplateExpression(node)) {
    const result = [escapeRegExp(node.head.text)];
    for (const span of node.templateSpans) result.push(...parts(span.expression), escapeRegExp(span.literal.text));
    return result;
  }
  // Same-named values in different scopes could point at each other; stop instead of looping.
  if (!ts.isIdentifier(node) || resolving.has(node.text)) return [ANY_TEXT];
  const constant = constants.get(node.text);
  if (!constant) return [ANY_TEXT];
  return builtStringParts(constant, constants, new Set([...resolving, node.text]));
}

/** Every text the UI can pass to `t`: literal strings, strings it builds, and text the server sends. */
function reachableUiText() {
  const texts: string[] = [];
  const builtStrings: RegExp[] = [];
  for (const file of sourceFiles(UI_DIRECTORIES, /\.(tsx?|mjs)$/)) {
    const tree = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const constants = fileConstants(tree);
    function visit(node: ts.Node) {
      if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isJsxText(node)) texts.push(node.text);
      if (ts.isTemplateExpression(node) || isStringConcatenation(node)) {
        const parts = builtStringParts(node, constants);
        const literalText = parts.filter((part) => part !== ANY_TEXT).join("");
        // A pattern with almost no literal text would match every entry and hide real leftovers.
        if (literalText.trim().length >= 3) builtStrings.push(new RegExp(`^${parts.join("")}$`, "s"));
      }
      ts.forEachChild(node, visit);
    }
    visit(tree);
  }
  for (const file of sourceFiles(UI_DIRECTORIES, /\.json$/)) texts.push(readFileSync(file, "utf8"));
  for (const file of trackedFiles(SERVER_DIRECTORIES, /\.(py|json)$/)) texts.push(readFileSync(file, "utf8"));
  const joined = texts.join("\n");
  // The UI prints API identifiers such as `stable_hit` with spaces before translating them.
  return { corpus: `${joined}\n${joined.replaceAll("_", " ")}`, builtStrings };
}

describe("Korean and English UI", () => {
  it("changes interface language without rewriting user content and follows another tab", () => {
    localStorage.setItem(LOCALE_KEY, "ko");
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
    // Hooks and helpers without markup live in .ts files, and their messages reach `t` too.
    const componentFiles = readdirSync("components").filter(
      (name) => /\.tsx?$/.test(name) && !name.includes(".test."),
    );
    for (const name of componentFiles) {
      const file = join("components", name);
      // Parsed as TSX, a .ts file's `<Type>value` assertion would read as markup.
      const scriptKind = name.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
      const source = readFileSync(file, "utf8");
      const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, scriptKind);
      function visit(node: ts.Node) {
        if (ts.isPropertyAssignment(node) && ["label", "title", "description", "mechanism", "tradeoff"].includes(node.name.getText(tree)) && ts.isStringLiteral(node.initializer)) {
          // An empty initial form value is metadata, not a translatable UI message.
          if (node.initializer.text && !(node.initializer.text in KO)) missing.add(node.initializer.text);
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

  it("covers app-owned help, pipeline, progress and diagnostic copy chosen by variables", () => {
    const messages = [
      ...Object.values(HELP_SCREEN_TITLES),
      ...Object.values(HELP_TOPICS).flatMap((topics) => topics.flatMap((topic) => [topic.title, ...topic.body, ...(topic.tune ? [topic.tune] : [])])),
      ...Object.values(STAGE_COPY).flatMap((stage) => [stage.title, stage.description, stage.why]),
      ...REVIEW_STEPS.flatMap((phase) => [phase.label, phase.detail]),
      ...RUN_FACTS.map(([, label]) => label),
      ...FAILURE_FACTS.map(([, label]) => label),
      ANSWER_MODEL_HINT,
    ];
    expect([...new Set(messages.filter((message) => !(message in KO)))]).toEqual([]);
  });

  it("keeps only Korean entries whose English text the UI can still show", () => {
    const { corpus, builtStrings } = reachableUiText();
    const isReachable = (english: string) => corpus.includes(english) || builtStrings.some((pattern) => pattern.test(english));
    expect(Object.keys(KO).filter((english) => !isReachable(english))).toEqual([]);
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
      localStorage.setItem(LOCALE_KEY, "ko");
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
    ["/docreview-rag/docs/", "overview", "/docs/en/"],
    ["/docreview-rag/docs/cli/", "cli", "/docs/en/cli/"],
  ] as const)("resolves saved English for legacy route %s", (path, documentId, destination) => {
    window.history.replaceState({}, "", path);
    localStorage.setItem(LOCALE_KEY, "en");
    render(<DocumentationRedirect documentId={documentId} />);
    expect(navigation.replace).toHaveBeenCalledWith(destination);
  });

  it("keeps explicit document language consistent when another tab changes its preference", () => {
    window.history.replaceState({}, "", "/docreview-rag/docs/en/cli/");
    localStorage.setItem(LOCALE_KEY, "ko");
    render(<I18nProvider><TestScreen /></I18nProvider>);
    expect(screen.getByRole("heading")).toHaveTextContent("Build");
    expect(localStorage.getItem(LOCALE_KEY)).toBe("en");
    fireEvent(window, new StorageEvent("storage", { key: LOCALE_KEY, newValue: "ko" }));
    expect(screen.getByRole("heading")).toHaveTextContent("Build");
    expect(document.documentElement.lang).toBe("en");
  });

  it("changes the app locale in place even on a document route", () => {
    window.history.replaceState({}, "", "/docreview-rag/docs/ko/cli/");
    render(<I18nProvider><TestScreen /></I18nProvider>);
    expect(screen.getByRole("heading")).toHaveTextContent("데이터 준비");
    fireEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(screen.getByRole("heading")).toHaveTextContent("Build");
    expect(localStorage.getItem(LOCALE_KEY)).toBe("en");
    expect(window.location.pathname).toBe("/docreview-rag/docs/ko/cli/");
    expect(navigation.replace).not.toHaveBeenCalled();
  });

  it("hands language choices to a document-supplied callback instead of the app locale", () => {
    const chosen = vi.fn();
    render(<I18nProvider><LanguageSwitch locale="ko" onChange={chosen} /></I18nProvider>);
    fireEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(chosen).toHaveBeenCalledWith("en");
    expect(screen.getByRole("button", { name: "EN" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "한국어" })).toHaveAttribute("aria-pressed", "true");
    expect(localStorage.getItem(LOCALE_KEY)).toBeNull();
  });

  it("keeps document identity and deployment prefix during language changes", () => {
    expect(localizedDocumentationRoute("/docreview-rag/docs/en/cli/", "ko")).toBe("/docreview-rag/docs/ko/cli/");
    expect(localizedDocumentationRoute("/docs", "en")).toBe("/docs/en/");
    expect(localizedDocumentationRoute("/docs/en/settings/", "ko", "#step-10")).toBe("/docs/ko/settings/#step-10");
    expect(preferredLocale("/docs/en/settings/", "ko")).toBe("en");
    expect(localizedDocumentationRoute("/documents/", "en")).toBeNull();
    expect(preferredLocale("/docs/ko/", "en")).toBe("ko");
    expect(preferredLocale("/docs/", "en")).toBe("en");
    expect(preferredLocale("/docs/", "invalid", "en-US")).toBe("en");
  });

  it.each([["ko", "ko"], ["ko-KR", "ko"], ["en-US", "en"], ["fr-FR", "en"], ["kok-IN", "en"], ["", "en"]] as const)("uses %s as the first-visit browser language", (browserLanguage, expected) => {
    expect(preferredLocale("/docreview-rag/", null, browserLanguage)).toBe(expected);
    expect(preferredLocale("/docs/", "invalid", browserLanguage)).toBe(expected);
  });

  it("keeps saved choices and explicit document locales ahead of the browser language", () => {
    expect(preferredLocale("/", "en", "ko-KR")).toBe("en");
    expect(preferredLocale("/", "ko", "fr-FR")).toBe("ko");
    expect(preferredLocale("/docs/en/", "ko", "ko-KR")).toBe("en");
    expect(preferredLocale("/docs/ko/", "en", "en-US")).toBe("ko");
  });

  it.each([["ko-KR", "/docs/ko/"], ["de-DE", "/docs/en/"]] as const)("uses the browser language for an unlocalized guide entry (%s)", (language, destination) => {
    const browserLanguage = vi.spyOn(window.navigator, "language", "get").mockReturnValue(language);
    try {
      window.history.replaceState({}, "", "/docreview-rag/docs/");
      render(<DocumentationRedirect documentId="overview" />);
      expect(navigation.replace).toHaveBeenCalledWith(destination);
    } finally { browserLanguage.mockRestore(); }
  });

  it("keeps browser-based selection and manual switching usable when preference storage is blocked", () => {
    const browserLanguage = vi.spyOn(window.navigator, "language", "get").mockReturnValue("ko-KR");
    const read = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("Storage blocked"); });
    const write = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Storage blocked"); });
    try {
      render(<I18nProvider><TestScreen /></I18nProvider>);
      expect(screen.getByRole("heading")).toHaveTextContent("데이터 준비");
      fireEvent.click(screen.getByRole("button", { name: "EN" }));
      expect(screen.getByRole("heading")).toHaveTextContent("Build");
    } finally { read.mockRestore(); write.mockRestore(); browserLanguage.mockRestore(); }
  });

  it.each([["ko-KR", "데이터 준비", "EN", "Build", "en"], ["fr-FR", "Build", "한국어", "데이터 준비", "ko"]] as const)("detects %s on first visit and restores an explicit choice after remount", (language, first, button, chosen, saved) => {
    const browserLanguage = vi.spyOn(window.navigator, "language", "get").mockReturnValue(language);
    try {
      const page = render(<I18nProvider><TestScreen /></I18nProvider>);
      expect(screen.getByRole("heading")).toHaveTextContent(first);
      fireEvent.click(screen.getByRole("button", { name: button }));
      expect(localStorage.getItem(LOCALE_KEY)).toBe(saved);
      page.unmount();
      render(<I18nProvider><TestScreen /></I18nProvider>);
      expect(screen.getByRole("heading")).toHaveTextContent(chosen);
    } finally { browserLanguage.mockRestore(); }
  });
});

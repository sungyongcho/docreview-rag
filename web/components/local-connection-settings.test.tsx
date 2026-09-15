import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { LocalConnectionSettings } from "./local-connection-settings";
import type { LocalLLMConnection, LocalLLMDiagnostics, Readiness } from "@/lib/types";
import { I18nProvider, LanguageSwitch, LOCALE_KEY } from "@/lib/i18n";

const INITIAL: LocalLLMConnection = {
  base_url: "http://host.docker.internal:11434", initial_base_url: "http://host.docker.internal:11434", protocol: "auto",
  source: "environment", error: null, local: { enabled: true, protocol: "ollama", models: [] },
  selected_server_id: "default", servers: [
    { id: "default", name: "Default", base_url: "http://host.docker.internal:11434", protocol: "auto", is_default: true },
    { id: "studio", name: "Studio", base_url: "http://studio:11434", protocol: "ollama", is_default: false },
  ],
};
const DIAGNOSTICS: LocalLLMDiagnostics = {
  checked_at: "2026-09-05T12:00:00Z", server_id: "default", server_name: "Default", protocol: "ollama",
  reachable: false, available: false, model_count: null, answer_model_count: null, models: [], checks: [
    { id: "configuration", status: "passed", code: "configured", remediation: [] },
    { id: "connection", status: "failed", code: "refused", remediation: ["check_ollama_service", "check_listener", "run_connection_diagnostics"] },
    { id: "models", status: "unknown", code: "unconfirmed", remediation: [] },
  ],
};
function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}
afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

it("selects Default without requiring an address and links to the localized setup guide in a new tab", async () => {
  const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => response(INITIAL)); vi.stubGlobal("fetch", fetchMock);
  render(<LocalConnectionSettings />);
  await waitFor(() => expect(screen.getByLabelText("Model server")).toBeEnabled());
  expect(screen.getByLabelText("Model server")).toHaveValue("default");
  expect(screen.queryByLabelText("Server URL")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Connect" })).toBeEnabled();
  expect(screen.getByRole("link", { name: /Set up Ollama/ })).toHaveAttribute("href", "/docreview-rag/docs/en/ollama/");
  expect(screen.getByRole("link", { name: /Set up Ollama/ })).toHaveAttribute("target", "_blank");
  fireEvent.change(screen.getByLabelText("Model server"), { target: { value: "studio" } });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Connect" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(fetchMock.mock.calls[1][1]?.body).toBe(JSON.stringify({ server_id: "studio" }));
});

it("connects Default by identity rather than exposing or resubmitting its address", async () => {
  const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => response(INITIAL)); vi.stubGlobal("fetch", fetchMock);
  render(<LocalConnectionSettings />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Connect" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Connect" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(fetchMock.mock.calls[1][1]?.body).toBe('{"server_id":"default"}');
  expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/select\/?$/);
});

it("adds a named server only through Add a server and preserves invalid drafts", async () => {
  const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => response(INITIAL)); vi.stubGlobal("fetch", fetchMock);
  render(<LocalConnectionSettings />);
  await waitFor(() => expect(screen.getByLabelText("Model server")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Model server"), { target: { value: "__add_server__" } });
  fireEvent.change(screen.getByLabelText("Server name"), { target: { value: "Office" } });
  fireEvent.change(screen.getByLabelText("Server URL"), { target: { value: "http://name:secret@office:11434" } });
  expect(screen.getByRole("button", { name: "Add & connect" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Run connection diagnostics" })).toBeDisabled();
  expect(screen.getByLabelText("Server URL")).toHaveValue("http://name:secret@office:11434");
  fireEvent.change(screen.getByLabelText("Server URL"), { target: { value: "http://office:11434" } });
  fireEvent.change(screen.getByLabelText("Protocol"), { target: { value: "ollama" } });
  fireEvent.click(screen.getByRole("button", { name: "Add & connect" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/servers\/?$/);
  expect(fetchMock.mock.calls[1][1]?.body).toBe(JSON.stringify({ name: "Office", base_url: "http://office:11434", protocol: "ollama" }));
});

it("keeps the working server and failed draft visible across a language change", async () => {
  localStorage.setItem(LOCALE_KEY, "en");
  vi.stubGlobal("fetch", vi.fn(async (_input, init) => init?.method === "POST" ? response({ error: "local_connection_failed", detail: "Connection refused" }, 503) : response(INITIAL)));
  render(<I18nProvider><LanguageSwitch /><LocalConnectionSettings /></I18nProvider>);
  await waitFor(() => expect(screen.getByLabelText("Model server")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Model server"), { target: { value: "__add_server__" } });
  fireEvent.change(screen.getByLabelText("Server name"), { target: { value: "Office" } });
  fireEvent.change(screen.getByLabelText("Server URL"), { target: { value: "http://office:11434" } });
  fireEvent.click(screen.getByRole("button", { name: "Add & connect" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Your previous connection setting was kept.");
  fireEvent.click(screen.getByRole("button", { name: "한국어" }));
  expect(screen.getByLabelText("서버 주소")).toHaveValue("http://office:11434");
  expect(screen.getByRole("alert")).toHaveTextContent("기존 연결 설정을 유지했습니다.");
  expect(screen.getByRole("link", { name: /macOS·Linux에서 Ollama/ })).toHaveAttribute("href", "/docreview-rag/docs/ko/ollama/");
});

it("runs selected-server diagnostics without saving or replacing the active connection", async () => {
  const changed = vi.fn();
  const fetchMock = vi.fn(async (_input, init) => response(init?.method === "POST" ? { ...DIAGNOSTICS, server_id: "studio", server_name: "Studio" } : INITIAL));
  vi.stubGlobal("fetch", fetchMock); render(<LocalConnectionSettings onChanged={changed} />);
  await waitFor(() => expect(screen.getByLabelText("Model server")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Model server"), { target: { value: "studio" } });
  fireEvent.click(screen.getByRole("button", { name: "Run connection diagnostics" }));
  const panel = await screen.findByRole("region", { name: "Connection diagnostics" });
  expect(panel).toHaveTextContent("The server refused the connection.");
  expect(panel).toHaveTextContent("Check that Ollama is running");
  expect(panel).toHaveTextContent("Run rag-dev doctor");
  expect(changed).not.toHaveBeenCalled();
  expect(fetchMock.mock.calls[1][1]?.body).toBe('{"server_id":"studio"}');
  expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/diagnostics\/?$/);
  expect(within(screen.getByRole("region", { name: "Connection status" })).getByText("Default")).toBeInTheDocument();
});

it("cancels a diagnostic on unmount and prevents duplicate operations while checking", async () => {
  let diagnosticSignal: AbortSignal | undefined;
  const fetchMock = vi.fn(async (_input, init) => {
    if (init?.method === "POST") { diagnosticSignal = init.signal; return new Promise<Response>(() => {}); }
    return response(INITIAL);
  });
  vi.stubGlobal("fetch", fetchMock); const view = render(<LocalConnectionSettings />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Run connection diagnostics" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Run connection diagnostics" }));
  expect(screen.getByRole("button", { name: "Checking connection…" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Connect" })).toBeDisabled();
  expect(screen.getByLabelText("Model server")).toBeDisabled();
  view.unmount(); expect(diagnosticSignal?.aborted).toBe(true);
});

it("localizes diagnostic status values and uses neutral details wording in Korean", async () => {
  localStorage.setItem(LOCALE_KEY, "ko");
  vi.stubGlobal("fetch", vi.fn(async (_input, init) => response(init?.method === "POST" ? DIAGNOSTICS : INITIAL)));
  render(<I18nProvider><LocalConnectionSettings /></I18nProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "연결 진단 실행" }));
  const panel = await screen.findByRole("region", { name: "연결 진단" });
  expect(panel).toHaveTextContent("통과");
  expect(panel).toHaveTextContent("실패");
  expect(panel).toHaveTextContent("확인되지 않음");
  expect(within(panel).getByText("진단 상세")).toBeInTheDocument();
  expect(within(panel).queryByText("Passed")).not.toBeInTheDocument();
});

it("disconnects and restores Default without dropping registered choices", async () => {
  const fetchMock = vi.fn(async (input, init) => response(String(input).replace(/\/?(\?|$)/, "$1").endsWith("/disconnect")
    ? { ...INITIAL, base_url: null, source: "disabled", local: { enabled: false, reason: "disconnected" } } : INITIAL));
  vi.stubGlobal("fetch", fetchMock); render(<LocalConnectionSettings />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Disconnect" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Disconnect" })).toBeDisabled());
  expect(screen.getByRole("option", { name: "Studio" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Use Default" }));
  expect(await screen.findByText("Default server restored. Your added servers are kept.")).toBeInTheDocument();
  expect(String(fetchMock.mock.calls.at(-1)?.[0])).toMatch(/\/select\/?$/);
  expect(fetchMock.mock.calls.at(-1)?.[1]?.body).toBe('{"server_id":"default"}');
});

it("loads a legacy saved custom connection without switching it to Default", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response({ ...INITIAL, servers: undefined, selected_server_id: undefined, base_url: "http://old:11434", source: "saved" })));
  render(<LocalConnectionSettings />);
  await waitFor(() => expect(screen.getByLabelText("Model server")).toHaveValue("legacy"));
  expect(screen.getByRole("option", { name: "Saved connection" })).toBeInTheDocument();
  expect(screen.queryByLabelText("Server URL")).not.toBeInTheDocument();
});

it("keeps a working custom connection when the Default replacement check fails", async () => {
  const changed = vi.fn();
  const current = { ...INITIAL, selected_server_id: "studio", base_url: "http://studio:11434" };
  const fetchMock = vi.fn(async (_input, init) => init?.method === "POST" ? response({ detail: "Default is unreachable" }, 503) : response(current));
  vi.stubGlobal("fetch", fetchMock); render(<LocalConnectionSettings onChanged={changed} />);
  await waitFor(() => expect(screen.getByLabelText("Model server")).toHaveValue("studio"));
  fireEvent.click(screen.getByRole("button", { name: "Use Default" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Your previous connection setting was kept.");
  expect(screen.getByLabelText("Model server")).toHaveValue("studio");
  expect(within(screen.getByRole("region", { name: "Connection status" })).getByText("Studio")).toBeInTheDocument();
  expect(changed).not.toHaveBeenCalled();
  expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/select\/?$/);
});

it("offers a load retry and copies the safe CLI diagnostic commands exactly", async () => {
  let failed = true;
  vi.stubGlobal("fetch", vi.fn(async () => failed ? response({ detail: "offline" }, 503) : response(INITIAL)));
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  render(<LocalConnectionSettings />);
  const retry = await screen.findByRole("button", { name: "Retry" }); failed = false; fireEvent.click(retry);
  await waitFor(() => expect(screen.getByLabelText("Model server")).toBeEnabled());
  fireEvent.click(screen.getByText("Diagnose from the terminal"));
  fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("source ./rag-alias.sh\nrag-dev doctor"));
});


const ANSWER_MODEL = { name: "gemma", selectable: true, loaded: false, size_bytes: 100, family: null, parameter_size: null, quantization_level: null, capabilities: ["completion"] };

it.each(["en", "ko"] as const)("puts the next model action before connection controls without generating in %s", async (locale) => {
  localStorage.setItem(LOCALE_KEY, locale);
  const connected = { ...INITIAL, local: { enabled: true, protocol: "ollama", models: [ANSWER_MODEL] } };
  const fetchMock = vi.fn(async () => response(connected)); vi.stubGlobal("fetch", fetchMock);
  const onOpen = vi.fn();
  render(<I18nProvider><LocalConnectionSettings localModel="gemma" selectedEngine="openai" onOpenModelSelection={onOpen} /></I18nProvider>);
  const next = await screen.findByRole("status", { name: locale === "en" ? "Local model status" : "로컬 모델 상태" });
  const button = screen.getByRole("button", { name: locale === "en" ? "Choose or use a model in conversation" : "대화에서 모델 선택·사용하기" });
  expect(next).toHaveTextContent(locale === "en" ? "Model not loaded" : "모델 미적재");
  expect(next).toHaveTextContent("OpenAI");
  expect(next.compareDocumentPosition(screen.getByRole("group", { name: locale === "en" ? "Connection actions" : "연결 관리" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  fireEvent.click(button);
  expect(onOpen).toHaveBeenCalledOnce();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("propagates actual use metadata while preserving unknown measurements before use", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response({ ...INITIAL, local: { enabled: true, models: [ANSWER_MODEL] } })));
  const view = render(<LocalConnectionSettings localModel="gemma" selectedEngine="local" onOpenModelSelection={vi.fn()} />);
  const next = await screen.findByRole("status", { name: "Local model status" });
  expect(next).toHaveTextContent("Model not loaded");
  const readiness = { status: "ready", mode: "runtime", admin_mode: "live", policy_revision: "test", models: {}, review_enabled: true, active_review_model: null, corpus: { availability: "not_applicable", database_connected: null, schema_status: null, schema_message: null, documents: 0, chunks: 0, embedded_chunks: 0, pending_embeddings: 0, bm25_ready: false, writable: false }, review_engines: { local: { enabled: true, models: [{ ...ANSWER_MODEL, loaded: true, placement: "gpu" }] } } } as Readiness;
  view.rerender(<LocalConnectionSettings localModel="gemma" selectedEngine="local" readiness={readiness} onOpenModelSelection={vi.fn()} />);
  expect(next).toHaveTextContent("Ready to answer");
  expect(next).toHaveClass("ready");
});

it.each([
  [{ enabled: false, reason: "unreachable" }, "Server unreachable"],
  [{ enabled: false, reason: "no_answer_models", models: [] }, "Model download required"],
  [{ enabled: true, models: [ANSWER_MODEL] }, "Selected model unavailable"],
])("gives recovery for a limited local state: %j", async (local, message) => {
  vi.stubGlobal("fetch", vi.fn(async () => response({ ...INITIAL, local })));
  render(<LocalConnectionSettings localModel="removed" selectedEngine="local" onOpenModelSelection={vi.fn()} />);
  expect(await screen.findByRole("status", { name: "Local model status" })).toHaveTextContent(message);
});

it("renders disconnected public controls without any local backend requests", () => {
  const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
  render(<LocalConnectionSettings readOnly />);
  expect(screen.getByRole("combobox", { name: "Model server" })).toBeDisabled();
  expect(screen.getByRole("option", { name: "Not connected" })).toBeInTheDocument();
  for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
  expect(fetchMock).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
});

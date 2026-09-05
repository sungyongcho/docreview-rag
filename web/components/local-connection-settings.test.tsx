import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { LocalConnectionSettings } from "./local-connection-settings";
import type { LocalLLMConnection } from "@/lib/types";
import { I18nProvider, LanguageSwitch } from "@/lib/i18n";

const INITIAL: LocalLLMConnection = {
  base_url: "http://model:11434", initial_base_url: "http://initial:11434", protocol: "auto",
  source: "environment", error: null, local: { enabled: true, protocol: "ollama", models: [] },
};
function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}
afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

it.each([
  ["default", "Application defaults"],
  ["dotenv", ".env file"],
  ["invalid", "Invalid saved settings"],
] as const)("labels the %s configuration source without changing its value", async (source, label) => {
  vi.stubGlobal("fetch", vi.fn(async () => response({ ...INITIAL, source })));
  render(<LocalConnectionSettings />);
  expect(await screen.findByText(label)).toBeInTheDocument();
  expect(screen.getByLabelText("Server URL")).toHaveValue(INITIAL.base_url);
});

it("connects and saves a probed URL, then disconnects and restores initial configuration", async () => {
  const onChanged = vi.fn();
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/disconnect")) return response({ ...INITIAL, base_url: null, source: "disabled", local: { enabled: false, reason: "disconnected" } });
    if (url.endsWith("/reset")) return response({ ...INITIAL, base_url: INITIAL.initial_base_url });
    if (init?.method === "POST") return response({ ...INITIAL, base_url: "http://new:11434", source: "saved" });
    return response(INITIAL);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<LocalConnectionSettings onChanged={onChanged} />);
  await waitFor(() => expect(screen.getByLabelText("Server URL")).toHaveValue(INITIAL.base_url));
  expect(screen.getByText("Environment defaults")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Server URL"), { target: { value: "http://new:11434" } });
  fireEvent.change(screen.getByLabelText("Protocol"), { target: { value: "ollama" } });
  fireEvent.click(screen.getByRole("button", { name: "Connect & save" }));
  await waitFor(() => expect(screen.getByText("Saved connection")).toBeInTheDocument());
  expect(fetchMock.mock.calls.find(([, init]) => init?.method === "POST")?.[1]?.body).toBe(JSON.stringify({ base_url: "http://new:11434", protocol: "ollama" }));
  expect(onChanged).toHaveBeenCalledWith(INITIAL.local);
  fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
  await waitFor(() => expect(screen.getAllByText("Disconnected")[0]).toBeInTheDocument());
  expect(screen.getByRole("button", { name: "Disconnect" })).toBeDisabled();
  expect(onChanged).toHaveBeenLastCalledWith({ enabled: false, reason: "disconnected" });
  fireEvent.click(screen.getByRole("button", { name: "Restore defaults" }));
  await waitFor(() => expect(screen.getByLabelText("Server URL")).toHaveValue(INITIAL.initial_base_url));
  expect(screen.getByText("Environment defaults")).toBeInTheDocument();
});

it("reports probe failure while retaining the previous active connection", async () => {
  const onChanged = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === "POST"
    ? response({ error: { code: "connection_failed", message: "The model server is unreachable." } }, 503)
    : response(INITIAL)));
  render(<LocalConnectionSettings onChanged={onChanged} />);
  await waitFor(() => expect(screen.getByLabelText("Server URL")).toHaveValue(INITIAL.base_url));
  fireEvent.change(screen.getByLabelText("Server URL"), { target: { value: "http://broken:11434" } });
  fireEvent.click(screen.getByRole("button", { name: "Connect & save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Your previous connection setting was kept.");
  expect(screen.getByText(INITIAL.base_url!)).toBeInTheDocument();
  expect(screen.getByText("Environment defaults")).toBeInTheDocument();
  expect(onChanged).not.toHaveBeenCalled();
});

it("switches connection guidance while preserving the entered URL and raw server error", async () => {
  const detail = "DocReview endpoint rejected the request: original server detail";
  vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === "POST"
    ? response({ error: { code: "connection_failed", message: detail } }, 503)
    : response(INITIAL)));
  render(<I18nProvider><LanguageSwitch /><LocalConnectionSettings /></I18nProvider>);
  await waitFor(() => expect(screen.getByLabelText("서버 주소")).toHaveValue(INITIAL.base_url));
  expect(screen.getByText("ollama로 연결했습니다. 이 탭이 보이는 동안 30초마다 모델 정보를 갱신합니다.")).toBeInTheDocument();
  const input = screen.getByLabelText("서버 주소");
  fireEvent.change(input, { target: { value: "http://my-model:11434" } });
  fireEvent.click(screen.getByRole("button", { name: "연결 및 저장" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(detail);
  expect(screen.getByRole("alert")).toHaveTextContent("기존 연결 설정을 유지했습니다.");
  fireEvent.click(screen.getByRole("button", { name: "EN" }));
  expect(screen.getByLabelText("Server URL")).toHaveValue("http://my-model:11434");
  expect(screen.getByRole("alert")).toHaveTextContent(detail);
  expect(screen.getByRole("alert")).toHaveTextContent("Your previous connection setting was kept.");
});

it("shows the active connection action and prevents duplicate saves while it is pending", async () => {
  let finish: (value: Response) => void = () => {};
  const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === "POST"
    ? new Promise<Response>((resolve) => { finish = resolve; }) : response(INITIAL));
  vi.stubGlobal("fetch", fetchMock);
  render(<LocalConnectionSettings />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Connect & save" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Connect & save" }));
  expect(screen.getByRole("button", { name: "Connecting…" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Disconnect" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Restore defaults" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Connecting…" }));
  expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  finish(response(INITIAL));
  await waitFor(() => expect(screen.getByRole("button", { name: "Connect & save" })).toBeEnabled());
});

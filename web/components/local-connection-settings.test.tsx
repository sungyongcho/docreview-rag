import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { LocalConnectionSettings } from "./local-connection-settings";
import type { LocalLLMConnection } from "@/lib/types";

const INITIAL: LocalLLMConnection = {
  base_url: "http://model:11434", initial_base_url: "http://initial:11434", protocol: "auto",
  source: "environment", error: null, local: { enabled: true, protocol: "ollama", models: [] },
};
function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

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
  expect(screen.getByText("environment")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Server URL"), { target: { value: "http://new:11434" } });
  fireEvent.change(screen.getByLabelText("Protocol"), { target: { value: "ollama" } });
  fireEvent.click(screen.getByRole("button", { name: "Connect & save" }));
  await waitFor(() => expect(screen.getByText("saved")).toBeInTheDocument());
  expect(fetchMock.mock.calls.find(([, init]) => init?.method === "POST")?.[1]?.body).toBe(JSON.stringify({ base_url: "http://new:11434", protocol: "ollama" }));
  expect(onChanged).toHaveBeenCalledWith(INITIAL.local);
  fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
  await waitFor(() => expect(screen.getByText("disabled")).toBeInTheDocument());
  expect(screen.getByRole("button", { name: "Disconnect" })).toBeDisabled();
  expect(onChanged).toHaveBeenLastCalledWith({ enabled: false, reason: "disconnected" });
  fireEvent.click(screen.getByRole("button", { name: "Reset to initial connection" }));
  await waitFor(() => expect(screen.getByLabelText("Server URL")).toHaveValue(INITIAL.initial_base_url));
  expect(screen.getByText("environment")).toBeInTheDocument();
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
  expect(screen.getByText("environment")).toBeInTheDocument();
  expect(onChanged).not.toHaveBeenCalled();
});

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AnswerEngineRows } from "./answer-engine-light";
import { PrepareLocalModel } from "./prepare-local-model";
import { prepareLocalLLM } from "@/lib/api";

vi.mock("@/lib/api", () => ({ prepareLocalLLM: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("loads only after clicking and forwards verified state", async () => {
  const onPrepared = vi.fn();
  const result = { local: { enabled: true, models: [{ name: "gemma", loaded: true }] } };
  vi.mocked(prepareLocalLLM).mockResolvedValue(result as Awaited<ReturnType<typeof prepareLocalLLM>>);
  render(<PrepareLocalModel model="gemma" onPrepared={onPrepared} />);
  expect(prepareLocalLLM).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Prepare model" }));
  expect(screen.getByRole("button", { name: "Preparing model…" })).toBeDisabled();
  await waitFor(() => expect(onPrepared).toHaveBeenCalledWith(result));
  expect(prepareLocalLLM).toHaveBeenCalledExactlyOnceWith("gemma");
});

it("reports failure and permits a retry without claiming readiness", async () => {
  vi.mocked(prepareLocalLLM).mockRejectedValue(new Error("Insufficient memory"));
  const onPrepared = vi.fn();
  render(<PrepareLocalModel model="gemma" onPrepared={onPrepared} />);
  fireEvent.click(screen.getByRole("button", { name: "Prepare model" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Insufficient memory");
  expect(screen.getByRole("button", { name: "Prepare model" })).toBeEnabled();
  expect(onPrepared).not.toHaveBeenCalled();
});


it("provides preparation inside the pipeline local-engine card", async () => {
  const onLocalPrepared = vi.fn();
  const local = { enabled: true, protocol: "ollama" as const, models: [{ name: "gemma", loaded: true }] };
  vi.mocked(prepareLocalLLM).mockResolvedValue({ local } as Awaited<ReturnType<typeof prepareLocalLLM>>);
  render(<AnswerEngineRows engines={[{ id: "local", label: "Local", light: "amber", reason: "Model not loaded", model: "gemma", server: "Ollama" }]} onOpenStatus={vi.fn()} onOpenLocal={vi.fn()} onLocalPrepared={onLocalPrepared} />);
  fireEvent.click(screen.getByRole("button", { name: "Prepare model" }));
  await waitFor(() => expect(onLocalPrepared).toHaveBeenCalledWith(local));
});

it("forwards compact status to the settings action header instead of duplicating an error below", async () => {
  const onStatus = vi.fn();
  vi.mocked(prepareLocalLLM).mockRejectedValue(new Error("Insufficient memory"));
  render(<PrepareLocalModel model="gemma" onStatus={onStatus} />);
  fireEvent.click(screen.getByRole("button", { name: "Prepare model" }));
  expect(onStatus).toHaveBeenCalledWith({ loading: true, error: "" });
  await waitFor(() => expect(onStatus).toHaveBeenLastCalledWith({ loading: false, error: "Insufficient memory" }));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

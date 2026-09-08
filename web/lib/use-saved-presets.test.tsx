import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { configurePresetStorage } from "./preset-storage";
import { BUILTIN_PRESETS, DEFAULT_PROFILE, DEFAULT_SESSION_PROFILE } from "./types";
import { RetrievalPresetManager } from "../components/retrieval-preset-manager";
import { RetrievalPresetSelect } from "../components/retrieval-preset-select";

afterEach(() => { cleanup(); configurePresetStorage(null); vi.useRealTimers(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it("shares one refresh between the page and composer and displays added files and corruption", async () => {
  vi.useFakeTimers();
  vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
  let changed = false;
  const fetch = vi.fn(async () => new Response(JSON.stringify({
    presets_version: changed ? "two" : "one", presets: [...BUILTIN_PRESETS.toReversed(), ...(changed ? [{ id: "dropped", name: "Dropped file", retrieval: DEFAULT_PROFILE }] : [])], errors: changed ? [{ file: "broken.json", error: "Invalid JSON" }] : [],
  })));
  vi.stubGlobal("fetch", fetch);
  await act(async () => { render(<><RetrievalPresetManager /><RetrievalPresetSelect profile={DEFAULT_SESSION_PROFILE} editable onChange={vi.fn()} /></>); });
  expect(fetch).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Register new preset" })).toBeDisabled();
  await act(async () => { configurePresetStorage({ environment: "dev", can_change_custom_retrieval: true }); });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Register new preset" })).toBeEnabled();
  expect([...document.querySelectorAll(".preset-list-row")].map(row => row.getAttribute("aria-label"))).toEqual(["Balanced", "Korean", "Accuracy"]);
  changed = true;
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("option", { name: "Dropped file" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Dropped file" })).toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent("broken.json");
  await act(async () => { configurePresetStorage({ environment: "prod", can_change_custom_retrieval: false }); });
  expect(screen.queryByRole("option", { name: "Dropped file" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Dropped file" })).toBeNull();
  await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
  cleanup();
  expect(fetch).toHaveBeenCalledTimes(2);
});

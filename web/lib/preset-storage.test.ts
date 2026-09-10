import { afterEach, expect, it, vi } from "vitest";
import { configurePresetStorage, deleteStoredPreset, presetStorageKind, readPresetCatalog, refreshFilePresets, saveStoredPreset } from "./preset-storage";
import { parsePresetJSON } from "./saved-presets";
import { BUILTIN_PRESETS, DEFAULT_PROFILE } from "./types";

const preset = { id: "research", name: "Research", description: "Detailed", retrieval: DEFAULT_PROFILE };
afterEach(() => { configurePresetStorage(null); localStorage.clear(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it("validates direct JSON and reserves built-in identities", () => {
  expect(parsePresetJSON(JSON.stringify(preset))).toEqual(preset);
  for (const payload of [{ ...preset, extra: 2 }, { ...preset, id: "../file" }, { ...preset, id: "balanced" }, { ...preset, retrieval: { ...DEFAULT_PROFILE, k: "5" } }, { ...preset, retrieval: { ...DEFAULT_PROFILE, candidate_k: 2 } }]) {
    expect(() => parsePresetJSON(JSON.stringify(payload))).toThrow();
  }
  expect(() => parsePresetJSON("{")).toThrow("Enter valid JSON.");
  for (const retrieval of [5, true, "hybrid", [], null]) expect(() => parsePresetJSON(JSON.stringify({ ...preset, retrieval }))).toThrow("Include all retrieval fields and no unknown fields.");
});

it("saves, updates and deletes PROD presets without the DEV file API", () => {
  vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "off");
  configurePresetStorage({ environment: "prod", can_change_custom_retrieval: false });
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  expect(presetStorageKind()).toBe("browser");
  saveStoredPreset(preset);
  expect(readPresetCatalog().presets[0].description).toBe("Detailed");
  saveStoredPreset({ ...preset, description: "Updated research" });
  expect(readPresetCatalog().presets[0].description).toBe("Updated research");
  expect(readPresetCatalog().presets).toHaveLength(1);
  deleteStoredPreset(preset.id);
  expect(readPresetCatalog().presets).toEqual([]);
  expect(fetch).not.toHaveBeenCalled();
});

it("uses the DEV file API and sends the cached version for cheap refreshes", async () => {
  vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
  configurePresetStorage({ environment: "dev", can_change_custom_retrieval: true });
  const fetch = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") return new Response(JSON.stringify(preset));
    return new Response(JSON.stringify(url.includes("?version=") ? { presets_version: "v1", unchanged: true, presets: [], errors: [] } : { presets_version: "v1", presets: [...BUILTIN_PRESETS, preset], errors: [{ file: "broken.json", error: "Invalid JSON" }] }));
  });
  vi.stubGlobal("fetch", fetch);
  await saveStoredPreset(preset);
  expect(readPresetCatalog().presets).toEqual([preset]);
  expect(readPresetCatalog().fileErrors[0].file).toBe("broken.json");
  await refreshFilePresets();
  expect(fetch.mock.calls.at(-1)?.[0]).toContain("/admin/presets?version=v1");
  expect(localStorage.length).toBe(0);
});

it("does not restore a deleted file when an older refresh completes late", async () => {
  vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
  configurePresetStorage({ environment: "dev", can_change_custom_retrieval: true });
  let release!: (response: Response) => void;
  const delayed = new Promise<Response>(resolve => { release = resolve; });
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => init?.method === "DELETE"
    ? new Response(JSON.stringify({ presets_version: "deleted", presets: BUILTIN_PRESETS, errors: [] }))
    : delayed));
  const refresh = refreshFilePresets();
  const deletion = deleteStoredPreset(preset.id);
  release(new Response(JSON.stringify({ presets_version: "older", presets: [...BUILTIN_PRESETS, preset], errors: [] })));
  await refresh; await deletion;
  expect(readPresetCatalog().presets).toEqual([]);
});


it("uses confirmed runtime permissions rather than trusting the live bundle", async () => {
  vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
  configurePresetStorage(null);
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  expect(presetStorageKind()).toBe("pending");
  await refreshFilePresets();
  expect(() => saveStoredPreset(preset)).toThrow(/server permissions/);
  expect(() => deleteStoredPreset(preset.id)).toThrow(/server permissions/);
  configurePresetStorage({ environment: "dev", can_change_custom_retrieval: false });
  expect(presetStorageKind()).toBe("pending");
  await refreshFilePresets();
  configurePresetStorage({ environment: "prod", can_change_custom_retrieval: false });
  expect(presetStorageKind()).toBe("browser");
  saveStoredPreset(preset);
  await refreshFilePresets();
  expect(readPresetCatalog().presets[0].id).toBe(preset.id);
  expect(fetch).not.toHaveBeenCalled();
});

it("ignores a file response that arrives after effective runtime permissions change", async () => {
  vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
  configurePresetStorage({ environment: "dev", can_change_custom_retrieval: true });
  let release!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(resolve => { release = resolve; })));
  const refresh = refreshFilePresets();
  configurePresetStorage({ environment: "prod", can_change_custom_retrieval: false });
  release(new Response(JSON.stringify({ presets_version: "foreign", presets: [...BUILTIN_PRESETS, preset], errors: [] })));
  await refresh;
  expect(presetStorageKind()).toBe("browser");
  expect(readPresetCatalog().presets).toEqual([]);
});

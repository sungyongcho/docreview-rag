import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { configurePresetStorage } from "@/lib/preset-storage";
import { loadSavedPresets, savePreset } from "@/lib/saved-presets";
import { BUILTIN_PRESETS, DEFAULT_PROFILE } from "@/lib/types";
import { RetrievalPresetManager } from "./retrieval-preset-manager";

afterEach(() => { cleanup(); configurePresetStorage(null); localStorage.clear(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it("allows PROD presets to be saved and deleted without the DEV file API", () => {
  configurePresetStorage({ environment: "prod", can_change_custom_retrieval: false });
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  render(<RetrievalPresetManager />);
  for (const name of ["Save current search as a preset", "Register new preset", "Import preset JSON"]) expect(screen.getByRole("button", { name })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Register new preset" }));
  fireEvent.change(screen.getByLabelText("Preset name"), { target: { value: "Browser research" } });
  fireEvent.click(screen.getByRole("button", { name: "Save preset" }));
  expect(loadSavedPresets()[0]).toMatchObject({ name: "Browser research", retrieval: DEFAULT_PROFILE });
  fireEvent.click(screen.getByRole("button", { name: "Browser research" }));
  fireEvent.click(screen.getByRole("button", { name: "Delete preset" }));
  expect(loadSavedPresets()).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
  expect(loadSavedPresets()).toEqual([]);
  expect(fetch).not.toHaveBeenCalled();
});

it("registers balanced defaults through JSON with inline validation", () => {
  render(<RetrievalPresetManager />);
  fireEvent.click(screen.getByRole("button", { name: "Register new preset" }));
  fireEvent.change(screen.getByLabelText("Preset name"), { target: { value: "JSON research" } });
  fireEvent.click(screen.getByRole("button", { name: "JSON" }));
  const area = screen.getByLabelText("Preset JSON");
  const draft = JSON.parse((area as HTMLTextAreaElement).value);
  expect(draft.retrieval).toEqual(DEFAULT_PROFILE);
  fireEvent.change(area, { target: { value: "{" } });
  expect(screen.getByRole("alert")).toHaveTextContent("Enter valid JSON.");
  expect(screen.getByRole("button", { name: "Save preset" })).toBeDisabled();
  fireEvent.change(area, { target: { value: JSON.stringify({ ...draft, description: "Research", retrieval: { ...draft.retrieval, k: 8 } }) } });
  fireEvent.click(screen.getByRole("button", { name: "Save preset" }));
  expect(loadSavedPresets()[0]).toMatchObject({ name: "JSON research", description: "Research", retrieval: { k: 8 } });
});

it("applies a saved row explicitly and requires confirmation for deletion", () => {
  savePreset({ id: "custom-one", name: "Private", retrieval: DEFAULT_PROFILE });
  const apply = vi.fn();
  render(<RetrievalPresetManager onApply={apply} />);
  fireEvent.click(screen.getByRole("button", { name: "Balanced" }));
  const builtin = screen.getByRole("region", { name: "Balanced" });
  expect(within(builtin).queryByRole("button", { name: "Delete preset" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Private" }));
  fireEvent.click(screen.getByRole("button", { name: "Select for conversation" }));
  expect(apply).toHaveBeenCalledWith(DEFAULT_PROFILE);
  fireEvent.click(screen.getByRole("button", { name: "Delete preset" }));
  expect(loadSavedPresets()).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
  expect(loadSavedPresets()).toEqual([]);
});

it("imports a file into the same editor and exports the saved shape", async () => {
  render(<RetrievalPresetManager />);
  const payload = { id: "imported", name: "Imported", description: "Portable", retrieval: DEFAULT_PROFILE };
  const file = new File([JSON.stringify(payload)], "imported.json", { type: "application/json" });
  Object.defineProperty(file, "text", { value: () => Promise.resolve(JSON.stringify(payload)) });
  fireEvent.change(screen.getByLabelText("Import preset JSON"), { target: { files: [file] } });
  const name = await screen.findByLabelText("Preset name");
  expect(name).toHaveValue("Imported copy");
  fireEvent.change(name, { target: { value: "Imported saved" } });
  fireEvent.click(screen.getByRole("button", { name: "Save preset" }));
  const saved = loadSavedPresets()[0];
  expect(saved.id).not.toBe(payload.id);
  expect(saved.description).toBe("Portable");
  fireEvent.click(screen.getByRole("button", { name: "Imported saved" }));
  const create = vi.fn(() => "blob:export");
  const revoke = vi.fn();
  const oldCreate = URL.createObjectURL, oldRevoke = URL.revokeObjectURL;
  URL.createObjectURL = create; URL.revokeObjectURL = revoke;
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  try {
    fireEvent.click(screen.getByRole("button", { name: "Export preset JSON" }));
    expect(create).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalledOnce();
    expect(revoke).toHaveBeenCalledWith("blob:export");
    fireEvent.click(screen.getByRole("button", { name: "Edit preset" }));
    expect(screen.getByLabelText("Preset name")).toHaveValue("Imported saved");
    fireEvent.change(screen.getByLabelText("Preset description"), { target: { value: "Updated" } });
    fireEvent.click(screen.getByRole("button", { name: "Save preset" }));
    expect(loadSavedPresets()).toHaveLength(1);
    expect(loadSavedPresets()[0].description).toBe("Updated");
  } finally { click.mockRestore(); URL.createObjectURL = oldCreate; URL.revokeObjectURL = oldRevoke; }
});

it.each(["balanced", "korean", "accuracy"])("renders %s with empty display ID and its canonical English name", id => {
  const preset = BUILTIN_PRESETS.find(item => item.id === id)!;
  render(<RetrievalPresetManager />);
  fireEvent.click(screen.getByRole("button", { name: preset.name }));
  const row = screen.getByRole("region", { name: preset.name });
  expect(JSON.parse(row.querySelector("pre")!.textContent!)).toEqual({ id: "", name: preset.name, description: preset.description ?? "", retrieval: preset.retrieval });
  expect(preset.id).toBe(id);
});

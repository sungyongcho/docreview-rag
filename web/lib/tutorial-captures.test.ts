import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import { captureCallouts, captureDetail, captureMobile, captureMobileDetail, captureOriginal, validateCapturePlan } from "./tutorial-captures.mjs";
import plan from "../../docs/TUTORIAL/capture-plan.json";

it("validates paired local light-mode capture instructions without requiring pending files", () => {
  expect(validateCapturePlan(plan)).toBe(plan);
  expect(plan.scenes.length).toBeGreaterThanOrEqual(28);
  expect(captureOriginal(plan, plan.scenes[0].id, "ko")).toBeUndefined();
});

it("rejects unpaired assets and undeclared Markdown capture markers", () => {
  const invalid = structuredClone(plan);
  invalid.scenes[0].variants.ko.original = invalid.scenes[0].variants.en.original;
  expect(() => validateCapturePlan(invalid)).toThrow(/Invalid capture asset/);
  expect(() => validateCapturePlan(plan, new Map([["en/answers.md", { captures: ["undeclared"] }]]))).toThrow(/Unknown capture placement/);
  expect(() => validateCapturePlan(plan, new Map([["en/answers.md", { captures: [] }]]))).toThrow(/Missing capture marker/);
});

it("links a reviewed original only after acceptance", () => {
  const accepted = structuredClone(plan);
  accepted.scenes[0].status = "accepted";
  expect(captureOriginal(accepted, accepted.scenes[0].id, "en", "revision")).toContain(".en.full.png?v=revision");
});

it("returns localized numbered callouts only for accepted scenes", () => {
  const accepted = plan.scenes.find((scene) => scene.status === "accepted")!;
  const callouts = captureCallouts(plan, accepted.id, "ko")!;
  expect(callouts.map((callout) => callout.number)).toEqual(accepted.callouts!.map((callout) => callout.number));
  expect(callouts[0].label).toBe(accepted.callouts![0].label.ko);
  expect(callouts[0].bounds).toMatchObject({ x: expect.any(Number), y: expect.any(Number), w: expect.any(Number), h: expect.any(Number) });
  const pending = plan.scenes.find((scene) => scene.status === "pending")!;
  expect(captureCallouts(plan, pending.id, "ko")).toBeUndefined();
  expect(captureOriginal(plan, pending.id, "ko")).toBeUndefined();
  expect(captureMobile(plan, pending.id, "ko")).toBeUndefined();
});

it("requires recorded pixel bounds before a scene is accepted", () => {
  const invalid = structuredClone(plan);
  const accepted = invalid.scenes.find((scene) => scene.status === "accepted")!;
  delete (accepted.callouts![0] as { bounds?: unknown }).bounds;
  expect(() => validateCapturePlan(invalid)).toThrow(/Missing accepted capture bounds/);
});

it("keeps every accepted capture variant on disk", () => {
  for (const scene of plan.scenes.filter((scene) => scene.status === "accepted")) {
    for (const [locale, variant] of Object.entries(scene.variants)) {
      const mobile = scene.mobile ? [variant.mobile] : [];
      const narrowDetail = scene.mobileDetail ? [variant.mobileDetail, variant.mobileDetailOriginal] : [];
      const detail = scene.detail ? [variant.detailFocused, variant.detailOriginal, variant.detailMobile, variant.detailMobileOriginal] : [];
      for (const path of [variant.original, variant.focused, ...mobile, ...narrowDetail, ...detail].filter((path): path is string => Boolean(path))) {
        expect(existsSync(resolve(process.cwd(), "../docs/TUTORIAL", path)), `${scene.id}/${locale}/${path}`).toBe(true);
      }
    }
  }
});

it("gives the supplemental narrow-screen figure its own crop, callouts and original", () => {
  const scene = plan.scenes.find((scene) => scene.status === "accepted" && scene.mobileDetail)!;
  const detail = captureMobileDetail(plan, scene.id, "ko", "revision")!;
  expect(detail.src).toContain(".ko.mobile-detail.png?v=revision");
  expect(detail.originalSrc).toContain(".ko.mobile-detail-full.png?v=revision");
  expect(detail.alt).toBe(scene.variants.ko.mobileDetailAlt);
  expect(detail.caption).toBe(scene.variants.ko.mobileDetailCaption);
  expect(detail.callouts.map((callout) => callout.number)).toEqual([2]);
  // The main narrow crop stops before that target, so it carries no bounds for callout 2.
  expect(captureCallouts(plan, scene.id, "ko")!.map((callout) => Boolean(callout.mobileBounds))).toEqual([true, false]);
  expect(captureMobileDetail(plan, "openai-per-call-caps-editor", "ko")).toBeUndefined();
});

type NarrowBounds = { mobile?: unknown; mobileDetail?: unknown };
const narrowBounds = (scenes: typeof plan.scenes, locale: "ko" | "en") =>
  (scenes.find((scene) => scene.status === "accepted" && scene.mobileDetail)!.callouts![1] as { bounds: Record<string, NarrowBounds> }).bounds[locale];

it("requires every callout to appear in one narrow frame and every narrow frame to be used", () => {
  const orphan = structuredClone(plan);
  delete narrowBounds(orphan.scenes, "ko").mobileDetail;
  expect(() => validateCapturePlan(orphan)).toThrow(/Missing accepted capture bounds/);
  const unused = structuredClone(plan);
  for (const locale of ["ko", "en"] as const) {
    const bounds = narrowBounds(unused.scenes, locale);
    bounds.mobile = bounds.mobileDetail;
    delete bounds.mobileDetail;
  }
  expect(() => validateCapturePlan(unused)).toThrow(/Unused capture frame/);
});

it("gives the supplemental readiness figure its own crop, mobile source, callouts and original", () => {
  const scene = plan.scenes.find((scene) => scene.status === "accepted" && scene.detail)!;
  const detail = captureDetail(plan, scene.id, "ko", "revision")!;
  expect(detail.src).toContain(".ko.detail.png?v=revision");
  expect(detail.mobileSrc).toContain(".ko.detail-mobile.png?v=revision");
  expect(detail.originalSrc).toContain(".ko.detail-full.png?v=revision");
  expect(detail.alt).toBe(scene.variants.ko.detailAlt);
  expect(detail.caption).toBe(scene.variants.ko.detailCaption);
  // The readiness callout belongs to this figure only, so the main figure never points at it.
  expect(detail.callouts.map((callout) => callout.number)).toEqual([3]);
  const main = captureCallouts(plan, scene.id, "ko")!;
  expect(main.filter((callout) => callout.bounds).map((callout) => callout.number)).toEqual([1, 2]);
  expect(captureDetail(plan, "company-year-inventory-selector", "ko")).toBeUndefined();
});

it("requires each declared figure to carry at least one callout", () => {
  const unused = structuredClone(plan);
  const scene = unused.scenes.find((scene) => scene.status === "accepted" && scene.detail)!;
  for (const locale of ["ko", "en"] as const) {
    const bounds = (scene.callouts![2] as { bounds: Record<string, Record<string, unknown>> }).bounds[locale];
    bounds.focused = bounds.detail;
    bounds.mobile = bounds.detailMobile;
    delete bounds.detail;
    delete bounds.detailMobile;
  }
  expect(() => validateCapturePlan(unused)).toThrow(/Unused capture frame/);
});

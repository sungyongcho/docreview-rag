import { afterEach, expect, it, vi } from "vitest";
import { buildFingerprint, builtAt, formatBuiltAtLocal, formatBuiltAtUtc, localBuildTime } from "./build-info";

afterEach(() => vi.unstubAllEnvs());

it("falls back to empty metadata when the env constants are unset", () => {
  expect(buildFingerprint()).toBe("");
  expect(builtAt()).toBeNull();
});

it("reads the injected fingerprint and ISO timestamp", () => {
  vi.stubEnv("NEXT_PUBLIC_DOCREVIEW_BUILD_FINGERPRINT", "0123456789ab");
  vi.stubEnv("NEXT_PUBLIC_DOCREVIEW_BUILT_AT", "2026-09-14T01:02:03.000Z");
  expect(buildFingerprint()).toBe("012345");
  expect(builtAt()?.toISOString()).toBe("2026-09-14T01:02:03.000Z");
});

it("treats a malformed timestamp as absent", () => {
  vi.stubEnv("NEXT_PUBLIC_DOCREVIEW_BUILT_AT", "not a date");
  expect(builtAt()).toBeNull();
});

it("renders a deterministic UTC label", () => {
  expect(formatBuiltAtUtc(new Date("2026-09-14T01:02:03.000Z"))).toBe("2026-09-14 01:02:03 UTC");
});

it("renders the browser local time with an explicit timezone label", () => {
  const date = new Date("2026-09-14T01:02:03.000Z");
  const zone = new Intl.DateTimeFormat().resolvedOptions().timeZone;
  const local = formatBuiltAtLocal(date);
  expect(local).toContain(zone);
  expect(local).not.toBe(formatBuiltAtUtc(date));
});

it("keeps the regional timezone and converts the same build instant", () => {
  const parts = localBuildTime(new Date("2026-09-14T01:02:03.000Z"), "Asia/Seoul");
  expect(parts.zone).toBe("Asia/Seoul");
  expect(parts.time).toBe("10:02:03");
});

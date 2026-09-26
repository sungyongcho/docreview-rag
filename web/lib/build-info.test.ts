import { afterEach, expect, it, vi } from "vitest";
import { builtAt, formatBuiltAtUtc, localBuildTime } from "./build-info";

afterEach(() => vi.unstubAllEnvs());

it("treats a malformed timestamp as absent", () => {
  vi.stubEnv("NEXT_PUBLIC_DOCREVIEW_BUILT_AT", "not a date");
  expect(builtAt()).toBeNull();
});

it("renders a deterministic UTC label", () => {
  expect(formatBuiltAtUtc(new Date("2026-09-14T01:02:03.000Z"))).toBe("2026-09-14 01:02:03 UTC");
});

it("keeps the regional timezone and converts the same build instant", () => {
  const parts = localBuildTime(new Date("2026-09-14T01:02:03.000Z"), "Asia/Seoul");
  expect(parts.zone).toBe("Asia/Seoul");
  expect(parts.time).toBe("10:02:03");
});

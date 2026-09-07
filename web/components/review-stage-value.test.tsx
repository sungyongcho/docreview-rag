import { readFileSync } from "node:fs";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { I18nProvider, LOCALE_KEY } from "@/lib/i18n";
import { RecordedValue, stageCompanyLabel } from "./review-stage-value";

afterEach(() => { cleanup(); localStorage.clear(); });

it("never confuses matching issuer codes across registries or invents missing names", () => {
  const names = { "sec:ABC": "ABC · US company", "dart:ABC": "ABC · Korean company" };
  expect(stageCompanyLabel("ABC", ["sec"], names)).toBe("ABC · US company");
  expect(stageCompanyLabel("ABC", ["dart"], names)).toBe("ABC · Korean company");
  expect(stageCompanyLabel("ABC", ["sec", "dart"], names)).toBe("ABC");
  expect(stageCompanyLabel("UNKNOWN", ["sec"], names)).toBe("UNKNOWN");
  expect(stageCompanyLabel("A", ["sec"], { "sec:A": "Agilent" })).toBe("A · Agilent");
  expect(stageCompanyLabel("A", ["sec"], { "sec:A": " " })).toBe("A");
});

it.each(["en", "ko"] as const)("maps nested structured values and empty/missing states in %s", (locale) => {
  localStorage.setItem(LOCALE_KEY, locale);
  render(<I18nProvider><RecordedValue value={{ registries: ["sec"], issuers: ["NVDA"], fiscal_years: [2024], empty: [], absent: null, elapsed_ms: 1.87 }} companyLabels={{ "sec:NVDA": "NVDA · NVIDIA" }} registries={["sec"]} /></I18nProvider>);
  expect(screen.getByText("SEC")).toBeVisible(); expect(screen.getByText("FY2024")).toBeVisible();
  expect(screen.getByText("NVDA · NVIDIA")).toBeVisible(); expect(screen.getByText("1.9")).toBeVisible();
  expect(screen.getByText(locale === "en" ? "None" : "없음")).toBeVisible();
  expect(screen.getByLabelText(locale === "en" ? "Not recorded for this run" : "이 실행에서 기록되지 않음")).toHaveTextContent("—");
  expect(document.querySelector("pre")).toBeNull();
});

it("lets the detail content grow and confines expansion to long tables", () => {
  const styles = readFileSync("components/review-stage-details.css", "utf8");
  expect(styles).not.toMatch(/max-height|overflow:\s*(auto|scroll)/);
  expect(styles).toContain("grid-auto-flow: row dense");
});

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { PRODUCT_ASCII, PRODUCT_MONOGRAM } from "@/branding/ascii";
import { ProductBrand } from "./product-brand";
import { CreatorSignature } from "./creator-signature";

afterEach(cleanup);

it.each([
  ["wordmark.txt", PRODUCT_ASCII, 78],
  ["monogram.txt", PRODUCT_MONOGRAM, 13],
] as const)("keeps %s identical to the canonical shell asset", (file, value, width) => {
  const asset = readFileSync(resolve(process.cwd(), "branding", file), "utf8");
  expect(value + "\n").toBe(asset);
  expect(value.split("\n")).toHaveLength(4);
  expect(Math.max(...value.split("\n").map((line) => line.length))).toBe(width);
});

it("uses the compact Small mark with a readable name and version by default", () => {
  const { container } = render(<ProductBrand />);
  expect(screen.getByRole("img", { name: "DocReview RAG v2" })).toBeInTheDocument();
  expect(container.querySelector(".product-ascii-compact")?.textContent).toBe(PRODUCT_MONOGRAM);
  expect(container.querySelector(".product-ascii-full")).toBeNull();
  expect(container.querySelector(".product-edition")).toHaveTextContent("DocReview RAG v2");
  expect(container.querySelector(".product-brand-lockup")).toHaveAttribute("aria-hidden", "true");
});

it("provides full and compact assets so spacious surfaces can respond to actual width", () => {
  const { container } = render(<ProductBrand hero />);
  expect(container.querySelector(".product-ascii-full")?.textContent).toBe(PRODUCT_ASCII);
  expect(container.querySelector(".product-ascii-compact")?.textContent).toBe(PRODUCT_MONOGRAM);
});

it("shares the same About brand and accessible creator link", () => {
  render(<CreatorSignature variant="about" />);
  expect(screen.getByRole("img", { name: "DocReview RAG v2" })).toBeInTheDocument();
  const portfolio = screen.getByRole("link", { name: "Sungyong Cho · portfolio (opens in a new tab)" });
  expect(portfolio).toHaveAttribute("href", "https://sungyongcho.com");
  expect(portfolio).toHaveAttribute("rel", "noopener noreferrer");
  expect(portfolio).toHaveTextContent("Designed & built by Sungyong Cho");
});

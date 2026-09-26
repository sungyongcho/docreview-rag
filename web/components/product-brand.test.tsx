import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { BuildInfo, ProductBrand } from "./product-brand";
import { CreatorSignature } from "./creator-signature";

afterEach(() => { cleanup(); vi.unstubAllEnvs(); });

it("shows the frozen build fingerprint and browser-local update time as text", () => {
  vi.stubEnv("NEXT_PUBLIC_DOCREVIEW_BUILD_FINGERPRINT", "0123456789ab");
  vi.stubEnv("NEXT_PUBLIC_DOCREVIEW_BUILT_AT", "2026-09-14T01:02:03.000Z");
  const { container } = render(<><ProductBrand /><BuildInfo onOpen={vi.fn()} /></>);
  const badge = container.querySelector(".build-info-link")!;
  const metadata = container.querySelector(".product-brand-tooltip")!;
  expect(badge).toHaveTextContent("Build 012345");
  expect(badge.querySelector("code")).toHaveTextContent(/^012345$/);
  expect(metadata).toHaveTextContent("Last updated");
  expect(container.querySelector(".sidebar-build-info")).not.toHaveTextContent("Last updated");
  expect(container.querySelector(".product-name")).toHaveAttribute("aria-describedby", metadata.id);
  expect(container.querySelector(".product-name")).toHaveAttribute("tabindex", "0");
  expect(badge.closest(".product-brand")).toBeNull();
  expect(metadata.querySelector("time")).toHaveAttribute("dateTime", "2026-09-14T01:02:03.000Z");
  const zone = new Intl.DateTimeFormat().resolvedOptions().timeZone;
  expect(metadata).toHaveTextContent(zone);
  expect(metadata).toHaveTextContent(/\d{2}:\d{2} [AP]M/);
  expect(metadata).not.toHaveTextContent(/\d{2}:\d{2}:\d{2}/);
});

it("omits the update tooltip and extra focus target on documentation logos", () => {
  vi.stubEnv("NEXT_PUBLIC_DOCREVIEW_BUILT_AT", "2026-09-14T01:02:03.000Z");
  const { container } = render(<ProductBrand showUpdated={false} />);
  expect(container.querySelector(".product-brand-tooltip")).toBeNull();
  expect(container.querySelector(".product-name")).not.toHaveAttribute("tabindex");
  expect(container.querySelector(".product-name")).not.toHaveAttribute("aria-describedby");
});

it("omits build metadata when nothing was injected", () => {
  const { container } = render(<BuildInfo onOpen={vi.fn()} />);
  expect(container.querySelector(".sidebar-build-info")).toBeNull();
});

it("opens build details from the compact badge", () => {
  vi.stubEnv("NEXT_PUBLIC_DOCREVIEW_BUILD_FINGERPRINT", "0123456789ab");
  const open = vi.fn();
  render(<BuildInfo onOpen={open} />);
  fireEvent.click(screen.getByRole("button", { name: "Build 012345" }));
  expect(open).toHaveBeenCalledOnce();
});

it("shares the same About brand and accessible creator link", () => {
  render(<CreatorSignature variant="about" />);
  expect(screen.getByRole("img", { name: "DocReview RAG" })).toBeInTheDocument();
  const portfolio = screen.getByRole("link", { name: "Sungyong Cho · portfolio (opens in a new tab)" });
  expect(portfolio).toHaveAttribute("href", "https://sungyongcho.com");
  expect(portfolio).toHaveAttribute("rel", "noopener noreferrer");
  expect(portfolio).toHaveTextContent("Designed & built by Sungyong Cho");
});

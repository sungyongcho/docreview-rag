import { cleanup, createEvent, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { TutorialImage } from "./tutorial-image";

const source = { src: "/docreview-rag/tutorial-assets/example.jpg?v=recorded", alt: "Recorded run", caption: "An existing saved run; no request was executed for this image.", locale: "en" as const };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("opens the original screenshot with its bottom caption and closes only on the backdrop", () => {
  const { container } = render(<p><TutorialImage {...source} /></p>);
  const trigger = screen.getByRole("link", { name: "Recorded run · Expand image" });
  trigger.focus();
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog", { name: "Image viewer" });
  expect(dialog).toHaveAttribute("aria-modal", "true");
  expect(container).not.toContainElement(dialog);
  expect(container).toHaveAttribute("inert");
  expect(document.body.style.overflow).toBe("hidden");
  expect(within(dialog).getByRole("img", { name: source.alt })).toHaveAttribute("src", source.src);
  expect(dialog.querySelector("footer")).toHaveTextContent(source.caption);
  const original = within(dialog).getByRole("link", { name: "Open original" });
  expect(original).toHaveAttribute("href", source.src);
  expect(original).toHaveAttribute("target", "_blank");
  expect(original).toHaveAttribute("rel", "noopener noreferrer");
  fireEvent.click(within(dialog).getByRole("img"));
  fireEvent.click(within(dialog).getByText(source.caption));
  expect(dialog).toBeInTheDocument();
  fireEvent.click(dialog.parentElement!);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(container).not.toHaveAttribute("inert");
  expect(document.body.style.overflow).toBe("");
  expect(trigger).toHaveFocus();
});

it("uses document-localized captions and keeps keyboard focus inside until Escape", () => {
  render(<><button>Background action</button><TutorialImage {...source} locale="ko" caption="실제 기록입니다. model-id 원문은 유지합니다." /></>);
  const trigger = screen.getByRole("link", { name: "Recorded run · 이미지 크게 보기" });
  trigger.focus();
  fireEvent.keyDown(trigger, { key: " " });
  const dialog = screen.getByRole("dialog", { name: "이미지 보기" });
  expect(dialog).toHaveAttribute("lang", "ko");
  expect(dialog.querySelector("footer")).toHaveTextContent("실제 기록입니다. model-id 원문은 유지합니다.");
  const close = within(dialog).getByRole("button", { name: "이미지 닫기" });
  expect(close).toHaveFocus();
  const stage = within(dialog).getByRole("region", { name: "스크롤할 수 있는 이미지" });
  stage.focus();
  fireEvent.keyDown(stage, { key: "Tab" });
  expect(within(dialog).getByRole("button", { name: "이미지 확대" })).toHaveFocus();
  screen.getByRole("button", { name: "Background action" }).focus();
  expect(close).toHaveFocus();
  fireEvent.keyDown(close, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

it("bounds wheel zoom and expands the scrollable image without scaling its caption", () => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true })));
  render(<TutorialImage {...source} />);
  fireEvent.click(screen.getByRole("link", { name: "Recorded run · Expand image" }));
  const dialog = screen.getByRole("dialog");
  const stage = within(dialog).getByRole("region", { name: "Scrollable image" });
  const image = within(dialog).getByRole("img");
  Object.defineProperty(stage, "clientWidth", { configurable: true, value: 800 });
  Object.defineProperty(image, "naturalWidth", { configurable: true, value: 1200 });
  fireEvent.resize(window);
  fireEvent.load(image);
  expect(image).toHaveStyle({ width: "800px" });
  fireEvent.wheel(image, { deltaY: -100000 });
  expect(within(dialog).getByRole("status")).toHaveTextContent("400%");
  expect(image).toHaveStyle({ width: "3200px" });
  expect(within(dialog).getByRole("button", { name: "Zoom in" })).toBeDisabled();
  expect(dialog.querySelector("footer")).not.toHaveAttribute("style");
  fireEvent.click(within(dialog).getByRole("button", { name: "Zoom out" }));
  expect(within(dialog).getByRole("status")).toHaveTextContent("320%");
  fireEvent.click(within(dialog).getByRole("button", { name: "Fit width" }));
  fireEvent.wheel(image, { deltaY: 100000 });
  expect(within(dialog).getByRole("status")).toHaveTextContent("100%");
  expect(image).toHaveStyle({ width: "800px" });
});

it("preserves modified-click access and closes a viewer when its revision changes", () => {
  const { rerender } = render(<TutorialImage {...source} />);
  const trigger = screen.getByRole("link", { name: "Recorded run · Expand image" });
  const modified = createEvent.click(trigger, { ctrlKey: true });
  fireEvent(trigger, modified);
  expect(modified.defaultPrevented).toBe(false);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(trigger);
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  rerender(<TutorialImage {...source} src="/docreview-rag/tutorial-assets/example.jpg?v=replaced" />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(trigger).toHaveAttribute("href", "/docreview-rag/tutorial-assets/example.jpg?v=replaced");
  expect(document.body.style.overflow).toBe("");
});

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

it("keeps numbered callouts in the image gutter with leaders to their targets", () => {
  const callouts = [
    { number: 1, label: "First", bounds: { x: 40, y: 20, w: 100, h: 80 } },
    { number: 2, label: "Second", bounds: { x: 200, y: 300, w: 50, h: 50 } },
  ];
  render(<TutorialImage {...source} width={400} height={400} callouts={callouts} displayWidth={200} />);
  const trigger = screen.getByRole("link", { name: "Recorded run · Expand image" });
  expect(trigger).toHaveStyle({ maxWidth: "200px" });
  expect(trigger.querySelector(".tutorial-image-figure-callouts")).not.toBeNull();
  const badges = trigger.querySelectorAll(".tutorial-image-callout");
  expect(badges).toHaveLength(2);
  expect(badges[0]).toHaveStyle({ top: "5%" });
  expect(badges[1]).toHaveStyle({ top: "75%" });
  const leaders = trigger.querySelectorAll(".tutorial-image-leader");
  expect(leaders[0]).toHaveStyle({ top: "5%", width: "10%", maxWidth: "62px" });
  expect(leaders[1]).toHaveStyle({ top: "75%", width: "50%", maxWidth: "62px" });
  expect(trigger.querySelector(".tutorial-image-callouts")).toHaveAttribute("aria-hidden", "true");
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog");
  expect(dialog.querySelectorAll(".tutorial-image-callout")).toHaveLength(2);
  const stage = within(dialog).getByRole("region", { name: "Scrollable image" });
  const image = within(dialog).getByRole("img");
  Object.defineProperty(stage, "clientWidth", { configurable: true, value: 800 });
  Object.defineProperty(image, "naturalWidth", { configurable: true, value: 1200 });
  fireEvent.resize(window);
  fireEvent.load(image);
  expect(image).toHaveStyle({ width: "762px" });
  expect(dialog.querySelector(".tutorial-image-canvas")).toHaveStyle({ width: "800px" });
});

it("uses a mobile variant with its own callout bounds under the mobile breakpoint", () => {
  render(<TutorialImage {...source} width={400} height={400} mobileSrc="/docreview-rag/tutorial-assets/captures/x.en.mobile.png" mobileWidth={100} mobileHeight={200}
    callouts={[{ number: 1, label: "First", bounds: { x: 40, y: 20, w: 100, h: 80 }, mobileBounds: { x: 10, y: 50, w: 30, h: 30 } }]} />);
  const trigger = screen.getByRole("link", { name: "Recorded run · Expand image" });
  const mobileSource = trigger.querySelector("source")!;
  expect(mobileSource).toHaveAttribute("media", "(max-width: 900px)");
  expect(trigger.style.getPropertyValue("--tutorial-mobile-frame-width")).toBe("88px");
  expect(mobileSource).toHaveAttribute("srcset", "/docreview-rag/tutorial-assets/captures/x.en.mobile.png");
  expect(mobileSource).toHaveAttribute("width", "100");
  expect(trigger.querySelectorAll(".tutorial-image-callouts")).toHaveLength(2);
  const mobileBadge = trigger.querySelector(".tutorial-image-callouts-mobile .tutorial-image-callout")!;
  expect(mobileBadge).toHaveStyle({ top: "25%" });
  expect(trigger.querySelector(".tutorial-image-callouts-mobile .tutorial-image-leader")).toHaveStyle({ top: "25%", width: "10%", maxWidth: "62px" });
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

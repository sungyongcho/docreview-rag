import type { ReactElement, ReactNode } from "react";
import type { DocumentationRegistry } from "./documentation-registry.mjs";
export { DOCUMENTS } from "./documentation-registry.mjs";
export type { TutorialDocument } from "./documentation-registry.mjs";
export interface TutorialHeading { id: string; text: string; depth: number }
export interface TutorialCode { code: string; language: string }
export interface TutorialImageSource { src: string; alt: string; title?: string; caption: string; locale: "ko" | "en" }
export function renderTutorial(source: string, options?: { locale?: "ko" | "en"; renderCode?: (block: TutorialCode) => ReactElement; renderDevelopmentNotice?: (content: ReactNode) => ReactElement; renderImage?: (image: TutorialImageSource) => ReactElement; assetVersion?: string; registry?: DocumentationRegistry }): {
  content: ReactElement;
  codes: TutorialCode[];
  headings: TutorialHeading[];
  images: string[];
  links: Array<{ file: string | null; hash: string }>;
};

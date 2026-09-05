import type { ReactElement } from "react";
import type { DocumentationRegistry } from "./documentation-registry.mjs";
export { DOCUMENTS } from "./documentation-registry.mjs";
export type { TutorialDocument } from "./documentation-registry.mjs";
export interface TutorialHeading { id: string; text: string; depth: number }
export interface TutorialCode { code: string; language: string }
export function renderTutorial(source: string, options?: { locale?: "ko" | "en"; renderCode?: (block: TutorialCode) => ReactElement; assetVersion?: string; registry?: DocumentationRegistry }): {
  content: ReactElement;
  codes: TutorialCode[];
  headings: TutorialHeading[];
  images: string[];
  links: Array<{ file: string | null; hash: string }>;
};

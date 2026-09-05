import type { ReactElement } from "react";
export interface TutorialHeading { id: string; text: string; depth: number }
export interface TutorialDocument { id: "walkthrough" | "cli"; locale: "ko" | "en"; file: string; title: string; label: string; href: string }
export const DOCUMENTS: TutorialDocument[];
export interface TutorialCode { code: string; language: string }
export function renderTutorial(source: string, options?: { locale?: "ko" | "en"; renderCode?: (block: TutorialCode) => ReactElement; assetVersion?: string }): {
  content: ReactElement;
  codes: TutorialCode[];
  headings: TutorialHeading[];
  images: string[];
  links: Array<{ file: string | null; hash: string }>;
};

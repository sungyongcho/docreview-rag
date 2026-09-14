import type { ReactElement, ReactNode } from "react";
import type { DocumentationRegistry } from "./documentation-registry.mjs";
import type { CaptureCallout } from "./tutorial-captures.mjs";
export { DOCUMENTS } from "./documentation-registry.mjs";
export type { TutorialDocument } from "./documentation-registry.mjs";
export interface TutorialHeading { id: string; text: string; depth: number; aliasFor?: string }
export interface TutorialCode { code: string; language: string }
export interface TutorialImageSource { src: string; alt: string; title?: string; caption: string; locale: "ko" | "en"; width?: number; height?: number; originalSrc?: string; captureId?: string; callouts?: CaptureCallout[]; mobileSrc?: string; mobileWidth?: number; mobileHeight?: number; displayWidth?: number }
export function renderTutorial(source: string, options?: { locale?: "ko" | "en"; renderCode?: (block: TutorialCode) => ReactElement; renderDevelopmentNotice?: (content: ReactNode) => ReactElement; renderImage?: (image: TutorialImageSource) => ReactElement; assetVersion?: string; imageDimensions?: Record<string, { width: number; height: number }>; math?: boolean; statusBadges?: boolean; overviewLayout?: boolean; registry?: DocumentationRegistry }): {
  content: ReactElement;
  codes: TutorialCode[];
  headings: TutorialHeading[];
  images: string[];
  captures: string[];
  links: Array<{ file: string | null; hash: string }>;
};

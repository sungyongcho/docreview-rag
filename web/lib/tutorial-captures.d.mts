export interface CaptureBounds { x: number; y: number; w: number; h: number }
export interface CapturePlan {
  version: number;
  theme: string;
  localOnly: boolean;
  locales: string[];
  scenes: Array<{ id: string; status: string; mobile?: boolean; mobileDetail?: boolean; detail?: boolean; callouts?: Array<{ number: number; label: Record<string, string>; bounds?: Record<string, { focused?: CaptureBounds; mobile?: CaptureBounds; mobileDetail?: CaptureBounds; detail?: CaptureBounds; detailMobile?: CaptureBounds }> }>; variants: Record<string, { original: string; focused: string; mobile?: string; mobileDetail?: string; mobileDetailOriginal?: string; mobileDetailAlt?: string; mobileDetailCaption?: string; detailFocused?: string; detailOriginal?: string; detailMobile?: string; detailMobileOriginal?: string; detailAlt?: string; detailCaption?: string; alt: string; caption: string }>; [key: string]: unknown }>;
}
export interface CaptureCallout { number: number; label: string; bounds?: CaptureBounds; mobileBounds?: CaptureBounds }
export interface CaptureDetail { path: string; src: string; originalSrc?: string; mobilePath?: string; mobileSrc?: string; alt: string; caption: string; callouts: CaptureCallout[] }
export interface CaptureMobileDetail { path: string; src: string; originalSrc?: string; alt: string; caption: string; callouts: CaptureCallout[] }
export function validateCapturePlan(plan: CapturePlan, documents?: Map<string, { captures?: string[]; headings?: Array<{ id: string }> }>): CapturePlan;
export function captureOriginal(plan: CapturePlan, id: string | undefined, locale: "ko" | "en", revision?: string): string | undefined;
export function captureCallouts(plan: CapturePlan, id: string | undefined, locale: "ko" | "en"): CaptureCallout[] | undefined;
export function captureMobile(plan: CapturePlan, id: string | undefined, locale: "ko" | "en", revision?: string): { src: string; path: string } | undefined;
export function captureDetail(plan: CapturePlan, id: string | undefined, locale: "ko" | "en", revision?: string): CaptureDetail | undefined;
export function captureMobileDetail(plan: CapturePlan, id: string | undefined, locale: "ko" | "en", revision?: string): CaptureMobileDetail | undefined;

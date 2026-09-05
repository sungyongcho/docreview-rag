"use client";

import { useSyncExternalStore } from "react";
import { previewState, serverPreviewState, subscribePreview } from "./production-preview";

/** Subscribe without sharing a React session or browser storage across the preview frame. */
export function useProductionPreview() {
  return useSyncExternalStore(subscribePreview, previewState, serverPreviewState);
}

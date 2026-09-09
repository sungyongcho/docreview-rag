"use client";
import "./development-badge.css";

import { Wrench } from "lucide-react";
import type { ReactNode } from "react";
import type { DevOnlyReason } from "@/lib/dev-mode";
import { DevModeBubble } from "./dev-mode-bubble";

/** A control that exists in DEV only: it keeps its place, turns grey, and explains itself on hover. */
export function DevLockedButton({ reason, children, className = "button", inline = true, ariaLabel }: { reason: DevOnlyReason | string; children: ReactNode; className?: string; inline?: boolean; ariaLabel?: string }) {
  return <DevModeBubble inline={inline} reason={reason}>
    <button type="button" className={`${className} dev-locked`} aria-label={ariaLabel} aria-disabled="true" onClick={(event) => event.preventDefault()}>{children}<span className="development-badge" aria-hidden="true"><Wrench size={13} aria-hidden="true" /><span>DEV</span></span></button>
  </DevModeBubble>;
}

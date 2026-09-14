"use client";

import { PRODUCT_ASCII, PRODUCT_MONOGRAM } from "@/branding/ascii";
import { buildFingerprint, builtAtIso, useBuildTimeParts } from "@/lib/build-info";
import "./product-brand.css";
import { useId, type ReactNode } from "react";

/** Keep the Small wordmark legible by switching to its compact monogram. */
export function ProductBrand({ hero = false, onActivate, actionLabel, showUpdated = true }: { hero?: boolean; onActivate?: () => void; actionLabel?: string; showUpdated?: boolean }) {
  const buildTime = useBuildTimeParts();
  const updated = showUpdated ? buildTime : null;
  const tooltipId = useId();
  const Root = onActivate ? "button" : "span";
  return <Root type={onActivate ? "button" : undefined} onClick={onActivate} aria-label={onActivate ? actionLabel : undefined} className={`product-brand${hero ? " product-brand-hero" : ""}${onActivate ? " product-brand-action" : ""}`}>
    <span className="product-brand-lockup">
      <span className="product-brand-mark" role="img" aria-label="DocReview RAG">
        {hero && <span className="product-ascii product-ascii-full">{PRODUCT_ASCII}</span>}
        <span className="product-ascii product-ascii-compact">{PRODUCT_MONOGRAM.replace(/^ /gm, "")}</span>
      </span>
      <span className="product-brand-content">
        <span className="product-name" tabIndex={updated && !onActivate ? 0 : undefined} aria-describedby={updated ? tooltipId : undefined}>
          <span className="product-edition">DocReview <span className="product-name-suffix">RAG</span></span>
          {updated && <span className="product-brand-tooltip" role="tooltip" id={tooltipId}>Last updated<time dateTime={builtAtIso()}>{updated.date} · {updated.shortTime}<span>{updated.zone}</span></time></span>}
        </span>
      </span>
    </span>
  </Root>;
}

/** Quiet footer metadata describes the fixed build, separate from the primary brand. */
export function BuildInfo({ onOpen, mode }: { onOpen: () => void; mode?: ReactNode }) {
  const fingerprint = buildFingerprint();
  if (!mode && !fingerprint) return null;
  return <div className="sidebar-build-info"><div className="sidebar-build-heading">{mode}{fingerprint && <button type="button" className="build-info-link" onClick={onOpen}>Build <code>{fingerprint}</code></button>}</div></div>;
}

# DocReview screenshot processing and placement handoff

Use SWE-2 Max for this stage after DeepSeek v4.1 Flash has delivered its captures. This is a future assignment; no screenshot processing has been performed yet.

Read `docs/TUTORIAL/CAPTURE_HANDOFF.md`, `docs/TUTORIAL/capture-plan.json`, and `/tmp/docreview-captures-2026-09-14/capture-results.json` and `capture-results.md` before editing. The raw PNGs are in that same temporary directory. Inspect the real image files and the surrounding Korean/English guide sections. Preserve the approved prose, menu structure, typography, existing viewer, source identities, and unrelated work.

## Acceptance before editing

1. Match each image to its declared scene, locale, runtime mode, source record, viewport, and DPR. Check actual PNG dimensions and hashes. Reject substitutes, low-resolution originals, mixed UI languages, loading/error screens, clipped controls, and any Next development indicator.
2. Check the image at its intended article size, not just at full zoom. Desktop originals are 2880 × 2000 pixels and mobile originals 780 × 1688. Focused crops retain native pixel density; never upscale a small crop to fill the 720px article.
3. Return a concise recapture request for each failed item: scene ID, locale, observed defect, and required replacement. Keep independent accepted work moving. Missing evidence stays pending or blocked; never generate a substitute or silently reuse a legacy image.

## Processing and placement

- Keep full originals unchanged. Use lossless crops or the captured focused images. Preserve RGB/alpha fidelity and all text; no generative fill, redrawing, text replacement, synthetic states, aggressive sharpening, or lossy conversion.
- Match temporary files to their capture IDs and copy accepted originals/processed variants to the final paths declared in `capture-plan.json`. Preserve the temporary originals and their traceability; do not require the capture worker to write into the repository.
- Choose a crop that makes the described operation obvious and retains enough context to identify the screen. Long dialogs may need separate figures; do not stitch different application states into one image.
- Add the planned numbered callouts as a separate HTML/SVG layer, using reported pixel bounds and the image aspect ratio. Scale positions with the figure. Keep numbers outside the control text, align their captions, and use the existing accent, border, font, and icon language. Add an arrow only when a number leaves its target unclear. Callouts are explanatory and do not execute controls.
- Keep a narrower crop at an appropriate maximum display width. Use the declared mobile variant when its arrangement differs materially; never squeeze the desktop screenshot into a narrow phone column as a substitute.
- Update only the relevant screenshot markers, image references, localized alt text/captions, capture status/metadata, and the minimal shared image-rendering code required for responsive variants or callouts. Preserve exact capture IDs, old document anchors, zoom, original-image access, keyboard dismissal, and reserved aspect ratio.
- Replace the legacy-layout notices only after their corresponding new images are accepted. Do not delete legacy assets without separate confirmation. Do not rewrite surrounding manual text or change application behavior to match a capture.

## Review and delivery

Verify both locales in light mode at 390, 768, 1280, and 1440 CSS pixels. Check text readability, callout placement, captions, clipping, page overflow, and the expanded/original-image viewer. Run guide preparation, capture-manifest/link checks, affected image-renderer tests, typecheck, and the affected web build.

Return a per-scene acceptance table, changed files, verification results, and remaining recapture items. Keep originals and evidence traceable. Review the final rendered pages on the running local service before considering deployment. The primary coordinator gives final acceptance before publication. No commit, push, deployment, new application model request, evaluation, index build, or runtime-mode switch is authorized by this processing assignment.

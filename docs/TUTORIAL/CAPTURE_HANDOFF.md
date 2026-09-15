# PNG screenshot capture assignment

Use OpenCode with DeepSeek v4.1 Flash. Your task is only to capture the requested screens.

Read `/tmp/docreview-captures-2026-09-14/capture-requests.json`. It contains 35 scenes, their URLs, required display states and exact output filenames. Each scene needs Korean and English captures in light mode; eleven scenes also need mobile captures.

1. Use the running local service at http://localhost:8000/docreview-rag/. Check that the visible DEV/PROD mode matches each scene. If the mode, required data or saved screen is unavailable, record that scene as blocked and continue with available scenes. Do not restart or reconfigure the service.
2. You may navigate, switch UI language/theme, open tabs and dialogs, expand details and scroll to the described state. Do not submit questions, start jobs, save settings, publish, delete or reset anything. Do not run terminal commands or inspect source files.
3. Capture directly as lossless **PNG**. Desktop: 1440 × 1000 CSS pixels at DPR 2, yielding **2880 × 2000 pixels**. Mobile: 390 × 844 at DPR 2, yielding **780 × 1688 pixels**. Verify actual PNG dimensions and observed DPR on the first pair before capturing the rest.
4. Save every image under `/tmp/docreview-captures-2026-09-14/` using the filenames in the shot list. For each desktop state, save a full original and a focused crop from that same state. Save the separate mobile image where requested. Do not send chat thumbnails as the image files.
5. Keep the original PNG unchanged. The crop must retain native resolution. Never enlarge a small image, apply sharpening to disguise low resolution, or convert to lossy JPEG. A crop displayed at 720 CSS pixels needs at least 1440 source pixels of width; narrower crops should be displayed narrower.
6. Wait for fonts, translations and the requested content to settle. No Next logo, development toolbar, loading state, error overlay or clipped control may appear. If one prevents a valid capture, report the blocked scene instead of hiding or painting over it.
7. UI-owned labels must match the selected language. Original filing excerpts, company names, model names and existing questions can retain their original language. Keep text and control boundaries sharp and readable at the intended display size.
8. Do not add arrows, numbers or other image edits. Record each requested callout target's bounding box in focused-image pixels; cropping refinements and annotations will be handled afterward.
9. Return `/tmp/docreview-captures-2026-09-14/capture-results.json` and `/tmp/docreview-captures-2026-09-14/capture-results.md`. For every scene and locale, report captured/blocked, observed URL and mode, actual viewport/DPR, PNG paths/dimensions, crop bounds, callout bounds, and any missing prerequisite. Do not replace an unavailable scene with a different screen.

Stop after saving the PNGs and the result reports.

[2026-09-07] [web/app/v2.css:313] [type: bug] At a 360px viewport, skipped-phase reason text can protrude into adjacent execution-strip tiles under the existing compact-theme layout. Observed during issue #140 browser QA; the text and layout rules are unchanged by that issue.

[2026-09-07] [web/components/service-shell.tsx] [type: bug] In 360px Chromium QA with the conversation title "Second preserved review", the history trigger overlaps the theme button hit target. Observed while testing browser storage; no header-layout changes were made or investigated.

[2026-09-08] [web/components/service-shell.tsx] [type: bug] At 390px viewport width, the shared topbar breadcrumb overlaps the locale controls on /docreview-rag/production-preview/?locale=ko&theme=light&view=measure&tab=presets. Observed during isolated preset browser QA; the preset list and editor controls fit within the viewport.

[2026-09-09] [app/ingestion/source_publication.py:35] [type: bug] fixed_path now expects `<registry>/<issuer>/<filing_id>/<name>`, so a corpus acquired on the previous main layout (`sec/<filing_id>/primary.html`) fails resolve_primary with a plain ValueError: not ready, not redownloadable, not deletable until start-fresh. Accept the legacy path or migrate registered artifacts on upgrade. Observed in PR #206 review; no local corpus uses the old layout.

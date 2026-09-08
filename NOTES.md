[2026-09-07] [tests/api/test_execution.py:82] [type: debt] The clean-checkout gate fails Ruff I001 on main because report_to_records precedes records_to_report in a local import; the one-line reorder is outside the approved script refactor and awaits explicit permission.
[2026-09-07] [tests/api/test_execution.py:82] [type: debt] Resolved by merged PR #113; the complete clean-checkout gate passed, including required live reset verification.

[2026-09-07] [web/app/v2.css:313] [type: bug] At a 360px viewport, skipped-phase reason text can protrude into adjacent execution-strip tiles under the existing compact-theme layout. Observed during issue #140 browser QA; the text and layout rules are unchanged by that issue.

[2026-09-07] [web/components/service-shell.tsx] [type: bug] In 360px Chromium QA with the conversation title "Second preserved review", the history trigger overlaps the theme button hit target. Observed while testing browser storage; no header-layout changes were made or investigated.
[2026-09-08] [web/components/service-shell.tsx] [type: bug] At 390px viewport width, the shared topbar breadcrumb overlaps the locale controls on /docreview-rag-agent/production-preview/?locale=ko&theme=light&view=measure&tab=presets. Observed during isolated preset browser QA; the preset list and editor controls fit within the viewport.

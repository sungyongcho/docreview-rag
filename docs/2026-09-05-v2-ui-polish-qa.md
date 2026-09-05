# DocReview RAG v2 visual and interaction QA

Baseline application: `be3d837`. Final capture starts only after bilingual documentation functionality
is verified. `TUTORIAL/captures.json` records pending slots separately; no placeholder image is used.

## Findings fixed before capture

| ID | Observed defect | Fix and evidence |
|---|---|---|
| I01 | A retained request inspector could remain visible and lock background interaction after its workspace hid. | Inherited activity gates the portal and handlers; failing regression now passes in be3d837. |
| I02 | A delayed interrupted-reset response could open a dialog over a different workspace. | Reset portal and keyboard/focus effects respect ancestor activity; regression passes in be3d837. |
| I03 | Pin guidance did not explicitly state that inclusion is not guaranteed citation. | Bilingual visible explanation and saved-result regression in be3d837. |

## Capture and polish record

| ID | Actual scene and defect | Fix | Retake |
|---|---|---|---|
| V01 |1440×1000 Korean connection diagnosis showed Passed and success used an error-details label. Before: `TUTORIAL/assets/qa/24-diagnostics-before.ko.png`.|a4d3d1b adds dynamic translation, neutral Diagnostic details, and a regression test.|24-connection-diagnostics.ko.png confirms 통과/진단 상세. Final framing is checked with the capture set.|
| V02 |Default setup link used browser blue against the restrained interface palette. Before: `TUTORIAL/assets/qa/13-default-before.ko.png`.|a4d3d1b keeps underlined links in the interface foreground color.|13-local-model.ko.png retaken.|

Later user-requested hotfixes consolidated Help to two screens, removed persistent markers, unified settings, compacted request inspection, highlighted company/year, ordered EN first, and diversified documentation icons. These are bounded requested changes; no further aesthetic exploration follows the scope freeze.

## Matrix accounting

Required CSS widths: 390, 768, 1280, 1440, 1920, 2560, 3440. Korean/English; light/dark; sidebar open/closed.
Record measured viewports and concrete screens rather than implying every possible combination was tested.
Running/loading/failure/legacy states must come from existing records or identified component tests;
no model calls or synthetic production outcomes will be created for an image.

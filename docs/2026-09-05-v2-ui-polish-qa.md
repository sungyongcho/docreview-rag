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

Pending actual capture. For each observed visual defect, record the exact scene/viewport, source location,
smallest fix, verification, and affected recapture. Unaffected scenes will not be recaptured.

## Matrix accounting

Required CSS widths: 390, 768, 1280, 1440, 1920, 2560, 3440. Korean/English; light/dark; sidebar open/closed.
Record measured viewports and concrete screens rather than implying every possible combination was tested.
Running/loading/failure/legacy states must come from existing records or identified component tests;
no model calls or synthetic production outcomes will be created for an image.

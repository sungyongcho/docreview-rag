# Shared DEV and PROD UI

`web/` in the main working checkout is the canonical frontend source. DEV and PROD
use the same components, styles, and tests; build mode and server capabilities select
the existing permitted controls. Preserve each mode's approved rendered behavior.

The local PROD frontend on port 8000 already mounts this directory. The isolated DEV
API on port 8010 serves static assets, so refresh its frontend from this same source:

```bash
python -m scripts.stack.refresh_dev_ui --container docreview-dev-parity-app-1
```

Use `--dry-run` to validate the target without building or copying anything. The helper
builds only the existing Docker `web` target with DEV presentation enabled, then copies
only its static output. It rejects PROD targets and checks that the API container identity
and start time stay unchanged. It does not restart the API, install Python packages,
change environment variables, touch data volumes, or remove assets used by open tabs.
Reload the 8010 browser after a successful refresh.

The earlier isolated source checkout is a comparison checkpoint, not a second UI authoring
location. Do not manually copy edited frontend files there. Backend packaging and rebuilds
remain separate, especially when the running DEV container has locally installed extras.

DEV's embedded PROD preview is deferred to [issue #211](https://github.com/sungyongcho/docreview-rag-agent/issues/211).
The release includes DEV and PROD only. Browser export/import changes remain outside this work.
No production deployment, publication, or integration is performed by this helper.

# DocReview Cloudflare router

`docreview-router` owns only `sungyongcho.com/docreview-rag` and
`sungyongcho.com/docreview-rag/*`. Its routing logic was separated from Gomoku's
router while preserving compatibility date `2026-02-11` and DocReview's existing
public URLs.

| Public request | Upstream |
| --- | --- |
| `/docreview-rag/api` or `/docreview-rag/api/` | `DOCREVIEW_ORIGIN/` |
| `/docreview-rag/api/<path>` | `DOCREVIEW_ORIGIN/<path>` |
| `/docreview-rag` or `/docreview-rag/<path>` | The same path on `DOCREVIEW_SITE_ORIGIN` |
| Other host or path | `404`, with no upstream request |

The API origin defaults to `http://docreview-api.sungyongcho.com:8880`; the static
origin defaults to `https://docreview-rag.web.app`. Query strings, methods and
request bodies pass through. Responses preserve status, headers, `Retry-After`,
redirects and SSE chunks. The Worker streams both directions, never retries, and
does not introduce login, sessions, visitor identifiers or another rate limiter.

The Caddy origin owns forwarded-IP sanitization and body-size enforcement. Its
direct peer address supplies the shared server request key; Worker IPs are not
authentication credentials. Before production changes, verify Caddy's observed
peer address and the Cloudflare-only firewall path independently.

## Local verification

Use Node.js 22 or newer. The lockfile pins Wrangler `4.141.0`, its matching
Miniflare `5.20260925.0-alpha`, and workerd. The Miniflare prerelease is the exact
version used by this Wrangler release; tests use its installed v5 API.

```bash
npm --prefix deploy/cloudflare ci
npm --prefix deploy/cloudflare test
npm --prefix deploy/cloudflare run deploy:dry-run
npm --prefix deploy/cloudflare run deploy:dry-run -- --bootstrap
```

Tests execute the maintained Worker in workerd against isolated local HTTP
origins. They verify prefix boundaries, query/header preservation, upload chunks
arriving before completion, SSE events arriving before completion, unchanged
error/redirect responses, no automatic retries, and isolation from Gomoku paths.
Deploy-entry tests verify the bootstrap configuration and credential boundary.
A dry run validates packaging; it does not verify the live firewall or routes.

## Credentials and deployment

Provide `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` in the invoking
environment or the repository's ignored `.env`; `DOTENV_PATH` can select another
dotenv file. Environment values win. Use account-scoped Worker edit and the
existing zone's Worker-route permissions. DNS edit is not used by this entry.

Optional `DEPLOY_DOCREVIEW_ORIGIN` and `DEPLOY_DOCREVIEW_SITE_ORIGIN` replace the
two defaults. Origins must be HTTP(S) roots without credentials, paths, queries
or fragments. Other dotenv settings, including OpenAI keys, are never copied to
Worker bindings. Generated configuration contains only non-secret Worker settings,
is ignored by Git, and is removed when the command exits. Credentials remain in
the Wrangler process environment.

For the initial split from `gomoku-ws-router`, keep the existing public routes on
that Worker until the backend and static site are ready:

```bash
npm --prefix deploy/cloudflare run deploy -- --bootstrap
```

Bootstrap creates/deploys `docreview-router` with `routes: []`, `workers_dev: false`
and `preview_urls: false`. It retains the canonical bindings and compatibility
settings. **Use bootstrap only before route ownership transfer**: running it
afterwards would remove this Worker's assigned routes. It does not edit the
Gomoku Worker or transfer any routes.

Then, as a separate authorized cutover, reassign only the two existing DocReview
route IDs from `gomoku-ws-router` to `docreview-router`. Check their expected
previous owner first, preserve the other routes, and remove the DocReview routes
from Gomoku's maintained deployment configuration so a later Gomoku deployment
cannot reclaim them. Do not create duplicate route patterns. Verify public
DocReview API/static paths and unchanged Gomoku routes after transfer.

After the transfer, normal deployments reconcile only this dedicated Worker:

```bash
npm --prefix deploy/cloudflare run deploy
```

The deploy entry never updates DNS or deploys another Worker. It is intentionally
not part of the Oracle or Firebase deployment scripts. Runtime observability
uses 1% sampling, disables invocation logs, and redacts URL query strings; the
Worker emits no application logs containing bodies, visitor IPs or credentials.

## References

- [Cloudflare streaming responses](https://developers.cloudflare.com/workers/runtime-apis/streams/)
- [Request forwarding and manual redirects](https://developers.cloudflare.com/workers/runtime-apis/request/)
- [Wrangler deployment configuration](https://developers.cloudflare.com/workers/wrangler/configuration/)
- [Wrangler Worker commands](https://developers.cloudflare.com/workers/wrangler/commands/workers/)
- [Workers traces and sampling](https://developers.cloudflare.com/workers/observability/traces/)

# Free Cloudflare Pages staging deployment

## Current blocker

Cloudflare API connectivity succeeded. The actual token-verify endpoint replied
HTTP400 / code1001 / Missing Authorization header. The official Wrangler4.151.1
CLI reported: "You are not authenticated. Please run `wrangler login`."
No Cloudflare site has been created or published. Local Pages/workerd is QA only.

## Only owner action required

Use the cloud environment's secure settings (not chat) to provide:

- CLOUDFLARE_API_TOKEN: a token limited to the owner's selected Cloudflare account,
  with Account → Cloudflare Pages → Edit. No billing, R2 or unrelated resource
  permission is required. Do not paste the token into source, logs or chat.
- CLOUDFLARE_ACCOUNT_ID: the chosen account ID (non-secret).

Requirements have been saved in the environment configuration draft. Saving the
requirements did not authenticate the current process or deploy an application.
The owner's free account must have Pages available. No payment card, paid plan,
Cloudflare subscription or R2 checkout is authorized. Do not use an anonymous
Wrangler --temporary account as a substitute for owner authorization.

## Agent continuation after secure authorization

Recheck the specific authorized API operation without printing credentials. Reuse
this exact built web/ directory. Do not rebuild the verified V4 or touch Replit.

The pinned CLI is `/tmp/hks-pages-deploy-cli-20261017/node_modules/.bin/wrangler`.
If unavailable after reconnect, install `wrangler@4.151.1` into a new /tmp prefix
with npm, no global install and no changes to preserved projects. Node>=22.
Disable optional metrics. These CLI commands are for authorized continuation:

```
wrangler pages project list
wrangler pages project create hks-pro-trader-browser-staging --production-branch browser-staging
wrangler pages deploy web --project-name hks-pro-trader-browser-staging --branch browser-staging --commit-dirty=true
```

Only create the project if absent in the selected account. Use free **Pages**
static direct upload, not a paid Worker/server or existing production project.
The 'production branch' above belongs only to this new staging Pages project;
it never refers to the existing Replit website. Do not push any Git repository.
No Pages Functions, secrets in assets, database bindings or paid storage exist.

## Verification required before claiming LIVE

Record actual deployment URL/ID, account/project identity, static manifest and
published checksums. Use the stable Pages project URL so OPFS/IndexedDB keep the
same origin between revisions. Deployment-hash preview URLs have distinct caches.

Verify remotely:

- HTTPS200 page, JS and WASM. COOP=same-origin and COEP=require-corp;
  crossOriginIsolated and SharedArrayBuffer actually available.
- Extensionless /sandbox and inert /vendor/pyodide/console CSP. Cloudflare redirects
  .html URLs; the final route must have the correct policy.
- Browser Python paste→Run, the hand-calculated partial case, genuine small data
  in Shared AND Individual mode; result hashes and reconciliations.
- Cache warm reuse performs zero candle downloads. Reload and fresh process retain
  source, report and source hashes. Cancel→reload→resume a verified checkpoint.
- Android owner's current Chrome: trusted-source acknowledgment, Run, touch journal,
  CSV export, reload, storage behavior and OS background/suspension recovery.

Until those checks run on the actual URL, hosted readiness is UNVERIFIED.

## Free limits and data/storage

Official free Pages documentation inspected in the preserved proof: static
requests are free, maximum asset25MiB, maximum20,000 files, and500 monthly builds.
Direct upload avoids a paid server. This site is approximately26.6MB with63 assets;
exact final counts/checksums are in evidence/STATIC_BUILD.json and SOURCE_SHA256.json.
No aggregate 'unlimited historical data storage' promise is made. No four-year
history is bundled or enabled. R2 requires checkout/overage billing and is excluded.
The actual owner's account/eligibility and hosted limits cannot be verified without
its authorization. A static website is public; do not add proprietary strategies,
private data, credentials or owner-only reports to web/.

## Recovery / rollback

Keep the preserved V4 and browser proof plus their hashes unchanged. Save the
new static build/source manifest and actual deployment receipt outside this
workspace after a verified handover. Existing Replit is untouched and remains
independent. Restore a previous Pages deployment only after verifying its source
manifest; source-bound checkpoints cannot resume under different runtime code.
Do not update the site mid-calculation. Completed reports remain local; export
important CSVs before clearing site data or changing origins. A device cache is
not durable shared hosting or an external backup.

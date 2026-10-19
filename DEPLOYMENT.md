# Preserved deployment configuration

Current Pages project: `hks-pro-trader-browser-staging`.
Verified deployment: `3f09eb4b-f8d9-4679-9c75-e08ccd2b49db`.
Production branch label on that direct-upload project: `browser-staging`.
The project has no Git integration; pushing this backup branch does not publish
the website. No GitHub deployment workflow is included here.

`wrangler.toml` and `web/_headers` are preserved exactly. Required COOP/COEP/CORP
and Content Security Policy isolate the strategy iframe and Web Workers. Local
testing uses the same policies through `serve.py`; a generic static server or
`file://` opening is insufficient.

This is a source-only backup, not an instruction to replace the live site with
missing market files. Restore the 26 excluded historical files and verify their
checksums before reproducing genuine-market functionality or packaging another
equivalent complete site. Keep verified old source/data packages for rollback.

No credentials are needed for local use. If the owner separately approves future
publishing, configure the existing Cloudflare account and least-privilege Pages
authorization securely in the CLI environment. The blank template is
`config/cloudflare.env.example`. Never put real values in Git or `web/`.

An authorized future staging publish uses the existing project and output
directory, with no Workers/Functions/database/billing changes. It must be followed
by HTTPS header/API verification, both financial modes, journal/CSV checks and
cache/reload/restart verification. Do not treat an upload receipt as functional
proof. Do not use this backup branch to alter Replit or the historical `main`.

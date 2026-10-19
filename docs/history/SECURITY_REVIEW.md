# Static browser security scope

Implemented: trusted financial interpreter and user-strategy interpreter are
separate Web Workers; strategy worker belongs to an iframe sandboxed with
allow-scripts and NO allow-same-origin. CSP denies its network/storage origin.
Only preloaded Pyodide runtime bytes, strategy API and causal observations enter
that realm. It receives neither app storage handles nor financial interpreter
references, SAB, host environment credentials, future candles or other users' data.

Pyodide JS FFI is not claimed disabled. This is trusted-code-only execution,
explicitly acknowledged before Run. Browser workers do not provide a hard memory
cap; large allocations can kill the tab or browser. Timeouts/cancel keep host app
responsive for tested cases but cannot certify adversarial resource containment.
The original secure server/container candidate remains unchanged and is not
replaced by an OS-equivalent security claim.

Checkpoints serialize financial state as explicitly tagged JSON with a closed
set of known dataclasses, Decimal/collections, bounded nesting and sizes. No
pickle/eval/source enters the financial decoder. Strategy pickle bytes are
opaque to the page and financial interpreter and unpickled ONLY in the already
isolated trusted-code strategy worker. Recovery of nondeterministic or unsupported
Python state is not certified; contract restrictions and explicit errors apply.

Checkpoint pointers commit only after write/close/hash read-back. The previous
complete pointer survives an interrupted new write. Compressed bytes are hashed
before restoration; identity binds strategy/config/data and the trusted runtime
source files. Latest two checkpoints are retained; other completed reports are
immutable local blobs with hashes. Web Locks prevents concurrent runners in the
same browser profile; this is not distributed account/server locking.

DOM rendering uses textContent (including code, errors, trades and metadata).
CSV exports escape formulas. Vendor console is inert on both .html and Pages
extensionless routes. A failed boot/unsupported browser displays an error and
leaves Run disabled. No insecure origin or --no-sandbox browser fallback is used.
No secrets/account API is present in the static application. Authenticated server
account features were not simulated; state is explicitly local to a device/profile.

The whole static web/ set is the publication allowlist. Credentials, .git, .env,
.wrangler, local database/state, private HKS/ABG artifacts and raw owner datasets
are excluded. Scan findings, source preservation and actual checks are recorded
in evidence. No real/demo exchange connectivity or production mutation exists.

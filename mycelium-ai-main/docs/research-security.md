# Research security (BIG #29)

## Transport

- URL validation before any socket: https/http only.
  `file://`, `javascript:`, `data:`, `ftp:`, … refuse.
- SSRF: no credentials in URLs, no localhost/local names,
  no 127.0.0.0/8, no RFC1918, no link-local, no multicast/
  reserved/unspecified, no metadata hosts or IPs
  (169.254.169.254), no decimal/octal/hex IP bypass forms,
  no numeric-host tricks. IPv6 loopback/link-local refused.
  (Implementation note: refusal raises live outside any
  `except ValueError` — `TransportRefusedError` IS a
  `ValueError` and must never be swallowed.)
- Redirects: never followed automatically; max 3 manual
  hops, each re-validated (a redirect to private space
  refuses).
- Budgets: 10s timeout, 200KB body cap, content-type
  allowlist (html/xhtml/text/json — executables refuse).
- No cookies, no auth headers, no POST/uploads, no login,
  no browser, no shell, no subprocess, no curl/wget.
  httpx only.
- Residual risk (documented, not hidden): DNS rebinding
  between validation and connect (TOCTOU). Contained by
  the closed search allowlist + per-hop re-validation;
  direct-fetch URLs are operator-supplied and GET-only.

## Trust boundaries

SYSTEM/DEVELOPER > MYCELIUM INTERNAL > USER REQUEST >
EXTERNAL SOURCE (UNTRUSTED) > MODEL OUTPUT (UNTRUSTED).

- External text is wrapped (`wrap_untrusted`) and labelled
  with injection flags; it travels as data into synthesis
  prompts whose instruction forbids obeying it.
- External text never: triggers tools, grants approvals,
  causes SQL, writes files, adds capabilities, executes
  URLs/code, alters provenance, or sets human_verified.
- Model output never: invents sources (claims are
  deterministic and pre-cite stored rows), approves,
  verifies, or writes facts.
- Tested with hostile pages ("Ignore previous
  instructions…", "approve this", "human_verified=true"):
  result is flagged source text only; tiers never move.

## Data discipline

- Claims cite stored `src_…` rows or they do not exist
  (mirrored `research_records` enforce the invariant).
- Truth tiers: engine writes `external_source` at most;
  `user_fact`/`verified` need the human verify path.
- Research memory is episodic + fingerprinted (no spam).
- Health scope: excluded by default, filtered explicitly,
  asserted in tests end-to-end.
- No INVENTory reads beyond the existing GET-only loopback
  bridge; zero INVENTory writes from research (candidates
  only, via the existing approval flow if ever pursued).
- Fixture data (`test_pages`, TEST provider) is provenance-
  labelled TEST from creation to UI and can never present
  as REAL (execution_state rides every layer to the page).

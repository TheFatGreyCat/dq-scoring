# DQ Scoring — Application UI Design

**Status:** Proposed design; not a description of a deployed UI. **Audience:** data stewards, data owners, analysts, and workspace administrators. **Scope:** browser application for the existing local/API workflow, with explicitly identified backend gaps. **Sources of truth:** [SRS](../Chapter_2.md) (especially IF-UI-001..016, AC-012, AC-022, AC-025), [scoring theory](../theory/DQ_SCORING_THEORY.md), [deployment guide](DEPLOYMENT_GUIDE.md), and the implemented `src/dq_scoring/presentation/api/` routes and schemas. Where these disagree, the implemented API defines what can run today; the SRS defines the target behavior.

## 1. Product boundary and choices

**Recommended stack:** React + TypeScript + Vite; React Router for routes; TanStack Query for server state and polling; shadcn/ui (accessible Radix primitives) with Tailwind CSS for forms/dialogs/tables; a small chart library only for actual assessment visualizations. Generate a typed client from FastAPI's `/openapi.json` once the API contract is stable. Do not introduce Next.js/server-side rendering for an authenticated internal application without a server-rendering requirement. No browser-to-PostgreSQL, browser-to-Spark, or direct privileged MinIO credentials. FastAPI owns authorization and reads; the worker/Spark own evaluation. The UI displays bounded API responses, never scans source datasets in the browser.

**Why not Streamlit as the primary UI:** the existing `src/dq_scoring/presentation/ui/dashboard.py` contains formatting functions, not a runnable dashboard; `deploy/charts/dq-scoring/values.yaml` disables UI deployment. A multi-tenant approval workflow, route permissions, large result tables, and distinct public/private projections need an application shell. Swagger at `/docs` remains a development tool, not the product UI.

**Alternatives considered:** Streamlit is quickest for a single-user demonstration but has poor fit for approval/navigation and secure public/private surfaces. Next.js is viable when server rendering or public discoverability matters, but adds an application server without a current requirement. React/Vite is the simplest bounded browser client here.

## 2. Navigation and page inventory

Authenticated desktop shell: persistent left navigation (**Overview**, **Assets**, **Rulesets**, **Policies**, **Runs**, **Assessments**); top bar shows workspace/tenant context, signed-in identity, theme toggle, and sign-out. On small screens use a labelled navigation drawer; never conceal run errors in toast-only messages. Deep links use IDs and survive refresh. The public assessment is a separate minimal layout, without internal navigation or metadata.

| Route (proposed browser path) | Primary purpose | State / visibility |
| --- | --- | --- |
| `/login` | Email/password login, optional tenant choice if membership exists | Public form; never include credentials in URL |
| `/` | Overview: latest visible assessments, run status and approvals awaiting action | **Requires new list/summary APIs**; until then show explicit links to known IDs rather than fabricated KPIs |
| `/assets`, `/assets/new`, `/assets/:id` | Register asset; view snapshot lineage/schema and register a read-only snapshot | Create supported; list/detail require APIs |
| `/rulesets`, `/rulesets/new`, `/rulesets/:id` | Define rules, submit, independently approve | Create/submit/approve supported; retrieval/list require APIs |
| `/policies`, `/policies/new`, `/policies/:id` | Configure weights/thresholds; submit, independently approve | Create/submit/approve supported; retrieval/list require APIs |
| `/runs`, `/runs/new`, `/runs/:id` | Select snapshot + ACTIVE configurations; trigger, observe terminal state | Trigger/status supported; history/list require API |
| `/assessments`, `/assessments/:id` | Browse results; detail scorecard and rule drill-down | Detail supported; list requires API |
| `/public/assessments/:id` | Sanitized published public scorecard | Existing public projection only; no rule/evidence data |

Prefer a single run wizard over nested modal workflows. Show persistent breadcrumb and copyable IDs on detail pages. No empty dashboard pretending that a list endpoint exists.

## 3. Key workflows

### 3.1 Authentication and tenant boundary

Login collects **email**, password, and optional tenant ID (not the sample username shown in the older user guide); POST `/api/v1/auth/login`. A failed login gives a generic non-enumerating message. On success store the access token **in memory** and set the current tenant from the authenticated session; do not put tokens in URLs, localStorage, analytics, or error reports. The current refresh endpoint accepts a refresh token in JSON; an HttpOnly, Secure, SameSite cookie/session design requires a separate backend contract before claiming cookie security. For an initial implementation, keep refresh credentials out of persistent browser storage, accept re-login on reload, and perform single-flight refresh while the page stays open. Reuse/revocation failure clears state and redirects to login. POST `/api/v1/auth/logout` revokes refresh token on sign-out. Never trust a client-supplied tenant as authorization; the server enforces membership/RLS. Switching tenant requires a fresh authenticated context, cancels in-flight queries and clears the tenant-scoped cache. Do not expose tenant switch until a supported membership-discovery flow exists.

### 3.2 Assets and snapshots

Create an asset with a name; show the returned `asset_id`. Snapshot registration accepts `asset_id`, `source_kind`, `source_descriptor`, `schema_definition`, `total_rows`, and `total_columns` per `asset_schemas.py`. For the local workflow, show a validated **server-visible** file descriptor and clear warning: entering a path does not upload bytes and the path must be readable by the worker. Avoid arbitrary client filesystem paths presented as safely uploaded data. Display immutable snapshot ID, capture time, schema and row/column counts; never offer an edit-source action. File upload to MinIO, content hashing/manifest verification, schema inference and asset browsing require dedicated server APIs; design those as separate additions, not client-side imitations. Do not embed MinIO root credentials in the browser.

### 3.3 Rulesets and scoring policies

Ruleset editor: choose an asset, enter name, add/remove rules; for each rule show type, dimension, target column, required/critical/advisory flags and validation specific to its schema. Policy editor: name, dimension weights, coverage and gate thresholds with units and inline validation. Review panels summarize what will be submitted; state progression **DRAFT → PENDING_APPROVAL → ACTIVE**. Show creator/submitter and approver identities when the backend supplies them; otherwise do not invent audit facts. Submission is explicit and approval requires a **different authorized user**; hide inapplicable controls for clarity, but always rely on server-side 403/status validation. A conflict/stale status returns the latest server state with a reload action. No editing ACTIVE revisions in place or implicit approval. Revision history requires a new read API.

### 3.4 Run initiation and lifecycle

Wizard checks snapshot ID, ACTIVE ruleset/policy IDs and compatible schema before POST `/api/v1/runs`; backend validation remains authoritative. Confirm `execution_profile`, optional outlier columns, and an idempotency key generated once per user intention and retained across network retries. Disable duplicate submission while pending; a timeout means **unknown**, not failed: offer lookup/retry with the same key rather than minting a second run. Show the returned run ID and `QUEUED` state immediately. Poll `GET /api/v1/runs/{run_id}/status` every 5–10 seconds while the page is visible; stop on `SUCCEEDED` or `FAILED`, stop on unmount/logout/tenant change, and refetch on return to the page. `SUCCEEDED` with assessment ID links to scorecard; `FAILED` shows a sanitized run error and **no assessment**. Polling transport failures are a separate reconnect state, not a fabricated run failure.

The SRS requests percent/stage/ETA (IF-UI-005), but the current endpoint provides only status, error, assessment ID, and update time. Display a labelled **indeterminate** activity indicator and actual status; do not calculate fake progress, ETA, rows processed, or live Spark metrics. Add server progress fields and semantics before implementing a determinate bar or SSE.

### 3.5 Assessment and evidence

Scorecard header has separate fields for **DQ Score, coverage, publication status, quality gate and timestamp**. Show the six dimension tiles, including explicit `Not measurable` / `Not applicable` for null scores. A `WITHHELD` assessment shows `—` for null DQ Score and an explanation based on available gate/measurement data; do not coerce it to zero. Gate precedence is `ERROR` > critical `FAIL` > `INSUFFICIENT_EVIDENCE` > score `FAIL` > `WARN` > `PASS`. Display the returned gate rather than re-scoring in JavaScript; a high score may still have a critical FAIL. A globally FAILED run has no assessment. Advisory outliers are labelled separately, with zero contribution to score/gate. Score/coverage formatting happens only for display; preserve distinct value/status fields and avoid intermediate rounding. Use the assessment hash and snapshot/run IDs as provenance, not as links to raw source.

Rule drill-down table: dimension, rule code, target column, measurement status, nullable score, valid denominator/counts, violation count, required/critical/advisory flags. Details show five mutually exclusive counts (`passed + failed + missing + miscast + not_applicable = total_observed`), sanitized measurement error when present, and **only bounded, redacted** `evidence_samples` returned by the private API. Never request an unbounded sample, render raw HTML, or display raw server paths/SQL/stack traces. Evidence downloads and paginated evidence viewer require a dedicated redacted server endpoint and CSV formula-injection protection; do not reconstruct an unsafe export from arbitrary JSON.

Public layout calls only `GET /api/v1/assessments/{id}/public` and renders score, six dimensions, coverage, gate, hash and timestamp. A non-published/non-public ID has a neutral unavailable page. Never fetch the private detail and then hide fields in CSS; no evidence, user, tenant, internal source descriptor, or infrastructure metadata may enter the public browser response. Public read availability is distinct from the deferred expiring share-token feature (IF-UI-010).

## 4. State, errors, and usability

Every data view has explicit loading, empty, success, unavailable/forbidden, and transport-error states. Keep previous server state visible with a 'Refreshing' label when safe; on tenant change clear it immediately. Handle 401 by re-authentication, 403 by explaining lack of access without revealing whether another tenant's record exists, 404 as unavailable, 409 as stale workflow state, 422 as field-level validation, and 5xx as retryable generic error with a non-sensitive correlation ID if provided. Render RFC 9457 safe detail only; never show raw response bodies if they contain traces. Make the run status and approval transitions screen-reader announcements, but avoid repeated polling announcements.

Visual language: compact enterprise analytics with a red-accent theme: white cards (`#FFFFFF`, 12px radius, soft shadow) on `#F5F5F5`, text `#282828`/`#5C5C5C`, borders `#D9D9D9`, 8px control radius, dark `#2C2F31` navigation. Brand red `#EE0033` is **chrome only** (top strip, active-nav marker, focus ring); text-bearing actions use `#D6002F` (hover `#BE0129`) because white on `#EE0033` is below 4.5:1. Gate/status hues are deliberately distinct from brand red: PASS `#157F3B`, WARN `#B54708`, FAIL crimson `#9F1239`, ERROR violet `#5B21B6`, INSUFFICIENT_EVIDENCE/WITHHELD slate `#475467`, active run blue `#0B63CE`, always as **text + icon + color**, never color alone. Tokens live in `frontend/src/styles/tokens.css` (light and dark) and a unit test enforces AA contrast for every text pair. Sarabun (OFL, includes Vietnamese glyphs) for UI and Roboto Mono for IDs/counts, both self-hosted; fixed-width numeric columns, clear units (`%`, rows, UTC timestamp with local-time display), tooltips defining coverage vs score. Responsive at 375/768/1024/1440 px: on narrow view stack cards and convert tables to labelled row summaries while preserving status and actions. Keyboard focus visible, labelled forms, logical heading order, 44px touch targets, WCAG 2.1 AA contrast (≥4.5:1 for normal text), reduced-motion support. Theme persistence may be browser-local because it carries no tenant data; light/dark mode is a planned requirement (IF-UI-006), not an excuse to block core flows.

Data-dense tables must use **server pagination and filters**; no download-all + client filtering or virtualizing a million records in memory. Server owns tenant filtering, sort and cursor/page bounds. URL search parameters preserve filters without containing secrets. Trend charts, heatmaps, full-text autocomplete, saved filters, favorite assets, share tokens and feedback widgets remain gated on their respective backend contracts; avoid drawing simulated history from one scorecard.

## 5. Backend contract needed for a complete application

Implemented today (see `src/dq_scoring/presentation/api/routes/`): auth login/refresh/logout; asset and snapshot creation and snapshot-by-ID; ruleset and policy create/submit/approve; run trigger and status-by-ID; private/public assessment-by-ID. Existing `schemas/assessment_schemas.py` provides full internal rule results and a limited public projection. The server remains responsible for redaction and RLS; client-side hiding does not confer privacy.

Required additions **before enabling corresponding UI controls**:

| Priority | Server contract | Enables / acceptance |
| --- | --- | --- |
| P0 | Authenticated `GET /api/v1/assets`, `GET /api/v1/assets/{id}`, `GET /api/v1/snapshots?asset_id=…`, `GET /api/v1/rulesets`, `GET /api/v1/rulesets/{id}`, `GET /api/v1/policies`, `GET /api/v1/policies/{id}` with bounded pagination | Pickers, asset detail, approval inbox; tenant-isolated, status filters, stable sort |
| P0 | `GET /api/v1/runs` and `GET /api/v1/assessments` with bounded pagination/status/date filters | Job history, overview, scorecard discovery; no client-side full-table scan |
| P0 | Secure user/tenant context (`GET /api/v1/me` or equivalent) and provisioned users/memberships | Identity display, authorized approval selection, real tenant switching; no client role assertions |
| P0 | Snapshot ingest contract (server-validated upload or scoped presigned transfer + commit/manifest/hash verification) | Browser-driven data registration; never expose long-lived S3/root secrets, maintain immutable source |
| P1 | Real run progress fields with well-defined stage/denominator/ETA or SSE | Determinate bar only when measured; status polling stays valid fallback |
| P1 | Redacted, paged evidence and safe export endpoint | IF-UI-015 and CSV export with bounded rows / injection defense |
| P1 | Server-side history/trend and comparison query with config-compatibility metadata | Trend and comparison charts without misleading cross-policy comparisons |
| P2 | Authorized, expiring share capability | IF-UI-010; separate from currently unrestricted public projection |

These are **proposed contracts**, not implemented endpoints. Agree on payload schemas, RLS and redaction before building page interactions; do not add a second backend in the frontend just to evade API gaps.

## 6. Frontend structure and delivery slices

Suggested feature layout: `src/app` (router, auth session and QueryClient), `src/features/{auth,assets,governance,runs,assessments}`, `src/components` (shared accessible primitives), `src/api` (generated types/client). Keep query keys tenant-scoped, abort in-flight requests on navigation/logout, and invalidate relevant lists after successful mutations. Route-level authorization is presentation only; the server decides access. No Redux, WebSocket, chart framework, or custom design-system package until a concrete use requires one.

1. **Usable vertical slice:** sign in, register asset/snapshot by existing server-visible descriptor, create/submit/approve ruleset and policy with two real accounts, trigger run, poll actual status, view private/public scorecard by ID. A missing list API means explicit ID entry, not fake browse pages.
2. **Browse and operate:** add bounded list/detail APIs, then overview, pickers, job history, filters, approval inbox and navigation. Observe empty and cross-tenant responses.
3. **Ingest and insights:** implement secure upload/manifest flow, real progress, redacted evidence export, trends and responsive charts only after matching server contracts exist.

**Design acceptance checks:** a two-user synthetic lifecycle completes without refresh losing authorization unexpectedly; creator cannot self-approve; cross-tenant and revoked sessions cannot see private detail; public view never requests private data; QUEUED/RUNNING/FAILED/SUCCEEDED/WITHHELD and all gate/measurement states are correctly labelled; null scores remain null; polling stops at terminal state; no browser request transfers full datasets; a 375px keyboard-only/screen-reader pass can reach every core action. Use browser/network inspection for real UI proof; mock-only screenshots are not sufficient evidence of the integrated workflow.

**Deployment boundary:** current local Compose provides PostgreSQL and MinIO, with API/worker launched separately. The UI would be a separately built static app hosted with a same-origin API proxy or an explicitly configured trusted origin; CORS, HTTPS, CSP, authentication transport and public/private routes require deployment review. Existing Helm `ui.enabled: false` remains correct until there is a real build and deployment wiring. This document does not declare k3s deployment ready.

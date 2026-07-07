# Vulcan SoA Connection — Connectathon Foundation

SMART on FHIR app for enrolling patients into research studies and tracking their
progress against a Vulcan Schedule of Activities (SoA) V2 protocol graph.

**Target:** HL7 Connectathon — FHIR R6 ballot (`6.0.0-ballot3`), Aidbox.

## Architecture

```
React/Vite SPA  →  FastAPI BFF  →  Aidbox (FHIR R6)
   :5173             :8000            :8888
```

- **SPA** — never holds a FHIR token; talks to the BFF via `HttpOnly` session cookie.
- **BFF** — SMART confidential client; holds tokens server-side; exposes a JSON API.
- **SoA engine** — pure Python module: `PlanDefinition` JSON in, computed schedule-state out.
  Subject progress is derived on every read from existing `Encounter` resources tagged back
  to their originating `PlanDefinition.action.id` — no separate state store.

### CPG activity flow

Each visit advances through the HL7 CPG [activity-flow](https://hl7.org/fhir/uv/cpg/activityflow.html)
lifecycle — `ServiceRequest` proposal → plan → order, then `Appointment` schedule/book, then
`Encounter` perform, then complete — with every resource in a chain linked by `basedOn` and
tagged with a shared action identifier so the chain can be reassembled on read. Load the WIP
PhUSE Schedule of Activities IG (which defines the USDM demo study,
`lzzt-usdm-demo-study`) with `task fixtures:load-soa-ig`, pointing `SOA_IG_RESOURCES_DIR` at
its `fsh-generated/resources` directory.

## Tech stack

| Layer | Stack |
|---|---|
| Backend | Python 3.11+, FastAPI, httpx, pydantic-settings, pytest/respx |
| Frontend | React 18, Vite, TypeScript, react-router-dom, Vitest, Playwright |
| FHIR server | Aidbox `edge` image, FHIR R6 ballot (`6.0.0-ballot3`) |
| Database | PostgreSQL 16 (managed by Docker Compose) |

## Prerequisites

- Docker + Docker Compose
- Python 3.11+
- Node 20+
- [go-task](https://taskfile.dev) (`brew install go-task`)
- An Aidbox license key from [aidbox.app](https://aidbox.app)

## Quick start

```bash
# 1. Clone and enter
git clone <repo> && cd vulcan-soa-connection-41

# 2. Set up env files
cp docker/.env.example docker/.env          # add AIDBOX_LICENSE=<your-key>
cp backend/.env.local.example backend/.env.local   # defaults match Docker

# 3. Start Aidbox (first run pulls ~200 MB)
task aidbox:up

# 4. Install and test the backend
task backend:install
task backend:test

# 5. Load the Vulcan SoA IG fixtures into Aidbox
task fixtures:load-ig          # requires IG output/ directory — see below
task fixtures:load-app         # loads backend/fixtures/

# 6. Run the integration test against live Aidbox
task backend:test-integration

# 7. Start the BFF and frontend dev servers
task dev                       # runs both concurrently
```

Open [http://localhost:5173](http://localhost:5173) — the SPA proxies `/api`, `/launch`,
and `/callback` to the backend.

## Environment files

| File | Purpose | Committed? |
|---|---|---|
| `docker/.env.example` | Template for Docker secrets | Yes |
| `docker/.env` | Real Docker secrets (AIDBOX_LICENSE etc.) | No |
| `backend/.env.local.example` | Template for backend config | Yes |
| `backend/.env.local` | Real backend config | No |
| `backend/.env.connectathon.example` | Connectathon instance config | Yes |

`SMART_CLIENT_SECRET` must match between `docker/.env` and `backend/.env.local`.

## Local Aidbox (Docker)

```
Aidbox UI       http://localhost:8888        admin / admin (default)
FHIR base       http://localhost:8888/fhir
PostgreSQL      localhost:5433
```

The `docker/aidbox/init-bundle.json` bootstraps on first start:
- `Client/vulcan-soa-bff` — SMART confidential client (authorization_code + basic)
- `AccessPolicy/open-for-vulcan-soa-bff` — open policy for dev
- `AccessPolicy/open-for-root` — open policy for the admin/root client

```bash
task aidbox:up       # start (detached)
task aidbox:down     # stop and remove containers
task aidbox:logs     # tail Aidbox logs
task aidbox:reset    # destroy volumes and restart clean
```

If Aidbox crash-loops on boot trying to download `hl7.fhir.r6.core-6.0.0-ballot3.tgz` from
`fs.get-ig.org` (truncated download), check that `docker/docker-compose.yml` points the
`aidbox` service at the local `pkg-server` sidecar with `BOX_FHIR_NPM_PACKAGE_REGISTRY`
(not `BOX_FHIR_PACKAGES_NPM_REGISTRY` — that name is silently ignored) and run
`task aidbox:reset`.

## Loading IG fixtures

The Vulcan SoA IG must be cloned separately. The fixture loader is generic —
it walks any directory of `*.json` FHIR resources and PUTs them into Aidbox.

```bash
# Set the IG output path (default: ~/Documents/Devel/hl7/Vulcan-schedule-ig/output)
export VULCAN_IG_OUTPUT_DIR=/path/to/Vulcan-schedule-ig/output

task fixtures:load-ig    # loads IG output/ (PlanDefinitions, StructureDefinitions, …)
task fixtures:load-app   # loads backend/fixtures/ (demo ResearchStudy + Patient)
```

## Backend

```bash
task backend:install          # create .venv and pip install -e ".[dev]"
task backend:test             # run all unit tests (no Aidbox needed)
task backend:test-integration # golden-path test against live Aidbox
task backend:serve            # uvicorn on :8000 with --reload
```

Unit tests: **119 passed, 2 skipped** (integration tests gated behind `RUN_INTEGRATION_TESTS=1`).

### Module map

```
backend/src/vulcan_soa/
  config.py          Settings (pydantic-settings, ENV_FILE driven)
  store.py           InMemoryStore[T] — sessions + pending launches
  fhir_client.py     FhirClient — thin Aidbox REST client (raw dicts, no typed models)
  auth.py            PKCE, authorize-URL builder, token exchange, fhirContext parsing
  soa_engine/
    graph.py         parse_protocol_graph → ProtocolGraph (PlanDefinition → DAG)
    conditions.py    evaluate_condition (text/x-soa-expressionplain interpreter)
    engine.py        resolve_schedule_state → ScheduleState
  scheduling.py      Encounter tagging, visit materialization, subject-context loading
  enrollment.py      enroll() — conditional-create ResearchSubject + materialize root visit
  tracking.py        withdraw_subject(), complete_visit()
  activity_flow.py   CPG activity-flow lifecycle: proposal→plan→order→schedule/book→perform→complete
  api/
    deps.py          FastAPI dependencies (session cookie → FhirClient)
    launch.py        /launch, /launch/standalone, /callback
    context.py       GET /api/context
    research_studies.py   GET /api/research-studies, POST /{id}/enroll
    research_subjects.py  GET /{id}/schedule, POST /{id}/visits/{actionId}/complete, POST /{id}/withdraw,
                           POST /{id}/visits/{actionId}/plan, POST /{id}/visits/{actionId}/order,
                           POST /{id}/visits/{actionId}/schedule, POST /{id}/visits/{actionId}/respond,
                           POST /{id}/visits/{actionId}/perform, POST /{id}/visits/{actionId}/tasks/{taskId}/complete
    app.py           create_app() factory
```

## Frontend

```bash
task frontend:install    # npm install
task frontend:test       # vitest run (24 tests)
task frontend:dev        # vite dev server on :5173
task frontend:build      # tsc + vite build
task frontend:e2e        # playwright test (requires running dev servers + Aidbox)
```

### View map

```
src/
  routes.tsx          Landing (context-aware) → StudyWorklist | Enroll | SubjectDashboard
  launch/
    LaunchPending.tsx  Shown while /api/context is in flight
    LaunchError.tsx    /launch-error?reason=untrusted_iss|invalid_state
  views/
    StudyWorklist/     Browse and select a ResearchStudy
    Enroll/            Enroll patient (from launch context or manual FHIR ID entry)
    SubjectDashboard/  Progress, complete visits, decision-support prompt, withdraw
  api/
    client.ts          Typed fetch wrapper (credentials: include)
    types.ts           Shared TS interfaces
```

## Registering the app with Aidbox

Aidbox knows this app as two resources: a `Client` (the BFF's SMART confidential
client, grants `authorization_code` + `basic`) and an `AccessPolicy` that authorizes
its requests. The registration is always **generated from the backend's own env
file**, so the secret and redirect URI can never drift from what the BFF actually
sends at token exchange:

```
backend/.env.local | .env.connectathon
  SMART_CLIENT_ID ────┐
  SMART_CLIENT_SECRET ┼──▶ scripts/generate_client_registration.py ──▶ Client/vulcan-soa-bff
  REDIRECT_URI ───────┘         (print Bundle, or --apply to PUT)       AccessPolicy/open-for-vulcan-soa-bff
```

- **Local Docker** — nothing to do: `docker/aidbox/init-bundle.json` creates both
  resources on first boot (identical shapes to what the generator produces).
- **Any other instance (e.g. Connectathon)** — generate the registration and either
  paste the printed `Bundle` into the Aidbox REST console (`POST /`), or push it
  directly with the instance's admin client:

  ```bash
  task aidbox:register-client                # print the registration Bundle
  AIDBOX_ADMIN_CLIENT_SECRET=<admin secret> \
    task aidbox:register-client -- --apply   # PUT Client + AccessPolicy via admin/root
  ```

Note that `Client` and `AccessPolicy` are Aidbox *system* resources — they live at the
box base URL (`http://localhost:8888/Client/...`), not under `/fhir`. Full
walkthrough, including troubleshooting: [docs/smart-on-fhir-setup.md](docs/smart-on-fhir-setup.md).

## Invoking the app against an Aidbox server

Once the client is registered and fixtures are loaded, start both dev servers
(`task dev`) and launch in one of two SMART modes:

```
EHR  →  GET /launch?iss=&launch=  →  Aidbox /authorize  →  GET /callback
     ←  session cookie (HttpOnly)  ←  token exchange
SPA  →  GET /api/context           →  {patientId, researchStudyId}
```

- **Standalone launch** — open [http://localhost:5173](http://localhost:5173) and
  follow *start a standalone launch*; log in on Aidbox's hosted screen (locally:
  `admin` / `admin`). No EHR context — you pick a study from the worklist.
- **EHR launch** — the EHR calls `GET /launch?iss=<fhir-base>&launch=<token>`. The
  `iss` must exactly equal the configured `FHIR_BASE_URL` or the user is bounced to
  `/launch-error?reason=untrusted_iss`. To simulate locally, use Aidbox's SMART
  launch UI (console → Auth → SMART on FHIR) pointed at
  `http://localhost:8000/launch`.

Scripts and integration tests (`load_fixtures.py`, `generate_client_registration.py
--apply`, `task backend:test-integration`) skip OAuth entirely and use the client's
`basic` grant with the same id/secret.

### Switching Aidbox instances

Which Aidbox you talk to is decided by `ENV_FILE` alone — no code changes:

```bash
# local Docker (default)
task backend:serve                             # uses backend/.env.local

# remote / Connectathon instance
cp backend/.env.connectathon.example backend/.env.connectathon
# fill in FHIR_BASE_URL, OAuth endpoints, a real SMART_CLIENT_SECRET, REDIRECT_URI
ENV_FILE=.env.connectathon task aidbox:register-client -- --apply   # once per instance
ENV_FILE=.env.connectathon task backend:serve
ENV_FILE=.env.connectathon task fixtures:load-all                   # loader honours the same switch
```

## R6 shape notes (confirmed against live Aidbox edge)

| Resource | Field | R6 shape |
|---|---|---|
| `ResearchSubject` | `status` | Required; `active`/`draft`/`retired`/`unknown` (PublicationStatus). **Withdrawal = `retired`.** |
| `ResearchSubject` | `subjectState` | `0..*` BackboneElement array: `{code: CodeableConcept, startDate: dateTime}` |
| `Encounter` | `status` | `planned` / `in-progress` / `completed` / `discharged` / `unknown`. **`finished` was removed in R6.** |
| `ServiceRequest` | group identifier | There is no `groupIdentifier` field — the composite/group identifier is `requisition` (`0..1 Identifier`, aliased `groupIdentifier` in the spec text). |
| `Appointment` | `start` / `end` | Invariant `app-3` requires both once `status` leaves `proposed`/`cancelled`/`waitlist` — stamp a placeholder window on at creation so a later `booked` transition doesn't 422. |

# Configurable Backend Port — Design

**Problem:** Another Docker stack on this machine (`planeswalker-ratel`) publishes
`[::]:8000`, while uvicorn binds only `127.0.0.1:8000`. Requests to
`localhost:8000` that resolve to `::1` (the Vite proxy and the OAuth
`redirect_uri` hop) land on Ratel, which answers "Asset not found for path
launch/standalone" — breaking the standalone launch. Companion to the
`FRONTEND_PORT` design (2026-07-07-configurable-frontend-port-design.md).

**Decision:** A `BACKEND_PORT` process environment variable, default `8000`,
honoured by uvicorn and the Vite dev proxy. Additionally, the proxy targets
switch from `localhost` to `127.0.0.1` so they always reach uvicorn's actual
bind address regardless of IPv6 squatters — this alone fixes the reported bug
even on the default port.

## Changes

1. **`frontend/vite.config.ts`** — `const backendTarget =
   \`http://127.0.0.1:${Number(process.env.BACKEND_PORT) || 8000}\`` used by all
   three proxy entries (`/api`, `/launch`, `/callback`).
2. **`Taskfile.yml`** —
   - `backend:serve` and `dev`: `uvicorn ... --port {{.BACKEND_PORT | default "8000"}}`.
   - `frontend:e2e` precondition curls `127.0.0.1:${BACKEND_PORT:-8000}` instead
     of `localhost:8000`.
   - `desc:` strings mention the override.
3. **Env values the user owns** (documented, not automated): `REDIRECT_URI` in
   `backend/.env.*` must use the new port, and the Aidbox Client must be
   re-registered (`task aidbox:register-client -- --apply`) since the redirect
   URI is part of the registration.
4. **Docs** — README port-override note extended to cover `BACKEND_PORT`; setup
   doc troubleshooting table gains the "asset not found" symptom row.

## Out of scope

- Changing uvicorn's bind host (stays `127.0.0.1`).
- `FRONTEND_URL`/`REDIRECT_URI` derivation from ports — env files stay authoritative.

## Verification

- Vite proxy reaches the BFF via IPv4 even with the Ratel container running.
- `BACKEND_PORT=8010 task backend:serve` binds :8010; proxied
  `/launch/standalone` through the dev server returns the BFF's redirect (307/302
  to Aidbox `/auth/authorize`), not Ratel's 404.
- Full launch chain re-verified with `task fhir:doctor` + browser-equivalent curl.
- vitest + backend pytest suites stay green.

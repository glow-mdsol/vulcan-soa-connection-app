# Configurable Frontend Dev-Server Port — Design

**Problem:** The Vite dev server is pinned to its default port 5173, which collides
with another app on the developer's machine. The port must be configurable per
environment without code changes.

**Decision:** A `FRONTEND_PORT` process environment variable, default `5173`,
honoured by the frontend tooling only. The backend's existing `FRONTEND_URL`
setting (CORS origin + post-callback redirect) remains a separate env knob that
the developer keeps in sync.

## Changes

1. **`frontend/vite.config.ts`** — add to the `server` block:
   - `port: Number(process.env.FRONTEND_PORT) || 5173` (the `||` form falls back
     on unset, empty, and non-numeric values alike)
   - `strictPort: true` — today Vite silently hops to 5174 when 5173 is busy,
     which breaks the backend's CORS/redirect in a confusing way; failing loudly
     is required behaviour now that the port is deliberate.
2. **`frontend/playwright.config.ts`** — derive `baseURL` from the same variable:
   `` `http://localhost:${Number(process.env.FRONTEND_PORT) || 5173}` ``.
3. **`frontend/e2e/golden-path.spec.ts`** — the skip-message codegen hint URL uses
   the same derived port so the instruction stays correct.
4. **`Taskfile.yml`** — `desc:` strings for `frontend:dev` and `dev` say
   "default :5173" instead of implying the port is fixed. No functional change:
   `task` inherits the shell environment, so `FRONTEND_PORT=5199 task dev` already
   reaches the Vite config.
5. **Docs** — README and `docs/smart-on-fhir-setup.md` get one note each: if you
   set `FRONTEND_PORT`, update `FRONTEND_URL` in `backend/.env.local` /
   `.env.connectathon` to match, and restart the BFF.

## Out of scope

- Backend port (:8000) and Vite proxy targets — unchanged.
- Deriving `FRONTEND_URL` from `FRONTEND_PORT` (single source of truth) —
  rejected to keep the backend env file authoritative.
- Production builds — the port only affects the dev server; `vite build` output
  is port-agnostic.

## Verification

No unit test — this is build-tool configuration with no seam worth mocking.
Verified by:

- `FRONTEND_PORT=5199 npm run dev` serves on 5199; unset serves on 5173.
- Occupying the chosen port and confirming Vite exits with an error
  (`strictPort`) instead of hopping.
- `task frontend:test` (vitest) still green.

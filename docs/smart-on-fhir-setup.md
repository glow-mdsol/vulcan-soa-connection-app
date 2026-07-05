# SMART on FHIR setup (Aidbox)

How to register and configure this application as a SMART on FHIR client against an
Aidbox instance — the local Docker instance for development, or a remote (e.g.
Connectathon) instance.

## How the app authenticates

```
Browser (SPA :5173) ──HttpOnly session cookie──▶ BFF (FastAPI :8000) ──Bearer token──▶ Aidbox (:8888)
```

- The **BFF is a SMART confidential client** (`authorization_code` grant with PKCE).
  It performs the OAuth dance, holds the access token server-side, and gives the
  browser only an `HttpOnly` session cookie. The SPA never sees a FHIR token.
- Two launch modes:
  - **EHR launch** — `GET /launch?iss=<fhir-base>&launch=<token>`. The `iss` must
    exactly equal the configured `FHIR_BASE_URL`, otherwise the user is bounced to
    `/launch-error?reason=untrusted_iss`.
  - **Standalone launch** — `GET /launch/standalone` (no EHR context; the user picks a
    study from the worklist instead).
- Scripts and tests (fixture loader, `validate_protocol.py`, integration tests) skip
  OAuth and use **basic auth** with the same client id/secret — that is why the client
  registration below includes the `basic` grant.

## The Client registration Aidbox needs

Whatever the instance, the app needs an Aidbox `Client` resource shaped like this
(this is exactly what the local bootstrap creates):

```json
{
  "resourceType": "Client",
  "id": "vulcan-soa-bff",
  "type": "confidential",
  "secret": "<SMART_CLIENT_SECRET>",
  "grant_types": ["authorization_code", "basic"],
  "auth": {
    "authorization_code": {
      "pkce": true,
      "redirect_uri": "http://localhost:8000/callback",
      "access_token_expiration": 3600,
      "token_format": "jwt"
    }
  },
  "scope": ["openid", "fhirUser", "launch", "patient/*.read"]
}
```

…plus an `AccessPolicy` linking to the client so its requests are authorized:

```json
{
  "resourceType": "AccessPolicy",
  "id": "open-for-vulcan-soa-bff",
  "engine": "allow",
  "link": [{ "resourceType": "Client", "id": "vulcan-soa-bff" }]
}
```

> **Security note:** `engine: allow` grants the client unrestricted access — fine for
> local dev and a Connectathon sandbox, not for anything real. On a shared instance,
> prefer a matcho/SQL policy scoped to the resource types the app touches
> (ResearchStudy, ResearchSubject, PlanDefinition, ActivityDefinition, ServiceRequest,
> Appointment, AppointmentResponse, Encounter, Task, Procedure, Patient,
> Practitioner).

## Local setup (Docker)

The local instance is fully bootstrapped — you never create the Client by hand.

1. **Env files:**

   ```bash
   cp docker/.env.example docker/.env                      # add AIDBOX_LICENSE=<key from aidbox.app>
   cp backend/.env.local.example backend/.env.local        # defaults already match Docker
   ```

   `SMART_CLIENT_SECRET` must be identical in both files (default `change-me`). If you
   change it in one place, change it in the other and restart both sides.

2. **Start Aidbox:**

   ```bash
   task aidbox:up      # first run pulls the image and seeds the database
   task aidbox:logs    # watch until "server started"
   ```

   On first start Aidbox loads `docker/aidbox/init-bundle.json`, which creates
   `Client/vulcan-soa-bff`, `AccessPolicy/open-for-vulcan-soa-bff`, and an
   `AccessPolicy/open-for-root` for the admin client. The client secret is injected
   from `docker/.env`.

3. **Load fixtures and start the app:**

   ```bash
   task fixtures:load-all     # IG resources + demo study/patient/practitioner
   task dev                   # BFF :8000 + SPA :5173
   ```

4. **Verify the SMART flow:** open <http://localhost:5173>, follow *start a standalone
   launch*, and log in with `admin` / `AIDBOX_ADMIN_PASSWORD` (default `admin`). You
   should land back on the study worklist with a session cookie set.

   To simulate an **EHR launch** locally, use Aidbox's SMART launch UI (Aidbox console
   → Auth → SMART on FHIR) pointed at `http://localhost:8000/launch`, or hit
   `http://localhost:8000/launch?iss=http://localhost:8888/fhir&launch=<token>`.

5. **Reset if needed:** `task aidbox:reset` destroys the volumes and re-runs the
   bootstrap (fixtures must be reloaded afterwards).

## Remote setup (Connectathon / hosted Aidbox)

On a remote instance you register the client yourself, then point the backend at it
with an env file — no code changes.

1. **Create the Client and AccessPolicy** on the remote instance. In the Aidbox
   console open *REST Console* and PUT the two resources from
   [the section above](#the-client-registration-aidbox-needs), with two edits:

   - `secret` — generate a real secret (`openssl rand -hex 24`); do not reuse
     `change-me`.
   - `auth.authorization_code.redirect_uri` — where the *backend* is reachable from
     the user's browser, e.g. `http://localhost:8000/callback` if you run the BFF
     locally against the remote Aidbox, or `https://<your-host>/callback` if the BFF
     is deployed.

   ```
   PUT /Client/vulcan-soa-bff
   PUT /AccessPolicy/open-for-vulcan-soa-bff
   ```

2. **Configure the backend** with a dedicated env file:

   ```bash
   cp backend/.env.connectathon.example backend/.env.connectathon
   ```

   ```ini
   FHIR_BASE_URL=https://<instance>.aidbox.app/fhir
   OAUTH_AUTHORIZE_URL=https://<instance>.aidbox.app/auth/authorize
   OAUTH_TOKEN_URL=https://<instance>.aidbox.app/auth/token
   SMART_CLIENT_ID=vulcan-soa-bff
   SMART_CLIENT_SECRET=<the real secret>
   REDIRECT_URI=<must match the Client's redirect_uri exactly>
   FRONTEND_URL=http://localhost:5173
   ```

   Never commit `backend/.env.connectathon` (only the `.example` is tracked).

3. **Run against the remote instance:**

   ```bash
   export ENV_FILE=backend/.env.connectathon
   task backend:serve
   task frontend:dev
   ```

   The fixture loader and drift guard honour the same switch:

   ```bash
   ENV_FILE=backend/.env.connectathon task fixtures:load-all
   ```

4. **EHR launch from someone else's EHR:** give them your launch URL
   (`https://<your-host>/launch` or `http://localhost:8000/launch` via a tunnel) and
   note that their `iss` must be exactly your configured `FHIR_BASE_URL` — the BFF
   rejects any other issuer.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Redirected to `/launch-error?reason=untrusted_iss` | The launch `iss` ≠ `FHIR_BASE_URL` (scheme/host/path must match exactly, including no trailing slash). |
| Redirected to `/launch-error?reason=invalid_state` | The OAuth `state` didn't match a pending launch — expired/restarted BFF between authorize and callback, or the URL was reused. |
| `401 invalid_client` at token exchange | `SMART_CLIENT_SECRET` mismatch between the backend env file and the Aidbox `Client.secret` (locally: `docker/.env` vs `backend/.env.local`). |
| Aidbox login page loops / `redirect_uri` error | The Client's `auth.authorization_code.redirect_uri` doesn't exactly match the backend's `REDIRECT_URI`. |
| Fixture loader / scripts get `401`/`403` | The Client is missing the `basic` grant type, or the AccessPolicy for the client is absent. |
| SPA gets `401` from `/api/*` | No session yet — complete a launch first; the session cookie is `HttpOnly` and per-BFF-process (in-memory store), so restarting the BFF logs everyone out. |

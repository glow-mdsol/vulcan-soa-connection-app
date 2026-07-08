# Subject Identifier at Enrollment + Study Roster — Design

**Problem:** Enrollment creates a `ResearchSubject` with no human identifier — the
dashboard greets coordinators with "Subject 3f2a9c…", and there is no way to see
who is enrolled in a study. Coordinators need to assign the sponsor-style subject
identifier (e.g. `LZZT-0001`) at enrollment, and each study needs a roster of its
enrolled subjects.

**Decisions (from brainstorm):** identifier is **manual and required** at enroll
time; the roster of **enrolled subjects** lives on the study-details card
(Enroll page). One spec — the roster is the identifier's display surface.

## FHIR shape

`ResearchSubject.identifier` gains one entry:
`{"system": "urn:vulcan-soa:subject-id", "value": "<typed value>"}` — same URN
namespace as the app's existing plan-action tags. No other resource changes.

## Backend

### Enrollment (`backend/src/vulcan_soa/enrollment.py`)

- `enroll(client, study_id, patient_id, subject_identifier: str)` — new required
  parameter; the created `ResearchSubject` carries the identifier entry.
- New module-level helper `subject_identifier_of(subject: dict) -> str | None`
  (named `_of` to avoid clashing with `enroll`'s `subject_identifier` parameter)
  returning the value of the `urn:vulcan-soa:subject-id` identifier entry (None
  when absent) — the single extraction point, reused by the routes below.
- New `class EnrollmentConflict(Exception)` with a human-readable message.
- **Collision rules** (enrollment stays idempotent on (study, patient) via the
  existing conditional-create; the identifier adds these checks):
  1. Before create: search `ResearchSubject?identifier=urn:vulcan-soa:subject-id|<value>&study=<study>`
     (token form, so identifiers from other systems can never collide);
     if a match exists for a DIFFERENT patient → `EnrollmentConflict`
     ("subject identifier already in use in this study").
  2. Re-enroll same patient + same identifier → idempotent success (as today).
  3. Re-enroll same patient + DIFFERENT identifier → `EnrollmentConflict`
     (identifiers are immutable once assigned; no silent ignore).
  4. Existing subject with NO identifier (pre-feature data) → add the identifier
     via a versioned update (`If-Match`), so retries of legacy enrollments
     converge instead of diverging.
- `EnrollRequest` (`api/models.py`) gains `subjectIdentifier: str` with
  `min_length=1` (FastAPI 422s blank/missing).
- Enroll route (`api/research_studies.py`) maps `EnrollmentConflict` → HTTP 409.

### Roster (`backend/src/vulcan_soa/api/research_studies.py`)

- `GET /api/research-studies/{study_id}/subjects` → list of
  `{"researchSubjectId": str, "subjectIdentifier": str | None,
  "patientId": str, "status": str}` from
  `search("ResearchSubject", {"study": f"ResearchStudy/{study_id}"})`.
  `status` is the R6 `ResearchSubject.status` (`active`/`retired`;
  retired = withdrawn). No pagination (demo scale, matches `/api/patients`).

### Schedule payload (`api/research_subjects.py`)

- `GET /{subject_id}/schedule` (which already reads the subject) adds
  `"subjectIdentifier": subject_identifier(subject)` to its response dict.
  Gate/expedite/complete responses do NOT carry the field — the dashboard reads
  it once from the initial load.

## Frontend

- `Enroll.tsx`: required `Subject identifier` text input (`form-field`, label
  exactly `Subject identifier`); Enroll button stays disabled until BOTH a
  patient and a non-blank identifier are set; 409 from the enroll call surfaces
  the existing inline alert with copy `Enrollment failed. Please try again.`
  replaced by the server's conflict detail when the response is a 409
  (`Subject identifier already in use in this study.` / mismatch message).
- `api/client.ts`: `enrollPatient(studyId, patientId, subjectIdentifier)`;
  new `listStudySubjects(studyId): Promise<StudySubjectSummary[]>`.
- `api/types.ts`: `StudySubjectSummary` mirroring the roster payload;
  `Schedule.subjectIdentifier?: string | null`.
- `SubjectDashboard.tsx`: page title becomes
  `Subject {subjectIdentifier ?? subjectId}` with the FHIR id demoted to the
  existing `.meta` span when an identifier is present.
- `ResearchStudyDetails.tsx`: new "Enrolled subjects" section — one row per
  subject: identifier (fallback: first 8 chars of `researchSubjectId`),
  patient id as `.meta`, `Withdrawn` badge (`.badge`) when `status ===
  "retired"`, row links to `/subjects/{researchSubjectId}`. Empty state:
  `No subjects enrolled yet.` Uses existing classes only.

## Blast radius

- `enroll()` signature change: update the two live integration tests and the
  e2e golden path (one `fill` step for the new required field). This is a
  deliberate behavior change; the specs exercise it.
- Existing `test_enrollment.py` tests updated for the new parameter.

## Testing

- Backend: identifier lands on created resource (respx payload assert); all
  four collision rules; roster route mapping incl. identifier-missing fallback
  and empty list; enroll route 409 + 422; schedule payload carries
  `subjectIdentifier`.
- Frontend: Enroll button gating on both fields; posted body includes
  `subjectIdentifier`; dashboard title uses identifier when present, falls back
  to id; roster rows/link/badge/empty state.
- Live: enroll with an identifier against local Aidbox, read the subject back,
  hit the roster route, confirm both show the identifier.

## Out of scope

- Auto-generation or format validation of identifiers (free text).
- Editing/reassigning an identifier after enrollment.
- Roster on the worklist; pagination; search within roster.

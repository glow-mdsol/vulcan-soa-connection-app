# Frontend UI Redesign ("Clinical Calm") — Design

**Problem:** The SPA is ~690 lines of completely unstyled semantic HTML — browser
defaults everywhere. Fine for proving the engine; not credible at a connectathon
booth. The user wants a distinctly more attractive experience.

**Direction (chosen via visual mockups):** *Clinical Calm* — light, airy
healthcare-SaaS styling (soft white cards, teal-blue primary, pill status badges,
rounded corners, generous whitespace) — with the Subject Dashboard laid out as a
**timeline rail + work area**: a left rail renders the subject's journey through
the protocol graph as a vertical timeline; the right pane holds active visit
cards and decision prompts. Plain hand-rolled CSS, no new dependencies, markup
semantics (roles/labels/names) preserved so existing tests keep passing.

## 1. Backend: titles for the timeline

The schedule payload returns `completed`/`current` as raw action-id UUIDs; titles
exist only on `nextSteps`. The rail must say "Screening", not `0700e721-…`.

- `schedule_response(state, visits=None)` in `backend/src/vulcan_soa/scheduling.py`
  gains a `graph: ProtocolGraph` parameter and emits
  `"titles": {action_id: node.title}` for every node in the graph. Every caller
  already has the parsed graph in scope; all call sites updated.
- `Schedule` TS type gains `titles: Record<string, string>`.
- Backend test: schedule response includes a title for each graph node.

## 2. App shell

`frontend/src/AppShell.tsx` wraps all routes (worklist, enroll, dashboard, launch
pages): a white header bar with the brand mark ("◈ Vulcan SoA"), the study title
and subject/patient context when known, over a centered max-width content
container on the `--bg` canvas. Launch pending/error pages render inside the
shell so even failure states look intentional.

## 3. Design system (plain CSS)

- `frontend/src/styles/tokens.css` — CSS custom properties:
  canvas `#f4f7fa`, surface `#ffffff`, borders `#dde5ec`/`#e2e9f0`,
  primary `#0f6a8b` (+ tint `#e6f4f9`), success `#19a97b`, decision amber
  (`#fff8e8` bg / `#f0dfae` border / `#8a6d1a` text), text `#1d2b36`,
  muted `#5b7286`; radius scale (8/12px, 999px pills); one soft card shadow;
  4px-base spacing scale. System font stack.
- `frontend/src/styles/app.css` — component classes: `.card`, `.badge`,
  `.btn` / `.btn-secondary` / `.btn-danger-quiet`, `.stepper` (segmented
  progress bar), `.timeline` / `.timeline-node` (done/active/upcoming states),
  `.banner-decision`, `.form-card`, layout helpers for the rail/work-area grid.
- Both imported once from `main.tsx`. No CSS modules, no CSS-in-JS, no Tailwind.

## 4. Views

- **SubjectDashboard** — two-pane grid (rail ~1/3, work area ~2/3; stacks below
  ~800px). Rail: completed nodes (✓, success color) → current (highlighted,
  primary) → next steps (dashed connector, muted). Work area: active
  `VisitCard`s, the amber "Decision needed" banner with choice buttons, then
  "Next steps" as muted chips; withdraw becomes a quiet destructive button at
  the bottom of the work area. Loading/error states styled.
- **VisitCard** — card with visit *title* prominent (from `titles`), pill badge
  for the current phase, the 7-phase `<ol>` restyled as a segmented progress
  bar (list semantics + `aria-current` kept), gate-action buttons as
  primary/secondary, tasks as a checklist. The raw action id stays visible as
  small muted meta text — the Playwright golden-path assertions
  (`getByText("0700e721-…")`) and existing vitest queries stay truthful.
- **StudyWorklist** — heading + one clickable card per study (link semantics
  unchanged).
- **Enroll** — centered form card; labelled input + primary button unchanged in
  semantics.
- **LaunchPending / LaunchError** — centered status card in the shell; error
  reasons rendered as the existing `role="alert"` copy.

## 5. Testing & verification

- Existing vitest suites must pass unmodified — restyling adds classNames only;
  roles, aria-labels, and accessible names are unchanged.
- New tests: AppShell (brand + context rendering), timeline rail (titled nodes
  in done/active/upcoming order), VisitCard shows title + keeps action-id text.
- Backend: `schedule_response` titles test (unit level).
- E2E golden-path spec runs unchanged against the restyled app.
- Visual check via the running dev servers (ports from root `.env`).

## Out of scope

- Dark mode, theming, and responsive work beyond the single ~800px stack point.
- Component libraries, icon fonts, webfonts (system stack only — no network
  assets; the connectathon venue's network is not to be trusted).
- Backend changes beyond the `titles` field.
- Redesigning launch/auth *flow* UX (screens keep their behavior).

# Clinical Calm Frontend UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the SPA into the "Clinical Calm" design (light healthcare-SaaS: soft cards, teal-blue primary, pill badges) with the Subject Dashboard laid out as a timeline rail + work area, per `docs/superpowers/specs/2026-07-07-frontend-ui-redesign-design.md`.

**Architecture:** Plain hand-rolled CSS (design tokens + component classes, imported once from `main.tsx`), a new `AppShell` wrapping all routes, a new `Timeline` rail component on the dashboard, and one additive backend field (`titles` map in the schedule payload) so the UI can show visit titles instead of UUIDs. Markup semantics (roles, aria-labels, accessible names) are preserved so all existing tests pass unmodified.

**Tech Stack:** React 18 + TypeScript + Vite (frontend), vitest/@testing-library (tests), plain CSS custom properties (no new dependencies), FastAPI backend (one function signature change).

## Global Constraints

- No new frontend dependencies: no component library, no Tailwind, no CSS-in-JS, no icon fonts, no webfonts (system font stack only; no network assets).
- All existing vitest suites, backend pytest suites, and the Playwright golden-path spec must pass **unmodified**. Backend tests for `schedule_response` are the one exception (its signature changes; those tests are updated in Task 1).
- Accessible names/roles that MUST NOT change: `h1` name exactly `Vulcan Schedule of Activities`; link `start a standalone launch`; headings `Current`, `Decision needed`; buttons `Accept proposal`, `Authorize`, `Schedule`, `Patient accepts`, `Site confirms`, `Perform visit`, `Complete visit`, `Done: <task>`, `Withdraw subject`, `Enroll`; label `Patient FHIR ID`; aria-labels `Visit <actionId>`, `Visit phases`, `Visit tasks`, `Appointment responses`, `Completed visits`/`Current visits`/`Next steps`/`Decision needed` sections; `role="alert"`/`role="status"` usage.
- Stepper phase words (`proposed` … `completed`) stay visible text inside the `<ol aria-label="Visit phases">` with `aria-current="step"` on the active one.
- Raw action ids stay visible in the DOM on visit cards (Playwright asserts `getByText("0700e721-…")`).
- `Schedule.titles` is **optional** in TS (`titles?: Record<string, string>`) — existing test mocks omit it.
- Colors come from the spec's token palette only; define once in `tokens.css`, reference via `var(--…)` everywhere.

## File Structure

```
backend/src/vulcan_soa/scheduling.py        # schedule_response gains graph param, emits titles
backend/src/vulcan_soa/activity_flow.py     # 2 call sites pass workspace.graph
backend/src/vulcan_soa/enrollment.py        # 1 call site passes graph
backend/src/vulcan_soa/api/research_subjects.py  # 1 call site passes graph
backend/tests/test_scheduling.py            # updated + titles test
backend/tests/test_activity_flow_chains.py  # call sites updated

frontend/src/styles/tokens.css              # NEW — design tokens (Clinical Calm palette)
frontend/src/styles/app.css                 # NEW — component classes
frontend/src/main.tsx                       # imports both stylesheets
frontend/src/api/types.ts                   # Schedule.titles?: Record<string, string>
frontend/src/AppShell.tsx                   # NEW — header + container shell
frontend/src/AppShell.test.tsx              # NEW
frontend/src/App.tsx                        # uses AppShell
frontend/src/routes.tsx                     # Landing no-session card styled
frontend/src/launch/LaunchPending.tsx       # status card
frontend/src/launch/LaunchError.tsx         # status card
frontend/src/views/StudyWorklist/StudyWorklist.tsx   # study cards
frontend/src/views/Enroll/Enroll.tsx        # form card
frontend/src/views/SubjectDashboard/VisitCard.tsx    # title, badge, styled stepper
frontend/src/views/SubjectDashboard/Timeline.tsx     # NEW — rail component
frontend/src/views/SubjectDashboard/Timeline.test.tsx # NEW
frontend/src/views/SubjectDashboard/SubjectDashboard.tsx # two-pane grid, wires titles
```

---

## Task 1: Backend — `titles` map in the schedule payload

**Files:**
- Modify: `backend/src/vulcan_soa/scheduling.py:20-30`
- Modify: `backend/src/vulcan_soa/activity_flow.py:269,527`
- Modify: `backend/src/vulcan_soa/enrollment.py:59`
- Modify: `backend/src/vulcan_soa/api/research_subjects.py:43`
- Test: `backend/tests/test_scheduling.py`, `backend/tests/test_activity_flow_chains.py`

**Interfaces:**
- Consumes: `ScheduleState` (`vulcan_soa.soa_engine.engine`), `ProtocolGraph`/`VisitNode` (`vulcan_soa.soa_engine.graph`).
- Produces: `schedule_response(state: ScheduleState, graph: ProtocolGraph, visits: dict[str, dict] | None = None) -> dict` whose payload now includes `"titles": {action_id: title}` for **every** node in the graph. Task 6's frontend reads this as `schedule.titles`.

- [x] **Step 1: Update the existing tests and add the titles test**

In `backend/tests/test_scheduling.py`, the two `schedule_response` tests build a `ScheduleState` directly. Add a tiny graph helper and pass it; add a titles assertion test. Replace the current test bodies as follows (keep the existing imports, add the graph imports):

```python
from vulcan_soa.soa_engine.graph import ProtocolGraph, VisitNode


def tiny_graph() -> ProtocolGraph:
    return ProtocolGraph(
        plan_definition_id="pd-1",
        nodes={
            "a-1": VisitNode(action_id="a-1", title="Screening", transitions=()),
            "b-2": VisitNode(action_id="b-2", title="Treatment Day 1", transitions=()),
        },
        root_ids=("a-1",),
    )
```

Then in `test_schedule_response_shapes_state_and_flags_ambiguous`, change `response = schedule_response(state)` to `response = schedule_response(state, tiny_graph())`; in `test_schedule_response_not_ambiguous_for_single_next_step`, change `schedule_response(state)["ambiguous"]` to `schedule_response(state, tiny_graph())["ambiguous"]`. Add:

```python
def test_schedule_response_includes_titles_for_every_graph_node():
    state = ScheduleState(
        completed_action_ids=frozenset(),
        current_action_ids=frozenset(),
        next_steps=(),
    )
    response = schedule_response(state, tiny_graph())
    assert response["titles"] == {"a-1": "Screening", "b-2": "Treatment Day 1"}
```

(Match the existing file's actual `ScheduleState` construction style — read the two existing tests first and mirror how they build `state`.)

In `backend/tests/test_activity_flow_chains.py:101-107` (`test_schedule_response_includes_visits`), update both calls to pass a graph. Add the same `tiny_graph` import/helper usage:

```python
from tests.test_scheduling import tiny_graph  # or duplicate the helper locally if import is awkward
```

If cross-test imports fail (pytest collection), duplicate the 10-line `tiny_graph()` helper into the file instead — do not create a new conftest fixture for this.

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_scheduling.py tests/test_activity_flow_chains.py -v`
Expected: FAIL — `TypeError: schedule_response() takes 1 positional argument …` (signature doesn't accept graph yet) and the new titles test fails.

- [x] **Step 3: Change `schedule_response` and all call sites**

`backend/src/vulcan_soa/scheduling.py` — replace the function:

```python
def schedule_response(
    state: ScheduleState, graph: ProtocolGraph, visits: dict[str, dict] | None = None
) -> dict:
    return {
        "completed": sorted(state.completed_action_ids),
        "current": sorted(state.current_action_ids),
        "nextSteps": [
            {"actionId": s.action_id, "title": s.title, "transitionType": s.transition_type}
            for s in state.next_steps
        ],
        "ambiguous": len(state.next_steps) > 1,
        "visits": visits or {},
        "titles": {action_id: node.title for action_id, node in graph.nodes.items()},
    }
```

Call sites (each already has the graph in scope):
- `backend/src/vulcan_soa/activity_flow.py:269`: `return schedule_response(state, workspace.graph, visits=visit_details(chains))`
- `backend/src/vulcan_soa/activity_flow.py:527`: `return schedule_response(final_state, workspace.graph, visits=visit_details(final_chains))`
- `backend/src/vulcan_soa/enrollment.py:59`: `"schedule": schedule_response(post_enroll_state, graph, visits=visits),`
- `backend/src/vulcan_soa/api/research_subjects.py:43`: `return schedule_response(state, graph, visits=visit_details(chains))`

- [x] **Step 4: Run the full backend suite**

Run: `cd backend && pytest`
Expected: all pass (previously 133 passed, 2 skipped; +1 new test).

- [x] **Step 5: Commit**

```bash
git add backend/src/vulcan_soa/scheduling.py backend/src/vulcan_soa/activity_flow.py backend/src/vulcan_soa/enrollment.py backend/src/vulcan_soa/api/research_subjects.py backend/tests/test_scheduling.py backend/tests/test_activity_flow_chains.py
git commit -m "Include per-node titles in the schedule payload"
```

---

## Task 2: Design tokens + component stylesheet

**Files:**
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/styles/app.css`
- Modify: `frontend/src/main.tsx` (two import lines)
- Modify: `frontend/src/api/types.ts` (one field)

**Interfaces:**
- Produces: CSS custom properties (`--bg`, `--surface`, `--border`, `--border-soft`, `--primary`, `--primary-tint`, `--success`, `--warn-bg`, `--warn-border`, `--warn-text`, `--danger`, `--text`, `--muted`, `--radius`, `--radius-lg`, `--shadow`) and component classes (`.app-header`, `.app-header-inner`, `.brand`, `.brand-mark`, `.container`, `.card`, `.card-title`, `.meta`, `.badge`, `.btn`, `.btn-secondary`, `.btn-danger-quiet`, `.btn-choice`, `.stepper`, `.banner-decision`, `.form-card`, `.form-field`, `.status-card`, `.study-list`, `.study-card`, `.dashboard-grid`, `.timeline`, `.timeline-node`, `.timeline-connector`, `.chip-list`, `.chip`, `.alert`, `.status-note`, `.section-title`, `.page-title`, `.task-list`, `.btn-row`) that Tasks 3–6 reference by exactly these names.
- Consumes: nothing.

- [x] **Step 1: Create `frontend/src/styles/tokens.css`**

```css
:root {
  /* Clinical Calm palette (spec §3) */
  --bg: #f4f7fa;
  --surface: #ffffff;
  --border: #dde5ec;
  --border-soft: #e2e9f0;
  --primary: #0f6a8b;
  --primary-dark: #0b5470;
  --primary-tint: #e6f4f9;
  --success: #19a97b;
  --success-tint: #e7f6f0;
  --warn-bg: #fff8e8;
  --warn-border: #f0dfae;
  --warn-text: #8a6d1a;
  --danger: #b3392f;
  --text: #1d2b36;
  --muted: #5b7286;
  --muted-light: #8fa3b3;

  --radius: 8px;
  --radius-lg: 12px;
  --radius-pill: 999px;
  --shadow: 0 1px 3px rgba(16, 42, 67, 0.06), 0 1px 2px rgba(16, 42, 67, 0.04);

  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;

  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
```

- [x] **Step 2: Create `frontend/src/styles/app.css`**

```css
* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font);
  line-height: 1.5;
}

/* ── App shell ─────────────────────────────────────────────── */
.app-header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}

.app-header-inner {
  max-width: 1040px;
  margin: 0 auto;
  padding: var(--space-3) var(--space-6);
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
}

.brand {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--primary);
  letter-spacing: 0.01em;
}

.brand-mark {
  color: var(--primary);
  margin-right: var(--space-2);
}

.brand-tag {
  color: var(--muted);
  font-size: 0.8rem;
}

.container {
  max-width: 1040px;
  margin: 0 auto;
  padding: var(--space-6);
}

/* ── Typography ────────────────────────────────────────────── */
.page-title {
  font-size: 1.3rem;
  font-weight: 700;
  margin: 0 0 var(--space-4);
}

.section-title {
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
  margin: 0 0 var(--space-3);
}

.meta {
  color: var(--muted-light);
  font-size: 0.75rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

/* ── Cards ─────────────────────────────────────────────────── */
.card {
  background: var(--surface);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  padding: var(--space-4);
  margin-bottom: var(--space-4);
}

.card-title {
  font-size: 1rem;
  font-weight: 600;
  margin: 0;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

/* ── Badges & chips ────────────────────────────────────────── */
.badge {
  background: var(--primary-tint);
  color: var(--primary);
  border-radius: var(--radius-pill);
  padding: 2px 10px;
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  white-space: nowrap;
}

.badge-success {
  background: var(--success-tint);
  color: var(--success);
}

.chip-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.chip {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  padding: var(--space-1) var(--space-3);
  color: var(--muted);
  font-size: 0.85rem;
}

/* ── Buttons ───────────────────────────────────────────────── */
.btn,
.btn-secondary,
.btn-danger-quiet,
.btn-choice {
  font: inherit;
  font-weight: 600;
  font-size: 0.9rem;
  border-radius: var(--radius);
  padding: var(--space-2) var(--space-4);
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease;
}

.btn {
  background: var(--primary);
  color: #fff;
  border: 1px solid var(--primary);
}

.btn:hover:not(:disabled) {
  background: var(--primary-dark);
}

.btn-secondary,
.btn-choice {
  background: var(--surface);
  color: var(--primary);
  border: 1px solid var(--primary);
}

.btn-secondary:hover:not(:disabled),
.btn-choice:hover:not(:disabled) {
  background: var(--primary-tint);
}

.btn-danger-quiet {
  background: transparent;
  color: var(--danger);
  border: 1px solid transparent;
}

.btn-danger-quiet:hover:not(:disabled) {
  border-color: var(--danger);
}

.btn:disabled,
.btn-secondary:disabled,
.btn-danger-quiet:disabled,
.btn-choice:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-row {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

/* ── Phase stepper (keeps <ol> + visible phase words) ──────── */
.stepper {
  list-style: none;
  display: flex;
  gap: var(--space-1);
  margin: var(--space-3) 0;
  padding: 0;
}

.stepper li {
  flex: 1;
  text-align: center;
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted-light);
  padding-top: var(--space-2);
  border-top: 4px solid var(--border);
  border-radius: 2px;
}

.stepper li.done {
  border-top-color: var(--success);
  color: var(--success);
}

.stepper li[aria-current="step"] {
  border-top-color: var(--primary);
  color: var(--primary);
  font-weight: 700;
}

/* ── Decision banner ───────────────────────────────────────── */
.banner-decision {
  background: var(--warn-bg);
  border: 1px solid var(--warn-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  margin-bottom: var(--space-4);
}

.banner-decision h2 {
  color: var(--warn-text);
  font-size: 1rem;
  margin: 0 0 var(--space-2);
}

.banner-decision ul {
  list-style: none;
  margin: var(--space-3) 0 0;
  padding: 0;
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

/* ── Alerts & status ───────────────────────────────────────── */
.alert {
  background: #fdecea;
  border: 1px solid #f2c4bf;
  color: var(--danger);
  border-radius: var(--radius);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-4);
}

.status-note {
  background: var(--success-tint);
  border: 1px solid #bfe7d7;
  color: var(--success);
  border-radius: var(--radius);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-4);
}

.status-card {
  background: var(--surface);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  padding: var(--space-8);
  max-width: 480px;
  margin: 10vh auto 0;
  text-align: center;
}

/* ── Forms ─────────────────────────────────────────────────── */
.form-card {
  background: var(--surface);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  padding: var(--space-6);
  max-width: 480px;
}

.form-field {
  display: block;
  margin-bottom: var(--space-4);
  font-weight: 600;
  font-size: 0.9rem;
}

.form-field input {
  display: block;
  width: 100%;
  margin-top: var(--space-2);
  padding: var(--space-2) var(--space-3);
  font: inherit;
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.form-field input:focus {
  outline: 2px solid var(--primary-tint);
  border-color: var(--primary);
}

/* ── Study worklist ────────────────────────────────────────── */
.study-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-3);
}

.study-card a {
  display: block;
  background: var(--surface);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  padding: var(--space-4) var(--space-6);
  color: var(--primary);
  font-weight: 600;
  text-decoration: none;
}

.study-card a:hover {
  border-color: var(--primary);
  background: var(--primary-tint);
}

/* ── Dashboard: timeline rail + work area ──────────────────── */
.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 2fr;
  gap: var(--space-6);
  align-items: start;
}

@media (max-width: 800px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}

.timeline {
  background: var(--surface);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  padding: var(--space-4);
}

.timeline ol {
  list-style: none;
  margin: 0;
  padding: 0;
}

.timeline-node {
  position: relative;
  padding: 0 0 var(--space-4) var(--space-6);
}

.timeline-node:last-child {
  padding-bottom: 0;
}

.timeline-node::before {
  content: "";
  position: absolute;
  left: 4px;
  top: 5px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--border);
}

.timeline-node::after {
  content: "";
  position: absolute;
  left: 9px;
  top: 21px;
  bottom: -2px;
  width: 2px;
  background: var(--border);
}

.timeline-node:last-child::after {
  display: none;
}

.timeline-node.done::before {
  background: var(--success);
}

.timeline-node.done::after {
  background: var(--success);
}

.timeline-node.active::before {
  background: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-tint);
}

.timeline-node.upcoming::before {
  background: var(--surface);
  border: 2px solid var(--muted-light);
  width: 8px;
  height: 8px;
}

.timeline-node.done {
  color: var(--success);
}

.timeline-node.active {
  color: var(--primary);
  font-weight: 700;
}

.timeline-node.upcoming {
  color: var(--muted-light);
}

/* ── Visit tasks ───────────────────────────────────────────── */
.task-list {
  list-style: none;
  margin: 0 0 var(--space-3);
  padding: 0;
  display: grid;
  gap: var(--space-2);
}

.task-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  background: var(--bg);
  border-radius: var(--radius);
  padding: var(--space-2) var(--space-3);
  font-size: 0.9rem;
}
```

- [x] **Step 3: Import the stylesheets and extend the `Schedule` type**

`frontend/src/main.tsx` — add at the top of the imports:

```ts
import "./styles/tokens.css";
import "./styles/app.css";
```

`frontend/src/api/types.ts` — in `Schedule`, add after `visits`:

```ts
  titles?: Record<string, string>;
```

- [x] **Step 4: Verify suites and build stay green**

Run: `cd frontend && npm test && npm run build`
Expected: 25 tests pass; `tsc` build clean. (CSS is inert until classes are used.)

- [x] **Step 5: Commit**

```bash
git add frontend/src/styles/tokens.css frontend/src/styles/app.css frontend/src/main.tsx frontend/src/api/types.ts
git commit -m "Add Clinical Calm design tokens and component stylesheet"
```

---

## Task 3: AppShell

**Files:**
- Create: `frontend/src/AppShell.tsx`
- Create: `frontend/src/AppShell.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: classes `.app-header`, `.app-header-inner`, `.brand`, `.brand-mark`, `.brand-tag`, `.container` (Task 2).
- Produces: `AppShell({ children }: { children: ReactNode })` — header + `<main class="container">`. `App` renders routes inside it. The `h1` accessible name stays exactly `Vulcan Schedule of Activities` (the `◈` mark is `aria-hidden`).

- [x] **Step 1: Write the failing test**

`frontend/src/AppShell.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AppShell from "./AppShell";

describe("AppShell", () => {
  it("renders the brand heading with its exact accessible name", () => {
    render(<AppShell>content</AppShell>);
    expect(
      screen.getByRole("heading", { name: "Vulcan Schedule of Activities" }),
    ).toBeInTheDocument();
  });

  it("renders children inside the main landmark", () => {
    render(<AppShell>page body</AppShell>);
    expect(screen.getByRole("main")).toHaveTextContent("page body");
  });
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/AppShell.test.tsx`
Expected: FAIL — cannot resolve `./AppShell`.

- [x] **Step 3: Implement `AppShell` and use it in `App`**

`frontend/src/AppShell.tsx`:

```tsx
import type { ReactNode } from "react";

export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <div>
      <header className="app-header">
        <div className="app-header-inner">
          <h1 className="brand">
            <span className="brand-mark" aria-hidden="true">
              ◈
            </span>
            Vulcan Schedule of Activities
          </h1>
          <span className="brand-tag">SoA connectathon demo</span>
        </div>
      </header>
      <main className="container">{children}</main>
    </div>
  );
}
```

`frontend/src/App.tsx` — replace entirely:

```tsx
import AppShell from "./AppShell";
import AppRoutes from "./routes";

export default function App() {
  return (
    <AppShell>
      <AppRoutes />
    </AppShell>
  );
}
```

- [x] **Step 4: Run the suite**

Run: `cd frontend && npm test`
Expected: all pass, including the untouched `App.test.tsx` (accessible name preserved; `aria-hidden` keeps the `◈` out of the name).

- [x] **Step 5: Commit**

```bash
git add frontend/src/AppShell.tsx frontend/src/AppShell.test.tsx frontend/src/App.tsx
git commit -m "Add Clinical Calm app shell around all routes"
```

---

## Task 4: Worklist, Enroll, launch pages, and Landing styling

**Files:**
- Modify: `frontend/src/views/StudyWorklist/StudyWorklist.tsx`
- Modify: `frontend/src/views/Enroll/Enroll.tsx`
- Modify: `frontend/src/launch/LaunchPending.tsx`
- Modify: `frontend/src/launch/LaunchError.tsx`
- Modify: `frontend/src/routes.tsx` (Landing no-session block only)

**Interfaces:**
- Consumes: classes from Task 2. No API/type changes. All roles, names, and copy strings unchanged.
- Produces: nothing consumed by later tasks.

- [x] **Step 1: Restyle `StudyWorklist`**

Replace the returned JSX only (imports/logic unchanged); error/loading/empty branches gain classes:

```tsx
  if (error) {
    return (
      <p role="alert" className="alert">
        {error}
      </p>
    );
  }

  if (studies === null) {
    return <p className="status-note">Loading studies…</p>;
  }

  if (studies.length === 0) {
    return <p className="chip">No research studies are available yet.</p>;
  }

  return (
    <div>
      <h2 className="page-title">Research studies</h2>
      <ul className="study-list">
        {studies.map((study) => (
          <li key={study.id} className="study-card">
            <Link to={`/enroll/${study.id}`}>{study.title}</Link>
          </li>
        ))}
      </ul>
    </div>
  );
```

- [x] **Step 2: Restyle `Enroll`**

Replace the returned JSX (logic unchanged; label text, button name, and copy identical):

```tsx
  if (status === "loading") {
    return <p className="status-note">Loading…</p>;
  }

  return (
    <div className="form-card">
      <h2 className="page-title">Enroll a patient</h2>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {contextPatientId ? (
        <p>
          Patient: <span className="meta">{contextPatientId}</span>
        </p>
      ) : (
        <label className="form-field">
          Patient FHIR ID
          <input
            value={manualPatientId}
            onChange={(event) => setManualPatientId(event.target.value)}
          />
        </label>
      )}
      <button className="btn" onClick={handleEnroll} disabled={status === "enrolling" || !patientId}>
        {status === "enrolling" ? "Enrolling…" : "Enroll"}
      </button>
    </div>
  );
```

- [x] **Step 3: Restyle launch pages and the Landing no-session block**

`frontend/src/launch/LaunchPending.tsx`:

```tsx
export default function LaunchPending() {
  return (
    <div className="status-card">
      <p role="status">Completing sign-in…</p>
    </div>
  );
}
```

`frontend/src/launch/LaunchError.tsx` — replace the returned JSX:

```tsx
  return (
    <div className="status-card">
      <p role="alert" className="alert">
        {message}
      </p>
      <p>Please relaunch this app from your EHR.</p>
    </div>
  );
```

`frontend/src/routes.tsx` — in `Landing`, replace the `failed` branch's JSX (link text and href unchanged — the e2e spec clicks this exact name):

```tsx
  if (failed) {
    return (
      <div className="status-card">
        <p>
          No active session. Launch this app from your EHR, or{" "}
          <a href="/launch/standalone">start a standalone launch</a>.
        </p>
      </div>
    );
  }
```

- [x] **Step 4: Run the suite**

Run: `cd frontend && npm test`
Expected: all pass unmodified (StudyWorklist, Enroll, LaunchError, routes tests query roles/names/copy, all preserved).

- [x] **Step 5: Commit**

```bash
git add frontend/src/views/StudyWorklist/StudyWorklist.tsx frontend/src/views/Enroll/Enroll.tsx frontend/src/launch/LaunchPending.tsx frontend/src/launch/LaunchError.tsx frontend/src/routes.tsx
git commit -m "Style worklist, enroll, launch, and landing views"
```

---

## Task 5: VisitCard — title, badge, styled stepper

**Files:**
- Modify: `frontend/src/views/SubjectDashboard/VisitCard.tsx`
- Test: `frontend/src/views/SubjectDashboard/VisitCard.test.tsx` (additions only — existing tests untouched)

**Interfaces:**
- Consumes: classes from Task 2.
- Produces: `VisitCardProps` gains optional `title?: string`. Rendered card shows the title (fallback: actionId) as `.card-title`, the phase as a `.badge`, the action id as `.meta` text (always visible), and keeps: `aria-label={\`Visit ${actionId}\`}`, `<ol aria-label="Visit phases">` with visible phase words + `aria-current="step"`, all button accessible names, `aria-label="Appointment responses"`, `aria-label="Visit tasks"`. Task 6 passes `title={schedule.titles?.[actionId]}`.

- [x] **Step 1: Add the new tests (append to the existing describe block)**

```tsx
  it("shows the visit title when provided and keeps the action id visible", () => {
    const handlers = noopHandlers();
    render(
      <VisitCard actionId="E1" title="Screening" detail={{ phase: "proposed" }} {...handlers} />,
    );

    expect(screen.getByText("Screening")).toBeInTheDocument();
    expect(screen.getByText("E1")).toBeInTheDocument();
  });

  it("falls back to the action id as the card heading when no title is given", () => {
    const handlers = noopHandlers();
    render(<VisitCard actionId="E1" detail={{ phase: "proposed" }} {...handlers} />);

    expect(screen.getByLabelText("Visit E1")).toBeInTheDocument();
  });
```

- [x] **Step 2: Run to verify the first new test fails**

Run: `cd frontend && npx vitest run src/views/SubjectDashboard/VisitCard.test.tsx`
Expected: FAIL — `title` prop not accepted / "Screening" not rendered.

- [x] **Step 3: Rewrite `VisitCard.tsx`**

```tsx
import type { VisitDetail } from "../../api/types";

const PHASES = ["proposed", "planned", "ordered", "scheduled", "booked", "performing", "completed"] as const;

interface VisitCardProps {
  actionId: string;
  title?: string;
  detail: VisitDetail | undefined;
  busy?: boolean;
  onPlan: () => void;
  onOrder: () => void;
  onSchedule: () => void;
  onRespond: (participant: "patient" | "site") => void;
  onPerform: () => void;
  onCompleteTask: (taskId: string) => void;
  onCompleteVisit: () => void;
}

export default function VisitCard({
  actionId,
  title,
  detail,
  busy = false,
  onPlan,
  onOrder,
  onSchedule,
  onRespond,
  onPerform,
  onCompleteTask,
  onCompleteVisit,
}: VisitCardProps) {
  const phase = detail?.phase ?? "proposed";
  const phaseIndex = PHASES.indexOf(phase as (typeof PHASES)[number]);
  const participantStatus = (role: "patient" | "site") =>
    detail?.participants?.find((p) => p.role === role)?.status;

  return (
    <li aria-label={`Visit ${actionId}`} className="card">
      <div className="card-header">
        <strong className="card-title">{title ?? actionId}</strong>
        <span className="badge">{phase}</span>
      </div>
      {title && <div className="meta">{actionId}</div>}
      <ol aria-label="Visit phases" className="stepper">
        {PHASES.map((p, index) => (
          <li
            key={p}
            aria-current={p === phase ? "step" : undefined}
            className={phaseIndex > index ? "done" : undefined}
          >
            {p}
          </li>
        ))}
      </ol>

      {phase === "revoked" && <p className="chip">Revoked — subject withdrawn</p>}

      {phase === "proposed" && (
        <button className="btn" onClick={onPlan} disabled={busy}>
          Accept proposal
        </button>
      )}
      {phase === "planned" && (
        <button className="btn" onClick={onOrder} disabled={busy}>
          Authorize
        </button>
      )}
      {phase === "ordered" && (
        <button className="btn" onClick={onSchedule} disabled={busy}>
          Schedule
        </button>
      )}

      {phase === "scheduled" && (
        <div aria-label="Appointment responses" className="btn-row">
          <button
            className="btn"
            onClick={() => onRespond("patient")}
            disabled={busy || participantStatus("patient") === "accepted"}
          >
            Patient accepts
          </button>
          <button
            className="btn-secondary"
            onClick={() => onRespond("site")}
            disabled={busy || participantStatus("site") === "accepted"}
          >
            Site confirms
          </button>
        </div>
      )}

      {phase === "booked" && (
        <button className="btn" onClick={onPerform} disabled={busy}>
          Perform visit
        </button>
      )}

      {phase === "performing" && (
        <div>
          <ul aria-label="Visit tasks" className="task-list">
            {detail?.tasks?.map((task) => (
              <li key={task.id}>
                <span>
                  {task.description} — {task.status}
                </span>
                {task.status !== "completed" && task.status !== "cancelled" && (
                  <button
                    className="btn-secondary"
                    onClick={() => onCompleteTask(task.id)}
                    disabled={busy}
                  >
                    Done: {task.description}
                  </button>
                )}
              </li>
            ))}
          </ul>
          <button className="btn" onClick={onCompleteVisit} disabled={busy}>
            Complete visit
          </button>
        </div>
      )}
    </li>
  );
}
```

Note: the task `<li>` wraps its text in a `<span>` for flex layout — the existing test asserts button names and `Done: …` absence, not the li's exact text nodes, so this is safe. The `"revoked"` phase is not in `PHASES`, so `phaseIndex` is `-1` and no stepper item is marked done — same as before.

- [x] **Step 4: Run the suite**

Run: `cd frontend && npm test`
Expected: all pass — 3 pre-existing VisitCard tests unmodified + 2 new.

- [x] **Step 5: Commit**

```bash
git add frontend/src/views/SubjectDashboard/VisitCard.tsx frontend/src/views/SubjectDashboard/VisitCard.test.tsx
git commit -m "Style VisitCard with title, phase badge, and segmented stepper"
```

---

## Task 6: Subject Dashboard — timeline rail + work area

**Files:**
- Create: `frontend/src/views/SubjectDashboard/Timeline.tsx`
- Create: `frontend/src/views/SubjectDashboard/Timeline.test.tsx`
- Modify: `frontend/src/views/SubjectDashboard/SubjectDashboard.tsx`

**Interfaces:**
- Consumes: `Schedule` with optional `titles` (Task 2), `VisitCard` with `title` prop (Task 5), classes from Task 2.
- Produces: `Timeline({ completed, current, nextSteps, titles }: { completed: string[]; current: string[]; nextSteps: NextStep[]; titles?: Record<string, string> })` — a `<nav aria-label="Study timeline">` rendering done → active → upcoming nodes. Not consumed elsewhere.

- [x] **Step 1: Write the failing Timeline test**

`frontend/src/views/SubjectDashboard/Timeline.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Timeline from "./Timeline";

describe("Timeline", () => {
  it("renders done, active, and upcoming nodes in order with titles", () => {
    render(
      <Timeline
        completed={["a-1"]}
        current={["b-2"]}
        nextSteps={[{ actionId: "c-3", title: "Day 7", transitionType: "SS" }]}
        titles={{ "a-1": "Screening", "b-2": "Treatment Day 1" }}
      />,
    );

    const rail = screen.getByRole("navigation", { name: "Study timeline" });
    const nodes = within(rail).getAllByRole("listitem");
    expect(nodes.map((n) => n.textContent)).toEqual(["Screening", "Treatment Day 1", "Day 7"]);
    expect(nodes[0].className).toContain("done");
    expect(nodes[1].className).toContain("active");
    expect(nodes[2].className).toContain("upcoming");
  });

  it("falls back to action ids when titles are missing", () => {
    render(<Timeline completed={["a-1"]} current={[]} nextSteps={[]} />);
    expect(screen.getByText("a-1")).toBeInTheDocument();
  });
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/views/SubjectDashboard/Timeline.test.tsx`
Expected: FAIL — cannot resolve `./Timeline`.

- [x] **Step 3: Implement `Timeline.tsx`**

```tsx
import type { NextStep } from "../../api/types";

interface TimelineProps {
  completed: string[];
  current: string[];
  nextSteps: NextStep[];
  titles?: Record<string, string>;
}

export default function Timeline({ completed, current, nextSteps, titles }: TimelineProps) {
  const label = (actionId: string) => titles?.[actionId] ?? actionId;

  return (
    <nav aria-label="Study timeline" className="timeline">
      <h2 className="section-title">Study timeline</h2>
      <ol>
        {completed.map((actionId) => (
          <li key={actionId} className="timeline-node done">
            {label(actionId)}
          </li>
        ))}
        {current.map((actionId) => (
          <li key={actionId} className="timeline-node active">
            {label(actionId)}
          </li>
        ))}
        {nextSteps.map((step) => (
          <li key={step.actionId} className="timeline-node upcoming">
            {step.title}
          </li>
        ))}
      </ol>
    </nav>
  );
}
```

- [x] **Step 4: Run the Timeline test to verify it passes**

Run: `cd frontend && npx vitest run src/views/SubjectDashboard/Timeline.test.tsx`
Expected: 2 passed.

- [x] **Step 5: Rewire `SubjectDashboard`'s JSX**

Only the returned JSX changes (all state/handlers stay). Replace everything from `if (!schedule) {` to the end of the component with:

```tsx
  if (!schedule) {
    return error ? (
      <p role="alert" className="alert">
        {error}
      </p>
    ) : (
      <p className="status-note">Loading schedule…</p>
    );
  }

  return (
    <div>
      <h2 className="page-title">
        Subject <span className="meta">{subjectId}</span>
      </h2>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {withdrawn && (
        <p role="status" className="status-note">
          Subject withdrawn from study.
        </p>
      )}

      <div className="dashboard-grid">
        <Timeline
          completed={schedule.completed}
          current={schedule.current}
          nextSteps={schedule.nextSteps}
          titles={schedule.titles}
        />

        <div>
          <section aria-label="Current visits">
            <h2 className="section-title">Current</h2>
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {schedule.current.map((actionId) => (
                <VisitCard
                  key={actionId}
                  actionId={actionId}
                  title={schedule.titles?.[actionId]}
                  detail={schedule.visits[actionId]}
                  busy={busy}
                  onPlan={() => runGate(() => promoteVisit(subjectId!, actionId, "plan"), "Could not accept the proposal.")}
                  onOrder={() => runGate(() => promoteVisit(subjectId!, actionId, "order"), "Could not authorize the visit.")}
                  onSchedule={() => runGate(() => scheduleVisit(subjectId!, actionId), "Could not schedule the visit.")}
                  onRespond={(participant) =>
                    runGate(
                      () => respondToAppointment(subjectId!, actionId, participant, "accepted"),
                      "Could not record the response.",
                    )
                  }
                  onPerform={() => runGate(() => performVisit(subjectId!, actionId), "Could not start the visit.")}
                  onCompleteTask={(taskId) =>
                    runGate(() => completeTask(subjectId!, actionId, taskId), "Could not complete the task.")
                  }
                  onCompleteVisit={() => handleComplete(actionId)}
                />
              ))}
            </ul>
          </section>

          {pendingChoice && (
            <section aria-label="Decision needed" className="banner-decision">
              <h2>Decision needed</h2>
              <p>More than one next step is valid. Choose which one to schedule:</p>
              <ul>
                {pendingChoice.options.map((option) => (
                  <li key={option.actionId}>
                    <button className="btn-choice" onClick={() => handleChoice(option.actionId)}>
                      {option.title}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {!pendingChoice && schedule.nextSteps.length > 0 && (
            <section aria-label="Next steps">
              <h2 className="section-title">Next steps</h2>
              <ul className="chip-list">
                {schedule.nextSteps.map((step) => (
                  <li key={step.actionId} className="chip">
                    {step.title}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <button className="btn-danger-quiet" onClick={handleWithdraw} disabled={withdrawn || busy}>
        Withdraw subject
          </button>
        </div>
      </div>
    </div>
  );
```

Add the import at the top: `import Timeline from "./Timeline";`

Two deliberate choices to call out:
- The old `<section aria-label="Completed visits">` list is replaced by the rail. No existing test queries "Completed visits" or the `Completed` heading, but the Playwright spec asserts completed action-id **text** is visible — the rail renders it (as the fallback or alongside; with real data the title shows and the id appears on the *current* visit card's meta line. The spec's `getByText("0700e721-…")` fires while that visit is **current**, before completion — verified against the spec flow in `frontend/e2e/golden-path.spec.ts:31-40`).
- The heading `Current` keeps its accessible name (`section-title` is styling only) — `SubjectDashboard.test.tsx:99` requires it.

- [x] **Step 6: Run the full frontend suite**

Run: `cd frontend && npm test`
Expected: all pass — the three untouched SubjectDashboard tests (their mocks lack `titles`; every access is optional-chained) plus Timeline and VisitCard additions. Total: 31.

- [x] **Step 7: Commit**

```bash
git add frontend/src/views/SubjectDashboard/Timeline.tsx frontend/src/views/SubjectDashboard/Timeline.test.tsx frontend/src/views/SubjectDashboard/SubjectDashboard.tsx
git commit -m "Lay out Subject Dashboard as timeline rail plus work area"
```

---

## Task 7: End-to-end verification

**Files:**
- No source changes. Verification only (fix-forward if anything fails, smallest change that keeps the constraint set).

- [x] **Step 1: Full test suites**

Run: `cd backend && source .venv/bin/activate && pytest && cd ../frontend && npm test && npm run build`
Expected: backend all green; frontend 31 tests; `tsc`/vite build clean.

- [x] **Step 2: Live visual + golden-path check**

With Aidbox up (`task aidbox:up && task aidbox:wait`, fixtures loaded) and dev servers running (`task dev` — ports come from the root `.env`, currently 5199/8010):

```bash
cd frontend
npx playwright test golden-path.spec.ts -g "standalone launch redirects"
```

Expected: 1 passed (the authenticated spec skips without a bootstrapped session — expected).

Then capture screenshots for a human look:

```bash
npx playwright screenshot http://localhost:5199/ /tmp/ui-landing.png
```

Open the app in a browser and click through worklist → enroll → dashboard; confirm the rail, cards, badges, and decision banner render styled (not browser defaults). If any page still shows unstyled content, check the two CSS imports in `main.tsx` load (view-source should list both files).

- [x] **Step 3: Commit anything the verification forced, then finish**

```bash
git status   # should be clean if Steps 1-2 needed no fixes
```

Use superpowers:finishing-a-development-branch to close out.

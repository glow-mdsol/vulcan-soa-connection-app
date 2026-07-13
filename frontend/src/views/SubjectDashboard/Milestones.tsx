import { useState } from "react";

import type { SubjectMilestone } from "../../api/types";

// NCI Thesaurus protocol milestone codes
const MILESTONE_OPTIONS = [
  { code: "C186210", label: "Declined to Continue Into Next Trial Element" },
  { code: "C176358", label: "Declined To Continue Into Survival Follow-Up" },
  { code: "C164344", label: "Did Not Meet Eligibility Criteria" },
  { code: "C132447", label: "Eligibility Criteria Met By Subject" },
  { code: "C161418", label: "Informed Assent" },
  { code: "C16735", label: "Informed Consent" },
  { code: "C202445", label: "Informed Consent Declined For Protocol-Specified Activity" },
  { code: "C202444", label: "Informed Consent Obtained For Protocol-Specified Activity" },
  { code: "C186211", label: "Opted to Continue Into Next Trial Element" },
  { code: "C186212", label: "Re-randomized" },
  { code: "C161417", label: "Subject Entered Into Trial" },
  { code: "C114209", label: "Subject is Randomized" },
];

function labelFor(entry: SubjectMilestone): string {
  return (
    entry.display ??
    MILESTONE_OPTIONS.find((option) => option.code === entry.milestone)?.label ??
    entry.milestone
  );
}

interface MilestonesProps {
  milestones: SubjectMilestone[];
  busy: boolean;
  onRecord: (milestone: string, date: string | null, display: string | null) => void;
}

export default function Milestones({ milestones, busy, onRecord }: MilestonesProps) {
  const [milestone, setMilestone] = useState("");
  const [date, setDate] = useState("");

  return (
    <section className="card" aria-label="Subject milestones">
      <p className="section-title">Milestones</p>
      {milestones.length === 0 ? (
        <p className="status-note">No milestones recorded yet.</p>
      ) : (
        <ul className="milestone-list">
          {milestones.map((entry, index) => (
            <li key={`${entry.milestone}-${index}`}>
              <span className="milestone-name">{labelFor(entry)}</span>
              {entry.date && <span className="meta">{entry.date}</span>}
            </li>
          ))}
        </ul>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!milestone) {
            return;
          }
          const label = MILESTONE_OPTIONS.find((option) => option.code === milestone)?.label;
          onRecord(milestone, date || null, label ?? null);
        }}
      >
        <label className="form-field">
          Milestone
          <select value={milestone} onChange={(event) => setMilestone(event.target.value)}>
            <option value="">Select a milestone</option>
            {MILESTONE_OPTIONS.map((option) => (
              <option key={option.code} value={option.code}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="form-field">
          Date
          <input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
        </label>
        <button type="submit" className="btn-secondary" disabled={busy || !milestone}>
          Record milestone
        </button>
      </form>
    </section>
  );
}

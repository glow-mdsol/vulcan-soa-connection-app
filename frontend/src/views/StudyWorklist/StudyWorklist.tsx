import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { listResearchStudies } from "../../api/client";
import type { ResearchStudySummary } from "../../api/types";

export default function StudyWorklist() {
  const [studies, setStudies] = useState<ResearchStudySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listResearchStudies()
      .then(setStudies)
      .catch(() => setError("Could not load research studies."));
  }, []);

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
}

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
    return <p role="alert">{error}</p>;
  }

  if (studies === null) {
    return <p>Loading studies…</p>;
  }

  if (studies.length === 0) {
    return <p>No research studies are available yet.</p>;
  }

  return (
    <ul>
      {studies.map((study) => (
        <li key={study.id}>
          <Link to={`/enroll/${study.id}`}>{study.title}</Link>
        </li>
      ))}
    </ul>
  );
}

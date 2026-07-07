import { useEffect, useState } from "react";

import { getResearchStudy } from "../../api/client";
import type { ResearchStudyDetail } from "../../api/types";

interface ResearchStudyDetailsProps {
  studyId: string;
}

export default function ResearchStudyDetails({ studyId }: ResearchStudyDetailsProps) {
  const [study, setStudy] = useState<ResearchStudyDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadStudy() {
      try {
        const result = await getResearchStudy(studyId);
        if (!active) {
          return;
        }
        setStudy(result);
        setError(null);
      } catch {
        if (!active) {
          return;
        }
        setError("Could not load study details.");
      }
    }

    loadStudy();

    return () => {
      active = false;
    };
  }, [studyId]);

  return (
    <section className="card" aria-label="Research study details">
      <div className="card-header">
        <div>
          <p className="section-title">Research Study</p>
          <h2 className="card-title">{study?.title ?? "Loading study details…"}</h2>
        </div>
        {study?.status && <span className="badge">{study.status}</span>}
      </div>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {study && (
        <>
          <p className="meta">{study.id}</p>
          <p>
            {study.protocolReferences.length === 1
              ? "1 protocol is attached to this study."
              : `${study.protocolReferences.length} protocols are attached to this study.`}
          </p>
          {study.protocolReferences.length > 0 && (
            <ul className="chip-list" aria-label="Study protocols">
              {study.protocolReferences.map((reference) => (
                <li key={reference} className="chip">
                  {reference}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
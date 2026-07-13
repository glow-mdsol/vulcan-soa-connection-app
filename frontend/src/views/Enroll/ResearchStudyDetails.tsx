import type { ResearchStudyDetail } from "../../api/types";

interface ResearchStudyDetailsProps {
  study: ResearchStudyDetail | null;
  error: string | null;
}

export default function ResearchStudyDetails({ study, error }: ResearchStudyDetailsProps) {
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

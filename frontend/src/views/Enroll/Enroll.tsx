import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { enrollPatient, getContext } from "../../api/client";

export default function Enroll() {
  const { studyId } = useParams<{ studyId: string }>();
  const navigate = useNavigate();
  const [contextPatientId, setContextPatientId] = useState<string | null>(null);
  const [manualPatientId, setManualPatientId] = useState("");
  const [status, setStatus] = useState<"loading" | "ready" | "enrolling">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getContext()
      .then((context) => setContextPatientId(context.patientId))
      .catch(() => {
        // No session context yet (e.g. mid-launch); treat as "no patient context".
      })
      .finally(() => setStatus("ready"));
  }, []);

  const patientId = contextPatientId ?? manualPatientId.trim();

  async function handleEnroll() {
    if (!studyId || !patientId) {
      return;
    }
    setStatus("enrolling");
    setError(null);
    try {
      const result = await enrollPatient(studyId, patientId);
      navigate(`/subjects/${result.researchSubjectId}`);
    } catch {
      setError("Enrollment failed. Please try again.");
      setStatus("ready");
    }
  }

  if (status === "loading") {
    return <p>Loading…</p>;
  }

  return (
    <div>
      <h2>Enroll a patient</h2>
      {error && <p role="alert">{error}</p>}
      {contextPatientId ? (
        <p>Patient: {contextPatientId}</p>
      ) : (
        <label>
          Patient FHIR ID
          <input
            value={manualPatientId}
            onChange={(event) => setManualPatientId(event.target.value)}
          />
        </label>
      )}
      <button onClick={handleEnroll} disabled={status === "enrolling" || !patientId}>
        {status === "enrolling" ? "Enrolling…" : "Enroll"}
      </button>
    </div>
  );
}

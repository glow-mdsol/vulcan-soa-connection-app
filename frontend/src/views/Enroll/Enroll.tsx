import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { enrollPatient, getContext, listPatients } from "../../api/client";
import { PatientSummary } from "../../api/types";
import ResearchStudyDetails from "./ResearchStudyDetails";

export default function Enroll() {
  const { studyId } = useParams<{ studyId: string }>();
  const navigate = useNavigate();
  const [contextPatientId, setContextPatientId] = useState<string | null>(null);
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [selectedPatientId, setSelectedPatientId] = useState<string>("");
  const [status, setStatus] = useState<"loading" | "ready" | "enrolling">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadPatients() {
      try {
        const [context, patientList] = await Promise.all([getContext(), listPatients()]);

        if (!active) {
          return;
        }

        setContextPatientId(context.patientId);
        setPatients(patientList);
        setSelectedPatientId(context.patientId ?? patientList[0]?.id ?? "");
      } catch {
        if (!active) {
          return;
        }

        setPatients([]);
        setSelectedPatientId("");
      } finally {
        if (active) {
          setStatus("ready");
        }
      }
    }

    loadPatients();

    return () => {
      active = false;
    };
  }, []);

  const patientId = selectedPatientId.trim();

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
    return <p className="status-note">Loading…</p>;
  }

  return (
    <div>
      {studyId && <ResearchStudyDetails studyId={studyId} />}
      <div className="form-card">
        <h2 className="page-title">Enroll a patient</h2>
        {error && (
          <p role="alert" className="alert">
            {error}
          </p>
        )}
        <label className="form-field">
          Patient
          <select
            value={selectedPatientId}
            onChange={(event) => setSelectedPatientId(event.target.value)}
            disabled={!patients.length}
          >
            <option value="">Select a patient</option>
            {patients.map((patient) => (
              <option key={patient.id} value={patient.id}>
                {patient.id.substring(0, 8)}
                {patient.gender ? ` · ${patient.gender}` : ""}
                {patient.birthDate ? ` · ${patient.birthDate}` : ""}
              </option>
            ))}
          </select>
        </label>
        {contextPatientId && <p className="meta">Launch context patient: {contextPatientId}</p>}
        <button className="btn" onClick={handleEnroll} disabled={status === "enrolling" || !patientId}>
          {status === "enrolling" ? "Enrolling…" : "Enroll"}
        </button>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { enrollPatient, getContext, getResearchStudy, listPatients } from "../../api/client";
import { PatientSummary, ResearchStudyDetail } from "../../api/types";
import EnrolledSubjects from "./EnrolledSubjects";
import ResearchStudyDetails from "./ResearchStudyDetails";

export default function Enroll() {
  const { studyId } = useParams<{ studyId: string }>();
  const navigate = useNavigate();
  const [contextPatientId, setContextPatientId] = useState<string | null>(null);
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [selectedPatientId, setSelectedPatientId] = useState<string>("");
  const [subjectIdentifier, setSubjectIdentifier] = useState<string>("");
  const [study, setStudy] = useState<ResearchStudyDetail | null>(null);
  const [studyError, setStudyError] = useState<string | null>(null);
  const [selectedPlanId, setSelectedPlanId] = useState<string>("");
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

  useEffect(() => {
    if (!studyId) {
      return;
    }
    let active = true;

    getResearchStudy(studyId)
      .then((result) => {
        if (!active) {
          return;
        }
        setStudy(result);
        setStudyError(null);
        setSelectedPlanId(
          (current) => current || (result.protocolReferences[0]?.split("/").pop() ?? ""),
        );
      })
      .catch(() => {
        if (active) {
          setStudyError("Could not load study details.");
        }
      });

    return () => {
      active = false;
    };
  }, [studyId]);

  const planIds = (study?.protocolReferences ?? []).map(
    (reference) => reference.split("/").pop() ?? reference,
  );

  const patientId = selectedPatientId.trim();
  const identifier = subjectIdentifier.trim();

  async function handleEnroll() {
    if (!studyId || !patientId || !identifier) {
      return;
    }
    setStatus("enrolling");
    setError(null);
    try {
      const result = await enrollPatient(studyId, patientId, identifier, selectedPlanId || null);
      navigate(`/subjects/${result.researchSubjectId}`);
    } catch (enrollError) {
      setError(
        enrollError instanceof Error && enrollError.message.includes("409")
          ? "That subject identifier is already in use in this study."
          : "Enrollment failed. Please try again.",
      );
      setStatus("ready");
    }
  }

  if (status === "loading") {
    return <p className="status-note">Loading…</p>;
  }

  return (
    <div>
      {studyId && <ResearchStudyDetails study={study} error={studyError} />}
      <div className="enroll-grid">
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
          {planIds.length > 1 && (
            <label className="form-field">
              Protocol
              <select
                value={selectedPlanId}
                onChange={(event) => setSelectedPlanId(event.target.value)}
              >
                {planIds.map((planId) => (
                  <option key={planId} value={planId}>
                    {planId}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="form-field">
            Subject identifier
            <input
              value={subjectIdentifier}
              onChange={(event) => setSubjectIdentifier(event.target.value)}
              placeholder="e.g. SUBJ-001"
            />
          </label>
          {contextPatientId && <p className="meta">Launch context patient: {contextPatientId}</p>}
          <button
            className="btn"
            onClick={handleEnroll}
            disabled={status === "enrolling" || !patientId || !identifier}
          >
            {status === "enrolling" ? "Enrolling…" : "Enroll"}
          </button>
        </div>
        {studyId && <EnrolledSubjects studyId={studyId} />}
      </div>
    </div>
  );
}

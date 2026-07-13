import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { assignSubjectIdentifier, deleteEnrollment, listStudySubjects } from "../../api/client";
import type { StudySubjectSummary } from "../../api/types";

interface EnrolledSubjectsProps {
  studyId: string;
}

export default function EnrolledSubjects({ studyId }: EnrolledSubjectsProps) {
  const [subjects, setSubjects] = useState<StudySubjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [assignError, setAssignError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadSubjects() {
      try {
        const result = await listStudySubjects(studyId);
        if (!active) {
          return;
        }
        setSubjects(result);
        setError(null);
      } catch {
        if (!active) {
          return;
        }
        setError("Could not load enrolled subjects.");
      }
    }

    loadSubjects();

    return () => {
      active = false;
    };
  }, [studyId]);

  async function handleAssign(subjectId: string) {
    const value = (drafts[subjectId] ?? "").trim();
    if (!value) {
      return;
    }
    setAssignError(null);
    try {
      const updated = await assignSubjectIdentifier(subjectId, value);
      setSubjects(
        (current) =>
          current?.map((subject) =>
            subject.researchSubjectId === subjectId ? updated : subject,
          ) ?? current,
      );
    } catch (assignmentError) {
      setAssignError(
        assignmentError instanceof Error && assignmentError.message.includes("409")
          ? "That subject identifier is already in use in this study."
          : "Could not assign the subject identifier. Please try again.",
      );
    }
  }

  async function handleDelete(subjectId: string) {
    setAssignError(null);
    try {
      await deleteEnrollment(subjectId);
      setSubjects(
        (current) =>
          current?.filter((subject) => subject.researchSubjectId !== subjectId) ?? current,
      );
    } catch {
      setAssignError("Could not delete the enrolment. Please try again.");
    }
  }

  return (
    <section className="card" aria-label="Enrolled research subjects">
      <p className="section-title">Enrolled subjects</p>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {assignError && (
        <p role="alert" className="alert">
          {assignError}
        </p>
      )}
      {!error && subjects === null && <p className="status-note">Loading enrolled subjects…</p>}
      {subjects && subjects.length === 0 && (
        <p className="status-note">No subjects are enrolled in this study yet.</p>
      )}
      {subjects && subjects.length > 0 && (
        <ul className="subject-roster">
          {subjects.map((subject) => {
            const shortId = subject.researchSubjectId.substring(0, 8);
            return (
              <li key={subject.researchSubjectId}>
                <div className="subject-roster-row">
                  <Link to={`/subjects/${subject.researchSubjectId}`}>
                    <span className="subject-roster-identifier">
                      {subject.subjectIdentifier ?? shortId}
                    </span>
                    <span className="meta">Patient {subject.patientId.substring(0, 8)}</span>
                    {subject.status && <span className="badge">{subject.status}</span>}
                  </Link>
                  <button
                    type="button"
                    className="btn-danger-quiet"
                    aria-label={`Remove ${subject.subjectIdentifier ?? shortId}`}
                    onClick={() => handleDelete(subject.researchSubjectId)}
                  >
                    Remove
                  </button>
                </div>
                {subject.subjectIdentifier === null && (
                  <form
                    className="assign-identifier"
                    onSubmit={(event) => {
                      event.preventDefault();
                      handleAssign(subject.researchSubjectId);
                    }}
                  >
                    <input
                      aria-label={`Subject identifier for ${shortId}`}
                      placeholder="Subject identifier"
                      value={drafts[subject.researchSubjectId] ?? ""}
                      onChange={(event) =>
                        setDrafts((current) => ({
                          ...current,
                          [subject.researchSubjectId]: event.target.value,
                        }))
                      }
                    />
                    <button
                      type="submit"
                      className="btn-secondary"
                      disabled={!(drafts[subject.researchSubjectId] ?? "").trim()}
                    >
                      Assign
                    </button>
                  </form>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

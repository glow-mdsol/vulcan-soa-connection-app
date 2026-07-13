import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import type { VisitDetail } from "../../api/types";

const PHASES = ["proposed", "planned", "ordered", "scheduled", "booked", "performing", "completed"] as const;

interface VisitCardProps {
  actionId: string;
  title?: string;
  detail: VisitDetail | undefined;
  busy?: boolean;
  subjectId?: string;
  studyId?: string;
  planDefinitionId?: string;
  onPlan: () => void;
  onOrder: () => void;
  onSchedule: () => void;
  onExpedite: () => void;
  onRespond: (participant: "patient" | "site") => void;
  onPerform: () => void;
  onCompleteTask: (taskId: string) => void;
  onCompleteVisit: () => void;
  children?: ReactNode;
}

export default function VisitCard({
  actionId,
  title,
  detail,
  busy = false,
  subjectId,
  studyId,
  planDefinitionId,
  onPlan,
  onOrder,
  onSchedule,
  onExpedite,
  onRespond,
  onPerform,
  onCompleteTask,
  onCompleteVisit,
  children,
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
      {(studyId || subjectId) && (
        <div className="workflow-diagram-links">
          {studyId && (
            <Link
              className="workflow-diagram-link"
              to={`/studies/${studyId}/protocol-tree${planDefinitionId ? `?plan=${planDefinitionId}` : ""}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              Definition diagram ↗
            </Link>
          )}
          {subjectId && (
            <Link
              className="workflow-diagram-link"
              to={`/subjects/${subjectId}/request-event-tree`}
              target="_blank"
              rel="noopener noreferrer"
            >
              Request/event diagram ↗
            </Link>
          )}
        </div>
      )}
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
        <div className="btn-row">
          <button className="btn" onClick={onPlan} disabled={busy}>
            Accept proposal
          </button>
          <button className="btn-secondary" onClick={onExpedite} disabled={busy}>
            Schedule now
          </button>
        </div>
      )}
      {phase === "planned" && (
        <div className="btn-row">
          <button className="btn" onClick={onOrder} disabled={busy}>
            Authorize
          </button>
          <button className="btn-secondary" onClick={onExpedite} disabled={busy}>
            Schedule now
          </button>
        </div>
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

      {children}
    </li>
  );
}

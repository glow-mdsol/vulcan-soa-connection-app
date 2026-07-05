import type { VisitDetail } from "../../api/types";

const PHASES = ["proposed", "planned", "ordered", "scheduled", "booked", "performing", "completed"] as const;

interface VisitCardProps {
  actionId: string;
  detail: VisitDetail | undefined;
  busy?: boolean;
  onPlan: () => void;
  onOrder: () => void;
  onSchedule: () => void;
  onRespond: (participant: "patient" | "site") => void;
  onPerform: () => void;
  onCompleteTask: (taskId: string) => void;
  onCompleteVisit: () => void;
}

export default function VisitCard({
  actionId,
  detail,
  busy = false,
  onPlan,
  onOrder,
  onSchedule,
  onRespond,
  onPerform,
  onCompleteTask,
  onCompleteVisit,
}: VisitCardProps) {
  const phase = detail?.phase ?? "proposed";
  const participantStatus = (role: "patient" | "site") =>
    detail?.participants?.find((p) => p.role === role)?.status;

  return (
    <li aria-label={`Visit ${actionId}`}>
      <strong>{actionId}</strong>
      <ol aria-label="Visit phases">
        {PHASES.map((p) => (
          <li key={p} aria-current={p === phase ? "step" : undefined}>
            {p}
          </li>
        ))}
      </ol>

      {phase === "revoked" && <p>Revoked — subject withdrawn</p>}

      {phase === "proposed" && <button onClick={onPlan} disabled={busy}>Accept proposal</button>}
      {phase === "planned" && <button onClick={onOrder} disabled={busy}>Authorize</button>}
      {phase === "ordered" && <button onClick={onSchedule} disabled={busy}>Schedule</button>}

      {phase === "scheduled" && (
        <div aria-label="Appointment responses">
          <button
            onClick={() => onRespond("patient")}
            disabled={busy || participantStatus("patient") === "accepted"}
          >
            Patient accepts
          </button>
          <button
            onClick={() => onRespond("site")}
            disabled={busy || participantStatus("site") === "accepted"}
          >
            Site confirms
          </button>
        </div>
      )}

      {phase === "booked" && <button onClick={onPerform} disabled={busy}>Perform visit</button>}

      {phase === "performing" && (
        <div>
          <ul aria-label="Visit tasks">
            {detail?.tasks?.map((task) => (
              <li key={task.id}>
                {task.description} — {task.status}
                {task.status !== "completed" && task.status !== "cancelled" && (
                  <button onClick={() => onCompleteTask(task.id)} disabled={busy}>
                    Done: {task.description}
                  </button>
                )}
              </li>
            ))}
          </ul>
          <button onClick={onCompleteVisit} disabled={busy}>Complete visit</button>
        </div>
      )}
    </li>
  );
}

import type { VisitDetail } from "../../api/types";

const PHASES = ["proposed", "planned", "ordered", "scheduled", "booked", "performing", "completed"] as const;

interface VisitCardProps {
  actionId: string;
  detail: VisitDetail | undefined;
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

      {phase === "proposed" && <button onClick={onPlan}>Accept proposal</button>}
      {phase === "planned" && <button onClick={onOrder}>Authorize</button>}
      {phase === "ordered" && <button onClick={onSchedule}>Schedule</button>}

      {phase === "scheduled" && (
        <div aria-label="Appointment responses">
          <button onClick={() => onRespond("patient")} disabled={participantStatus("patient") === "accepted"}>
            Patient accepts
          </button>
          <button onClick={() => onRespond("site")} disabled={participantStatus("site") === "accepted"}>
            Site confirms
          </button>
        </div>
      )}

      {phase === "booked" && <button onClick={onPerform}>Perform visit</button>}

      {phase === "performing" && (
        <div>
          <ul aria-label="Visit tasks">
            {detail?.tasks?.map((task) => (
              <li key={task.id}>
                {task.description} — {task.status}
                {task.status !== "completed" && task.status !== "cancelled" && (
                  <button onClick={() => onCompleteTask(task.id)}>Done: {task.description}</button>
                )}
              </li>
            ))}
          </ul>
          <button onClick={onCompleteVisit}>Complete visit</button>
        </div>
      )}
    </li>
  );
}

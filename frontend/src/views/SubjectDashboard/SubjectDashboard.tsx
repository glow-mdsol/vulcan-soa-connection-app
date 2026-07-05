import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import {
  completeTask,
  completeVisit,
  getSchedule,
  performVisit,
  promoteVisit,
  respondToAppointment,
  scheduleVisit,
  withdrawSubject,
} from "../../api/client";
import type { NextStep, Schedule } from "../../api/types";
import VisitCard from "./VisitCard";

interface PendingChoice {
  actionId: string;
  options: NextStep[];
}

export default function SubjectDashboard() {
  const { subjectId } = useParams<{ subjectId: string }>();
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [pendingChoice, setPendingChoice] = useState<PendingChoice | null>(null);
  const [withdrawn, setWithdrawn] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (!subjectId) {
      return;
    }
    getSchedule(subjectId)
      .then(setSchedule)
      .catch(() => setError("Could not load this subject's schedule."));
  }, [subjectId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleComplete(actionId: string) {
    if (!subjectId) {
      return;
    }
    try {
      const result = await completeVisit(subjectId, actionId, null);
      if (result.ambiguous) {
        setPendingChoice({ actionId, options: result.nextSteps });
      } else {
        setPendingChoice(null);
        setSchedule(result);
      }
    } catch {
      setError("Could not mark this visit complete.");
    }
  }

  async function handleChoice(targetActionId: string) {
    if (!subjectId || !pendingChoice) {
      return;
    }
    try {
      const result = await completeVisit(subjectId, pendingChoice.actionId, targetActionId);
      setPendingChoice(null);
      setSchedule(result);
    } catch {
      setError("Could not schedule the chosen next visit.");
    }
  }

  async function runGate(action: () => Promise<Schedule>, failure: string) {
    try {
      setSchedule(await action());
    } catch {
      setError(failure);
    }
  }

  async function handleWithdraw() {
    if (!subjectId) {
      return;
    }
    try {
      await withdrawSubject(subjectId);
      setWithdrawn(true);
      refresh();
    } catch {
      setError("Could not withdraw this subject.");
    }
  }

  if (error) {
    return <p role="alert">{error}</p>;
  }

  if (!schedule) {
    return <p>Loading schedule…</p>;
  }

  return (
    <div>
      {withdrawn && <p role="status">Subject withdrawn from study.</p>}

      <section aria-label="Completed visits">
        <h2>Completed</h2>
        <ul>
          {schedule.completed.map((actionId) => (
            <li key={actionId}>{actionId}</li>
          ))}
        </ul>
      </section>

      <section aria-label="Current visits">
        <h2>Current</h2>
        <ul>
          {schedule.current.map((actionId) => (
            <VisitCard
              key={actionId}
              actionId={actionId}
              detail={schedule.visits[actionId]}
              onPlan={() => runGate(() => promoteVisit(subjectId!, actionId, "plan"), "Could not accept the proposal.")}
              onOrder={() => runGate(() => promoteVisit(subjectId!, actionId, "order"), "Could not authorize the visit.")}
              onSchedule={() => runGate(() => scheduleVisit(subjectId!, actionId), "Could not schedule the visit.")}
              onRespond={(participant) =>
                runGate(
                  () => respondToAppointment(subjectId!, actionId, participant, "accepted"),
                  "Could not record the response.",
                )
              }
              onPerform={() => runGate(() => performVisit(subjectId!, actionId), "Could not start the visit.")}
              onCompleteTask={(taskId) =>
                runGate(() => completeTask(subjectId!, actionId, taskId), "Could not complete the task.")
              }
              onCompleteVisit={() => handleComplete(actionId)}
            />
          ))}
        </ul>
      </section>

      {pendingChoice && (
        <section aria-label="Decision needed">
          <h2>Decision needed</h2>
          <p>More than one next step is valid. Choose which one to schedule:</p>
          <ul>
            {pendingChoice.options.map((option) => (
              <li key={option.actionId}>
                <button onClick={() => handleChoice(option.actionId)}>{option.title}</button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {!pendingChoice && schedule.nextSteps.length > 0 && (
        <section aria-label="Next steps">
          <h2>Next steps</h2>
          <ul>
            {schedule.nextSteps.map((step) => (
              <li key={step.actionId}>{step.title}</li>
            ))}
          </ul>
        </section>
      )}

      <button onClick={handleWithdraw} disabled={withdrawn}>
        Withdraw subject
      </button>
    </div>
  );
}

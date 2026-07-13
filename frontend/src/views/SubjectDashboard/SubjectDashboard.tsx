import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import {
  completeTask,
  completeVisit,
  expediteVisit,
  getSchedule,
  performVisit,
  promoteVisit,
  recordMilestone,
  respondToAppointment,
  scheduleVisit,
  withdrawSubject,
} from "../../api/client";
import type { NextStep, Schedule } from "../../api/types";
import Milestones from "./Milestones";
import Timeline from "./Timeline";
import VisitActivities from "./VisitActivities";
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
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    if (!subjectId) {
      return;
    }
    getSchedule(subjectId)
      .then((result) => {
        setSchedule(result);
        setError(null);
      })
      .catch(() => setError("Could not load this subject's schedule."));
  }, [subjectId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleComplete(actionId: string) {
    if (!subjectId) {
      return;
    }
    setBusy(true);
    try {
      const result = await completeVisit(subjectId, actionId, null);
      setError(null);
      if (result.ambiguous) {
        setPendingChoice({ actionId, options: result.nextSteps });
      } else {
        setPendingChoice(null);
        setSchedule(result);
      }
    } catch {
      setError("Could not mark this visit complete.");
    } finally {
      setBusy(false);
    }
  }

  async function handleChoice(targetActionId: string) {
    if (!subjectId || !pendingChoice) {
      return;
    }
    setBusy(true);
    try {
      const result = await completeVisit(subjectId, pendingChoice.actionId, targetActionId);
      setError(null);
      setPendingChoice(null);
      setSchedule(result);
    } catch {
      setError("Could not schedule the chosen next visit.");
    } finally {
      setBusy(false);
    }
  }

  async function runGate(action: () => Promise<Schedule>, failure: string) {
    setBusy(true);
    try {
      setSchedule(await action());
      setError(null);
    } catch {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  async function handleRecordMilestone(
    milestone: string,
    date: string | null,
    display: string | null,
  ) {
    if (!subjectId) {
      return;
    }
    setBusy(true);
    try {
      const result = await recordMilestone(subjectId, milestone, date, display);
      setSchedule((current) => (current ? { ...current, milestones: result.milestones } : current));
      setError(null);
    } catch {
      setError("Could not record the milestone.");
    } finally {
      setBusy(false);
    }
  }

  async function handleWithdraw() {
    if (!subjectId) {
      return;
    }
    setBusy(true);
    try {
      await withdrawSubject(subjectId);
      setError(null);
      setWithdrawn(true);
      refresh();
    } catch {
      setError("Could not withdraw this subject.");
    } finally {
      setBusy(false);
    }
  }

  if (!schedule) {
    return error ? (
      <p role="alert" className="alert">
        {error}
      </p>
    ) : (
      <p className="status-note">Loading schedule…</p>
    );
  }

  return (
    <div>
      <h2 className="page-title">
        Subject <span className="meta">{subjectId}</span>{" "}
        {schedule.subjectStatus && (
          <span
            className={
              schedule.subjectStatus === "active" ? "badge badge-success" : "badge"
            }
          >
            {schedule.subjectStatus}
          </span>
        )}{" "}
        {schedule.subjectState && <span className="badge">{schedule.subjectState}</span>}
      </h2>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {withdrawn && (
        <p role="status" className="status-note">
          Subject withdrawn from study.
        </p>
      )}

      <div className="dashboard-grid">
        <div className="dashboard-rail">
          <Timeline
            completed={schedule.completed}
            current={schedule.current}
            nextSteps={schedule.nextSteps}
            titles={schedule.titles}
          />
          <Milestones
            milestones={schedule.milestones ?? []}
            busy={busy}
            onRecord={handleRecordMilestone}
          />
        </div>

        <div>
          <section aria-label="Current visits">
            <h2 className="section-title">Current</h2>
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {schedule.current.map((actionId) => (
                <VisitCard
                  key={actionId}
                  actionId={actionId}
                  title={schedule.titles?.[actionId]}
                  detail={schedule.visits[actionId]}
                  busy={busy}
                  subjectId={subjectId}
                  studyId={schedule.studyId}
                  planDefinitionId={schedule.planDefinitionId}
                  onPlan={() => runGate(() => promoteVisit(subjectId!, actionId, "plan"), "Could not accept the proposal.")}
                  onOrder={() => runGate(() => promoteVisit(subjectId!, actionId, "order"), "Could not authorize the visit.")}
                  onSchedule={() => runGate(() => scheduleVisit(subjectId!, actionId), "Could not schedule the visit.")}
                  onExpedite={() =>
                    runGate(() => expediteVisit(subjectId!, actionId), "Could not fast-forward this visit.")
                  }
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
                >
                  <VisitActivities subjectId={subjectId!} actionId={actionId} />
                </VisitCard>
              ))}
            </ul>
          </section>

          {pendingChoice && (
            <section aria-label="Decision needed" className="banner-decision">
              <h2>Decision needed</h2>
              <p>More than one next step is valid. Choose which one to schedule:</p>
              <ul>
                {pendingChoice.options.map((option) => (
                  <li key={option.actionId}>
                    <button className="btn-choice" onClick={() => handleChoice(option.actionId)}>
                      {option.title}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {!pendingChoice && schedule.nextSteps.length > 0 && (
            <section aria-label="Next steps">
              <h2 className="section-title">Next steps</h2>
              <ul className="chip-list">
                {schedule.nextSteps.map((step) => (
                  <li key={step.actionId} className="chip">
                    {step.title}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <button className="btn-danger-quiet" onClick={handleWithdraw} disabled={withdrawn || busy}>
        Withdraw subject
          </button>
        </div>
      </div>
    </div>
  );
}

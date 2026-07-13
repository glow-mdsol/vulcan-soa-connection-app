import { useEffect, useState } from "react";

import { listVisitActivities } from "../../api/client";
import type { ActivityObservation, VisitActivity } from "../../api/types";

function ObservationItems({ observations }: { observations: ActivityObservation[] }) {
  return (
    <>
      {observations.map((observation) => (
        <li key={observation.id}>
          {observation.display}
          {observation.members.length > 0 && (
            <ul className="observation-list">
              <ObservationItems observations={observation.members} />
            </ul>
          )}
        </li>
      ))}
    </>
  );
}

interface VisitActivitiesProps {
  subjectId: string;
  actionId: string;
}

export default function VisitActivities({ subjectId, actionId }: VisitActivitiesProps) {
  const [activities, setActivities] = useState<VisitActivity[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let active = true;

    listVisitActivities(subjectId, actionId)
      .then((result) => {
        if (active) {
          setActivities(result ?? []);
        }
      })
      .catch(() => {
        // Planned activities are supplementary; keep the visit card usable if they fail.
      });

    return () => {
      active = false;
    };
  }, [subjectId, actionId]);

  if (activities.length === 0) {
    return null;
  }

  return (
    <section aria-label={`Planned activities for ${actionId}`}>
      <p className="section-title">Planned activities</p>
      <ul className="activity-list">
        {activities.map((activity) => (
          <li key={activity.id}>
            <div className="activity-row">
              <span className="activity-title">{activity.title}</span>
              <span className="badge">{activity.type}</span>
              {activity.observations.length > 0 && (
                <button
                  type="button"
                  className="btn-secondary"
                  aria-expanded={!!expanded[activity.id]}
                  onClick={() =>
                    setExpanded((current) => ({
                      ...current,
                      [activity.id]: !current[activity.id],
                    }))
                  }
                >
                  {expanded[activity.id]
                    ? "Hide observations"
                    : `Show observations (${activity.observations.length})`}
                </button>
              )}
            </div>
            {expanded[activity.id] && (
              <ul
                className="observation-list"
                aria-label={`Expected observations for ${activity.title}`}
              >
                <ObservationItems observations={activity.observations} />
              </ul>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

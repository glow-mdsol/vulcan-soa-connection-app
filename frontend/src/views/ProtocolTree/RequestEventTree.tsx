import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getRequestEventTree } from "../../api/client";
import type { RequestEventTreeNode } from "../../api/types";
import { EVENT_RESOURCE_STYLES, EVENT_TYPE_ORDER } from "./eventResourceStyles";
import TreeDiagram from "./TreeDiagram";

export default function RequestEventTree() {
  const { subjectId } = useParams<{ subjectId: string }>();

  const [tree, setTree] = useState<RequestEventTreeNode | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!subjectId) {
      return;
    }
    let active = true;

    getRequestEventTree(subjectId)
      .then((result) => {
        if (active) {
          setTree(result);
          setError(null);
        }
      })
      .catch(() => {
        if (active) {
          setError("Could not load the request/event diagram for this subject.");
        }
      });

    return () => {
      active = false;
    };
  }, [subjectId]);

  if (error) {
    return (
      <p role="alert" className="alert">
        {error}
      </p>
    );
  }

  if (!tree) {
    return <p className="status-note">Loading request/event diagram…</p>;
  }

  if (tree.children.length === 0) {
    return (
      <p className="status-note">
        Nothing has been materialized for this subject yet — no requests, appointments, or tasks
        exist so far.
      </p>
    );
  }

  return (
    <TreeDiagram
      tree={tree}
      typeOrder={EVENT_TYPE_ORDER}
      styles={EVENT_RESOURCE_STYLES}
      heading="Request / event diagram"
      downloadFileName={`request-event-tree-${subjectId ?? "subject"}`}
    />
  );
}

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { getProtocolTree } from "../../api/client";
import type { ProtocolTreeNode } from "../../api/types";
import { DEFINITION_RESOURCE_STYLES, DEFINITION_TYPE_ORDER } from "./definitionResourceStyles";
import TreeDiagram from "./TreeDiagram";

export default function DefinitionTree() {
  const { studyId } = useParams<{ studyId: string }>();
  const [searchParams] = useSearchParams();
  const planDefinitionId = searchParams.get("plan");

  const [tree, setTree] = useState<ProtocolTreeNode | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!studyId) {
      return;
    }
    let active = true;

    getProtocolTree(studyId, planDefinitionId)
      .then((result) => {
        if (active) {
          setTree(result);
          setError(null);
        }
      })
      .catch(() => {
        if (active) {
          setError("Could not load the workflow diagram for this study.");
        }
      });

    return () => {
      active = false;
    };
  }, [studyId, planDefinitionId]);

  if (error) {
    return (
      <p role="alert" className="alert">
        {error}
      </p>
    );
  }

  if (!tree) {
    return <p className="status-note">Loading workflow diagram…</p>;
  }

  return (
    <TreeDiagram
      tree={tree}
      typeOrder={DEFINITION_TYPE_ORDER}
      styles={DEFINITION_RESOURCE_STYLES}
      heading="Definition diagram"
      downloadFileName={`protocol-tree-${studyId ?? "study"}`}
    />
  );
}

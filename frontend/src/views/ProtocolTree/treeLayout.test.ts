import { describe, expect, it } from "vitest";

import type { ProtocolTreeNode } from "../../api/types";
import { NODE_HEIGHT, NODE_WIDTH, computeTreeLayout } from "./treeLayout";

function node(
  id: string,
  type: ProtocolTreeNode["type"],
  children: ProtocolTreeNode[] = [],
): ProtocolTreeNode {
  return { id, type, label: id, children };
}

describe("computeTreeLayout", () => {
  it("places a single leaf node inset by the margin", () => {
    const tree = node("study-1", "ResearchStudy");

    const layout = computeTreeLayout(tree);

    expect(layout.nodes).toHaveLength(1);
    expect(layout.edges).toHaveLength(0);
    expect(layout.nodes[0].y).toBeGreaterThan(0);
    expect(layout.width).toBeGreaterThan(NODE_WIDTH);
    expect(layout.height).toBeGreaterThan(NODE_HEIGHT);
  });

  it("centers a parent above its children and draws one edge per child", () => {
    const tree = node("plan-1", "PlanDefinition", [
      node("visit-1", "PlanDefinition"),
      node("visit-2", "PlanDefinition"),
    ]);

    const layout = computeTreeLayout(tree);

    expect(layout.nodes).toHaveLength(3);
    expect(layout.edges).toHaveLength(2);

    const parent = layout.nodes.find((n) => n.id === "plan-1")!;
    const [child1, child2] = layout.nodes.filter((n) => n.id !== "plan-1");
    expect(parent.x).toBeCloseTo((child1.x + child2.x) / 2);
    // A visit action deeper in the tree sits at a greater y (top-down layout).
    expect(child1.y).toBeGreaterThan(parent.y);
  });

  it("assigns distinct layout keys to repeated resource ids at different tree positions", () => {
    // e.g. the same ActivityDefinition ("Vital Signs") planned at two different visits.
    const tree = node("study-1", "ResearchStudy", [
      node("visit-1", "PlanDefinition", [node("act-vitals", "ActivityDefinition")]),
      node("visit-2", "PlanDefinition", [node("act-vitals", "ActivityDefinition")]),
    ]);

    const layout = computeTreeLayout(tree);

    const vitalsNodes = layout.nodes.filter((n) => n.id === "act-vitals");
    expect(vitalsNodes).toHaveLength(2);
    expect(vitalsNodes[0].key).not.toBe(vitalsNodes[1].key);
    expect(vitalsNodes[0].x).not.toBe(vitalsNodes[1].x);
  });

  it("does not overlap sibling leaf nodes horizontally", () => {
    const tree = node("plan-1", "PlanDefinition", [
      node("visit-1", "PlanDefinition"),
      node("visit-2", "PlanDefinition"),
      node("visit-3", "PlanDefinition"),
    ]);

    const layout = computeTreeLayout(tree);
    const leaves = layout.nodes.filter((n) => n.id !== "plan-1").sort((a, b) => a.x - b.x);

    for (let i = 1; i < leaves.length; i++) {
      expect(leaves[i].x - leaves[i - 1].x).toBeGreaterThanOrEqual(NODE_WIDTH);
    }
  });
});

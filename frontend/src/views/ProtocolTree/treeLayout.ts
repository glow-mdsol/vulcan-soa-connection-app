import type { WorkflowTreeNode } from "../../api/types";

export const NODE_WIDTH = 176;
export const NODE_HEIGHT = 52;
const SLOT_GAP = 28;
const LEVEL_HEIGHT = 108;
const MARGIN = 32;

export interface PositionedNode<TType extends string = string> {
  key: string;
  id: string;
  type: TType;
  label: string;
  depth: number;
  x: number;
  y: number;
}

export interface TreeEdge {
  key: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface TreeLayout<TType extends string = string> {
  nodes: PositionedNode<TType>[];
  edges: TreeEdge[];
  width: number;
  height: number;
}

// A resource id (e.g. a shared ActivityDefinition like "Vital Signs", or a
// shared Encounter under two Tasks) can recur at many points in the tree, so
// layout identity uses a path-based key, not id.
export function computeTreeLayout<TType extends string>(
  root: WorkflowTreeNode<TType>,
): TreeLayout<TType> {
  const nodes: PositionedNode<TType>[] = [];
  const edges: TreeEdge[] = [];
  let cursor = 0;

  function place(node: WorkflowTreeNode<TType>, depth: number, key: string): number {
    const y = MARGIN + depth * LEVEL_HEIGHT;

    if (node.children.length === 0) {
      const left = cursor;
      cursor += NODE_WIDTH + SLOT_GAP;
      const x = left + NODE_WIDTH / 2;
      nodes.push({ key, id: node.id, type: node.type, label: node.label, depth, x, y });
      return x;
    }

    const childCenters = node.children.map((childNode, index) =>
      place(childNode, depth + 1, `${key}.${index}`),
    );
    const x = (childCenters[0] + childCenters[childCenters.length - 1]) / 2;
    nodes.push({ key, id: node.id, type: node.type, label: node.label, depth, x, y });

    node.children.forEach((_child, index) => {
      edges.push({
        key: `${key}.${index}-edge`,
        x1: x,
        y1: y + NODE_HEIGHT,
        x2: childCenters[index],
        y2: y + LEVEL_HEIGHT,
      });
    });

    return x;
  }

  place(root, 0, "0");

  const maxDepth = Math.max(...nodes.map((node) => node.depth));
  const width = Math.max(cursor - SLOT_GAP, NODE_WIDTH) + MARGIN * 2;
  const height = MARGIN + (maxDepth + 1) * LEVEL_HEIGHT + MARGIN;

  // Layout is built against a 0-based cursor; shift everything right by the margin.
  return {
    nodes: nodes.map((node) => ({ ...node, x: node.x + MARGIN })),
    edges: edges.map((edge) => ({
      ...edge,
      x1: edge.x1 + MARGIN,
      x2: edge.x2 + MARGIN,
    })),
    width,
    height,
  };
}

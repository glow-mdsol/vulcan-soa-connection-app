import { useMemo, useRef } from "react";

import type { WorkflowTreeNode } from "../../api/types";
import { NODE_HEIGHT, NODE_WIDTH, computeTreeLayout } from "./treeLayout";
import { wrapLabel } from "./wrapLabel";

export interface ResourceTypeStyle {
  label: string;
  stroke: string;
  fill: string;
}

function collectTypesInOrder<TType extends string>(
  node: WorkflowTreeNode<TType>,
  found: Set<TType>,
) {
  found.add(node.type);
  node.children.forEach((child) => collectTypesInOrder(child, found));
}

function TextOutline<TType extends string>({
  node,
  styles,
}: {
  node: WorkflowTreeNode<TType>;
  styles: Record<TType, ResourceTypeStyle>;
}) {
  return (
    <li>
      {node.label} ({styles[node.type].label})
      {node.children.length > 0 && (
        <ul>
          {node.children.map((child, index) => (
            <TextOutline key={`${child.id}-${index}`} node={child} styles={styles} />
          ))}
        </ul>
      )}
    </li>
  );
}

interface TreeDiagramProps<TType extends string> {
  tree: WorkflowTreeNode<TType>;
  typeOrder: TType[];
  styles: Record<TType, ResourceTypeStyle>;
  heading: string;
  downloadFileName: string;
}

// Shared renderer for both workflow diagrams (static definition tree and the
// instance-level request/event tree) — layout, colouring by resource type,
// legend, print/export chrome, and an accessible text fallback are identical;
// only the fetched tree, its type domain, and the colour map differ per caller.
export default function TreeDiagram<TType extends string>({
  tree,
  typeOrder,
  styles,
  heading,
  downloadFileName,
}: TreeDiagramProps<TType>) {
  const svgRef = useRef<SVGSVGElement>(null);
  const layout = useMemo(() => computeTreeLayout(tree), [tree]);

  const presentTypes = useMemo(() => {
    const found = new Set<TType>();
    collectTypesInOrder(tree, found);
    return typeOrder.filter((type) => found.has(type));
  }, [tree, typeOrder]);

  function handlePrint() {
    window.print();
  }

  function handleDownloadSvg() {
    const svg = svgRef.current;
    if (!svg) {
      return;
    }
    const serialized = new XMLSerializer().serializeToString(svg);
    const blob = new Blob([`<?xml version="1.0" encoding="UTF-8"?>\n${serialized}`], {
      type: "image/svg+xml;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${downloadFileName}.svg`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="protocol-tree-page">
      <div className="protocol-tree-toolbar no-print">
        <h2 className="page-title">{heading}</h2>
        <div className="btn-row">
          <button type="button" className="btn-secondary" onClick={handlePrint}>
            Print
          </button>
          <button type="button" className="btn-secondary" onClick={handleDownloadSvg}>
            Download SVG
          </button>
        </div>
      </div>

      <div className="protocol-tree-canvas">
        <div className="protocol-tree-scroll">
          <svg
            ref={svgRef}
            role="img"
            aria-label={`${heading} for ${tree.label}`}
            width={layout.width}
            height={layout.height}
            viewBox={`0 0 ${layout.width} ${layout.height}`}
          >
            <rect x={0} y={0} width={layout.width} height={layout.height} fill="#ffffff" />
            {layout.edges.map((edge) => (
              <path
                key={edge.key}
                d={`M ${edge.x1} ${edge.y1} C ${edge.x1} ${(edge.y1 + edge.y2) / 2}, ${edge.x2} ${(edge.y1 + edge.y2) / 2}, ${edge.x2} ${edge.y2}`}
                fill="none"
                stroke="#b7c2cc"
                strokeWidth={1.5}
              />
            ))}
            {layout.nodes.map((node) => {
              const style = styles[node.type];
              const lines = wrapLabel(node.label);
              const textStartY = node.y + NODE_HEIGHT / 2 - ((lines.length - 1) * 13) / 2;
              return (
                <g key={node.key}>
                  <title>{`${node.label} — ${style.label} (${node.id})`}</title>
                  <rect
                    x={node.x - NODE_WIDTH / 2}
                    y={node.y}
                    width={NODE_WIDTH}
                    height={NODE_HEIGHT}
                    rx={10}
                    fill={style.fill}
                    stroke={style.stroke}
                    strokeWidth={2}
                  />
                  <text x={node.x} y={textStartY} textAnchor="middle" className="protocol-tree-label">
                    {lines.map((line, index) => (
                      <tspan key={index} x={node.x} dy={index === 0 ? 0 : 13}>
                        {line}
                      </tspan>
                    ))}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      </div>

      <ul className="protocol-tree-legend" aria-label="Legend">
        {presentTypes.map((type) => (
          <li key={type}>
            <span
              className="protocol-tree-swatch"
              style={{ background: styles[type].fill, borderColor: styles[type].stroke }}
              aria-hidden="true"
            />
            {styles[type].label}
          </li>
        ))}
      </ul>

      <ul className="sr-only" aria-label="Text outline">
        <TextOutline node={tree} styles={styles} />
      </ul>
    </div>
  );
}

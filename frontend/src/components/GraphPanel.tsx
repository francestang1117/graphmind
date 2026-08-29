import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { House, Minus, Plus, RefreshCcw } from "lucide-react";
import { useGraph } from "../hooks/useGraph";
import { useAppStore } from "../stores/appStore";
import type { GraphEdge, GraphNode } from "../services/api";

const colors: Record<string, string> = {
  CONCEPT: "#8b5cf6",
  FRAMEWORK: "#3b82f6",
  LIBRARY: "#38bdf8",
  ORGANIZATION: "#f97316",
  PRODUCT: "#ec4899",
  LANGUAGE: "#10b981",
  PROGRAMMING_LANGUAGE: "#10b981",
  DOCUMENT: "#f59e0b",
  PERSON: "#ef4444",
  DEPENDENCY: "#38bdf8",
  FUNCTION: "#a78bfa",
  CLASS: "#fb7185",
};

const typeLabels: Record<string, string> = {
  CONCEPT: "Concept",
  FRAMEWORK: "Framework",
  LIBRARY: "Library",
  ORGANIZATION: "Organization",
  PRODUCT: "Product",
  LANGUAGE: "Language",
  PROGRAMMING_LANGUAGE: "Language",
  DOCUMENT: "Document",
  PERSON: "Person",
  DEPENDENCY: "Dependency",
  FUNCTION: "Function",
  CLASS: "Class",
};

// Keep these out of the main view for now; they make the graph noisy fast.
const weakRelations = new Set(["RELATED_TO", "ASSOCIATED_WITH", "REFERENCES"]);

// Labels are only worth showing when the relation says something specific.
const labeledRelations = new Set(["USES", "USED_BY", "WRITTEN_IN", "HAS_FRAMEWORK", "HAS_LIBRARY", "INTEGRATES_WITH"]);

interface SimNode extends GraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
}

interface ViewState {
  scale: number;
  x: number;
  y: number;
}

interface SimulationState {
  alpha: number;
  stableFrames: number;
}

interface RelationRow {
  label: string;
  relation: string;
  direction: "in" | "out";
  type: string;
  weak: boolean;
  weight: number;
}

export default function GraphPanel() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<number>(0);
  const simRef = useRef<SimNode[]>([]);
  const simulationRef = useRef<SimulationState>({ alpha: 1, stableFrames: 0 });
  const dragRef = useRef<{ node: SimNode; dx: number; dy: number } | null>(null);
  const panRef = useRef<{ sx: number; sy: number; x: number; y: number } | null>(null);
  const { nodes, edges, stats, loading, refreshing, error, refetch } = useGraph();
  const setGraphStats = useAppStore((state) => state.setGraphStats);
  const [selected, setSelected] = useState<SimNode | null>(null);
  const [hovered, setHovered] = useState<SimNode | null>(null);
  const [showSources, setShowSources] = useState(false);
  const [view, setView] = useState<ViewState>({ scale: 1, x: 0, y: 0 });
  const viewRef = useRef(view);

  useEffect(() => {
    viewRef.current = view;
  }, [view]);

  useEffect(() => {
    setGraphStats(stats);
  }, [setGraphStats, stats]);

  const displayNodes = useMemo(() => {
    if (showSources) return nodes;

    // Default to the actual knowledge nodes; files can come back in Sources.
    const entityNodes = nodes.filter((node) => node.type !== "DOCUMENT");
    const entityNodeIds = new Set(entityNodes.map((node) => node.id));
    const strongEntityIds = new Set<string>();
    edges.forEach((edge) => {
      if (!entityNodeIds.has(edge.source) || !entityNodeIds.has(edge.target)) return;
      if (isWeakEdge(edge)) return;
      strongEntityIds.add(edge.source);
      strongEntityIds.add(edge.target);
    });

    // Keep a few big nodes even if their current edges are weak.
    const focusedNodes = entityNodes.filter((node) => strongEntityIds.has(node.id) || (node.size ?? 0) >= 14);
    return focusedNodes.length >= 6 ? focusedNodes : entityNodes;
  }, [edges, nodes, showSources]);

  const displayNodeIds = useMemo(() => new Set(displayNodes.map((node) => node.id)), [displayNodes]);
  const sourceNodeCount = useMemo(
    () => nodes.filter((node) => node.type === "DOCUMENT").length,
    [nodes],
  );

  const displayEdges = useMemo(() => {
    return edges.filter((edge) => {
      if (!displayNodeIds.has(edge.source) || !displayNodeIds.has(edge.target)) return false;
      if (!showSources && isSourceEdge(edge)) return false;
      return true;
    });
  }, [displayNodeIds, edges, showSources]);

  const resetLayout = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const width = canvas.clientWidth || 900;
    const height = canvas.clientHeight || 600;
    const radiusX = width * (displayNodes.length <= 12 ? 0.28 : 0.35);
    const radiusY = height * (displayNodes.length <= 12 ? 0.26 : 0.32);
    simRef.current = displayNodes.map((node, index) => {
      const angle = index * 2.399963229728653;
      const ring = 0.58 + (index % 4) * 0.12;
      return {
        ...node,
        x: width / 2 + Math.cos(angle) * radiusX * ring,
        y: height / 2 + Math.sin(angle) * radiusY * ring,
        vx: 0,
        vy: 0,
        r: node.type === "DOCUMENT" ? Math.max(6, Math.min(10, node.size || 8)) : Math.max(7, Math.min(18, node.size || 8)),
      };
    });
    simulationRef.current = { alpha: 1, stableFrames: 0 };
  }, [displayNodes]);

  useEffect(() => {
    resetLayout();
  }, [resetLayout]);

  const activeSelected = selected && displayNodeIds.has(selected.id) ? selected : null;
  const activeHovered = hovered && displayNodeIds.has(hovered.id) ? hovered : null;

  const strongEdges = useMemo(() => displayEdges.filter((edge) => !isWeakEdge(edge)), [displayEdges]);
  const sourceViewEdges = useMemo(
    // In Sources mode, file links can shape the layout. Weak entity links cannot.
    () => displayEdges.filter((edge) => isSourceEdge(edge) || !isWeakEdge(edge)),
    [displayEdges],
  );

  const typeCounts = useMemo(() => {
    return displayNodes.reduce<Record<string, number>>((acc, node) => {
      acc[node.type] = (acc[node.type] ?? 0) + 1;
      return acc;
    }, {});
  }, [displayNodes]);

  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const selectedDetail = useMemo(() => {
    if (!activeSelected) return null;

    const relationRows: RelationRow[] = [];
    const sourceNames = new Set<string>();

    edges.forEach((edge) => {
      const outgoing = edge.source === activeSelected.id;
      const incoming = edge.target === activeSelected.id;
      if (!outgoing && !incoming) return;

      const other = nodeById.get(outgoing ? edge.target : edge.source);
      if (!other) return;

      if (other.type === "DOCUMENT" || isSourceEdge(edge)) {
        sourceNames.add(other.label);
        return;
      }

      relationRows.push({
        label: other.label,
        relation: formatRelation(edge.type ?? "RELATED_TO"),
        direction: outgoing ? "out" : "in",
        type: other.type,
        weak: isWeakEdge(edge),
        weight: edge.weight ?? 1,
      });
    });

    const strongRows = relationRows
      .filter((row) => !row.weak)
      .sort((left, right) => right.weight - left.weight)
      .slice(0, 8);
    const weakCount = relationRows.length - strongRows.length;

    return {
      strongRows,
      weakCount,
      sources: [...sourceNames].sort().slice(0, 6),
      totalConnections: relationRows.length + sourceNames.size,
    };
  }, [activeSelected, edges, nodeById]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const render = () => {
      // The graph rules are still moving, so keep the renderer easy to tune.
      const dpr = window.devicePixelRatio || 1;
      const width = canvas.clientWidth || 900;
      const height = canvas.clientHeight || 600;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);

      const { scale, x: panX, y: panY } = viewRef.current;
      const idMap = new Map(simRef.current.map((node) => [node.id, node]));
      const focus = activeHovered ?? activeSelected;
      const renderEdges = focus
        ? displayEdges.filter((edge) => isSourceEdge(edge) || !isWeakEdge(edge) || edge.source === focus.id || edge.target === focus.id)
        : showSources
          ? sourceViewEdges
          : strongEdges;

      const simulation = simulationRef.current;
      if (simulation.alpha > 0) {
        const alpha = simulation.alpha;
        simRef.current.forEach((node) => {
          simRef.current.forEach((other) => {
            if (node.id === other.id) return;
            const dx = node.x - other.x;
            const dy = node.y - other.y;
            const distance = Math.hypot(dx, dy) || 1;
            const minDistance = node.r + other.r + 68;
            const force = (3600 / (distance * distance)) * alpha;
            node.vx += (dx / distance) * force * 0.42;
            node.vy += (dy / distance) * force * 0.42;
            if (distance < minDistance) {
              const push = (minDistance - distance) * 0.028 * alpha;
              node.vx += (dx / distance) * push;
              node.vy += (dy / distance) * push;
            }
          });
          node.vx += (width / 2 - node.x) * 0.0008 * alpha;
          node.vy += (height / 2 - node.y) * 0.0008 * alpha;
        });

        const layoutEdges = showSources ? sourceViewEdges : strongEdges;
        layoutEdges.forEach((edge) => {
          const source = idMap.get(edge.source);
          const target = idMap.get(edge.target);
          if (!source || !target) return;
          const dx = target.x - source.x;
          const dy = target.y - source.y;
          const distance = Math.hypot(dx, dy) || 1;
          const ideal = isSourceEdge(edge) ? 230 : 170;
          const force = (distance - ideal) * (isSourceEdge(edge) ? 0.012 : 0.034) * alpha;
          source.vx += (dx / distance) * force;
          source.vy += (dy / distance) * force;
          target.vx -= (dx / distance) * force;
          target.vy -= (dy / distance) * force;
        });

        let maxSpeed = 0;
        simRef.current.forEach((node) => {
          if (dragRef.current?.node === node) return;
          node.vx *= 0.84;
          node.vy *= 0.84;
          maxSpeed = Math.max(maxSpeed, Math.hypot(node.vx, node.vy));
          node.x = Math.max(node.r + 20, Math.min(width - node.r - 20, node.x + node.vx));
          node.y = Math.max(node.r + 20, Math.min(height - node.r - 20, node.y + node.vy));
        });

        simulation.stableFrames = maxSpeed < 0.04 ? simulation.stableFrames + 1 : 0;
        simulation.alpha *= 0.965;
        if (simulation.alpha < 0.015 || simulation.stableFrames >= 18) {
          simulation.alpha = 0;
          simRef.current.forEach((node) => {
            node.vx = 0;
            node.vy = 0;
          });
        }
      }

      const connected = focus
        ? new Set(
            renderEdges
              .filter((edge) => edge.source === focus.id || edge.target === focus.id)
              .flatMap((edge) => [edge.source, edge.target]),
          )
        : null;
      const toScreen = (node: SimNode) => ({
        x: (node.x + panX) * scale,
        y: (node.y + panY) * scale,
      });

      // If labels collide, skip the later one. A missing label is better than a messy one.
      const relationLabelBoxes: Array<{ x: number; y: number; width: number; height: number }> = [];

      renderEdges.forEach((edge) => {
        const source = idMap.get(edge.source);
        const target = idMap.get(edge.target);
        if (!source || !target) return;
        const active = !connected || (connected.has(edge.source) && connected.has(edge.target));
        const sourcePoint = toScreen(source);
        const targetPoint = toScreen(target);
        ctx.beginPath();
        ctx.moveTo(sourcePoint.x, sourcePoint.y);
        ctx.lineTo(targetPoint.x, targetPoint.y);
        const weak = isWeakEdge(edge);
        const edgeWidth = relationStrokeWidth(edge, weak);
        ctx.strokeStyle = active
          ? weak
            ? "rgba(167,139,250,.18)"
            : `rgba(255,255,255,${Math.min(0.5, 0.2 + edgeWidth * 0.07)})`
          : "rgba(255,255,255,.05)";
        ctx.lineWidth = active ? edgeWidth : 0.7;
        ctx.stroke();
        if (focus && active && edge.type && scale > 0.65 && shouldDrawRelationLabel(edge)) {
          ctx.font = "600 10px Inter, system-ui";
          const label = `${formatRelation(edge.type)}${(edge.weight ?? 1) > 1 ? ` ×${edge.weight}` : ""}`;
          const labelX = (sourcePoint.x + targetPoint.x) / 2;
          const labelY = (sourcePoint.y + targetPoint.y) / 2 - 5;
          const labelWidth = ctx.measureText(label).width;
          const labelBox = { x: labelX - labelWidth / 2, y: labelY - 10, width: labelWidth, height: 14 };
          const overlaps = relationLabelBoxes.some((box) => boxesOverlap(box, labelBox));
          if (overlaps) return;
          relationLabelBoxes.push(labelBox);
          ctx.fillStyle = "rgba(167,139,250,.88)";
          ctx.textAlign = "center";
          ctx.fillText(label, labelX, labelY);
        }
      });

      const labelBoxes: Array<{ x: number; y: number; width: number; height: number }> = [];

      simRef.current.forEach((node) => {
        const color = colors[node.type] ?? "#a1a1aa";
        const point = toScreen(node);
        const isSelected = focus?.id === node.id;
        const isConnected = connected?.has(node.id) ?? false;
        const muted = connected && !isSelected && !isConnected;
        const radius = node.r * scale * (isSelected ? 1.25 : 1);

        if (isSelected) {
          ctx.beginPath();
          ctx.arc(point.x, point.y, radius + 12, 0, Math.PI * 2);
          ctx.fillStyle = `${color}24`;
          ctx.fill();
        }
        ctx.beginPath();
        ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
        ctx.fillStyle = muted ? `${color}55` : color;
        ctx.fill();

        const shouldLabel =
          !muted &&
          (isSelected ||
            isConnected ||
            (node.type === "DOCUMENT" && showSources) ||
            node.size >= 12 ||
            simRef.current.length <= 28);

        if (shouldLabel) {
          const label = truncateLabel(node.label, isSelected || simRef.current.length <= 16 ? 28 : 20);
          ctx.font = `${isSelected ? 700 : 500} ${Math.max(10, Math.min(12, 11 * scale))}px Inter, system-ui`;
          const labelWidth = ctx.measureText(label).width;
          const labelHeight = 16;
          const labelBox = {
            x: point.x - labelWidth / 2,
            y: point.y + radius + 6,
            width: labelWidth,
            height: labelHeight,
          };
          const overlaps = labelBoxes.some((box) => boxesOverlap(box, labelBox));
          if (overlaps && !isSelected && !isConnected) return;
          labelBoxes.push(labelBox);
          ctx.fillStyle = "rgba(245,245,245,.82)";
          ctx.textAlign = "center";
          ctx.fillText(label, point.x, point.y + radius + 16);
        }
      });

      frameRef.current = requestAnimationFrame(render);
    };

    frameRef.current = requestAnimationFrame(render);
    return () => cancelAnimationFrame(frameRef.current);
  }, [activeHovered, activeSelected, displayEdges, showSources, sourceViewEdges, strongEdges]);

  const screenToWorld = (x: number, y: number) => {
    const { scale, x: panX, y: panY } = viewRef.current;
    return { x: x / scale - panX, y: y / scale - panY };
  };

  const findNodeAt = (x: number, y: number) => {
    const world = screenToWorld(x, y);
    return [...simRef.current]
      .reverse()
      .find((node) => Math.hypot(node.x - world.x, node.y - world.y) < node.r + 8);
  };

  const handlePointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const match = findNodeAt(x, y);
    event.currentTarget.setPointerCapture(event.pointerId);
    if (match) {
      const world = screenToWorld(x, y);
      dragRef.current = { node: match, dx: match.x - world.x, dy: match.y - world.y };
      setSelected(match);
    } else {
      panRef.current = { sx: event.clientX, sy: event.clientY, x: viewRef.current.x, y: viewRef.current.y };
      setSelected(null);
    }
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    if (dragRef.current) {
      const world = screenToWorld(x, y);
      dragRef.current.node.x = world.x + dragRef.current.dx;
      dragRef.current.node.y = world.y + dragRef.current.dy;
      dragRef.current.node.vx = 0;
      dragRef.current.node.vy = 0;
      return;
    }
    if (panRef.current) {
      const { scale } = viewRef.current;
      setView({
        scale,
        x: panRef.current.x + (event.clientX - panRef.current.sx) / scale,
        y: panRef.current.y + (event.clientY - panRef.current.sy) / scale,
      });
      return;
    }
    setHovered(findNodeAt(x, y) ?? null);
  };

  const handlePointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (dragRef.current) {
      simulationRef.current = { alpha: 0.28, stableFrames: 0 };
    }
    dragRef.current = null;
    panRef.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const handleWheel = (event: React.WheelEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const before = screenToWorld(event.clientX - rect.left, event.clientY - rect.top);
    const nextScale = clamp(viewRef.current.scale * (event.deltaY > 0 ? 0.9 : 1.1), 0.55, 2.4);
    setView({
      scale: nextScale,
      x: (event.clientX - rect.left) / nextScale - before.x,
      y: (event.clientY - rect.top) / nextScale - before.y,
    });
  };

  const handleRefresh = async () => {
    setSelected(null);
    await refetch();
    requestAnimationFrame(resetLayout);
  };

  const zoom = (factor: number) => {
    setView((current) => ({ ...current, scale: clamp(current.scale * factor, 0.55, 2.4) }));
  };

  const resetView = () => {
    setView({ scale: 1, x: 0, y: 0 });
    setSelected(null);
    setHovered(null);
  };

  const changeGraphMode = (sourcesVisible: boolean) => {
    setSelected(null);
    setHovered(null);
    setShowSources(sourcesVisible);
  };

  return (
    <div className="graph-panel">
      <div className="graph-canvas-wrap">
        {loading && <div className="graph-loading">Loading graph...</div>}
        {!loading && !displayNodes.length && (
          <div className="graph-empty">
            <strong>No graph yet</strong>
            <span>Upload and process a document to build nodes and relations.</span>
          </div>
        )}
        {!loading && error && (
          <div className="graph-empty graph-empty-error">
            <strong>Graph unavailable</strong>
            <span>Check that the backend is running, then refresh this view.</span>
          </div>
        )}
        <canvas
          ref={canvasRef}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          onWheel={handleWheel}
        />
        <div className="graph-controls">
          <button onClick={() => zoom(1.15)} aria-label="Zoom in" title="Zoom in"><Plus size={12} /></button>
          <button onClick={() => zoom(0.85)} aria-label="Zoom out" title="Zoom out"><Minus size={12} /></button>
          <button onClick={resetView} aria-label="Reset graph view" title="Reset view"><House size={12} /></button>
          <button onClick={handleRefresh} aria-label="Refresh graph" disabled={refreshing} title="Refresh graph data">
            <RefreshCcw className={refreshing ? "spin" : ""} size={12} />
          </button>
        </div>
        <div className="graph-caption">
          {displayNodes.length} shown nodes · {strongEdges.length} entity edges
          {!showSources ? ` · ${sourceNodeCount} sources hidden` : ""}
          {activeHovered ? ` · ${activeHovered.label}` : activeSelected ? ` · ${activeSelected.label}` : " · drag nodes, scroll to zoom"}
        </div>
        {activeHovered && <GraphTooltip node={activeHovered} edges={edges} />}
      </div>
      <aside className="graph-side">
        <div className="graph-view-card">
          <div className="section-heading">Graph view</div>
          <div className="graph-mode-toggle" role="group" aria-label="Graph view mode">
            <button className={!showSources ? "active" : ""} onClick={() => changeGraphMode(false)}>
              Entities
            </button>
            <button className={showSources ? "active" : ""} onClick={() => changeGraphMode(true)}>
              Sources
            </button>
          </div>
          <p>
            {showSources
              ? "Show the files behind the graph, with document links kept quieter than entity links."
              : "Hide file nodes for a cleaner look at concepts, tools, and stronger relations."}
          </p>
        </div>
        <div className="section-heading">Node types</div>
        <div className="legend-list">
          {Object.entries(typeCounts).map(([type, count]) => (
            <div className="legend-row" key={type}>
              <span style={{ background: colors[type] ?? "#a1a1aa" }} />
              <strong>{type.replaceAll("_", " ")}</strong>
              <em>{count}</em>
            </div>
          ))}
        </div>
        <div className="node-detail">
          <div className="section-heading">Selection</div>
          {activeSelected ? (
            <NodeDetail node={activeSelected} detail={selectedDetail} />
          ) : (
            <p>Select a node to focus its neighborhood.</p>
          )}
        </div>
      </aside>
    </div>
  );
}

function NodeDetail({
  node,
  detail,
}: {
  node: SimNode;
  detail: {
    strongRows: RelationRow[];
    weakCount: number;
    sources: string[];
    totalConnections: number;
  } | null;
}) {
  return (
    <div className="node-detail-body">
      <div className="node-detail-title">
        <span style={{ background: colors[node.type] ?? "#a1a1aa" }} />
        <strong>{node.label}</strong>
      </div>
      <div className="node-detail-meta">
        <span>{node.type.replaceAll("_", " ")}</span>
        <span>{node.connections ?? detail?.totalConnections ?? 0} connections</span>
        <span>{Math.round((node.importance ?? 0) * 100)}% importance</span>
      </div>

      <DetailSection title="Strong relations" empty="No strong relations yet.">
        {detail?.strongRows.map((row) => (
          <div className="relation-row" key={`${row.direction}-${row.relation}-${row.label}`}>
            <span>{row.direction === "out" ? "→" : "←"}</span>
            <div>
              <strong>{row.label}</strong>
              <em>{row.relation} · strength {row.weight}</em>
            </div>
          </div>
        ))}
      </DetailSection>

      <DetailSection title="Source files" empty="No source file edge visible.">
        {detail?.sources.map((source) => (
          <div className="source-row" key={source}>{truncateLabel(source, 30)}</div>
        ))}
      </DetailSection>

      {Boolean(detail?.weakCount) && (
        <p className="weak-note">{detail?.weakCount} weaker links hidden from the canvas.</p>
      )}
    </div>
  );
}

function DetailSection({
  title,
  empty,
  children,
}: {
  title: string;
  empty: string;
  children?: ReactNode;
}) {
  const hasChildren = Array.isArray(children) ? children.length > 0 : Boolean(children);
  return (
    <div className="detail-section">
      <span>{title}</span>
      {hasChildren ? children : <p>{empty}</p>}
    </div>
  );
}

function GraphTooltip({ node, edges }: { node: SimNode; edges: GraphEdge[] }) {
  const connections = edges.filter((edge) => edge.source === node.id || edge.target === node.id);
  return (
    <div className="graph-tooltip">
      <strong>{node.label}</strong>
      <span>{typeLabels[node.type] ?? node.type.replaceAll("_", " ")}</span>
      <em>{node.connections ?? connections.length} connections · {Math.round((node.importance ?? 0) * 100)}% importance</em>
    </div>
  );
}

function truncateLabel(text: string, max = 20) {
  if (text.length <= max) return text;
  const slice = text.slice(0, max).trimEnd();
  const lastSpace = slice.lastIndexOf(" ");
  if (lastSpace > max * 0.55) {
    return `${slice.slice(0, lastSpace)}…`;
  }
  return `${slice}…`;
}

function formatRelation(type: string) {
  return type.replaceAll("_", " ").toLowerCase();
}

function isWeakEdge(edge: GraphEdge) {
  if (isSourceEdge(edge)) return true;
  const repeated = (edge.weight ?? 1) >= 2;
  return (!repeated && weakRelations.has(edge.type ?? "")) || (!repeated && (edge.confidence ?? 1) < 0.7);
}

function isSourceEdge(edge: GraphEdge) {
  const relation = edge.type ?? "";
  return (
    edge.source.startsWith("doc_") ||
    edge.target.startsWith("doc_") ||
    ["CONTAINS", "DISCUSSES", "MENTIONS"].includes(relation)
  );
}

function relationStrokeWidth(edge: GraphEdge, weak: boolean) {
  const strength = Math.max(1, edge.weight ?? 1);
  const growth = Math.log2(strength + 1);
  return weak ? Math.min(1.2, 0.55 + growth * 0.2) : Math.min(3.2, 0.85 + growth * 0.75);
}

function shouldDrawRelationLabel(edge: GraphEdge) {
  return Boolean(edge.type && labeledRelations.has(edge.type));
}

function boxesOverlap(
  a: { x: number; y: number; width: number; height: number },
  b: { x: number; y: number; width: number; height: number },
) {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

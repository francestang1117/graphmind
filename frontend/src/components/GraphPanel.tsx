import { useEffect, useMemo, useRef, useState } from "react";
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

export default function GraphPanel() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<number>(0);
  const simRef = useRef<SimNode[]>([]);
  const dragRef = useRef<{ node: SimNode; dx: number; dy: number } | null>(null);
  const panRef = useRef<{ sx: number; sy: number; x: number; y: number } | null>(null);
  const { nodes, edges, stats, loading, refreshing, refetch } = useGraph();
  const setGraphStats = useAppStore((state) => state.setGraphStats);
  const [selected, setSelected] = useState<SimNode | null>(null);
  const [hovered, setHovered] = useState<SimNode | null>(null);
  const [view, setView] = useState<ViewState>({ scale: 1, x: 0, y: 0 });
  const viewRef = useRef(view);

  useEffect(() => {
    viewRef.current = view;
  }, [view]);

  useEffect(() => {
    setGraphStats(stats);
  }, [setGraphStats, stats]);

  useEffect(() => {
    resetLayout();
  }, [nodes]);

  const resetLayout = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const width = canvas.clientWidth || 900;
    const height = canvas.clientHeight || 600;
    simRef.current = nodes.map((node, index) => {
      const angle = (Math.PI * 2 * index) / Math.max(nodes.length, 1);
      return {
        ...node,
        x: width / 2 + Math.cos(angle) * width * 0.26,
        y: height / 2 + Math.sin(angle) * height * 0.26,
        vx: 0,
        vy: 0,
        r: 6 + Math.min(5, node.size || 1) * 1.8,
      };
    });
  };

  const typeCounts = useMemo(() => {
    return nodes.reduce<Record<string, number>>((acc, node) => {
      acc[node.type] = (acc[node.type] ?? 0) + 1;
      return acc;
    }, {});
  }, [nodes]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const render = () => {
      // The force layout is intentionally tiny; it keeps the graph readable without another dependency.
      const dpr = window.devicePixelRatio || 1;
      const width = canvas.clientWidth || 900;
      const height = canvas.clientHeight || 600;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);

      const { scale, x: panX, y: panY } = viewRef.current;
      const idMap = new Map(simRef.current.map((node) => [node.id, node]));
      const focus = hovered ?? selected;

      simRef.current.forEach((node) => {
        simRef.current.forEach((other) => {
          if (node.id === other.id) return;
          const dx = node.x - other.x;
          const dy = node.y - other.y;
          const distance = Math.hypot(dx, dy) || 1;
          const force = 2200 / (distance * distance);
          node.vx += (dx / distance) * force * 0.38;
          node.vy += (dy / distance) * force * 0.38;
        });
        node.vx += (width / 2 - node.x) * 0.0015;
        node.vy += (height / 2 - node.y) * 0.0015;
      });

      edges.forEach((edge) => {
        const source = idMap.get(edge.source);
        const target = idMap.get(edge.target);
        if (!source || !target) return;
        const dx = target.x - source.x;
        const dy = target.y - source.y;
        const distance = Math.hypot(dx, dy) || 1;
        const force = (distance - 145) * 0.045;
        source.vx += (dx / distance) * force;
        source.vy += (dy / distance) * force;
        target.vx -= (dx / distance) * force;
        target.vy -= (dy / distance) * force;
      });

      simRef.current.forEach((node) => {
        if (dragRef.current?.node === node) return;
        node.vx *= 0.84;
        node.vy *= 0.84;
        node.x = Math.max(node.r + 20, Math.min(width - node.r - 20, node.x + node.vx));
        node.y = Math.max(node.r + 20, Math.min(height - node.r - 20, node.y + node.vy));
      });

      const connected = focus
        ? new Set(
            edges
              .filter((edge) => edge.source === focus.id || edge.target === focus.id)
              .flatMap((edge) => [edge.source, edge.target]),
          )
        : null;
      const toScreen = (node: SimNode) => ({
        x: (node.x + panX) * scale,
        y: (node.y + panY) * scale,
      });

      edges.forEach((edge) => {
        const source = idMap.get(edge.source);
        const target = idMap.get(edge.target);
        if (!source || !target) return;
        const active = !connected || (connected.has(edge.source) && connected.has(edge.target));
        const sourcePoint = toScreen(source);
        const targetPoint = toScreen(target);
        ctx.beginPath();
        ctx.moveTo(sourcePoint.x, sourcePoint.y);
        ctx.lineTo(targetPoint.x, targetPoint.y);
        ctx.strokeStyle = active ? "rgba(255,255,255,.2)" : "rgba(255,255,255,.05)";
        ctx.lineWidth = active ? 1.5 : 0.8;
        ctx.stroke();
        if (focus && active && edge.type && scale > 0.65) {
          ctx.font = "600 10px Inter, system-ui";
          ctx.fillStyle = "rgba(167,139,250,.86)";
          ctx.textAlign = "center";
          ctx.fillText(edge.type.replaceAll("_", " ").toLowerCase(), (sourcePoint.x + targetPoint.x) / 2, (sourcePoint.y + targetPoint.y) / 2 - 5);
        }
      });

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
            node.type === "DOCUMENT" ||
            node.size >= 12 ||
            simRef.current.length <= 28);

        if (shouldLabel) {
          const label = fitLabel(ctx, node.label, isSelected ? 140 : 96);
          ctx.font = `${isSelected ? 700 : 500} ${Math.max(10, Math.min(12, 11 * scale))}px Inter, system-ui`;
          ctx.fillStyle = "rgba(245,245,245,.82)";
          ctx.textAlign = "center";
          ctx.fillText(label, point.x, point.y + radius + 16);
        }
      });

      frameRef.current = requestAnimationFrame(render);
    };

    frameRef.current = requestAnimationFrame(render);
    return () => cancelAnimationFrame(frameRef.current);
  }, [edges, selected, hovered]);

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

  return (
    <div className="graph-panel">
      <div className="graph-canvas-wrap">
        {loading && <div className="graph-loading">Loading graph...</div>}
        <canvas
          ref={canvasRef}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          onWheel={handleWheel}
        />
        <div className="graph-controls">
          <button onClick={() => zoom(1.15)} aria-label="Zoom in" title="Zoom in"><Plus size={15} /></button>
          <button onClick={() => zoom(0.85)} aria-label="Zoom out" title="Zoom out"><Minus size={15} /></button>
          <button onClick={resetView} aria-label="Reset graph view" title="Reset view"><House size={15} /></button>
          <button onClick={handleRefresh} aria-label="Refresh graph" disabled={refreshing} title="Refresh graph data">
            <RefreshCcw className={refreshing ? "spin" : ""} size={15} />
          </button>
        </div>
        <div className="graph-caption">
          {stats.total_nodes} nodes · {stats.total_edges} edges
          {hovered ? ` · ${hovered.label}` : selected ? ` · ${selected.label}` : " · drag nodes, scroll to zoom"}
        </div>
        {hovered && <GraphTooltip node={hovered} edges={edges} />}
      </div>
      <aside className="graph-side">
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
          {selected ? (
            <>
              <strong>{selected.label}</strong>
              <span>{selected.type.replaceAll("_", " ")}</span>
            </>
          ) : (
            <p>Select a node to focus its neighborhood.</p>
          )}
        </div>
      </aside>
    </div>
  );
}

function GraphTooltip({ node, edges }: { node: SimNode; edges: GraphEdge[] }) {
  const connections = edges.filter((edge) => edge.source === node.id || edge.target === node.id);
  return (
    <div className="graph-tooltip">
      <strong>{node.label}</strong>
      <span>{typeLabels[node.type] ?? node.type.replaceAll("_", " ")}</span>
      <em>{connections.length} connections</em>
    </div>
  );
}

function fitLabel(ctx: CanvasRenderingContext2D, text: string, maxWidth: number) {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let next = text;
  while (next.length > 4 && ctx.measureText(`${next}...`).width > maxWidth) {
    next = next.slice(0, -1);
  }
  return `${next}...`;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

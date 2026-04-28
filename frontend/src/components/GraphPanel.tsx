import { useEffect, useMemo, useRef, useState } from "react";
import { RefreshCcw } from "lucide-react";
import { useGraph } from "../hooks/useGraph";
import { useAppStore } from "../stores/appStore";
import type { GraphNode } from "../services/api";

const colors: Record<string, string> = {
  CONCEPT: "#8b5cf6",
  FRAMEWORK: "#3b82f6",
  LANGUAGE: "#10b981",
  PROGRAMMING_LANGUAGE: "#10b981",
  DOCUMENT: "#f59e0b",
  PERSON: "#ef4444",
};

interface SimNode extends GraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

export default function GraphPanel() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<number>(0);
  const simRef = useRef<SimNode[]>([]);
  const { nodes, edges, stats, loading, refetch } = useGraph();
  const setGraphStats = useAppStore((state) => state.setGraphStats);
  const [selected, setSelected] = useState<SimNode | null>(null);

  useEffect(() => {
    setGraphStats(stats);
  }, [setGraphStats, stats]);

  useEffect(() => {
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
      };
    });
  }, [nodes]);

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

      const idMap = new Map(simRef.current.map((node) => [node.id, node]));

      simRef.current.forEach((node) => {
        simRef.current.forEach((other) => {
          if (node.id === other.id) return;
          const dx = node.x - other.x;
          const dy = node.y - other.y;
          const distance = Math.hypot(dx, dy) || 1;
          const force = 900 / (distance * distance);
          node.vx += (dx / distance) * force * 0.35;
          node.vy += (dy / distance) * force * 0.35;
        });
        node.vx += (width / 2 - node.x) * 0.002;
        node.vy += (height / 2 - node.y) * 0.002;
      });

      edges.forEach(([sourceId, targetId]) => {
        const source = idMap.get(sourceId);
        const target = idMap.get(targetId);
        if (!source || !target) return;
        const dx = target.x - source.x;
        const dy = target.y - source.y;
        const distance = Math.hypot(dx, dy) || 1;
        const force = (distance - 135) * 0.035;
        source.vx += (dx / distance) * force;
        source.vy += (dy / distance) * force;
        target.vx -= (dx / distance) * force;
        target.vy -= (dy / distance) * force;
      });

      simRef.current.forEach((node) => {
        node.vx *= 0.86;
        node.vy *= 0.86;
        node.x = Math.max(46, Math.min(width - 46, node.x + node.vx));
        node.y = Math.max(46, Math.min(height - 46, node.y + node.vy));
      });

      const connected = selected
        ? new Set(
            edges
              .filter(([sourceId, targetId]) => sourceId === selected.id || targetId === selected.id)
              .flatMap(([sourceId, targetId]) => [sourceId, targetId]),
          )
        : null;

      edges.forEach(([sourceId, targetId]) => {
        const source = idMap.get(sourceId);
        const target = idMap.get(targetId);
        if (!source || !target) return;
        const active = !connected || (connected.has(sourceId) && connected.has(targetId));
        ctx.beginPath();
        ctx.moveTo(source.x, source.y);
        ctx.lineTo(target.x, target.y);
        ctx.strokeStyle = active ? "rgba(255,255,255,.16)" : "rgba(255,255,255,.045)";
        ctx.lineWidth = active ? 1.4 : 0.8;
        ctx.stroke();
      });

      simRef.current.forEach((node) => {
        const color = colors[node.type] ?? "#a1a1aa";
        const isSelected = selected?.id === node.id;
        const isConnected = connected?.has(node.id) ?? false;
        const muted = connected && !isSelected && !isConnected;
        const radius = (node.size || 8) * (isSelected ? 1.35 : 1);

        if (isSelected) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, radius + 12, 0, Math.PI * 2);
          ctx.fillStyle = `${color}24`;
          ctx.fill();
        }
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
        ctx.fillStyle = muted ? `${color}55` : color;
        ctx.fill();

        if (!muted) {
          ctx.font = `${isSelected ? 700 : 500} 12px Inter, system-ui`;
          ctx.fillStyle = "rgba(245,245,245,.82)";
          ctx.textAlign = "center";
          ctx.fillText(node.label, node.x, node.y + radius + 18);
        }
      });

      frameRef.current = requestAnimationFrame(render);
    };

    frameRef.current = requestAnimationFrame(render);
    return () => cancelAnimationFrame(frameRef.current);
  }, [edges, selected]);

  const handleClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const match = simRef.current.find((node) => Math.hypot(node.x - x, node.y - y) < node.size + 12);
    setSelected(match ?? null);
  };

  return (
    <div className="graph-panel">
      <div className="graph-canvas-wrap">
        {loading && <div className="graph-loading">Loading graph...</div>}
        <canvas ref={canvasRef} onClick={handleClick} />
        <button className="graph-refresh" onClick={() => refetch()} aria-label="Refresh graph">
          <RefreshCcw size={18} />
        </button>
        <div className="graph-caption">
          {stats.total_nodes} nodes · {stats.total_edges} edges
          {selected ? ` · ${selected.label}` : " · click a node to explore"}
        </div>
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

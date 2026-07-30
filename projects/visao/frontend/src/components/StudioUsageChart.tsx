import { useEffect, useId, useMemo, useState } from "react";
import type { StudioUsageDashboard } from "../studio/api";

type Point = StudioUsageDashboard["series"][number];
type Props = { points: Point[] };

const numberFormat = new Intl.NumberFormat("pt-BR");
const width = 920;
const height = 270;
const inset = { top: 24, right: 18, bottom: 36, left: 18 };

function smoothPath(coordinates: Array<{ x: number; y: number }>) {
  if (!coordinates.length) return "";
  return coordinates.slice(1).reduce((path, point, index) => {
    const previous = coordinates[index];
    const middle = (previous.x + point.x) / 2;
    return `${path} C ${middle} ${previous.y}, ${middle} ${point.y}, ${point.x} ${point.y}`;
  }, `M ${coordinates[0].x} ${coordinates[0].y}`);
}

export function StudioUsageChart({ points }: Props) {
  const gradientId = `studio-chart-${useId().replace(/:/g, "")}`;
  const lastUsed = Math.max(0, points.reduce((found, point, index) => point.pictures > 0 ? index : found, -1));
  const [selected, setSelected] = useState(lastUsed);
  useEffect(() => setSelected(lastUsed), [lastUsed, points]);
  const maximum = Math.max(1, ...points.map((point) => point.tokens));
  const plotWidth = width - inset.left - inset.right;
  const plotHeight = height - inset.top - inset.bottom;
  const coordinates = useMemo(() => points.map((point, index) => ({
    x: inset.left + (points.length === 1 ? plotWidth / 2 : index * plotWidth / (points.length - 1)),
    y: inset.top + plotHeight - point.tokens / maximum * plotHeight
  })), [maximum, plotHeight, plotWidth, points]);
  const line = smoothPath(coordinates);
  const area = coordinates.length ? `${line} L ${coordinates.at(-1)!.x} ${inset.top + plotHeight} L ${coordinates[0].x} ${inset.top + plotHeight} Z` : "";
  const labelStep = Math.max(1, Math.ceil(points.length / 7));
  const selectedIndex = Math.min(selected, Math.max(0, points.length - 1));
  const active = points[selectedIndex];

  return (
    <div className="studio-chart">
      <div className="studio-chart__focus" aria-live="polite">
        <strong>{active ? numberFormat.format(active.tokens) : "0"} tokens</strong>
        <span>{active?.label || "—"} · {active?.pictures || 0} foto{active?.pictures === 1 ? "" : "s"}</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Linha de consumo de tokens no período">
        <defs>
          <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#1682cf" stopOpacity="0.2" />
            <stop offset="100%" stopColor="#1682cf" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
          <line
            className="studio-chart__grid"
            key={ratio}
            x1={inset.left}
            x2={width - inset.right}
            y1={inset.top + plotHeight * ratio}
            y2={inset.top + plotHeight * ratio}
          />
        ))}
        {area && <path d={area} fill={`url(#${gradientId})`} />}
        {line && <path className="studio-chart__line" d={line} />}
        {coordinates.map((coordinate, index) => (
          <g
            className={`studio-chart__point ${index === selectedIndex ? "is-active" : ""}`}
            key={points[index].key}
            onPointerEnter={() => setSelected(index)}
            onFocus={() => setSelected(index)}
            tabIndex={0}
            role="button"
            aria-label={`${points[index].label}: ${numberFormat.format(points[index].tokens)} tokens em ${points[index].pictures} fotos`}
          >
            <circle className="studio-chart__hit" cx={coordinate.x} cy={coordinate.y} r="14" />
            <circle className="studio-chart__dot" cx={coordinate.x} cy={coordinate.y} r={index === selectedIndex ? "5" : "3"} />
          </g>
        ))}
        {points.map((point, index) => (
          (index % labelStep === 0 || index === points.length - 1) && (
            <text className="studio-chart__label" key={point.key} x={coordinates[index].x} y={height - 8} textAnchor="middle">
              {point.label}
            </text>
          )
        ))}
      </svg>
      {!points.some((point) => point.pictures > 0) && <p className="studio-chart__empty">Nenhuma foto processada neste período.</p>}
    </div>
  );
}

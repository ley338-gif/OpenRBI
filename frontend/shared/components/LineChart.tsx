import { useId, useState } from "react";

export interface LineChartPoint {
  t: string; // ISO timestamp
  value: number;
}

/**
 * Roadmap B1.10.2 — a small, hand-rolled SVG line chart. No charting
 * library existed anywhere in the frontend before this (checked); adding
 * one for a handful of admin-portal line charts would be a heavier
 * dependency than this actually needs. Deliberately not decorative —
 * every chart this renders backs a real administrative number (session
 * count, CPU/RAM over time), never a visual flourish (see the task's own
 * "no decorative graphs without administrative value" instruction).
 *
 * Handles its own loading/empty/error states so callers never have to
 * remember to; `data === null` means still loading, `error` overrides
 * everything, an empty array renders the axis with an explicit "no data"
 * message rather than a blank box that could be mistaken for zero.
 */
export function LineChart({
  data,
  error,
  yLabel,
  formatX,
  formatY,
  height = 220,
}: {
  data: LineChartPoint[] | null;
  error?: string | null;
  yLabel?: string;
  formatX?: (iso: string) => string;
  formatY?: (value: number) => string;
  height?: number;
}) {
  const gradientId = useId();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  if (error) {
    return (
      <div className="chart-state chart-state-error" style={{ height }}>
        {error}
      </div>
    );
  }
  if (data === null) {
    return (
      <div className="chart-state" style={{ height }}>
        <span className="spinner" />
      </div>
    );
  }
  if (data.length === 0) {
    return (
      <div className="chart-state chart-state-empty" style={{ height }}>
        No data for this range yet.
      </div>
    );
  }

  const width = 800; // viewBox width — scales responsively via CSS, not a pixel count
  const paddingLeft = 44;
  const paddingRight = 12;
  const paddingTop = 12;
  const paddingBottom = 28;
  const plotWidth = width - paddingLeft - paddingRight;
  const plotHeight = height - paddingTop - paddingBottom;

  const values = data.map((p) => p.value);
  const maxValue = Math.max(...values, 1);
  const minValue = Math.min(...values, 0);
  const range = maxValue - minValue || 1;

  // Positioned by real elapsed time, not array index: the backend only
  // returns buckets that actually have data (app/services/metrics_history.py),
  // so a gap in collection (e.g. the backend being restarted) means real,
  // irregular time deltas between consecutive points — spacing them evenly
  // by index would visually compress/stretch time and mislead about when
  // things happened.
  const times = data.map((p) => new Date(p.t).getTime());
  const minTime = times[0];
  const maxTime = times[times.length - 1];
  const timeRange = maxTime - minTime || 1;

  const xFor = (i: number) =>
    paddingLeft + (data.length === 1 ? plotWidth / 2 : ((times[i] - minTime) / timeRange) * plotWidth);
  const yFor = (v: number) => paddingTop + plotHeight - ((v - minValue) / range) * plotHeight;

  const linePoints = data.map((p, i) => `${xFor(i)},${yFor(p.value)}`).join(" ");
  const areaPoints = `${paddingLeft},${paddingTop + plotHeight} ${linePoints} ${paddingLeft + plotWidth},${paddingTop + plotHeight}`;

  // At most ~6 x-axis labels, evenly spaced by clock time (not by index —
  // buckets are sparse/irregular whenever metric collection had a gap, so
  // picking every Nth point can still bunch or skip labels in real time).
  const maxLabels = 6;
  const labelIndices = new Set<number>();
  if (data.length <= maxLabels) {
    data.forEach((_p, i) => labelIndices.add(i));
  } else {
    for (let s = 0; s < maxLabels; s++) {
      const targetTime = minTime + (s / (maxLabels - 1)) * timeRange;
      let closest = 0;
      let closestDelta = Infinity;
      for (let i = 0; i < times.length; i++) {
        const delta = Math.abs(times[i] - targetTime);
        if (delta < closestDelta) {
          closestDelta = delta;
          closest = i;
        }
      }
      labelIndices.add(closest);
    }
  }
  const yTicks = [minValue, minValue + range / 2, maxValue];

  const hovered = hoverIndex !== null ? data[hoverIndex] : null;

  return (
    <div className="line-chart" style={{ height }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={yLabel ? `${yLabel} over time` : "Line chart"}
        onMouseLeave={() => setHoverIndex(null)}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.22" />
            <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" />
          </linearGradient>
        </defs>

        {yTicks.map((tick, i) => (
          <g key={i}>
            <line
              x1={paddingLeft}
              x2={width - paddingRight}
              y1={yFor(tick)}
              y2={yFor(tick)}
              className="chart-gridline"
            />
            <text x={paddingLeft - 8} y={yFor(tick)} textAnchor="end" dominantBaseline="middle" className="chart-axis-label">
              {formatY ? formatY(tick) : Math.round(tick)}
            </text>
          </g>
        ))}

        <polygon points={areaPoints} fill={`url(#${gradientId})`} stroke="none" />
        <polyline points={linePoints} fill="none" className="chart-line" />

        {data.map((p, i) =>
          labelIndices.has(i) ? (
            <text key={i} x={xFor(i)} y={height - 6} textAnchor="middle" className="chart-axis-label">
              {formatX ? formatX(p.t) : p.t}
            </text>
          ) : null,
        )}

        {data.map((_p, i) => {
          // Hit region spans the midpoint to each neighbor, not a fixed
          // fraction of the plot width — points aren't evenly spaced in
          // time (see xFor above), so a uniform hit-width would drift out
          // of alignment with the visible point wherever a gap exists.
          const left = i === 0 ? paddingLeft : (xFor(i - 1) + xFor(i)) / 2;
          const right = i === data.length - 1 ? paddingLeft + plotWidth : (xFor(i) + xFor(i + 1)) / 2;
          return (
            <rect
              key={`hit-${i}`}
              x={left}
              y={paddingTop}
              width={Math.max(right - left, 1)}
              height={plotHeight}
              fill="transparent"
              onMouseEnter={() => setHoverIndex(i)}
            />
          );
        })}

        {hoverIndex !== null && (
          <line
            x1={xFor(hoverIndex)}
            x2={xFor(hoverIndex)}
            y1={paddingTop}
            y2={paddingTop + plotHeight}
            className="chart-hover-line"
          />
        )}
        {hoverIndex !== null && (
          <circle cx={xFor(hoverIndex)} cy={yFor(data[hoverIndex].value)} r={3.5} className="chart-hover-dot" />
        )}
      </svg>

      {hovered && (
        <div
          className="chart-tooltip"
          style={{ left: `${(xFor(hoverIndex!) / width) * 100}%` }}
        >
          <div className="chart-tooltip-value">{formatY ? formatY(hovered.value) : hovered.value}</div>
          <div className="chart-tooltip-label">{formatX ? formatX(hovered.t) : hovered.t}</div>
        </div>
      )}
    </div>
  );
}

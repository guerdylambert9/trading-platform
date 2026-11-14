import { useEffect, useRef, useState, type PointerEvent } from "react";

import { day, money, pct } from "../format";
import type { EquityPoint } from "../types";

const HEIGHT = 240;
const PAD = { top: 12, right: 12, bottom: 28, left: 64 };

function niceStep(span: number, count: number): number {
  const raw = span / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const fraction = raw / power;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return nice * power;
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(560);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, Math.floor(entry.contentRect.width))));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

export function EquityChart({ points, benchmark }: { points: EquityPoint[]; benchmark: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  if (points.length < 2) {
    return (
      <section className="panel chart" ref={ref}>
        <h2>Account against {benchmark}</h2>
        <p className="empty">The chart starts after two daily broker checks (4:30 pm ET).</p>
      </section>
    );
  }

  const values = points.flatMap((p) => (p.benchmark == null ? [p.equity] : [p.equity, p.benchmark]));
  const low = Math.min(...values);
  const high = Math.max(...values);
  const step = niceStep(high - low || high * 0.02 || 1, 4);
  const min = Math.floor(low / step) * step;
  const max = Math.ceil(high / step) * step;
  const ticks: number[] = [];
  for (let value = min; value <= max + step / 2; value += step) ticks.push(value);

  const plotWidth = width - PAD.left - PAD.right;
  const plotHeight = HEIGHT - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (i / (points.length - 1)) * plotWidth;
  const y = (v: number) => PAD.top + (1 - (v - min) / (max - min || 1)) * plotHeight;
  const line = (pick: (p: EquityPoint) => number | null) =>
    points
      .map((p, i) => {
        const value = pick(p);
        return value == null ? null : `${x(i).toFixed(1)},${y(value).toFixed(1)}`;
      })
      .filter(Boolean)
      .join(" ");

  const first = points[0];
  const last = points[points.length - 1];
  const accountChange = (last.equity / first.equity - 1) * 100;
  const benchmarkChange =
    first.benchmark && last.benchmark ? (last.benchmark / first.benchmark - 1) * 100 : null;
  const summary = `Account ${pct(accountChange, 1, true)}${
    benchmarkChange == null ? "" : `, ${benchmark} ${pct(benchmarkChange, 1, true)}`
  } since ${day(first.as_of)}`;
  const xLabels = [0, Math.floor((points.length - 1) / 2), points.length - 1];
  const focus = hover == null ? null : points[hover];

  function track(event: PointerEvent<SVGSVGElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - box.left - PAD.left) / plotWidth;
    setHover(Math.min(points.length - 1, Math.max(0, Math.round(ratio * (points.length - 1)))));
  }

  return (
    <section className="panel chart" ref={ref}>
      <h2>Account against {benchmark}</h2>
      <p className="chart-summary">{summary}</p>
      <svg
        width={width}
        height={HEIGHT}
        role="img"
        aria-label={summary}
        onPointerMove={track}
        onPointerLeave={() => setHover(null)}
      >
        <g className="grid">
          {ticks.map((tick) => (
            <line key={tick} x1={PAD.left} x2={width - PAD.right} y1={y(tick)} y2={y(tick)} />
          ))}
        </g>
        <g className="axis">
          {ticks.map((tick) => (
            <text key={tick} x={PAD.left - 8} y={y(tick) + 4} textAnchor="end">
              {money(tick)}
            </text>
          ))}
          {xLabels.map((i, n) => (
            <text key={i} x={x(i)} y={HEIGHT - 8} textAnchor={n === 0 ? "start" : n === 2 ? "end" : "middle"}>
              {day(points[i].as_of)}
            </text>
          ))}
        </g>
        <polyline className="line-bench" points={line((p) => p.benchmark)} />
        <polyline className="line-account" points={line((p) => p.equity)} />
        {focus && hover != null && (
          <g className="focus">
            <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={HEIGHT - PAD.bottom} />
            <circle cx={x(hover)} cy={y(focus.equity)} r={4} />
          </g>
        )}
      </svg>
      <div className="chart-key">
        <span className="key-account">Account</span>
        <span className="key-bench">{benchmark}, scaled to the same start</span>
        {focus && (
          <span className="chart-readout">
            {day(focus.as_of)}: {money(focus.equity)}
            {focus.benchmark != null && ` vs ${money(focus.benchmark)}`}
          </span>
        )}
      </div>
    </section>
  );
}

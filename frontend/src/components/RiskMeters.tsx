import { pct } from "../format";
import type { Risk } from "../types";

interface Meter {
  label: string;
  value: number;
  limit: number;
  text: string;
}

export function RiskMeters({ risk }: { risk: Risk }) {
  const { limits, usage } = risk;
  const loss = Math.max(0, -(usage.day_pnl_pct ?? 0));
  const meters: Meter[] = [
    {
      label: "Orders sent today",
      value: usage.orders_today,
      limit: limits.max_orders_per_day,
      text: `${usage.orders_today} of ${limits.max_orders_per_day}`,
    },
    {
      label: "Open positions",
      value: usage.open_positions ?? 0,
      limit: limits.max_open_positions,
      text: `${usage.open_positions ?? "–"} of ${limits.max_open_positions}`,
    },
    {
      label: "Below peak",
      value: usage.drawdown_pct ?? 0,
      limit: limits.max_drawdown_pct,
      text: `${pct(usage.drawdown_pct)} of ${limits.max_drawdown_pct}%`,
    },
    {
      label: "Loss today",
      value: loss,
      limit: limits.daily_loss_limit_pct,
      text: `${pct(loss, 2)} of ${limits.daily_loss_limit_pct}%`,
    },
  ];

  return (
    <section className="panel risk">
      <h2>Risk limits</h2>
      <ul className="meters">
        {meters.map((meter) => {
          const ratio = meter.limit > 0 ? Math.min(meter.value / meter.limit, 1) : 0;
          const level = ratio >= 1 ? "hit" : ratio >= 0.75 ? "near" : "ok";
          return (
            <li key={meter.label} className={`meter meter-${level}`}>
              <div className="meter-text">
                <span>{meter.label}</span>
                <span className="figure-sm">{meter.text}</span>
              </div>
              <div
                className="meter-track"
                role="meter"
                aria-label={meter.label}
                aria-valuemin={0}
                aria-valuemax={meter.limit}
                aria-valuenow={meter.value}
              >
                <div className="meter-fill" style={{ width: `${ratio * 100}%` }} />
              </div>
            </li>
          );
        })}
      </ul>
      <ul className="limits-list">
        <li>
          A trade risks at most {limits.risk_per_trade_pct}% of equity, with its stop {limits.stop_loss_pct}% below
          the entry.
        </li>
        <li>A new position starts at no more than {limits.max_position_pct}% of equity.</li>
        <li>
          Hitting {limits.max_drawdown_pct}% below peak engages the kill switch; losing {limits.daily_loss_limit_pct}%
          in a day pauses new entries until tomorrow.
        </li>
        <li>
          Orders go out from {limits.no_trade_after_open_min} minutes after the open until{" "}
          {limits.no_trade_before_close_min} minutes before the close, and skip any entry that gapped up more than{" "}
          {risk.max_gap_pct}%.
        </li>
      </ul>
    </section>
  );
}

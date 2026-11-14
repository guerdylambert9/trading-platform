import { day, money, moment } from "../format";
import type { AIDecision, Status } from "../types";

export function Checks({ status, ai }: { status: Status; ai: AIDecision[] }) {
  const check = status.last_reconciliation;
  return (
    <section className="panel" aria-labelledby="checks-title">
      <h2 id="checks-title">Broker check</h2>
      {!check ? (
        <p className="empty">No check yet. It runs at 4:30 pm ET, or use “Check against the broker”.</p>
      ) : check.ok ? (
        <p className="check-line">
          <span className="dot dot-ok" aria-hidden="true" />
          The ledger matches the broker. Checked {moment(check.ts)}.
        </p>
      ) : (
        <>
          <p className="check-line">
            <span className="dot dot-bad" aria-hidden="true" />
            {check.mismatches.length} {check.mismatches.length === 1 ? "problem" : "problems"} found {moment(check.ts)}:
          </p>
          <ul className="problems">
            {check.mismatches.map((m, i) => (
              <li key={`${m.type}-${i}`}>{m.message}</li>
            ))}
          </ul>
        </>
      )}

      <h2 className="spaced">AI reviews</h2>
      {status.ai_mode === "off" ? (
        <p className="muted small">
          Off until Phase 3. Set AI_MODE to log_only or veto on paper account B to start the A/B test.
        </p>
      ) : ai.length === 0 ? (
        <p className="muted small">No AI reviews yet. They run on new entries during the 5:15 pm ET run.</p>
      ) : (
        <table className="ledger compact">
          <thead>
            <tr>
              <th scope="col">Symbol</th>
              <th scope="col">Date</th>
              <th scope="col">Rating</th>
              <th scope="col" className="num">Cost</th>
            </tr>
          </thead>
          <tbody>
            {ai.map((d) => (
              <tr key={d.id} title={d.summary}>
                <th scope="row" className="symbol">{d.symbol}</th>
                <td>{day(d.as_of)}</td>
                <td>{d.rating.replace("_", " ")}</td>
                <td className="num">{d.cost_usd == null ? "–" : money(d.cost_usd, true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

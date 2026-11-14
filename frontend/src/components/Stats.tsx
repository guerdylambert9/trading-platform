import { money, pct, trend } from "../format";
import type { Account } from "../types";

export function Stats({ account, maxPositions }: { account: Account; maxPositions: number }) {
  return (
    <dl className="stats">
      <div className="stat stat-equity">
        <dt>Equity</dt>
        <dd className="figure">{money(account.equity)}</dd>
      </div>
      <div className="stat">
        <dt>Today</dt>
        <dd className={`figure ${trend(account.day_pnl_pct)}`}>{pct(account.day_pnl_pct, 2, true)}</dd>
      </div>
      <div className="stat">
        <dt>Below peak</dt>
        <dd className="figure">{pct(account.drawdown_pct, 1)}</dd>
      </div>
      <div className="stat">
        <dt>Cash</dt>
        <dd className="figure">{money(account.cash)}</dd>
      </div>
      <div className="stat">
        <dt>Positions</dt>
        <dd className="figure">
          {account.open_positions}
          <span className="of"> of {maxPositions}</span>
        </dd>
      </div>
    </dl>
  );
}

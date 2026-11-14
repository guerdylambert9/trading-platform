import { day, money, moment, pct, px, qty, signedMoney, trend } from "../format";
import type { Order, Position, Signal } from "../types";

export function PositionsTable({ positions }: { positions: Position[] }) {
  return (
    <section className="section" aria-labelledby="positions-title">
      <h2 id="positions-title">Positions</h2>
      {positions.length === 0 ? (
        <p className="empty">No open positions.</p>
      ) : (
        <div className="table-wrap">
          <table className="ledger">
            <thead>
              <tr>
                <th scope="col">Symbol</th>
                <th scope="col" className="num">Shares</th>
                <th scope="col" className="num">Avg cost</th>
                <th scope="col" className="num">Price</th>
                <th scope="col" className="num">Value</th>
                <th scope="col" className="num">Gain</th>
                <th scope="col" className="num">Of equity</th>
                <th scope="col" className="num">Stop</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.symbol}>
                  <th scope="row" className="symbol">{p.symbol}</th>
                  <td className="num">{qty(p.qty)}</td>
                  <td className="num">{px(p.avg_entry_price)}</td>
                  <td className="num">{px(p.current_price)}</td>
                  <td className="num">{money(p.market_value)}</td>
                  <td className={`num ${trend(p.unrealized_pl)}`}>
                    {signedMoney(p.unrealized_pl)} <span className="muted">({pct(p.unrealized_pl_pct, 1, true)})</span>
                  </td>
                  <td className="num">{pct(p.weight_pct)}</td>
                  <td className="num">
                    {p.protected ? px(p.stop_price) : <span className="warn">No stop</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

const ORDER_STATUS: Record<string, string> = {
  filled: "Filled",
  new: "Working",
  accepted: "Working",
  partially_filled: "Part filled",
  canceled: "Canceled",
  expired: "Expired",
  rejected: "Rejected",
};

export function OrdersTable({ orders }: { orders: Order[] }) {
  return (
    <section className="section" aria-labelledby="orders-title">
      <h2 id="orders-title">Orders sent</h2>
      {orders.length === 0 ? (
        <p className="empty">No orders sent yet. Approved orders go out at 9:50 am ET.</p>
      ) : (
        <div className="table-wrap">
          <table className="ledger">
            <thead>
              <tr>
                <th scope="col">Sent (ET)</th>
                <th scope="col">Order</th>
                <th scope="col" className="num">Limit</th>
                <th scope="col" className="num">Stop</th>
                <th scope="col" className="num">Filled at</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <td>{moment(o.submitted_at, false)}</td>
                  <td>
                    <span className={o.side === "buy" ? "side-word buy" : "side-word sell"}>
                      {o.side === "buy" ? "Buy" : "Sell"}
                    </span>{" "}
                    {qty(o.qty)} <span className="symbol">{o.symbol}</span>
                  </td>
                  <td className="num">{px(o.limit_price)}</td>
                  <td className="num">{px(o.stop_price)}</td>
                  <td className="num">{px(o.filled_avg_price)}</td>
                  <td>{ORDER_STATUS[o.status] ?? o.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function SignalsTable({ signals }: { signals: Signal[] }) {
  return (
    <section className="panel" aria-labelledby="signals-title">
      <h2 id="signals-title">Latest targets</h2>
      {signals.length === 0 ? (
        <p className="empty">No signals yet. They appear after the first 5:15 pm ET run.</p>
      ) : (
        <>
          <p className="muted small">From the close on {day(signals[0].as_of)}.</p>
          <table className="ledger compact">
            <thead>
              <tr>
                <th scope="col">Symbol</th>
                <th scope="col" className="num">Target</th>
                <th scope="col" className="num">Close</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((s) => (
                <tr key={s.id} className={s.target_weight > 0 ? "" : "dim"}>
                  <th scope="row" className="symbol">{s.symbol}</th>
                  <td className="num">{s.target_weight > 0 ? pct(s.target_weight * 100) : "Cash"}</td>
                  <td className="num">{px(s.price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

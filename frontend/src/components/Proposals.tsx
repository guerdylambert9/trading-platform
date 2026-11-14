import { useState } from "react";

import { day, money, pct, px, qty } from "../format";
import type { Proposal } from "../types";

interface Props {
  pending: Proposal[];
  recent: Proposal[];
  equity: number | null;
  schedulerRunning: boolean;
  onDecide: (proposal: Proposal, approve: boolean) => Promise<void>;
}

const STATUS_WORD: Record<string, string> = {
  approved: "Approved",
  rejected: "Rejected",
  blocked: "Blocked",
  submitted: "Sent",
  filled: "Filled",
  canceled: "Canceled",
  expired: "Expired",
  dry_run: "Dry run",
  error: "Error",
};

export function Proposals({ pending, recent, equity, schedulerRunning, onDecide }: Props) {
  const [busy, setBusy] = useState<number | null>(null);
  const decided = recent.filter((p) => p.status !== "pending").slice(0, 8);

  async function decide(proposal: Proposal, approve: boolean) {
    setBusy(proposal.id);
    try {
      await onDecide(proposal, approve);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="proposals" aria-labelledby="proposals-title">
      <div className="section-head">
        <h2 id="proposals-title">Orders waiting for you</h2>
        {pending.length > 0 && (
          <p className="muted small">
            {schedulerRunning
              ? "Approved orders go out at 9:50 am ET on the next trading day."
              : "Approved orders go out when you press Send approved orders."}
          </p>
        )}
      </div>

      {pending.length === 0 ? (
        <p className="empty">
          {schedulerRunning
            ? "Nothing to approve. After each close, the 5:15 pm ET run proposes any new orders here."
            : "Nothing to approve. Press Run tonight's signals after the close to check for new orders."}
        </p>
      ) : (
        <ul className="tickets">
          {pending.map((proposal) => (
            <Ticket
              key={proposal.id}
              proposal={proposal}
              equity={equity}
              busy={busy === proposal.id}
              onDecide={(approve) => decide(proposal, approve)}
            />
          ))}
        </ul>
      )}

      {decided.length > 0 && (
        <div className="decided">
          <h3>Recent decisions</h3>
          <ul className="decided-list">
            {decided.map((proposal) => (
              <DecidedRow key={proposal.id} proposal={proposal} />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function Ticket({
  proposal,
  equity,
  busy,
  onDecide,
}: {
  proposal: Proposal;
  equity: number | null;
  busy: boolean;
  onDecide: (approve: boolean) => void;
}) {
  const amount = proposal.qty * proposal.limit_price;
  const share = equity ? (amount / equity) * 100 : null;
  const label = `${proposal.side === "buy" ? "Buy" : "Sell"} ${qty(proposal.qty)} ${proposal.symbol}`;

  return (
    <li className={`ticket side-${proposal.side}`}>
      <div className="ticket-body">
        <p className="ticket-line">
          <span className="ticket-side">{proposal.side === "buy" ? "Buy" : "Sell"}</span>
          <span className="ticket-qty">{qty(proposal.qty)}</span>
          <span className="ticket-symbol">{proposal.symbol}</span>
        </p>
        <dl className="ticket-terms">
          <div>
            <dt>Limit</dt>
            <dd>{px(proposal.limit_price)}</dd>
          </div>
          {proposal.stop_price != null && (
            <div>
              <dt>Stop</dt>
              <dd>{px(proposal.stop_price)}</dd>
            </div>
          )}
          <div>
            <dt>{proposal.side === "buy" ? "Cost" : "Proceeds"}</dt>
            <dd>
              {money(amount)}
              {share != null && <span className="muted"> ({pct(share)} of equity)</span>}
            </dd>
          </div>
        </dl>
        <p className="ticket-reason">{proposal.reason}</p>
        {proposal.ai_rating && proposal.ai_rating !== "no_opinion" && (
          <p className="ticket-ai">AI rating: {proposal.ai_rating}</p>
        )}
        <p className="ticket-meta muted small">
          Signal from {day(proposal.as_of)}, proposal #{proposal.id}
        </p>
      </div>
      <div className="ticket-stub">
        <button type="button" className="btn btn-go" disabled={busy} onClick={() => onDecide(true)} aria-label={`Approve: ${label}`}>
          Approve
        </button>
        <button type="button" className="btn btn-quiet" disabled={busy} onClick={() => onDecide(false)} aria-label={`Reject: ${label}`}>
          Reject
        </button>
      </div>
    </li>
  );
}

function DecidedRow({ proposal }: { proposal: Proposal }) {
  const why = proposal.violations.length
    ? proposal.violations.map((v) => v.message).join(" ")
    : proposal.status === "error" || proposal.status === "canceled"
      ? proposal.error
      : null;
  return (
    <li className={`decided-row status-${proposal.status}`}>
      <span className="decided-status">{STATUS_WORD[proposal.status] ?? proposal.status}</span>
      <span className="decided-what">
        {proposal.side === "buy" ? "Buy" : "Sell"} {qty(proposal.qty)} {proposal.symbol}
      </span>
      <span className="decided-when muted">{day(proposal.as_of)}</span>
      {why && <span className="decided-why">{why}</span>}
    </li>
  );
}

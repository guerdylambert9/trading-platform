import type { Status } from "../types";

const NAME: Record<Status["mode"], string> = { DEMO: "Demo", PAPER: "Paper", LIVE: "Live" };

const COPY: Record<Status["mode"], string> = {
  DEMO: "A fake broker and made-up prices. Nothing here is real money.",
  PAPER: "Alpaca paper account: simulated orders at real market prices.",
  LIVE: "Real money. Every approved order goes to your Alpaca account.",
};

export function ModeBand({ status }: { status: Status }) {
  return (
    <div className={`mode-band mode-${status.mode.toLowerCase()}`} role="status">
      <div className="mode-inner">
        <strong className="mode-name">{NAME[status.mode]}</strong>
        <span>{COPY[status.mode]}</span>
        {status.dry_run && <span className="mode-extra">Dry run is on: approved orders are checked but never sent.</span>}
        {status.auto_approve && <span className="mode-extra">Auto-approve is on: proposals skip your approval.</span>}
      </div>
    </div>
  );
}

import { useState, type FormEvent } from "react";

import { moment } from "../format";
import type { KillSwitchState } from "../types";

interface Props {
  state: KillSwitchState;
  onEngage: (reason: string) => Promise<void>;
  onRelease: () => Promise<void>;
}

export function KillSwitch({ state, onEngage, onRelease }: Props) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  }

  if (state.engaged) {
    const release = (event: FormEvent) => {
      event.preventDefault();
      void run(async () => {
        await onRelease();
        setConfirmText("");
      });
    };
    return (
      <div className="kill kill-engaged" role="alert">
        <p className="kill-title">
          <span className="kill-light" aria-hidden="true" />
          Kill switch engaged
        </p>
        <p className="kill-reason">
          {state.reason || "No reason given."}{" "}
          {state.at && <span className="muted">Since {moment(state.at)}.</span>}
        </p>
        <p className="muted small">No new orders go out. Protective stops stay in place.</p>
        <form className="kill-form" onSubmit={release}>
          <label htmlFor="release-confirm">Type RELEASE to allow new orders</label>
          <div className="inline-field">
            <input
              id="release-confirm"
              type="text"
              value={confirmText}
              onChange={(event) => setConfirmText(event.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
            <button type="submit" className="btn" disabled={busy || confirmText.trim().toUpperCase() !== "RELEASE"}>
              Release
            </button>
          </div>
        </form>
      </div>
    );
  }

  if (!open) {
    return (
      <div className="kill">
        <button type="button" className="kill-guard" onClick={() => setOpen(true)} aria-expanded="false">
          <span className="switch-icon" aria-hidden="true" />
          Kill switch
        </button>
        <p className="muted small">Stops all new orders in one step.</p>
      </div>
    );
  }

  const engage = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      await onEngage(reason.trim() || "Engaged from the dashboard");
      setOpen(false);
      setReason("");
    });
  };

  return (
    <form className="kill kill-open" onSubmit={engage}>
      <p className="kill-title">Engage the kill switch?</p>
      <p className="muted small">
        Pending entries are canceled and no new orders go out until you release it. Protective stops stay in place.
      </p>
      <label htmlFor="kill-reason">Reason (optional)</label>
      <input
        id="kill-reason"
        type="text"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder="Market looks wrong, reviewing"
        autoFocus
      />
      <div className="kill-actions">
        <button type="submit" className="btn btn-stop" disabled={busy}>
          Engage kill switch
        </button>
        <button type="button" className="btn btn-quiet" onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
}

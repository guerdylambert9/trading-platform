import { useState } from "react";

import { moment } from "../format";
import type { JobName, Status } from "../types";

const JOBS: { name: JobName; label: string; time: string; detail: string }[] = [
  { name: "nightly", label: "Run tonight's signals", time: "5:15 pm", detail: "Computes targets and proposes orders." },
  { name: "submit", label: "Send approved orders", time: "9:50 am", detail: "Only works inside the trading window." },
  { name: "reconcile", label: "Check against the broker", time: "4:30 pm", detail: "Compares the ledger with the broker." },
];

export function Jobs({ status, onRun }: { status: Status; onRun: (name: JobName) => Promise<void> }) {
  const [busy, setBusy] = useState<JobName | null>(null);

  async function run(name: JobName) {
    setBusy(name);
    try {
      await onRun(name);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="panel" aria-labelledby="jobs-title">
      <h2 id="jobs-title">Run a job now</h2>
      <p className="muted small">
        {status.scheduler_running
          ? "The scheduler runs these on weekdays (New York time)."
          : (
            <>
              The scheduler is off, so these only run when you press them. Start it with{" "}
              <code>trader serve --scheduler</code>.
            </>
          )}
      </p>
      <ul className="jobs">
        {JOBS.map((job) => {
          const last = status.last_runs[job.name];
          return (
            <li key={job.name} className="job">
              <button type="button" className="btn btn-quiet" disabled={busy !== null} onClick={() => void run(job.name)}>
                {busy === job.name ? "Running" : job.label}
              </button>
              <span className="muted small">
                {job.name === "submit" && status.mode === "DEMO" ? "Sends them to the demo broker." : job.detail} Scheduled{" "}
                {job.time} ET. Last run {last ? moment(last.at) : "never"}.
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

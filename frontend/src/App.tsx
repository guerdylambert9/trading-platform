import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api, saveToken } from "./api";
import { Checks } from "./components/Checks";
import { EquityChart } from "./components/EquityChart";
import { Toast, TokenPrompt, Unreachable, type ToastMessage } from "./components/Feedback";
import { Jobs } from "./components/Jobs";
import { KillSwitch } from "./components/KillSwitch";
import { ModeBand } from "./components/ModeBand";
import { Proposals } from "./components/Proposals";
import { RiskMeters } from "./components/RiskMeters";
import { Stats } from "./components/Stats";
import { OrdersTable, PositionsTable, SignalsTable } from "./components/Tables";
import { clockTime, moment } from "./format";
import type { DeskData, JobName, JobResult, Proposal, Status, Tone } from "./types";

type Load =
  | { kind: "loading" }
  | { kind: "ready"; data: DeskData; at: Date }
  | { kind: "error"; message: string }
  | { kind: "token" };

const REFRESH_MS = 30_000;

function describeStrategy(strategy: Status["strategy"]): string {
  if (strategy.name === "trend") return `Trend following on a ${String(strategy.window)}-day average`;
  if (strategy.name === "momentum") return `Momentum: top ${String(strategy.top_n)} by ${String(strategy.lookback)}-day return`;
  return strategy.name;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function describeJob(outcome: JobResult): string {
  const result = outcome.result;
  if (result.skipped_reason) return String(result.skipped_reason);
  const count = (key: string) => (Array.isArray(result[key]) ? (result[key] as unknown[]).length : Number(result[key] ?? 0));
  const parts: string[] = [];

  if (outcome.job === "nightly") {
    if (count("pending")) parts.push(`${plural(count("pending"), "order")} waiting for you`);
    if (count("approved")) parts.push(`${count("approved")} approved automatically`);
    if (count("blocked")) parts.push(`${count("blocked")} blocked by the risk checks`);
    return parts.length ? `Signals are done: ${parts.join(", ")}.` : "Signals are done. No orders are needed.";
  }
  if (outcome.job === "submit") {
    if (count("submitted")) parts.push(`Sent ${plural(count("submitted"), "order")}`);
    if (count("dry_run")) parts.push(`Logged ${plural(count("dry_run"), "dry-run order")}`);
    if (count("blocked")) parts.push(`${count("blocked")} blocked by the risk checks`);
    if (count("expired")) parts.push(`${count("expired")} expired`);
    if (count("errors")) parts.push(plural(count("errors"), "error"));
    return parts.length ? `${parts.join(", ")}.` : "No approved orders to send.";
  }
  if (result.kill_switch_engaged) return "The account hit its drawdown limit, so the kill switch is now engaged.";
  return result.ok ? "The ledger matches the broker." : `The broker check found ${plural(count("mismatches"), "problem")}.`;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default function App() {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [toast, setToast] = useState<ToastMessage | null>(null);

  const say = useCallback((text: string, tone: Tone = "neutral") => setToast({ id: Date.now(), text, tone }), []);
  const clearToast = useCallback(() => setToast(null), []);
  const schedulerOn = useRef(false);
  useEffect(() => {
    if (load.kind === "ready") schedulerOn.current = load.data.status.scheduler_running;
  }, [load]);

  const refresh = useCallback(async () => {
    try {
      const status = await api.status();
      const results = await Promise.allSettled([
        api.proposals("pending"),
        api.proposals(null, 30),
        api.positions(),
        api.orders(),
        api.signals(),
        api.equity(),
        api.risk(),
        api.aiDecisions(),
      ] as const);
      const pick = <T,>(result: PromiseSettledResult<T>, fallback: T): T =>
        result.status === "fulfilled" ? result.value : fallback;
      const [pending, recent, positions, orders, signals, equity, risk, ai] = results;
      if (risk.status === "rejected") throw risk.reason;
      setLoad({
        kind: "ready",
        at: new Date(),
        data: {
          status,
          pending: pick(pending, []),
          recent: pick(recent, []),
          positions: pick(positions, []),
          orders: pick(orders, []),
          signals: pick(signals, []),
          equity: pick(equity, []),
          risk: risk.value,
          ai: pick(ai, []),
        },
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setLoad({ kind: "token" });
        return;
      }
      setLoad((previous) => {
        if (previous.kind === "ready") {
          say(`Couldn't refresh: ${errorText(error)}`, "bad");
          return previous;
        }
        return { kind: "error", message: errorText(error) };
      });
    }
  }, [say]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh]);

  const decide = useCallback(
    async (proposal: Proposal, approve: boolean) => {
      const what = `${proposal.side === "buy" ? "buy" : "sell"} ${proposal.qty} ${proposal.symbol}`;
      try {
        if (approve) {
          await api.approve(proposal.id);
          const when = schedulerOn.current
            ? "It goes out at 9:50 am ET on the next trading day."
            : "Press Send approved orders to send it.";
          say(`Approved: ${what}. ${when}`, "good");
        } else {
          await api.reject(proposal.id);
          say(`Rejected: ${what}.`);
        }
      } catch (error) {
        say(errorText(error), "bad");
      }
      await refresh();
    },
    [refresh, say],
  );

  const engage = useCallback(
    async (reason: string) => {
      try {
        await api.killSwitch({ engage: true, reason });
        say("Kill switch engaged. Pending entries were canceled; stops stay in place.", "bad");
      } catch (error) {
        say(errorText(error), "bad");
      }
      await refresh();
    },
    [refresh, say],
  );

  const release = useCallback(async () => {
    try {
      await api.killSwitch({ engage: false, confirm: "RELEASE" });
      say("Kill switch released. New orders are allowed again.", "good");
    } catch (error) {
      say(errorText(error), "bad");
    }
    await refresh();
  }, [refresh, say]);

  const runJob = useCallback(
    async (name: JobName) => {
      try {
        say(describeJob(await api.runJob(name)));
      } catch (error) {
        say(errorText(error), "bad");
      }
      await refresh();
    },
    [refresh, say],
  );

  if (load.kind === "loading") return <p className="boot">Loading the trading desk</p>;
  if (load.kind === "token")
    return (
      <TokenPrompt
        onSave={(token) => {
          saveToken(token);
          setLoad({ kind: "loading" });
          void refresh();
        }}
      />
    );
  if (load.kind === "error") return <Unreachable message={load.message} onRetry={() => void refresh()} />;

  const { data, at } = load;
  const { status, risk } = data;
  const market =
    status.mode === "DEMO"
      ? "The demo market never closes, so you can send orders at any hour."
      : status.clock
        ? status.clock.is_open
          ? "The market is open."
          : `The market is closed; it opens ${moment(status.clock.next_open)}.`
        : "";

  return (
    <>
      <ModeBand status={status} />
      <main className="desk">
        <header className="desk-head">
          <div>
            <h1>Trading desk</h1>
            <p className="muted">
              {describeStrategy(status.strategy)} across {status.universe.length} tickers, measured against{" "}
              {status.benchmark}. {market}
            </p>
          </div>
          <KillSwitch state={status.kill_switch} onEngage={engage} onRelease={release} />
        </header>

        {status.broker_error && (
          <p className="notice notice-bad" role="alert">
            Can't read the account from the broker: {status.broker_error}
          </p>
        )}
        {status.account && <Stats account={status.account} maxPositions={risk.limits.max_open_positions} />}

        <div className="main-grid">
          <Proposals
            pending={data.pending}
            recent={data.recent}
            equity={status.account?.equity ?? null}
            schedulerRunning={status.scheduler_running}
            onDecide={decide}
          />
          <div className="side">
            <EquityChart points={data.equity} benchmark={status.benchmark} />
            <RiskMeters risk={risk} />
          </div>
        </div>

        <PositionsTable positions={data.positions} />
        <OrdersTable orders={data.orders} />

        <div className="lower">
          <SignalsTable signals={data.signals} />
          <Checks status={status} ai={data.ai} />
          <Jobs status={status} onRun={runJob} />
        </div>

        <footer className="foot muted small">
          Updated {clockTime(at)}; refreshes every 30
          seconds. Account {status.account_label}. This tool places only the orders its rules and limits allow; it
          is not investment advice.
        </footer>
      </main>
      <Toast message={toast} onDone={clearToast} />
    </>
  );
}

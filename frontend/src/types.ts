export type Mode = "DEMO" | "PAPER" | "LIVE";
export type JobName = "nightly" | "submit" | "reconcile";

export interface KillSwitchState {
  engaged: boolean;
  reason: string | null;
  at: string | null;
  by: string | null;
}

export interface Violation {
  code: string;
  message: string;
}

export interface Reconciliation {
  id: number;
  ts: string;
  ok: boolean;
  mismatches: { type: string; message: string }[];
}

export interface Account {
  equity: number;
  cash: number;
  buying_power: number;
  day_pnl_pct: number;
  drawdown_pct: number;
  peak_equity: number;
  open_positions: number;
}

export interface Status {
  mode: Mode;
  broker: string;
  trading_mode: string;
  dry_run: boolean;
  account_label: string;
  strategy: { name: string } & Record<string, unknown>;
  universe: string[];
  benchmark: string;
  ai_mode: string;
  auto_approve: boolean;
  kill_switch: KillSwitchState;
  account: Account | null;
  clock: { is_open: boolean; next_open: string; next_close: string } | null;
  broker_error: string | null;
  pending_proposals: number;
  scheduler_running: boolean;
  last_runs: Record<string, ({ at: string } & Record<string, unknown>) | null>;
  last_reconciliation: Reconciliation | null;
}

export interface Proposal {
  id: number;
  created_at: string;
  as_of: string;
  symbol: string;
  side: "buy" | "sell";
  kind: "entry" | "exit";
  qty: number;
  est_price: number;
  limit_price: number;
  stop_price: number | null;
  reason: string;
  source: string;
  status: string;
  violations: Violation[];
  ai_rating: string | null;
  ai_summary: string | null;
  client_order_id: string;
  decided_at: string | null;
  decided_by: string | null;
  submitted_at: string | null;
  broker_order_id: string | null;
  error: string | null;
}

export interface Position {
  symbol: string;
  qty: number;
  avg_entry_price: number;
  current_price: number;
  market_value: number;
  unrealized_pl: number;
  unrealized_pl_pct: number;
  weight_pct: number;
  stop_price: number | null;
  protected: boolean;
}

export interface Order {
  id: number;
  client_order_id: string;
  broker_order_id: string | null;
  proposal_id: number | null;
  symbol: string;
  side: string;
  qty: number;
  filled_qty: number;
  filled_avg_price: number | null;
  status: string;
  order_class: string;
  limit_price: number | null;
  stop_price: number | null;
  submitted_at: string | null;
  updated_at: string;
}

export interface Signal {
  id: number;
  as_of: string;
  strategy: string;
  symbol: string;
  target_weight: number;
  price: number | null;
}

export interface EquityPoint {
  as_of: string;
  equity: number;
  benchmark: number | null;
}

export interface RiskLimits {
  risk_per_trade_pct: number;
  stop_loss_pct: number;
  max_position_pct: number;
  max_open_positions: number;
  daily_loss_limit_pct: number;
  max_drawdown_pct: number;
  max_orders_per_day: number;
  no_trade_after_open_min: number;
  no_trade_before_close_min: number;
  entry_limit_buffer_pct: number;
  max_entry_fraction: number;
}

export interface Risk {
  limits: RiskLimits;
  usage: {
    orders_today: number;
    open_positions: number | null;
    drawdown_pct: number | null;
    day_pnl_pct: number | null;
  };
  max_gap_pct: number;
  auto_approve: boolean;
}

export interface AIDecision {
  id: number;
  created_at: string;
  as_of: string;
  symbol: string;
  rating: string;
  summary: string;
  model: string;
  cost_usd: number | null;
}

export interface JobResult {
  job: JobName;
  result: Record<string, unknown> & { skipped_reason?: string | null };
}

export interface DeskData {
  status: Status;
  pending: Proposal[];
  recent: Proposal[];
  positions: Position[];
  orders: Order[];
  signals: Signal[];
  equity: EquityPoint[];
  risk: Risk;
  ai: AIDecision[];
}

export type Tone = "good" | "bad" | "neutral";

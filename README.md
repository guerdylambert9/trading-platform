# Trading Platform

A trading app you run yourself. After each market close it turns daily prices into trade signals, checks every order against hard risk limits, and waits for your approval. Then it places the orders with Alpaca. A dashboard shows your account, the orders waiting for you, and a kill switch. Backtests and a series of gates tell you, with numbers, when it has earned the next step from demo to paper to live money.

One rule runs through all of it: **AI proposes, code decides.** Rules (and later an optional AI research desk) can suggest trades. Only code with fixed risk limits, plus your approval, can send them. The AI can veto an entry; it can never add or enlarge one.

> Out of the box it runs a fake broker on made-up prices. It cannot touch real money unless you set three things on purpose: `BROKER=alpaca`, `TRADING_MODE=live` and `LIVE_TRADING_CONFIRMED=true`. This is a personal tool, not investment advice.

## What it does

- **Signals.** Two rules strategies on a basket of ETFs: trend following (hold what trades above its 200-day average) and momentum (the top 3 by 12-month return, skipping the last month, rebalanced monthly).
- **Risk checks.** Every order is checked when it is planned and again right before it is sent: size, risk per trade, open positions, daily loss, drawdown, daily order cap, trading window, duplicates, buying power, no shorting.
- **Approvals.** From the dashboard, the command line or Telegram buttons. Nothing goes out without you unless you turn on `AUTO_APPROVE`.
- **Execution.** Limit orders through the official `alpaca-py` SDK. Every entry carries a protective stop held at Alpaca, so it protects you even when this app is off.
- **Broker check.** Every afternoon the ledger is compared with Alpaca: unfilled entries are canceled, equity is recorded, and the kill switch engages by itself at the drawdown limit.
- **Kill switch.** One button cancels pending entries and blocks new orders. Protective stops stay in place.
- **Backtests and gates.** The backtester uses the same order planner as live trading, so a backtest trades exactly the way the app would. Gates 0 to 5 decide each step forward.
- **AI research desk (optional, phase 3).** TradingAgents reviews entries on a second paper account, and Gate 3 decides whether it earns its LLM costs.

## Try the demo (no accounts needed)

You need Python 3.11 or newer and Node.js 22.12 or newer (20.19+ also works).

```bash
# Terminal 1: the backend
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
trader demo                        # replays the last 120 trading days with a fake broker
trader serve                       # the API, on http://127.0.0.1:8000
```

```bash
# Terminal 2: the dashboard
cd frontend
npm install
npm run dev                        # open http://localhost:5173
```

The dashboard shows the demo account, its equity against SPY, and the last day's proposals waiting for you. Approve one, then press **Send approved orders**. The demo market never closes, so this works at any hour. The demo keeps its records in `backend/demo.db`, apart from any real account.

To run everything from one process and one port, build the dashboard once with `npm run build`; `trader serve` then serves it at http://127.0.0.1:8000.

## How a trading day runs

Times are New York time on weekdays. With the scheduler on (`ENABLE_SCHEDULER=true` or `trader serve --scheduler`) the jobs run by themselves. You can also press them in the dashboard or run them from the command line.

| When | Job | What happens |
|---|---|---|
| 5:15 pm | Signals (`trader run-nightly`) | Reads the day's closes, computes target weights, plans whole-share orders, runs the risk checks, and posts proposals to the dashboard and Telegram. |
| Evening | You | Approve or reject each proposal. |
| 9:50 am next trading day | Send (`trader submit`) | Re-prices each approved order at the latest price, skips entries that gapped up too far, re-checks the limits, and sends limit orders. Entries carry a stop 8% below; exits cancel that stop first. |
| 4:30 pm | Broker check (`trader reconcile`) | Compares the ledger with Alpaca, cancels entries that didn't fill, records equity, and engages the kill switch at 10% below the peak. |

## The road to live trading

Each gate is a command that prints its checks and exits with 0 on a pass and 1 on a fail. [docs/GATES.md](docs/GATES.md) explains every check and why it is there.

| Phase | Weeks | What you do | Gate to pass | Command |
|---|---|---|---|---|
| 0. Set up | 1 | Open Alpaca, put paper keys in `.env` | Your code places, reads back and cancels a paper order | `trader smoke-test` |
| 1. One strategy | 2 to 4 | Backtest 2016 to 2022 on real prices | Beats SPY on the held-out years (2023 to now) after costs, and holds up when parameters move or trades come a day late | `trader gate1` |
| 2. The app on paper | 5 to 8 | Run the scheduler on paper, approve daily, drill the kill switch | Ten weekdays of clean broker checks, kill switch tested | `trader gate2` |
| 3. AI A/B test | 9 to 20 | Paper account B runs the same rules plus the AI veto | B beats A after its LLM costs | `trader compare-ab` |
| 4. Paper forward test | 9 to 20 | Account A keeps trading on paper | Twelve weeks inside the backtest's ranges | `trader gate4` |
| 5. Live, small | 21 on | Live keys, small size, paper still running | Three live months track paper before you add money | `trader gate5` |

### Phase 0: connect Alpaca paper trading

1. Open an account at [alpaca.markets](https://alpaca.markets). In the dashboard, switch to your paper account and generate API keys.
2. Copy the settings file and fill it in (from the repository root):

   ```bash
   cp .env.example .env
   ```

   ```ini
   BROKER=alpaca
   ALPACA_API_KEY=your-paper-key
   ALPACA_SECRET_KEY=your-paper-secret
   DATA_SOURCE=alpaca
   ```

3. From `backend/`, run `trader smoke-test`. It places a one-share limit buy far below the market (it can't fill), reads it back by its client order ID, and cancels it.

### Phase 1: test a strategy on real prices

```bash
trader backtest --strategy trend        # 2016 to 2022 only
trader backtest --strategy momentum
trader gate1 --strategy trend           # 2023 to today; run it once per idea
```

Write down what would count as a pass before you run `gate1`. Every run is logged in `reports/holdout_log.jsonl`, because each extra look at the held-out years makes a pass less trustworthy. If an idea fails, change the idea, not the test. `trader fetch-data` saves the prices to `data/closes.csv` so you can backtest offline with `DATA_SOURCE=csv`.

With `DATA_SOURCE=synthetic` these commands run, but the prices are random, so the results mean nothing. Gate 1 usually fails on them, as it should.

### Phase 2: run it on paper

1. Set `ENABLE_SCHEDULER=true` and run `trader serve` on a computer that stays on, or use Docker on a small server (see below).
2. Optionally set up Telegram approvals (see below).
3. Each evening, approve or reject the proposals. Each day, glance at the broker check on the dashboard.
4. Drill the kill switch once: engage it, confirm that pending entries were canceled and the stops stayed, then release it.
5. After ten weekdays, run `trader gate2`.

### Phase 3: the AI A/B test on paper account B

Alpaca lets you open up to three paper accounts. Open a second one for account B.

1. Install TradingAgents into the backend's environment and set up its LLM provider keys as its README describes:

   ```bash
   pip install git+https://github.com/TauricResearch/TradingAgents.git
   ```

2. Copy your settings to `.env.b` and change these lines:

   ```ini
   ACCOUNT_LABEL=B
   ALPACA_API_KEY=account-b-paper-key
   ALPACA_SECRET_KEY=account-b-paper-secret
   DATABASE_URL=sqlite:///./trader-b.db
   AI_MODE=veto
   AI_RESEARCHER=tradingagents
   AI_COST_PER_CALL_USD=0.50
   ```

   Set `AI_COST_PER_CALL_USD` to what a research call really costs you, so Gate 3 charges it against B.

3. Run B next to A: `trader --env-file ../.env.b serve --port 8001`. With the dashboard built, B's dashboard is at http://127.0.0.1:8001.
4. After twelve weeks, compare: `trader compare-ab --a sqlite:///./trader.db --b sqlite:///./trader-b.db`.

The AI is judged only on results logged going forward. Backtesting an LLM is unreliable, because the model may already know what happened next.

### Phase 4: the paper forward test

Account A keeps trading on paper with the rules alone. After twelve weeks, `trader gate4` checks that its return and drawdown sit inside the range the backtest produced over twelve-week windows. Don't reset the paper account during the test: a reset breaks the equity history.

### Phase 5: live, with small money

Give the live account its own settings file, `.env.live`, with its own database:

```ini
TRADING_MODE=live
LIVE_TRADING_CONFIRMED=true
BROKER=alpaca
ACCOUNT_LABEL=L
ALPACA_API_KEY=your-live-key
ALPACA_SECRET_KEY=your-live-secret
DATABASE_URL=sqlite:///./trader-live.db
ENABLE_SCHEDULER=true
```

Run it next to paper account A with `trader --env-file ../.env.live serve --port 8002`. Start with an amount you can afford to lose. The dashboard's top band turns into hazard stripes in live mode. After three months, run `trader --env-file ../.env.live gate5 --paper sqlite:///./trader.db` before adding money.

The app buys whole shares, and a new position starts at no more than 10% of equity. In a small account that rules out the pricier ETFs: with $5,000, 10% is $500, which buys no SPY. For a fair comparison, give the paper account the same cash as live (use your third paper account, or reset A's balance after Gate 4), or choose a universe of cheaper ETFs.

## Approvals on your phone (Telegram)

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, and put the token it gives you in `TELEGRAM_BOT_TOKEN`.
2. Send your new bot any message, then open `https://api.telegram.org/bot<token>/getUpdates` and copy the number after `"chat":{"id":` into `TELEGRAM_CHAT_ID`.
3. Restart `trader serve` with the scheduler on. Each proposal arrives with Approve and Reject buttons, and only your chat can use them.

## Talk to your account in Claude (optional)

The [Alpaca MCP server](https://github.com/alpacahq/alpaca-mcp-server) lets Claude read your account and market data in a chat. It is a window onto the account, not the trading engine: this app's orders go through its own code and risk checks. Two example configs are in [docs/mcp](docs/mcp):

- `claude_desktop_config.paper.json`: paper keys, every tool.
- `claude_desktop_config.live-readonly.json`: live keys with the `trading` toolset left out, so Claude can look but not trade.

Run the MCP server only on your own computer. Never expose it to the internet.

## Commands

Run these from `backend/` with the virtual environment active. `trader --help` lists them all, and `trader <command> --help` shows each one's options.

| Command | What it does |
|---|---|
| `trader demo` | Replays recent trading days on made-up prices with the fake broker |
| `trader serve` | Runs the API and the built dashboard (add `--scheduler` to run the daily jobs) |
| `trader status` | Mode, account, kill switch and equity at a glance |
| `trader run-nightly` | Computes today's signals and creates proposals |
| `trader proposals`, `trader approve ID`, `trader reject ID` | Reviews and decides proposals |
| `trader submit` | Sends approved proposals (only inside the trading window) |
| `trader reconcile` | Runs the broker check, records equity, applies the drawdown limit |
| `trader kill-switch engage --reason "..."`, `trader kill-switch release` | Stops or resumes new orders |
| `trader fetch-data` | Saves adjusted daily closes from Alpaca to a CSV |
| `trader backtest` | Backtests on the development years, 2016 to 2022 |
| `trader smoke-test`, `gate1`, `gate2`, `compare-ab`, `gate4`, `gate5` | Gates 0 to 5 |
| `trader --env-file ../.env.b <command>` | Runs any command with another account's settings |

## Settings

Settings come from environment variables or a `.env` file in the repository root or in `backend/`. [.env.example](.env.example) lists every setting with its safe default. Relative paths (the SQLite file, `data/`, `reports/`) resolve from `backend/`, so run commands from there.

Each account keeps its own database. The first time the app opens a database, it records which mode and account it belongs to, and from then on it refuses to open it with other settings. Demo, paper and live records can't mix.

## Safety

- **Safe defaults.** Fake broker, made-up prices, paper mode, and every order waits for your approval.
- **Live needs three deliberate settings.** The app refuses to start with `TRADING_MODE=live` unless `LIVE_TRADING_CONFIRMED=true` and `BROKER=alpaca`.
- **Limits in code.** At most 1% of equity at risk per trade, a stop 8% below each entry, no new position over 10% of equity, at most 8 open positions and 10 orders a day, no new entries after a 2% daily loss, the kill switch at 10% below the peak, and no orders in the first or last 15 minutes of the session.
- **Stops live at Alpaca.** Entries are sent as one-triggers-other orders, so the stop exists at the broker as soon as the entry fills.
- **Separate ledgers.** Each database belongs to one mode and account, so demo, paper and live records never mix.
- **No double orders.** Each signal gets a unique client order ID (for example `tpA-20261113-SPY-buy`), and the broker check flags any order the ledger doesn't know.
- **Kill switch.** On the dashboard, on the command line, and automatic at the drawdown limit. Releasing it takes a deliberate confirmation (typing RELEASE on the dashboard).
- **The AI can only say no.** In veto mode it can block an entry; it can never create or enlarge an order.
- **Keys stay local.** They live only in `.env`, which git ignores. Set `API_TOKEN` before the API is reachable from any other machine.

## Run it on a server (Docker)

```bash
cp .env.example .env               # set BROKER, your keys and API_TOKEN
docker compose up -d --build
docker compose exec app trader status
```

This starts Postgres and the app with the scheduler on. The dashboard is at http://127.0.0.1:8000 on that machine. To reach it from elsewhere, put it behind an HTTPS reverse proxy such as Caddy or nginx, and set `API_TOKEN`.

Set `BROKER` and your keys before the first start, and set `POSTGRES_PASSWORD` in `.env` too. The database remembers which account it belongs to, so switching from the demo to Alpaca later means starting a fresh database: `docker compose down -v` deletes all the app's data.

## Project layout

```
backend/
  src/trader/
    strategies/   trend and momentum rules, pure functions of prices
    planner.py    target weights to whole-share orders, shared by live trading and backtests
    risk/         the limits and the order checks
    broker/       Alpaca (alpaca-py) and the fake demo broker
    data/         daily closes from Alpaca, a CSV, or made-up prices
    backtest/     backtester, metrics and Gate 1
    services/     signals, sending, broker check, kill switch, approvals, replay, gates 2 to 4
    ai/           the optional AI research desk (TradingAgents adapter)
    notify/       Telegram approvals
    api/          the FastAPI routes behind the dashboard
    cli.py        the trader command
  tests/          unit, end-to-end and live-versus-backtest parity tests
frontend/         React + Vite dashboard
docs/             architecture, gates and MCP configs
```

## Development

```bash
cd backend && pytest && ruff check . && ruff format --check .
cd frontend && npm run build        # type-checks, then builds
```

`make check` runs the same steps. GitHub Actions runs them on every push to `main` and on every pull request. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) explains how the pieces fit together.

## Put it on GitHub

```bash
cd trading-platform
git init -b main
git add .
git commit -m "Initial commit"
gh repo create trading-platform --private --source . --push
```

Without the GitHub CLI, create an empty private repository on github.com, then run `git remote add origin https://github.com/<you>/trading-platform.git` and `git push -u origin main`. Keep the repository private: it describes your strategy and risk settings. The `.gitignore` already keeps `.env`, databases and reports out.

## Disclaimer

Trading carries a risk of loss, and backtested or paper results don't guarantee live results. This software is for managing your own account and is not investment advice. Offering it to other people is a separate decision that needs a regulatory and licensing review first.

# Gates

A gate is a test you pass before taking the next step toward real money. Each gate has a command. It prints its checks, saves a JSON report in `backend/reports/`, and exits with 0 on a pass and 1 on a fail, so you can also run it from a script.

Three habits make the gates worth having:

- **Decide the pass mark before you look.** The defaults below are a sensible start. If you change one, do it before running the gate, not after seeing a result.
- **Never loosen a gate you just failed.** A fail means change the idea or fix the app, then go again.
- **Keep the reports.** They are your record of why you moved forward.

| Gate | Phase | Command | Settings it needs |
|---|---|---|---|
| 0 | Set up | `trader smoke-test` | `BROKER=alpaca`, paper keys |
| 1 | One strategy | `trader gate1` | Real prices (`DATA_SOURCE=alpaca` or `csv`) |
| 2 | The app on paper | `trader gate2` | Account A on Alpaca paper |
| 3 | AI A/B test | `trader compare-ab` | Ledgers of paper accounts A and B |
| 4 | Paper forward test | `trader gate4` | Account A on Alpaca paper, real prices |
| 5 | Live, small | `trader gate5` | The live account's settings, plus the paper ledger |

## Gate 0: the plumbing works

`trader smoke-test` runs only against an Alpaca paper account. It:

1. reads the account,
2. places a one-share limit buy at half the last price, so it cannot fill,
3. reads the order back by its client order ID,
4. cancels it and confirms the cancel.

It passes when every step succeeds. Check that the order also appears, canceled, in Alpaca's paper dashboard.

## Gate 1: the strategy has an edge

Price history is split in two:

- **Development years, 2016 to 2022.** Use `trader backtest` here as often as you like.
- **Held-out years, 2023 to today.** `trader gate1` looks at these. Look once per idea.

Every run of `gate1` is logged in `reports/holdout_log.jsonl`. From the second look at the same strategy, the command warns you, because every extra look makes a pass less trustworthy.

| Check | Passes when (defaults) | Change it with |
|---|---|---|
| `beats_benchmark` | The held-out Calmar ratio is positive and at least SPY's over the same years. If SPY lost money, the strategy must make money and beat SPY's return. | `--min-calmar-ratio` |
| `max_drawdown` | The worst held-out drawdown is 25% or less. | `--max-drawdown` |
| `enough_trades` | At least 30 closed trades over the whole run, so the result isn't luck. | `--min-trades` |
| `robust_to_parameters` | With the main parameter moved about 20% each way, each version keeps at least half the Calmar ratio. | |
| `survives_one_day_delay` | Trading one day later keeps at least 75% of the Calmar ratio. | |

The Calmar ratio is yearly return divided by the worst drawdown: return per unit of the worst pain. It suits a system with a drawdown kill switch. Costs are 5 basis points per side (`--cost-bps`).

With `DATA_SOURCE=synthetic` the prices are random, so Gate 1 should fail, and usually does. Only real prices count.

## Gate 2: the app runs cleanly on paper

Run account A on Alpaca paper with the scheduler on, approve proposals as they come, then run `trader gate2`.

| Check | Passes when |
|---|---|
| `paper_account` | `BROKER=alpaca` and `TRADING_MODE=paper`. |
| `clean_broker_checks` | Each of the last ten weekdays, counting back from the newest check, has a broker check that found nothing wrong. The scheduler runs the check every weekday at 4:30 pm ET, holidays included, so a missing day means the app wasn't running. |
| `recent` | The newest broker check is at most four days old. |
| `kill_switch_tested` | The kill switch has been engaged and then released, and is released now. |

What the broker check looks for:

- `missing_at_broker`: the ledger sent an order that Alpaca doesn't have.
- `unknown_order`: Alpaca has an order with this app's ID prefix that the ledger doesn't know. Check for a second copy of the app running against the same account.
- `unprotected_position`: a position with no protective stop at Alpaca.
- `unmanaged_position`: a position in a symbol outside the strategy's universe, such as one you bought by hand.

## Gate 3: the AI earns its cost

Account B runs the same rules as A on its own paper account and its own ledger, with `AI_MODE=veto`. The AI reviews each entry and can block it. `trader compare-ab --a <A's database URL> --b <B's database URL>` passes when:

- both ledgers share at least 60 trading days (about twelve weeks; `--min-days`),
- B's return after AI costs beats A's return, and
- B's worst drawdown is no deeper than A's.

AI costs are the number of research calls in B's ledger times `AI_COST_PER_CALL_USD`, subtracted from B's equity. Measure your real cost per call and set it before the test starts.

If B fails, keep the AI off for live trading and go forward with the rules alone. The AI is judged only on results logged going forward, because a language model may already know what happened after the dates in a backtest.

## Gate 4: paper trading matches the backtest

After twelve weeks of account A on paper, `trader gate4` compares the paper results with the backtest:

| Check | Passes when (defaults) |
|---|---|
| `paper_account` | `BROKER=alpaca` and `TRADING_MODE=paper`. |
| `enough_history` | At least 61 daily equity records (twelve weeks of five days, plus the starting day). |
| `return_in_range` | The paper return over those twelve weeks is between the 5th and 95th percentile of the backtest's twelve-week returns. |
| `drawdown_in_range` | The paper drawdown is no deeper than the backtest's twelve-week drawdowns in 95% of windows. |

The ranges come from a backtest of the same strategy and limits, from 2016 up to the day before the paper window, using every 60-trading-day window. Change the length with `--weeks`. Don't reset the paper account during the test.

If it fails, find out why before going live. Look for fills far from the prices the backtest assumed, days the app missed, proposals left unapproved, and data differences.

## Gate 5: live tracks paper

Go live with small money and keep a paper account running the same rules over the same days. After three months, run Gate 5 with the live account's settings, pointing it at the paper account's database:

```bash
trader --env-file ../.env.live gate5 --paper sqlite:///./trader.db
```


| Check | Passes when (defaults) |
|---|---|
| `live_account` | The settings are the live account's (`TRADING_MODE=live`). |
| `enough_days` | Both ledgers share at least 63 trading days (about three months; `--min-days`). |
| `return_gap` | The live and paper returns over those days are at most 2 percentage points apart. |
| `drawdown_gap` | The live drawdown is at most 2 percentage points deeper than paper's. |
| `daily_tracking` | Daily returns of the two accounts have a correlation of at least 0.9. |

Two practical notes:

- **Match the starting cash.** The app buys whole shares, and a new position starts at no more than 10% of equity. In a small account that rules out the pricier ETFs: with $5,000, 10% is $500, which buys no SPY. Start the paper comparison account with the same cash as live (Alpaca lets you reset a paper account's balance), or pick a universe of cheaper ETFs.
- **Add money in steps.** After a pass, raise the live amount gradually and keep watching the same checks.

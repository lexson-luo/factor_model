# Short-horizon factor risk framework

A full implementation of the framework in `short_horizon_factor_model.pdf` (revised: three-level
crowding and intraday factors). It includes a generator for realistic synthetic data covering
everything the framework consumes.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python generate_data.py     # ~20 s: writes raw datasets to ./data
.venv/bin/python run_framework.py     # ~65 s: runs layers 1-7 and writes ./output
.venv/bin/python -m pytest -q tests
```

## Architecture (Section 3.1)

The core model is hybrid: `r = X f + B g + u`. Cross-sectional factors `X f` are estimated by
regression each day. Time-series shock factors `B g` use observed shock series `g`, so only the
sensitivities `B` are estimated. A few statistical residual factors catch what nobody defined.

| Layer | Module | What it does |
|---|---|---|
| 1. Data | `data_loader.py` | Corporate-action adjustment, suspensions, FX, point-in-time short interest, borrow availability/utilisation, fundamentals, ETF and 13F ownership; builds the observed shock series per market (implied-vol change, liquidity shock from aggregate spread and depth, currency, rates futures, prior US session) |
| 2. Exposures | `exposures.py` | Short-horizon descriptors with MAD winsorisation and cap-weighted standardisation; liquidity includes relative tick size; five-input short-side crowding composite; events (earnings, index rebalances, option expiry, corporate actions, in-play flag); time-series betas shrunk toward the industry average; candidate and background-monitor exposures |
| 3. Factor returns | `estimation.py` | Removes `B g`, then runs daily WLS with a cap-weighted industry constraint; overnight/intraday regressions; statistical residual factors; second-stage slow-factor regression (monitoring layer) |
| 4. Risk model | `risk_model.py` | EWMA covariance including the shock series, Ledoit-Wolf shrinkage (capped), overlap-weighted pairwise correlations, eigenfactor adjustment, volatility regime adjustment, macro-announcement uplift, structural specific risk with event-day uplift (earnings, in-play) |
| 5. Attribution | `attribution.py` | Factor (incl. time-series), slow-factor, specific, FX, trading at decision price, delay/impact, fees, financing, borrow, funding; reconciliation to official P&L; Carino linking; returns-based cross-check |
| Intraday | `intraday.py` | Index futures as the intraday market factor, using Dimson (lag-corrected) intraday betas against the Epps bias; bar-level factor returns; order-flow imbalance factor (attribution only); seasonality-normalised bar risk; macro release bars; reconciles to daily |
| Global | `global_layer.py` | Cross-model covariance of US, CN, crypto and CNY with a Newey-West lag term; firm-level risk |
| 6. Diagnostics | `diagnostics.py` | ML surrogate (XGBoost on position weights, explained with exact TreeSHAP and SHAP interaction values, benchmarked in and out of sample against a linear model); SHAP attribution cross-check from a per-date return surrogate, compared bucket by bucket with the linear attribution), overlap and effective bets, regimes, missing-factor tests, drift, model releases; **factor-level crowding** (comomentum, short interest in the short leg); **shock sensitivities** (model-implied and rolling empirical) |
| Validation | `validation.py` | Bias statistics, R², VIF, stability, challengers, truth recovery, event replay; **factor selection tests** (drop-one / add-one, affected-stock R² for events, variance explained for time-series factors); time-series beta stability and shrinkage |
| Stress & limits | `stress.py`, `limits.py` | Hypothetical scenarios including vol, liquidity, FX, rates and prior-session shocks, scaled up for crowded factors; historical and model-free replays; liquidity stress; **internal crowding** (firm exit cost vs standalone); limits including expected loss in a 3-sigma vol/liquidity shock (worse of model and empirical) |
| 7. Reporting | `reporting.py` | `risk_report.md`, `pm_report.md`, `management_summary.md`, `validation_report.md`, plus charts and CSV tables |

All tunable settings live in `factor_framework/config.py`: factor taxonomy, time-series factors per
market, candidates, orthogonalisation order, half-lives, limits and scenarios.

## Revised PDF → code

| PDF section | Implementation |
|---|---|
| 2.2 Market / beta (index futures intraday) | `intraday.IntradayModel` – futures bar returns as the observed market factor; Dimson betas kept as same-bar and next-bar parts (b0 shrunk toward daily beta, b1 toward 0), each bar removing b0·futures(b) + b1·futures(b−1) |
| 2.2 Liquidity incl. relative tick size | `exposures.py` `liq_tick` component; generator floors spreads at one tick |
| 2.2 Short-side crowding (level 1) | `exposures.py`: five inputs lagged to publication, log/winsorised, standardised within market, averaged over available inputs (missing → 0), cleaned of size/volatility/liquidity in fixed order (`config.ORTHOGONALISATION`); squeeze-day check in `validation.factor_selection` |
| 2.2 Factor-level crowding (level 2) | `diagnostics.factor_crowding`; drives alerts and `stress.hypothetical_scenarios(..., crowding_mult)` |
| 2.2 Internal crowding (level 3) | `stress.internal_crowding`; shown in the risk report |
| 2.2 Events incl. in-play flag, option expiry, corporate actions, macro | `exposures.py` event dummies; macro calendar → `risk_model` macro-day uplift and intraday macro bars |
| 2.2 Volatility / liquidity shocks; currency, rates, prior-session (time-series) | `data_loader` shock series, `exposures.time_series_betas`, `estimation.ts_component`; `diagnostics.shock_sensitivities`, `rolling_shock_betas`; `limits` shock-loss limit |
| 2.2 Medium priority: ETF/basket, retail flow, order flow | ETF ownership and retail attention promoted to core styles after passing `validation.factor_selection` (`config.PROMOTED_CANDIDATES`), cleaned of size (`config.ORTHOGONALISATION`); order flow in `intraday` only |
| 2.2 Deliberately excluded: intraday seasonality as alpha | normalised in intraday bar risk (`seasonality_bias` test) |
| 2.1 Selection tests | `validation.factor_selection` (decisions in `validation_report.md`; promotion via `config.PROMOTED_CANDIDATES`) |
| 3.4 Epps effect, noisy time-series betas | Dimson intraday betas; Bayesian shrinkage of time-series betas to the industry average |
| 3.7 Risk report incl. internal crowding | `reporting.write_risk_report` |

## Synthetic data (`factor_framework/synthetic_data.py`)

Returns are simulated from a latent structure the model has to recover from raw files.

* **Markets:** 300 US stocks, 160 China A-shares (price limits, lots, limited shorting, suspensions,
  CNY) and 40 crypto tokens on two venues.
* **Time-series shocks:** GJR-GARCH implied-vol index and a liquidity state that widens spreads and
  thins depth. Reversal returns load negatively on vol/liquidity shocks (Nagel 2012). Sector-driven
  sensitivities to the dollar index / USDCNY and to 10y bond futures, and China's response to the
  prior US session.
* **Intraday:** index futures lead the cash market (small caps lag more → Epps bias); U-shaped
  volatility; FOMC bursts at 14:00; signed buy/sell volume per bar.
* **Events and flows:** unscheduled news with abnormal volume (in-play), option expiry, corporate
  actions, ETF ownership, retail-flow share, 13F ownership, borrow availability and utilisation,
  macro calendar with release times.
* **Hidden structure to discover:** an AI-theme factor outside the core model, crowding shocks,
  cross-market lead/lag, crypto spill-over.
* **Six strategies across five teams** with EOD positions, fills, prime-broker charges and official
  books. Among them: B1 hedges intraday beta with concurrent betas (so it carries real beta), D1
  adds a volatility bet at a model release, C1 is beta-short until its release, A1 is short
  volatility through its reversal exposure.

`data/truth/` holds the simulated factor returns, shocks, sensitivities, regimes and stress dates.
They are used only by validation, to check what the model recovers.
# factor_model

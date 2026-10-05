# PM attribution report - as of 2026-09-30

> **Decisions supported:** hedges and optimizer constraints, model-release approval, capacity and cost management.

Short-window attribution (20 days) is noisy - read it alongside the since-inception columns.

## A1_US_STATARB (TEAM_ALPHA)

![attribution](charts/attribution_A1_US_STATARB.png)

| index | since_inception | last_20d |
|---|---|---|
| factor | 8.85m | 1.07m |
| slow_factor | 0.97m | 63,412 |
| specific | 41.15m | 1.29m |
| fx | 0 | 0 |
| trading | -9.72m | 0.82m |
| delay_cost | 5.04m | -0.81m |
| impact_cost | -11.40m | -0.24m |
| commissions | -1.37m | -50,316 |
| financing | -0.46m | -16,390 |
| borrow | -0.54m | -20,822 |
| funding | 0 | 0 |
| TOTAL attributed | 32.51m | 2.10m |
| official | 32.54m | 2.10m |

**Largest factor P&L contributors (since inception)**

| factor | pnl_usd |
|---|---|
| st_reversal | 8.89m |
| size | -2.16m |
| crypto_beta | -1.83m |
| liquidity | 1.33m |
| ind_Health Care | -0.82m |
| stat_2 | 0.62m |
| st_momentum | 0.58m |
| ind_Semiconductors | 0.58m |

**Execution costs:** 3.61 bps of 21.4bn traded (delay -2.35, impact 5.32, fees 0.64 bps).

**Intraday decomposition (last 60 days, 30-minute bars)**

| overnight_futures | overnight_factor | overnight_residual | intraday_futures | intraday_factor | intraday_order_flow | intraday_residual | within_bar_trading | intraday_total | daily_mtm | reconciliation_diff |
|---|---|---|---|---|---|---|---|---|---|---|
| -8,539 | 1.09m | 1.09m | 51,610 | 1.32m | 1.92m | 1.31m | -1.42m | 5.35m | 5.35m | 0 |

Intraday vs daily reconciliation: max |diff| $0 per day. Futures = index-futures market factor (intraday beta); order flow = imbalance factor (attribution only).

**Intraday beta at peak position** (per $ gross): concurrent 30-minute -0.002, lag-corrected (Dimson) +0.015, daily +0.012. A gap between the first two is the Epps effect.

**Market-wide shock sensitivity (3-sigma, USD):** vol_shock model +31k / empirical -231k; liq_shock model -23k / empirical -214k; fx model -65k / empirical -14k; rates model -43k / empirical -53k

**Candidate / background monitor exposures** (std units per $ gross, not attributed): etf_ownership +0.16, retail_attention -0.03, hf_ownership_13f -0.03

**Hedging / neutralisation candidates**

| factor | exposure_usd_per_unit | risk_contrib_pct | vol_reduction_pct | suggested_tool |
|---|---|---|---|---|
| st_reversal | 19.65m | 31.2% | 14.9% | optimizer constraint |
| liquidity | -15.13m | 6.9% | 3.6% | optimizer constraint |

**What the model is effectively selecting on** (gradient-boosting surrogate, out-of-sample R² 0.24; permutation importance)

| feature | importance | std | maps_to_core_factor |
|---|---|---|---|
| reversal_5d | 0.506 | 0.008 | st_reversal |
| volatility_20d | 0.063 | 0.003 | volatility |
| log_turnover | 0.061 | 0.004 | liquidity |
| intraday_mom_3d | 0.053 | 0.002 | st_momentum |
| theme_tag | 0.036 | 0.001 | – |
| log_mcap | 0.009 | 0.001 | size |
| gap_5d | 0.006 | 0.001 | overnight_gap |
| relative_tick | 0.003 | 0.001 | liquidity |

Strongest interactions (Friedman H): log_turnover × intraday_mom_3d = 0.78; volatility_20d × log_turnover = 0.31; reversal_5d × theme_tag = 0.27

**Model release comparison (20 days before vs after)**

| version | release_date | factor | before | after | t_stat | material |
|---|---|---|---|---|---|---|
| v3.2 | 2025-09-15 | beta | -0.070 | 0.064 | 3.248 | yes |
| v3.2 | 2025-09-15 | beta_adj_net | -0.014 | 0.016 | 3.434 | yes |
| v3.2 | 2025-09-15 | crowding | 0.091 | 0.117 | 0.822 | no |
| v3.2 | 2025-09-15 | fx | -0.082 | 0.002 | 4.018 | yes |
| v3.2 | 2025-09-15 | liq_shock | -0.002 | -0.001 | 3.049 | yes |
| v3.2 | 2025-09-15 | liquidity | -0.184 | -0.182 | 0.083 | no |
| v3.2 | 2025-09-15 | overnight_gap | -0.326 | -0.331 | -0.127 | no |
| v3.2 | 2025-09-15 | rates | 0.041 | 0.166 | 3.388 | yes |
| v3.2 | 2025-09-15 | size | -0.170 | -0.088 | 1.949 | no |
| v3.2 | 2025-09-15 | st_momentum | -0.181 | -0.185 | -0.096 | no |
| v3.2 | 2025-09-15 | st_reversal | 0.496 | 0.511 | 0.513 | no |
| v3.2 | 2025-09-15 | stat_1 | 0.131 | 0.168 | 0.985 | no |
| v3.2 | 2025-09-15 | vol_shock | -0.003 | -0.003 | 0.087 | no |
| v3.2 | 2025-09-15 | volatility | 0.110 | 0.160 | 1.118 | no |

## A2_CN_STATARB (TEAM_ALPHA)

![attribution](charts/attribution_A2_CN_STATARB.png)

| index | since_inception | last_20d |
|---|---|---|
| factor | 3.01m | -87,683 |
| slow_factor | 0.73m | 8,795 |
| specific | 21.52m | 0.67m |
| fx | -7,610 | -6,005 |
| trading | -7.06m | -0.19m |
| delay_cost | 2.82m | 0.14m |
| impact_cost | -7.68m | -0.30m |
| commissions | -3.07m | -0.11m |
| financing | -0.60m | -18,684 |
| borrow | -2.34m | -79,708 |
| funding | 0 | 0 |
| TOTAL attributed | 7.34m | 28,974 |
| official | 7.34m | 28,917 |

**Largest factor P&L contributors (since inception)**

| factor | pnl_usd |
|---|---|
| st_reversal | 1.95m |
| overnight_gap | 1.89m |
| size | -1.17m |
| beta | -0.96m |
| ind_Autos | 0.60m |
| slow:earnings_yield | 0.50m |
| ind_Machinery | -0.47m |
| st_momentum | 0.42m |

**Execution costs:** 10.60 bps of 7.5bn traded (delay -3.78, impact 10.27, fees 4.10 bps).

**Market-wide shock sensitivity (3-sigma, USD):** vol_shock model -36k / empirical -85k; liq_shock model -24k / empirical -70k; fx model +37k / empirical +9k; rates model -6k / empirical -9k; us_session model +34k / empirical -34k

**Candidate / background monitor exposures** (std units per $ gross, not attributed): etf_ownership -0.25, retail_attention +0.13

**Hedging / neutralisation candidates**

| factor | exposure_usd_per_unit | risk_contrib_pct | vol_reduction_pct | suggested_tool |
|---|---|---|---|---|
| size | -9.09m | 32.4% | 17.9% | optimizer constraint |
| st_reversal | 7.86m | 21.1% | 7.5% | optimizer constraint |

**What the model is effectively selecting on** (gradient-boosting surrogate, out-of-sample R² 0.48; permutation importance)

| feature | importance | std | maps_to_core_factor |
|---|---|---|---|
| short_interest | 0.487 | 0.003 | crowding |
| reversal_5d | 0.193 | 0.008 | st_reversal |
| log_mcap | 0.064 | 0.003 | size |
| utilisation | 0.018 | 0.002 | crowding |
| intraday_mom_3d | 0.012 | 0.002 | st_momentum |
| borrow_fee | 0.012 | 0.001 | crowding |
| sector | 0.009 | 0.001 | industry |
| volatility_20d | 0.005 | 0.000 | volatility |

Strongest interactions (Friedman H): short_interest × reversal_5d = 1.31; short_interest × log_mcap = 1.00; short_interest × utilisation = 1.00

**Model release comparison (20 days before vs after)**

| version | release_date | factor | before | after | t_stat | material |
|---|---|---|---|---|---|---|
| v2.3 | 2025-05-12 | beta | 0.177 | 0.082 | -1.184 | no |
| v2.3 | 2025-05-12 | beta_adj_net | 0.021 | -0.003 | -1.292 | no |
| v2.3 | 2025-05-12 | crowding | -0.030 | 0.146 | 4.509 | yes |
| v2.3 | 2025-05-12 | fx | 0.101 | -0.045 | -8.282 | yes |
| v2.3 | 2025-05-12 | liq_shock | 0.004 | 0.004 | -0.494 | no |
| v2.3 | 2025-05-12 | liquidity | 0.014 | 0.016 | 0.063 | no |
| v2.3 | 2025-05-12 | overnight_gap | -0.289 | -0.263 | 0.512 | no |
| v2.3 | 2025-05-12 | rates | -0.160 | 0.081 | 5.173 | yes |
| v2.3 | 2025-05-12 | size | 0.001 | -0.249 | -6.374 | yes |
| v2.3 | 2025-05-12 | st_momentum | -0.139 | -0.119 | 0.528 | no |
| v2.3 | 2025-05-12 | st_reversal | 0.419 | 0.409 | -0.255 | no |
| v2.3 | 2025-05-12 | stat_1 | 0.028 | -0.024 | -2.285 | no |
| v2.3 | 2025-05-12 | us_session | 0.005 | 0.017 | 1.676 | no |
| v2.3 | 2025-05-12 | vol_shock | -0.004 | -0.006 | -1.178 | no |
| v2.3 | 2025-05-12 | volatility | 0.030 | 0.140 | 2.672 | no |

## B1_US_INTRADAY (TEAM_BRAVO)

![attribution](charts/attribution_B1_US_INTRADAY.png)

| index | since_inception | last_20d |
|---|---|---|
| factor | -1.24m | -44,009 |
| slow_factor | 71,709 | 3,881 |
| specific | -0.23m | -88,802 |
| fx | 0 | 0 |
| trading | 55.65m | 1.44m |
| delay_cost | -0.71m | -53,836 |
| impact_cost | -38.39m | -1.42m |
| commissions | -2.79m | -98,756 |
| financing | -85,832 | -2,462 |
| borrow | -53,394 | -2,202 |
| funding | 0 | 0 |
| TOTAL attributed | 12.22m | -0.27m |
| official | 12.21m | -0.27m |

**Largest factor P&L contributors (since inception)**

| factor | pnl_usd |
|---|---|
| size | -0.76m |
| crypto_beta | -0.25m |
| market | 0.23m |
| rates | -0.20m |
| overnight_gap | -0.16m |
| vol_shock | 0.15m |
| beta | -0.13m |
| st_momentum | 92,031 |

**Execution costs:** 9.59 bps of 43.7bn traded (delay 0.16, impact 8.79, fees 0.64 bps).

**Intraday decomposition (last 60 days, 30-minute bars)**

| overnight_futures | overnight_factor | overnight_residual | intraday_futures | intraday_factor | intraday_order_flow | intraday_residual | within_bar_trading | intraday_total | daily_mtm | reconciliation_diff |
|---|---|---|---|---|---|---|---|---|---|---|
| 16,618 | -0.15m | 4,523 | -28,578 | -4.28m | 6.44m | 2.74m | -3.37m | 1.37m | 1.37m | -0 |

Intraday vs daily reconciliation: max |diff| $0 per day. Futures = index-futures market factor (intraday beta); order flow = imbalance factor (attribution only).

**Intraday beta at peak position** (per $ gross): concurrent 30-minute -0.015, lag-corrected (Dimson) +0.046, daily -0.006. A gap between the first two is the Epps effect.

**Market-wide shock sensitivity (3-sigma, USD):** vol_shock model -35k / empirical -100k; liq_shock model -9k / empirical -55k; fx model -4k / empirical +0k; rates model -3k / empirical -3k

**Candidate / background monitor exposures** (std units per $ gross, not attributed): etf_ownership -0.47, retail_attention +0.76, hf_ownership_13f +0.07

**Hedging / neutralisation candidates**

| factor | exposure_usd_per_unit | risk_contrib_pct | vol_reduction_pct | suggested_tool |
|---|---|---|---|---|
| size | -5.06m | 38.7% | 22.7% | optimizer constraint |
| volatility | 2.52m | 11.4% | 7.3% | optimizer constraint |

**Model release comparison (20 days before vs after)**

| version | release_date | factor | before | after | t_stat | material |
|---|---|---|---|---|---|---|
| v5.1 | 2025-03-03 | beta | -0.040 | -0.133 | -1.454 | no |
| v5.1 | 2025-03-03 | beta_adj_net | 0.046 | 0.048 | 0.244 | no |
| v5.1 | 2025-03-03 | crowding | 0.012 | 0.062 | 0.926 | no |
| v5.1 | 2025-03-03 | fx | 0.008 | -0.041 | -2.262 | no |
| v5.1 | 2025-03-03 | liq_shock | -0.002 | -0.004 | -1.735 | no |
| v5.1 | 2025-03-03 | liquidity | 0.049 | 0.092 | 1.031 | no |
| v5.1 | 2025-03-03 | overnight_gap | -0.369 | -0.426 | -0.718 | no |
| v5.1 | 2025-03-03 | rates | 0.011 | 0.002 | -0.177 | no |
| v5.1 | 2025-03-03 | size | -0.626 | -0.639 | -0.265 | no |
| v5.1 | 2025-03-03 | st_momentum | 0.423 | 0.325 | -1.589 | no |
| v5.1 | 2025-03-03 | st_reversal | -0.097 | -0.041 | 0.679 | no |
| v5.1 | 2025-03-03 | stat_1 | 0.078 | 0.059 | -0.407 | no |
| v5.1 | 2025-03-03 | vol_shock | -0.012 | -0.012 | -0.178 | no |
| v5.1 | 2025-03-03 | volatility | 0.053 | 0.044 | -0.152 | no |

## C1_US_EVENT (TEAM_CHARLIE)

![attribution](charts/attribution_C1_US_EVENT.png)

| index | since_inception | last_20d |
|---|---|---|
| factor | -0.83m | 0.42m |
| slow_factor | -0.13m | -62,586 |
| specific | 11.04m | -0.40m |
| fx | 0 | 0 |
| trading | -4.02m | -16,332 |
| delay_cost | 1.06m | 16,908 |
| impact_cost | -1.84m | -4,929 |
| commissions | -0.22m | -675 |
| financing | -0.21m | -8,772 |
| borrow | -0.38m | -3,271 |
| funding | 0 | 0 |
| TOTAL attributed | 4.47m | -64,346 |
| official | 4.44m | -64,389 |

**Largest factor P&L contributors (since inception)**

| factor | pnl_usd |
|---|---|
| st_reversal | -1.94m |
| beta | -1.10m |
| ind_Financials | 0.96m |
| size | 0.95m |
| volatility | 0.80m |
| liquidity | -0.71m |
| slow:earnings_yield | 0.71m |
| slow:quality | -0.66m |

**Execution costs:** 2.87 bps of 3.5bn traded (delay -3.02, impact 5.25, fees 0.64 bps).

**Intraday decomposition (last 60 days, 30-minute bars)**

| overnight_futures | overnight_factor | overnight_residual | intraday_futures | intraday_factor | intraday_order_flow | intraday_residual | within_bar_trading | intraday_total | daily_mtm | reconciliation_diff |
|---|---|---|---|---|---|---|---|---|---|---|
| -26,896 | 0.11m | -0.60m | -26,058 | 0.34m | 0.49m | -16,387 | -0.27m | 8,269 | 8,269 | 0 |

Intraday vs daily reconciliation: max |diff| $0 per day. Futures = index-futures market factor (intraday beta); order flow = imbalance factor (attribution only).

**Intraday beta at peak position** (per $ gross): concurrent 30-minute -0.050, lag-corrected (Dimson) -0.051, daily -0.018. A gap between the first two is the Epps effect.

**Market-wide shock sensitivity (3-sigma, USD):** vol_shock model +13k / empirical +105k; liq_shock model -2k / empirical +93k; fx model -11k / empirical -21k; rates model +2k / empirical -59k

**Candidate / background monitor exposures** (std units per $ gross, not attributed): etf_ownership +0.08, retail_attention -0.01, hf_ownership_13f -0.04

**Hedging / neutralisation candidates**

| factor | exposure_usd_per_unit | risk_contrib_pct | vol_reduction_pct | suggested_tool |
|---|---|---|---|---|
| size | 5.11m | 4.4% | 2.4% | optimizer constraint |
| st_reversal | 2.71m | 1.7% | 1.1% | optimizer constraint |

**What the model is effectively selecting on** (gradient-boosting surrogate, out-of-sample R² -0.11; permutation importance)

| feature | importance | std | maps_to_core_factor |
|---|---|---|---|
| short_interest | 0.024 | 0.007 | crowding |
| log_mcap | 0.014 | 0.003 | size |
| gap_5d | 0.004 | 0.002 | overnight_gap |
| reversal_5d | 0.003 | 0.001 | st_reversal |
| volatility_20d | 0.002 | 0.001 | volatility |
| utilisation | 0.001 | 0.002 | crowding |
| in_play | 0.000 | 0.000 | in_play |
| shortable | 0.000 | 0.000 | – |

Strongest interactions (Friedman H): short_interest × reversal_5d = 1.12; short_interest × log_turnover = 1.00; gap_5d × log_turnover = 1.00

**Model release comparison (20 days before vs after)**

| version | release_date | factor | before | after | t_stat | material |
|---|---|---|---|---|---|---|
| v1.4 | 2026-01-12 | beta | -0.411 | -0.176 | 4.773 | yes |
| v1.4 | 2026-01-12 | beta_adj_net | -0.106 | -0.053 | 3.677 | yes |
| v1.4 | 2026-01-12 | crowding | 0.061 | 0.147 | 3.031 | yes |
| v1.4 | 2026-01-12 | fx | 0.061 | -0.006 | -3.398 | yes |
| v1.4 | 2026-01-12 | liq_shock | 0.003 | 0.003 | -0.352 | no |
| v1.4 | 2026-01-12 | liquidity | 0.061 | -0.064 | -4.034 | yes |
| v1.4 | 2026-01-12 | overnight_gap | -0.054 | 0.454 | 4.016 | yes |
| v1.4 | 2026-01-12 | rates | -0.256 | -0.118 | 4.587 | yes |
| v1.4 | 2026-01-12 | size | 0.107 | 0.139 | 2.481 | no |
| v1.4 | 2026-01-12 | st_momentum | 0.012 | 0.038 | 0.398 | no |
| v1.4 | 2026-01-12 | st_reversal | 0.029 | -0.325 | -3.309 | yes |
| v1.4 | 2026-01-12 | stat_1 | -0.035 | 0.034 | 1.084 | no |
| v1.4 | 2026-01-12 | vol_shock | 0.003 | 0.003 | -0.227 | no |
| v1.4 | 2026-01-12 | volatility | 0.044 | -0.014 | -1.158 | no |

## D1_US_CROWDING (TEAM_DELTA)

![attribution](charts/attribution_D1_US_CROWDING.png)

| index | since_inception | last_20d |
|---|---|---|
| factor | 5.00m | 0.86m |
| slow_factor | 0.22m | 26,076 |
| specific | 16.29m | 0.58m |
| fx | 0 | 0 |
| trading | -1.78m | -0.10m |
| delay_cost | 0.65m | 6,890 |
| impact_cost | -3.14m | -75,755 |
| commissions | -0.40m | -13,859 |
| financing | -0.36m | -13,226 |
| borrow | -1.79m | -47,174 |
| funding | 0 | 0 |
| TOTAL attributed | 14.69m | 1.22m |
| official | 14.68m | 1.22m |

**Largest factor P&L contributors (since inception)**

| factor | pnl_usd |
|---|---|
| volatility | 3.39m |
| st_momentum | 1.22m |
| crowding | 0.71m |
| ind_Utilities | -0.62m |
| ind_Energy | 0.49m |
| ind_Communication | -0.39m |
| rates | -0.37m |
| beta | -0.37m |

**Execution costs:** 4.60 bps of 6.3bn traded (delay -1.04, impact 4.99, fees 0.64 bps).

**Intraday decomposition (last 60 days, 30-minute bars)**

| overnight_futures | overnight_factor | overnight_residual | intraday_futures | intraday_factor | intraday_order_flow | intraday_residual | within_bar_trading | intraday_total | daily_mtm | reconciliation_diff |
|---|---|---|---|---|---|---|---|---|---|---|
| -19,399 | 0.42m | 0.45m | -35,938 | 1.31m | 0.48m | 0.45m | -0.27m | 2.79m | 2.79m | 0 |

Intraday vs daily reconciliation: max |diff| $0 per day. Futures = index-futures market factor (intraday beta); order flow = imbalance factor (attribution only).

**Intraday beta at peak position** (per $ gross): concurrent 30-minute -0.043, lag-corrected (Dimson) -0.014, daily -0.024. A gap between the first two is the Epps effect.

**Market-wide shock sensitivity (3-sigma, USD):** vol_shock model -106k / empirical -101k; liq_shock model -41k / empirical -66k; fx model -48k / empirical -20k; rates model -27k / empirical -39k

**Candidate / background monitor exposures** (std units per $ gross, not attributed): etf_ownership -0.15, retail_attention +0.31, hf_ownership_13f -0.39

**Hedging / neutralisation candidates**

| factor | exposure_usd_per_unit | risk_contrib_pct | vol_reduction_pct | suggested_tool |
|---|---|---|---|---|
| crowding | -40.63m | 27.4% | 14.1% | optimizer constraint |
| volatility | 24.66m | 23.5% | 12.6% | optimizer constraint |

**What the model is effectively selecting on** (gradient-boosting surrogate, out-of-sample R² 0.60; permutation importance)

| feature | importance | std | maps_to_core_factor |
|---|---|---|---|
| short_interest | 0.590 | 0.006 | crowding |
| volatility_20d | 0.201 | 0.003 | volatility |
| theme_tag | 0.054 | 0.003 | – |
| log_mcap | 0.039 | 0.001 | size |
| sector | 0.021 | 0.002 | industry |
| utilisation | 0.016 | 0.002 | crowding |
| beta | 0.011 | 0.002 | beta |
| relative_tick | 0.007 | 0.000 | liquidity |

Strongest interactions (Friedman H): short_interest × log_turnover = 1.00; short_interest × log_mcap = 1.00; log_mcap × log_turnover = 1.00

**Model release comparison (20 days before vs after)**

| version | release_date | factor | before | after | t_stat | material |
|---|---|---|---|---|---|---|
| v2.0 | 2025-06-02 | beta | -0.179 | -0.222 | -3.783 | yes |
| v2.0 | 2025-06-02 | beta_adj_net | -0.047 | -0.050 | -0.945 | no |
| v2.0 | 2025-06-02 | crowding | -1.025 | -0.901 | 7.711 | yes |
| v2.0 | 2025-06-02 | fx | -0.121 | -0.095 | 3.339 | yes |
| v2.0 | 2025-06-02 | liq_shock | -0.002 | -0.002 | -5.174 | yes |
| v2.0 | 2025-06-02 | liquidity | 0.125 | 0.062 | -7.093 | yes |
| v2.0 | 2025-06-02 | overnight_gap | -0.069 | -0.000 | 2.816 | no |
| v2.0 | 2025-06-02 | rates | -0.148 | -0.137 | 0.927 | no |
| v2.0 | 2025-06-02 | size | 0.053 | -0.137 | -14.685 | yes |
| v2.0 | 2025-06-02 | st_momentum | -0.011 | 0.051 | 1.586 | no |
| v2.0 | 2025-06-02 | st_reversal | 0.095 | -0.020 | -3.211 | yes |
| v2.0 | 2025-06-02 | stat_1 | 0.194 | 0.187 | -0.433 | no |
| v2.0 | 2025-06-02 | vol_shock | 0.002 | -0.004 | -10.157 | yes |
| v2.0 | 2025-06-02 | volatility | -0.038 | 0.443 | 10.695 | yes |

## E1_CRYPTO_CARRY (TEAM_ECHO)

![attribution](charts/attribution_E1_CRYPTO_CARRY.png)

| index | since_inception | last_20d |
|---|---|---|
| factor | 5.04m | -0.24m |
| slow_factor | 0 | 0 |
| specific | 70.96m | 1.35m |
| fx | 0 | 0 |
| trading | -23.56m | -0.94m |
| delay_cost | 13.97m | 1.06m |
| impact_cost | -43.48m | -2.14m |
| commissions | -3.93m | -99,887 |
| financing | 0 | 0 |
| borrow | 0 | 0 |
| funding | 1.70m | 31,055 |
| TOTAL attributed | 20.68m | -0.97m |
| official | 20.68m | -0.97m |

**Largest factor P&L contributors (since inception)**

| factor | pnl_usd |
|---|---|
| funding | -1.95m |
| sec_Meme | 1.83m |
| size | 1.16m |
| sec_DeFi | 1.15m |
| sec_Infrastructure | 1.05m |
| sec_Smart Contract L1 | 0.94m |
| sec_Exchange Token | 0.70m |
| market | -0.57m |

**Execution costs:** 34.02 bps of 9.8bn traded (delay -14.21, impact 44.23, fees 4.00 bps).

**Hedging / neutralisation candidates**

| factor | exposure_usd_per_unit | risk_contrib_pct | vol_reduction_pct | suggested_tool |
|---|---|---|---|---|
| funding | -9.96m | 43.4% | 23.7% | optimizer constraint |
| btc_beta | -5.19m | 5.6% | 0.8% | index futures / beta hedge |

**Model release comparison (20 days before vs after)**

| version | release_date | factor | before | after | t_stat | material |
|---|---|---|---|---|---|---|
| v1.6 | 2025-12-01 | beta_adj_net | -0.049 | 0.008 | 2.870 | no |
| v1.6 | 2025-12-01 | btc_beta | -0.193 | 0.012 | 2.722 | no |
| v1.6 | 2025-12-01 | funding | -0.646 | -0.436 | 4.277 | yes |
| v1.6 | 2025-12-01 | momentum | -0.122 | 0.074 | 4.038 | yes |
| v1.6 | 2025-12-01 | size | 0.019 | 0.080 | 1.041 | no |
| v1.6 | 2025-12-01 | stat_1 | -0.049 | -0.103 | -1.234 | no |

## Returns-based cross-check (C1_US_EVENT)

Holdings-based exposures vs a rolling regression of strategy returns on factor returns (Sharpe 1992). Agreement in sign confirms the holdings pipeline; the returns-based estimates are noisier and lag.

| factor | returns_based | holdings_based |
|---|---|---|
| beta | -0.248 | -0.425 |
| market | -0.073 | -0.002 |
| st_reversal | -0.157 | -0.195 |
| volatility | 0.154 | 0.070 |

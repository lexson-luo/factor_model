# PM attribution report - as of 2026-09-30

> **Decisions supported:** hedges and optimizer constraints, model-release approval, capacity and cost management.

Short-window attribution (20 days) is noisy - read it alongside the since-inception columns.

## A1_US_STATARB (TEAM_ALPHA)

![attribution](charts/attribution_A1_US_STATARB.png)

| index | since_inception | last_20d |
|---|---|---|
| factor | 8.58m | 1.03m |
| slow_factor | 1.08m | 41,880 |
| specific | 41.31m | 1.35m |
| basis | 0 | 0 |
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
| st_reversal | 10.01m |
| size | -2.27m |
| crypto_beta | -1.78m |
| liquidity | 1.29m |
| ind_Health Care | -0.80m |
| st_momentum | 0.69m |
| ind_Semiconductors | 0.66m |
| rates | -0.61m |

**Execution costs:** 3.61 bps of 21.4bn traded (delay -2.35, impact 5.32, fees 0.64 bps).

**Intraday decomposition (last 60 days, 30-minute bars)**[^intraday-factors]

| overnight_futures | overnight_factor | overnight_residual | intraday_futures | intraday_factor | intraday_order_flow | intraday_residual | within_bar_trading | intraday_total | daily_mtm | reconciliation_diff |
|---|---|---|---|---|---|---|---|---|---|---|
| -8,539 | 1.04m | 1.13m | 30,817 | 1.38m | 1.93m | 1.26m | -1.42m | 5.35m | 5.35m | 0 |

Intraday vs daily reconciliation: max |diff| $0 per day. Futures = index-futures market factor (intraday beta); order flow = imbalance factor (attribution only).

**Intraday beta at peak position** (per $ gross): concurrent 30-minute -0.002, lag-corrected (Dimson) +0.015, daily +0.012. A gap between the first two is the Epps effect.

**Market-wide shock sensitivity (3-sigma, USD):** vol_shock model +38k / empirical -231k; liq_shock model -16k / empirical -212k; fx model -67k / empirical -14k; rates model -50k / empirical -53k

**Candidate / background monitor exposures** (std units per $ gross, not attributed): hf_ownership_13f -0.03

**Hedging / neutralisation candidates**

| factor | exposure_usd_per_unit | risk_contrib_pct | vol_reduction_pct | suggested_tool |
|---|---|---|---|---|
| st_reversal | 19.65m | 17.2% | 8.9% | optimizer constraint |
| liquidity | -15.13m | 6.0% | 3.3% | optimizer constraint |

**What the model is effectively selecting on** (XGBoost surrogate of position weight / GMV; R² 0.33 in sample, 0.23 out of sample on the last 30% of dates)

| feature | mean_abs_shap_bp | shap_share | perm_importance | maps_to_core_factor |
|---|---|---|---|---|
| reversal_5d | 15.566 | 34.3% | 0.558 | st_reversal |
| log_turnover | 6.277 | 13.8% | 0.065 | liquidity |
| intraday_mom_3d | 5.540 | 12.2% | 0.062 | st_momentum |
| volatility_20d | 5.345 | 11.8% | 0.063 | volatility |
| theme_tag | 3.991 | 8.8% | 0.036 | – |
| gap_5d | 2.213 | 4.9% | 0.011 | overnight_gap |
| sector | 1.562 | 3.4% | 0.000 | industry |
| log_mcap | 1.532 | 3.4% | 0.010 | size |

Grouped by core factor (SHAP summed within a group, so correlated inputs are not split): st_reversal 35%; liquidity 14%; st_momentum 12%; volatility 12%; unmapped:theme_tag 9%

Strongest interactions (mean |SHAP interaction|, bp): reversal_5d × intraday_mom_3d = 2.1; reversal_5d × gap_5d = 1.1; reversal_5d × log_turnover = 1.0

Fit by target (linear = ridge on the same features; trees adding little over linear means the selection is close to a linear screen):

| target | model | metric | in_sample | out_of_sample |
|---|---|---|---|---|
| weight | xgboost | R² | 0.325 | 0.234 |
| weight | linear | R² | 0.231 | 0.221 |
| rank | xgboost | R² | 0.321 | 0.240 |
| rank | linear | R² | 0.231 | 0.224 |
| held_only | xgboost | R² | 0.364 | 0.261 |
| held_only | linear | R² | 0.271 | 0.252 |
| held | xgboost | AUC | 0.797 | 0.588 |

**SHAP cross-check of the linear attribution** (return surrogate: per-date additive XGBoost, cross-fitted R² 0.097 vs 0.098 for a cross-fitted linear model on the same features and 0.308 in-sample for the factor model). Both columns add up to the same holdings P&L. The cross-fitted surrogate cannot absorb a stock's own return, so its characteristic buckets are smaller and its residual larger: read agreement from the daily correlation and sign, not the size of the totals.

| bucket | linear_usd | shap_usd | diff_usd | daily_corr |
|---|---|---|---|---|
| base | 39,435 | -0.13m | -0.17m | 0.461 |
| industry | -80,442 | 1.51m | 1.59m | 0.681 |
| st_reversal | 10.01m | 2.02m | -8.00m | 0.657 |
| volatility | 27,354 | -1.26m | -1.28m | 0.699 |
| liquidity | 1.29m | 1.05m | -0.24m | 0.717 |
| size | -2.27m | -0.30m | 1.97m | 0.640 |
| crowding | 90,654 | -0.10m | -0.19m | 0.688 |
| beta | -0.11m | -4,384 | 0.11m | 0.717 |
| earnings | 0.40m | -40,262 | -0.44m | 0.229 |
| in_play | -9,891 | 0 | 9,891 | – |
| overnight_gap | 74,125 | 1.28m | 1.21m | 0.510 |
| st_momentum | 0.69m | 0.37m | -0.32m | 0.471 |
| etf_ownership | -0.40m | -0.11m | 0.29m | 0.614 |
| retail_attention | -0.29m | 0.11m | 0.40m | -0.076 |
| unmapped:theme_tag | 0 | -0.36m | -0.36m | – |
| other (linear only) | -0.89m | 0 | 0.89m | – |
| slow (linear only) | 1.08m | 0 | -1.08m | – |
| residual | 41.31m | 46.70m | 5.40m | 0.649 |
| outside_estu | 0 | 0.24m | 0.24m | – |
| total | 50.97m | 50.97m | 0 | 1.000 |

Decision view (weight-side SHAP: P&L of the slice of the book each characteristic explains; unexplained weights +43.72m): st_reversal +9.00m; st_momentum -1.21m; unmapped:theme_tag +0.93m; liquidity -0.63m; industry -0.60m.

**Model release comparison (20 days before vs after)**

| version | release_date | factor | before | after | t_stat | material |
|---|---|---|---|---|---|---|
| v3.2 | 2025-09-15 | beta | -0.070 | 0.064 | 3.248 | yes |
| v3.2 | 2025-09-15 | beta_adj_net | -0.014 | 0.016 | 3.434 | yes |
| v3.2 | 2025-09-15 | crowding | 0.091 | 0.117 | 0.822 | no |
| v3.2 | 2025-09-15 | fx | -0.080 | 0.003 | 3.976 | yes |
| v3.2 | 2025-09-15 | liq_shock | -0.004 | -0.002 | 4.039 | yes |
| v3.2 | 2025-09-15 | liquidity | -0.184 | -0.182 | 0.083 | no |
| v3.2 | 2025-09-15 | overnight_gap | -0.326 | -0.331 | -0.127 | no |
| v3.2 | 2025-09-15 | rates | 0.040 | 0.166 | 3.426 | yes |
| v3.2 | 2025-09-15 | size | -0.170 | -0.088 | 1.949 | no |
| v3.2 | 2025-09-15 | st_momentum | -0.181 | -0.185 | -0.096 | no |
| v3.2 | 2025-09-15 | st_reversal | 0.496 | 0.511 | 0.513 | no |
| v3.2 | 2025-09-15 | stat_1 | 0.111 | 0.157 | 1.252 | no |
| v3.2 | 2025-09-15 | vol_shock | -0.003 | -0.003 | -0.247 | no |
| v3.2 | 2025-09-15 | volatility | 0.110 | 0.160 | 1.118 | no |

## A2_CN_STATARB (TEAM_ALPHA)

![attribution](charts/attribution_A2_CN_STATARB.png)

| index | since_inception | last_20d |
|---|---|---|
| factor | 3.54m | -75,221 |
| slow_factor | 0.86m | 25,643 |
| specific | 20.88m | 0.64m |
| basis | 0 | 0 |
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
| st_reversal | 2.07m |
| overnight_gap | 1.81m |
| size | -1.22m |
| beta | -0.90m |
| ind_Autos | 0.60m |
| st_momentum | 0.60m |
| ind_Machinery | -0.45m |
| ind_Electronics | -0.40m |

**Execution costs:** 10.60 bps of 7.5bn traded (delay -3.78, impact 10.27, fees 4.10 bps).

**Market-wide shock sensitivity (3-sigma, USD):** vol_shock model -29k / empirical -85k; liq_shock model -18k / empirical -65k; fx model +62k / empirical +9k; rates model -26k / empirical -9k; us_session model +23k / empirical -34k

**Hedging / neutralisation candidates**

| factor | exposure_usd_per_unit | risk_contrib_pct | vol_reduction_pct | suggested_tool |
|---|---|---|---|---|
| size | -9.09m | 33.0% | 19.0% | optimizer constraint |
| st_reversal | 7.86m | 15.0% | 8.7% | optimizer constraint |

**What the model is effectively selecting on** (XGBoost surrogate of position weight / GMV; R² 0.55 in sample, 0.48 out of sample on the last 30% of dates)

| feature | mean_abs_shap_bp | shap_share | perm_importance | maps_to_core_factor |
|---|---|---|---|---|
| short_interest | 24.148 | 23.7% | 0.167 | crowding |
| utilisation | 23.517 | 23.1% | 0.163 | crowding |
| reversal_5d | 19.364 | 19.0% | 0.241 | st_reversal |
| log_mcap | 9.714 | 9.5% | 0.069 | size |
| intraday_mom_3d | 6.149 | 6.0% | 0.018 | st_momentum |
| gap_5d | 4.154 | 4.1% | 0.007 | overnight_gap |
| etf_ownership | 3.001 | 2.9% | 0.005 | etf_ownership |
| borrow_fee | 2.821 | 2.8% | 0.002 | crowding |

Grouped by core factor (SHAP summed within a group, so correlated inputs are not split): crowding 50%; st_reversal 19%; size 10%; st_momentum 6%; overnight_gap 4%

Strongest interactions (mean |SHAP interaction|, bp): reversal_5d × gap_5d = 3.3; reversal_5d × short_interest = 3.1; reversal_5d × intraday_mom_3d = 3.1

Fit by target (linear = ridge on the same features; trees adding little over linear means the selection is close to a linear screen):

| target | model | metric | in_sample | out_of_sample |
|---|---|---|---|---|
| weight | xgboost | R² | 0.549 | 0.479 |
| weight | linear | R² | 0.421 | 0.464 |
| rank | xgboost | R² | 0.515 | 0.461 |
| rank | linear | R² | 0.408 | 0.459 |
| held_only | xgboost | R² | 0.646 | 0.584 |
| held_only | linear | R² | 0.516 | 0.565 |
| held | xgboost | AUC | 0.850 | 0.758 |

**SHAP cross-check of the linear attribution** (return surrogate: per-date additive XGBoost, cross-fitted R² 0.055 vs 0.054 for a cross-fitted linear model on the same features and 0.363 in-sample for the factor model). Both columns add up to the same holdings P&L. The cross-fitted surrogate cannot absorb a stock's own return, so its characteristic buckets are smaller and its residual larger: read agreement from the daily correlation and sign, not the size of the totals.

| bucket | linear_usd | shap_usd | diff_usd | daily_corr |
|---|---|---|---|---|
| base | -17,447 | -0.29m | -0.28m | 0.738 |
| industry | 0.32m | 1.03m | 0.71m | 0.523 |
| st_reversal | 2.07m | 1.66m | -0.41m | 0.666 |
| volatility | -0.30m | -0.76m | -0.46m | 0.606 |
| liquidity | 0.24m | -0.15m | -0.39m | 0.364 |
| size | -1.22m | -0.16m | 1.06m | 0.778 |
| crowding | -0.15m | -0.85m | -0.69m | 0.094 |
| beta | -0.90m | -0.50m | 0.40m | 0.758 |
| earnings | 0.18m | 14,676 | -0.16m | -0.075 |
| in_play | -3,692 | 0 | 3,692 | – |
| overnight_gap | 1.81m | 1.24m | -0.57m | 0.433 |
| st_momentum | 0.60m | 31,856 | -0.57m | 0.335 |
| etf_ownership | 39,463 | -0.56m | -0.59m | 0.336 |
| retail_attention | 99,193 | -0.16m | -0.26m | 0.130 |
| other (linear only) | 0.77m | 0 | -0.77m | – |
| slow (linear only) | 0.86m | 0 | -0.86m | – |
| residual | 20.88m | 24.63m | 3.76m | 0.652 |
| outside_estu | 0 | 87,906 | 87,906 | – |
| total | 25.27m | 25.27m | 0 | 1.000 |

Disagreement (daily correlation below 0.3 on a material bucket): crowding (corr +0.09)

Decision view (weight-side SHAP: P&L of the slice of the book each characteristic explains; unexplained weights +25.93m): st_reversal +1.89m; crowding -1.41m; overnight_gap -0.40m; st_momentum -0.33m; industry -0.20m.

**Model release comparison (20 days before vs after)**

| version | release_date | factor | before | after | t_stat | material |
|---|---|---|---|---|---|---|
| v2.3 | 2025-05-12 | beta | 0.177 | 0.082 | -1.184 | no |
| v2.3 | 2025-05-12 | beta_adj_net | 0.021 | -0.003 | -1.292 | no |
| v2.3 | 2025-05-12 | crowding | -0.030 | 0.146 | 4.509 | yes |
| v2.3 | 2025-05-12 | fx | 0.101 | -0.046 | -8.266 | yes |
| v2.3 | 2025-05-12 | liq_shock | 0.006 | 0.005 | -0.488 | no |
| v2.3 | 2025-05-12 | liquidity | 0.014 | 0.016 | 0.063 | no |
| v2.3 | 2025-05-12 | overnight_gap | -0.289 | -0.263 | 0.512 | no |
| v2.3 | 2025-05-12 | rates | -0.162 | 0.076 | 5.152 | yes |
| v2.3 | 2025-05-12 | size | 0.001 | -0.249 | -6.374 | yes |
| v2.3 | 2025-05-12 | st_momentum | -0.139 | -0.119 | 0.528 | no |
| v2.3 | 2025-05-12 | st_reversal | 0.419 | 0.409 | -0.255 | no |
| v2.3 | 2025-05-12 | stat_1 | 0.037 | -0.010 | -1.992 | no |
| v2.3 | 2025-05-12 | us_session | 0.007 | 0.017 | 1.590 | no |
| v2.3 | 2025-05-12 | vol_shock | -0.004 | -0.006 | -1.525 | no |
| v2.3 | 2025-05-12 | volatility | 0.030 | 0.140 | 2.672 | no |

## B1_US_INTRADAY (TEAM_BRAVO)

![attribution](charts/attribution_B1_US_INTRADAY.png)

| index | since_inception | last_20d |
|---|---|---|
| factor | -1.17m | -23,734 |
| slow_factor | 53,308 | -4,781 |
| specific | -0.28m | -0.10m |
| basis | 0 | 0 |
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
| size | -0.77m |
| crypto_beta | -0.25m |
| market | 0.24m |
| rates | -0.21m |
| vol_shock | 0.17m |
| overnight_gap | -0.16m |
| beta | -0.14m |
| retail_attention | 98,388 |

**Execution costs:** 9.59 bps of 43.7bn traded (delay 0.16, impact 8.79, fees 0.64 bps).

**Intraday decomposition (last 60 days, 30-minute bars)**[^intraday-factors]

| overnight_futures | overnight_factor | overnight_residual | intraday_futures | intraday_factor | intraday_order_flow | intraday_residual | within_bar_trading | intraday_total | daily_mtm | reconciliation_diff |
|---|---|---|---|---|---|---|---|---|---|---|
| 16,618 | -0.14m | -5,400 | -10,417 | -4.40m | 6.45m | 2.84m | -3.37m | 1.37m | 1.37m | -0 |

Intraday vs daily reconciliation: max |diff| $0 per day. Futures = index-futures market factor (intraday beta); order flow = imbalance factor (attribution only).

**Intraday beta at peak position** (per $ gross): concurrent 30-minute -0.015, lag-corrected (Dimson) +0.046, daily -0.006. A gap between the first two is the Epps effect.

**Market-wide shock sensitivity (3-sigma, USD):** vol_shock model -35k / empirical -100k; liq_shock model -8k / empirical -59k; fx model -4k / empirical +0k; rates model -1k / empirical -3k

**Candidate / background monitor exposures** (std units per $ gross, not attributed): hf_ownership_13f +0.07

**Hedging / neutralisation candidates**

| factor | exposure_usd_per_unit | risk_contrib_pct | vol_reduction_pct | suggested_tool |
|---|---|---|---|---|
| size | -5.06m | 42.1% | 26.3% | optimizer constraint |
| volatility | 2.52m | 10.6% | 6.8% | optimizer constraint |

**Model release comparison (20 days before vs after)**

| version | release_date | factor | before | after | t_stat | material |
|---|---|---|---|---|---|---|
| v5.1 | 2025-03-03 | beta | -0.040 | -0.133 | -1.454 | no |
| v5.1 | 2025-03-03 | beta_adj_net | 0.046 | 0.048 | 0.244 | no |
| v5.1 | 2025-03-03 | crowding | 0.012 | 0.062 | 0.926 | no |
| v5.1 | 2025-03-03 | fx | 0.008 | -0.035 | -2.221 | no |
| v5.1 | 2025-03-03 | liq_shock | -0.001 | -0.006 | -1.977 | no |
| v5.1 | 2025-03-03 | liquidity | 0.049 | 0.092 | 1.031 | no |
| v5.1 | 2025-03-03 | overnight_gap | -0.369 | -0.426 | -0.718 | no |
| v5.1 | 2025-03-03 | rates | 0.011 | 0.003 | -0.150 | no |
| v5.1 | 2025-03-03 | size | -0.626 | -0.639 | -0.265 | no |
| v5.1 | 2025-03-03 | st_momentum | 0.423 | 0.325 | -1.589 | no |
| v5.1 | 2025-03-03 | st_reversal | -0.097 | -0.041 | 0.679 | no |
| v5.1 | 2025-03-03 | stat_1 | 0.080 | 0.065 | -0.322 | no |
| v5.1 | 2025-03-03 | vol_shock | -0.014 | -0.013 | 0.067 | no |
| v5.1 | 2025-03-03 | volatility | 0.053 | 0.044 | -0.152 | no |

## C1_US_EVENT (TEAM_CHARLIE)

![attribution](charts/attribution_C1_US_EVENT.png)

| index | since_inception | last_20d |
|---|---|---|
| factor | -0.92m | 0.50m |
| slow_factor | -0.17m | -77,074 |
| specific | 11.17m | -0.47m |
| basis | 0 | 0 |
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
| st_reversal | -2.36m |
| beta | -1.30m |
| ind_Financials | 1.07m |
| size | 0.94m |
| volatility | 0.78m |
| overnight_gap | 0.71m |
| liquidity | -0.69m |
| slow:earnings_yield | 0.62m |

**Execution costs:** 2.87 bps of 3.5bn traded (delay -3.02, impact 5.25, fees 0.64 bps).

**Intraday decomposition (last 60 days, 30-minute bars)**[^intraday-factors]

| overnight_futures | overnight_factor | overnight_residual | intraday_futures | intraday_factor | intraday_order_flow | intraday_residual | within_bar_trading | intraday_total | daily_mtm | reconciliation_diff |
|---|---|---|---|---|---|---|---|---|---|---|
| -26,896 | 0.10m | -0.59m | -28,274 | 0.39m | 0.49m | -60,004 | -0.27m | 8,269 | 8,269 | 0 |

Intraday vs daily reconciliation: max |diff| $0 per day. Futures = index-futures market factor (intraday beta); order flow = imbalance factor (attribution only).

**Intraday beta at peak position** (per $ gross): concurrent 30-minute -0.050, lag-corrected (Dimson) -0.051, daily -0.018. A gap between the first two is the Epps effect.

**Market-wide shock sensitivity (3-sigma, USD):** vol_shock model +17k / empirical +105k; liq_shock model -1k / empirical +82k; fx model -12k / empirical -21k; rates model +3k / empirical -59k

**Candidate / background monitor exposures** (std units per $ gross, not attributed): hf_ownership_13f -0.04

**Hedging / neutralisation candidates**

| factor | exposure_usd_per_unit | risk_contrib_pct | vol_reduction_pct | suggested_tool |
|---|---|---|---|---|
| size | 5.11m | 3.8% | 1.7% | optimizer constraint |
| liquidity | -5.20m | 1.4% | 0.9% | optimizer constraint |

**What the model is effectively selecting on** (XGBoost surrogate of position weight / GMV; R² 0.42 in sample, -0.10 out of sample on the last 30% of dates)

*The surrogate does not generalise (out-of-sample R² below 0.05): the attributions below describe an overfit model and are not used to propose factors.*

| feature | mean_abs_shap_bp | shap_share | perm_importance | maps_to_core_factor |
|---|---|---|---|---|
| beta | 14.647 | 26.5% | -0.014 | beta |
| sector | 8.300 | 15.0% | -0.043 | industry |
| etf_ownership | 6.044 | 10.9% | 0.010 | etf_ownership |
| log_mcap | 4.337 | 7.8% | 0.046 | size |
| short_interest | 4.034 | 7.3% | 0.039 | crowding |
| relative_tick | 3.143 | 5.7% | -0.003 | liquidity |
| utilisation | 2.634 | 4.8% | 0.005 | crowding |
| log_turnover | 2.163 | 3.9% | -0.010 | liquidity |

Grouped by core factor (SHAP summed within a group, so correlated inputs are not split): beta 29%; industry 16%; etf_ownership 12%; crowding 10%; size 9%

Strongest interactions (mean |SHAP interaction|, bp): beta × sector = 5.4; etf_ownership × sector = 4.9; beta × etf_ownership = 4.2

Fit by target (linear = ridge on the same features; trees adding little over linear means the selection is close to a linear screen):

| target | model | metric | in_sample | out_of_sample |
|---|---|---|---|---|
| weight | xgboost | R² | 0.424 | -0.103 |
| weight | linear | R² | 0.059 | -0.026 |
| rank | xgboost | R² | 0.297 | -0.108 |
| rank | linear | R² | 0.076 | -0.044 |
| held_only | xgboost | R² | 0.666 | -0.187 |
| held_only | linear | R² | 0.184 | -0.065 |
| held | xgboost | AUC | 0.825 | 0.674 |

**SHAP cross-check of the linear attribution** (return surrogate: per-date additive XGBoost, cross-fitted R² 0.097 vs 0.098 for a cross-fitted linear model on the same features and 0.309 in-sample for the factor model). Both columns add up to the same holdings P&L. The cross-fitted surrogate cannot absorb a stock's own return, so its characteristic buckets are smaller and its residual larger: read agreement from the daily correlation and sign, not the size of the totals.

| bucket | linear_usd | shap_usd | diff_usd | daily_corr |
|---|---|---|---|---|
| base | -83,218 | 0.23m | 0.31m | 0.362 |
| industry | 0.39m | 1.02m | 0.63m | 0.658 |
| st_reversal | -2.36m | -0.31m | 2.06m | 0.494 |
| volatility | 0.78m | 0.83m | 47,855 | 0.444 |
| liquidity | -0.69m | -0.36m | 0.34m | 0.465 |
| size | 0.94m | 0.13m | -0.82m | 0.562 |
| crowding | 0.35m | 0.20m | -0.15m | 0.590 |
| beta | -1.30m | -0.87m | 0.43m | 0.762 |
| earnings | -2,696 | -3,111 | -415 | -0.260 |
| in_play | -0.25m | 0 | 0.25m | – |
| overnight_gap | 0.71m | -0.10m | -0.82m | 0.445 |
| st_momentum | 0.34m | 0.12m | -0.22m | 0.483 |
| etf_ownership | -0.24m | -0.15m | 86,252 | 0.484 |
| retail_attention | 74,441 | -0.11m | -0.18m | 0.620 |
| unmapped:theme_tag | 0 | 0.15m | 0.15m | – |
| other (linear only) | 0.42m | 0 | -0.42m | – |
| slow (linear only) | -0.17m | 0 | 0.17m | – |
| residual | 11.17m | 9.44m | -1.74m | 0.875 |
| outside_estu | 0 | -0.14m | -0.14m | – |
| total | 10.08m | 10.08m | -0 | 1.000 |

Decision view (weight-side SHAP: P&L of the slice of the book each characteristic explains; unexplained weights +11.04m): overnight_gap -1.16m; st_reversal -0.88m; beta -0.52m; etf_ownership +0.51m; size +0.50m. *Weight surrogate does not generalise; treat as indicative only.*

**Model release comparison (20 days before vs after)**

| version | release_date | factor | before | after | t_stat | material |
|---|---|---|---|---|---|---|
| v1.4 | 2026-01-12 | beta | -0.411 | -0.176 | 4.773 | yes |
| v1.4 | 2026-01-12 | beta_adj_net | -0.106 | -0.053 | 3.677 | yes |
| v1.4 | 2026-01-12 | crowding | 0.061 | 0.147 | 3.031 | yes |
| v1.4 | 2026-01-12 | fx | 0.061 | -0.006 | -3.419 | yes |
| v1.4 | 2026-01-12 | liq_shock | 0.003 | 0.004 | 0.807 | no |
| v1.4 | 2026-01-12 | liquidity | 0.061 | -0.064 | -4.034 | yes |
| v1.4 | 2026-01-12 | overnight_gap | -0.054 | 0.454 | 4.016 | yes |
| v1.4 | 2026-01-12 | rates | -0.257 | -0.117 | 4.637 | yes |
| v1.4 | 2026-01-12 | size | 0.107 | 0.139 | 2.481 | no |
| v1.4 | 2026-01-12 | st_momentum | 0.012 | 0.038 | 0.398 | no |
| v1.4 | 2026-01-12 | st_reversal | 0.029 | -0.325 | -3.309 | yes |
| v1.4 | 2026-01-12 | stat_1 | -0.004 | 0.066 | 1.139 | no |
| v1.4 | 2026-01-12 | vol_shock | 0.004 | 0.003 | -0.503 | no |
| v1.4 | 2026-01-12 | volatility | 0.044 | -0.014 | -1.158 | no |

## D1_US_CROWDING (TEAM_DELTA)

![attribution](charts/attribution_D1_US_CROWDING.png)

| index | since_inception | last_20d |
|---|---|---|
| factor | 5.05m | 0.89m |
| slow_factor | 0.20m | 23,621 |
| specific | 16.26m | 0.55m |
| basis | 0 | 0 |
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
| volatility | 3.43m |
| st_momentum | 1.34m |
| crowding | 0.78m |
| ind_Utilities | -0.63m |
| beta | -0.49m |
| ind_Energy | 0.45m |
| liq_shock | 0.40m |
| ind_Communication | -0.40m |

**Execution costs:** 4.60 bps of 6.3bn traded (delay -1.04, impact 4.99, fees 0.64 bps).

**Intraday decomposition (last 60 days, 30-minute bars)**[^intraday-factors]

| overnight_futures | overnight_factor | overnight_residual | intraday_futures | intraday_factor | intraday_order_flow | intraday_residual | within_bar_trading | intraday_total | daily_mtm | reconciliation_diff |
|---|---|---|---|---|---|---|---|---|---|---|
| -19,399 | 0.40m | 0.46m | -40,505 | 1.31m | 0.48m | 0.45m | -0.27m | 2.79m | 2.79m | 0 |

Intraday vs daily reconciliation: max |diff| $0 per day. Futures = index-futures market factor (intraday beta); order flow = imbalance factor (attribution only).

**Intraday beta at peak position** (per $ gross): concurrent 30-minute -0.043, lag-corrected (Dimson) -0.014, daily -0.024. A gap between the first two is the Epps effect.

**Market-wide shock sensitivity (3-sigma, USD):** vol_shock model -105k / empirical -101k; liq_shock model -29k / empirical -65k; fx model -44k / empirical -20k; rates model -28k / empirical -39k

**Candidate / background monitor exposures** (std units per $ gross, not attributed): hf_ownership_13f -0.39

**Hedging / neutralisation candidates**

| factor | exposure_usd_per_unit | risk_contrib_pct | vol_reduction_pct | suggested_tool |
|---|---|---|---|---|
| volatility | 24.66m | 24.7% | 14.2% | optimizer constraint |
| crowding | -40.63m | 19.9% | 10.7% | optimizer constraint |

**What the model is effectively selecting on** (XGBoost surrogate of position weight / GMV; R² 0.72 in sample, 0.61 out of sample on the last 30% of dates)

| feature | mean_abs_shap_bp | shap_share | perm_importance | maps_to_core_factor |
|---|---|---|---|---|
| short_interest | 21.821 | 44.3% | 0.599 | crowding |
| volatility_20d | 6.960 | 14.1% | 0.197 | volatility |
| theme_tag | 4.608 | 9.3% | 0.053 | – |
| utilisation | 4.389 | 8.9% | 0.013 | crowding |
| log_mcap | 1.816 | 3.7% | 0.039 | size |
| sector | 1.633 | 3.3% | 0.021 | industry |
| beta | 1.610 | 3.3% | 0.010 | beta |
| borrow_fee | 1.317 | 2.7% | 0.001 | crowding |

Grouped by core factor (SHAP summed within a group, so correlated inputs are not split): crowding 55%; volatility 15%; unmapped:theme_tag 10%; size 4%; industry 3%

Strongest interactions (mean |SHAP interaction|, bp): volatility_20d × beta = 1.7; volatility_20d × short_interest = 1.6; log_mcap × short_interest = 1.2

Fit by target (linear = ridge on the same features; trees adding little over linear means the selection is close to a linear screen):

| target | model | metric | in_sample | out_of_sample |
|---|---|---|---|---|
| weight | xgboost | R² | 0.716 | 0.606 |
| weight | linear | R² | 0.595 | 0.520 |
| rank | xgboost | R² | 0.679 | 0.606 |
| rank | linear | R² | 0.570 | 0.514 |
| held_only | xgboost | R² | 0.757 | 0.645 |
| held_only | linear | R² | 0.658 | 0.572 |
| held | xgboost | AUC | 0.819 | 0.723 |

**SHAP cross-check of the linear attribution** (return surrogate: per-date additive XGBoost, cross-fitted R² 0.097 vs 0.098 for a cross-fitted linear model on the same features and 0.308 in-sample for the factor model). Both columns add up to the same holdings P&L. The cross-fitted surrogate cannot absorb a stock's own return, so its characteristic buckets are smaller and its residual larger: read agreement from the daily correlation and sign, not the size of the totals.

| bucket | linear_usd | shap_usd | diff_usd | daily_corr |
|---|---|---|---|---|
| base | -0.12m | 8,866 | 0.13m | 0.463 |
| industry | -0.56m | 0.89m | 1.45m | 0.710 |
| st_reversal | -47,110 | -0.12m | -69,867 | 0.584 |
| volatility | 3.43m | 1.02m | -2.41m | 0.833 |
| liquidity | -0.16m | -20,648 | 0.14m | 0.587 |
| size | 26,331 | 0.22m | 0.19m | 0.689 |
| crowding | 0.78m | -0.40m | -1.19m | 0.882 |
| beta | -0.49m | -0.26m | 0.23m | 0.625 |
| earnings | 79,925 | 15,253 | -64,672 | 0.100 |
| in_play | -38,213 | 0 | 38,213 | – |
| overnight_gap | 0.13m | 35,034 | -96,130 | 0.468 |
| st_momentum | 1.34m | 71,214 | -1.27m | 0.349 |
| etf_ownership | -50,958 | 0.36m | 0.42m | 0.545 |
| retail_attention | -91,673 | -9,805 | 81,867 | 0.464 |
| unmapped:theme_tag | 0 | -0.31m | -0.31m | – |
| other (linear only) | 0.80m | 0 | -0.80m | – |
| slow (linear only) | 0.20m | 0 | -0.20m | – |
| residual | 16.26m | 19.90m | 3.64m | 0.587 |
| outside_estu | 0 | 98,622 | 98,622 | – |
| total | 21.51m | 21.51m | 0 | 1.000 |

Decision view (weight-side SHAP: P&L of the slice of the book each characteristic explains; unexplained weights +19.81m): unmapped:theme_tag +0.89m; volatility +0.60m; st_reversal +0.58m; size -0.39m; st_momentum -0.17m.

**Model release comparison (20 days before vs after)**

| version | release_date | factor | before | after | t_stat | material |
|---|---|---|---|---|---|---|
| v2.0 | 2025-06-02 | beta | -0.179 | -0.222 | -3.783 | yes |
| v2.0 | 2025-06-02 | beta_adj_net | -0.047 | -0.050 | -0.945 | no |
| v2.0 | 2025-06-02 | crowding | -1.025 | -0.901 | 7.711 | yes |
| v2.0 | 2025-06-02 | fx | -0.118 | -0.092 | 3.294 | yes |
| v2.0 | 2025-06-02 | liq_shock | -0.003 | -0.004 | -4.343 | yes |
| v2.0 | 2025-06-02 | liquidity | 0.125 | 0.062 | -7.093 | yes |
| v2.0 | 2025-06-02 | overnight_gap | -0.069 | -0.000 | 2.816 | no |
| v2.0 | 2025-06-02 | rates | -0.148 | -0.138 | 0.902 | no |
| v2.0 | 2025-06-02 | size | 0.053 | -0.137 | -14.685 | yes |
| v2.0 | 2025-06-02 | st_momentum | -0.011 | 0.051 | 1.586 | no |
| v2.0 | 2025-06-02 | st_reversal | 0.095 | -0.020 | -3.211 | yes |
| v2.0 | 2025-06-02 | stat_1 | 0.194 | 0.183 | -0.712 | no |
| v2.0 | 2025-06-02 | vol_shock | 0.002 | -0.004 | -10.263 | yes |
| v2.0 | 2025-06-02 | volatility | -0.038 | 0.443 | 10.695 | yes |

## E1_CRYPTO_CARRY (TEAM_ECHO)

![attribution](charts/attribution_E1_CRYPTO_CARRY.png)

| index | since_inception | last_20d |
|---|---|---|
| factor | 5.04m | -0.24m |
| slow_factor | 0 | 0 |
| specific | 68.47m | 1.30m |
| basis | 2.49m | 45,787 |
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
| funding | -9.96m | 33.3% | 17.7% | optimizer constraint |
| btc_beta | -5.19m | 2.1% | -1.5% | index futures / beta hedge |

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
| beta | -0.340 | -0.425 |
| market | -0.046 | -0.002 |
| st_reversal | -0.151 | -0.195 |
| volatility | 0.178 | 0.070 |

## Appendix A: intraday factor P&L by factor

Split of `overnight_factor` and `intraday_factor` from the intraday decomposition, summed over the last 60 days of 30-minute bars. Factor returns are re-estimated bar by bar on the daily exposures, so these are not the daily factor P&L figures. Index futures and order flow are separate buckets and are not shown. Factors with no P&L are omitted. Daily rows: `tables/intraday_factor_attribution.csv`.

### A1_US_STATARB

| factor | group | overnight_pnl | intraday_pnl | total_pnl |
|---|---|---|---|---|
| st_reversal | style | 1.71m | 0.79m | 2.49m |
| crypto_beta | market_specific | -0.32m | -86,859 | -0.41m |
| size | style | -25,511 | 0.25m | 0.23m |
| ind_Semiconductors | industry | 85,645 | 0.10m | 0.19m |
| ind_Industrials | industry | -0.10m | -67,967 | -0.17m |
| crowding | style | 50,282 | 0.12m | 0.17m |
| liquidity | style | 72,302 | 64,270 | 0.14m |
| etf_ownership | style | -58,366 | -45,513 | -0.10m |
| st_momentum | style | -0.22m | 0.12m | -94,694 |
| beta | style | 25,667 | 66,369 | 92,036 |
| stat_2 | statistical | -63,154 | -22,376 | -85,530 |
| ind_Utilities | industry | 40,751 | 35,627 | 76,378 |
| ind_Energy | industry | -38,792 | -32,752 | -71,544 |
| earnings | event | 54,908 | 331 | 55,240 |
| market | market | -1,661 | -48,165 | -49,826 |
| ind_Consumer Discretionary | industry | -6,847 | -30,870 | -37,717 |
| ind_Health Care | industry | -27,255 | 54,077 | 26,822 |
| ind_Consumer Staples | industry | -15,798 | -9,430 | -25,228 |
| retail_attention | style | 13,657 | 11,336 | 24,993 |
| option_expiry | event | -1,349 | -21,871 | -23,220 |
| ind_Materials | industry | 41,844 | -18,882 | 22,962 |
| stat_1 | statistical | -8,497 | -12,980 | -21,477 |
| ind_Communication | industry | -7,305 | -11,947 | -19,253 |
| volatility | style | -68,908 | 81,670 | 12,762 |
| overnight_gap | style | -94,910 | 99,977 | 5,067 |
| in_play | event | 5,102 | -1,745 | 3,357 |
| ind_Technology | industry | -21,613 | 19,169 | -2,445 |
| corporate_action | event | 2,613 | -269 | 2,344 |
| index_rebalance | event | 639 | 325 | 964 |
| ind_Financials | industry | 23,405 | -23,835 | -429 |
| TOTAL |  | 1.04m | 1.38m | 2.42m |

### B1_US_INTRADAY

| factor | group | overnight_pnl | intraday_pnl | total_pnl |
|---|---|---|---|---|
| crypto_beta | market_specific | -61,106 | -0.73m | -0.79m |
| size | style | -89,832 | -0.67m | -0.76m |
| volatility | style | 3,103 | -0.39m | -0.39m |
| st_reversal | style | -26,878 | -0.30m | -0.33m |
| ind_Energy | industry | -16,129 | -0.30m | -0.32m |
| ind_Communication | industry | -6,864 | -0.30m | -0.30m |
| ind_Utilities | industry | 1,267 | -0.30m | -0.30m |
| ind_Financials | industry | 894 | -0.22m | -0.22m |
| stat_1 | statistical | 13,440 | -0.21m | -0.20m |
| ind_Health Care | industry | -13,637 | -0.18m | -0.19m |
| ind_Technology | industry | 9,520 | -0.19m | -0.18m |
| crowding | style | -15,908 | -0.10m | -0.12m |
| beta | style | 24,619 | 94,519 | 0.12m |
| liquidity | style | 1,359 | -0.11m | -0.11m |
| ind_Industrials | industry | 163 | -0.11m | -0.11m |
| ind_Consumer Discretionary | industry | -5,046 | -85,922 | -90,968 |
| option_expiry | event | -3,420 | -60,978 | -64,399 |
| st_momentum | style | 27,661 | -82,368 | -54,707 |
| ind_Materials | industry | -4,409 | -37,488 | -41,896 |
| overnight_gap | style | -4,473 | 38,447 | 33,975 |
| stat_2 | statistical | 2,373 | -34,874 | -32,501 |
| market | market | -674 | -30,561 | -31,235 |
| retail_attention | style | 7,338 | -35,011 | -27,673 |
| ind_Semiconductors | industry | 7,799 | -29,427 | -21,628 |
| earnings | event | -4,135 | -14,392 | -18,527 |
| ind_Consumer Staples | industry | 6,512 | -11,746 | -5,234 |
| in_play | event | -4,863 | -77 | -4,941 |
| corporate_action | event | -506 | -1,039 | -1,546 |
| index_rebalance | event | 0 | 574 | 574 |
| etf_ownership | style | 7,882 | -7,610 | 272 |
| TOTAL |  | -0.14m | -4.40m | -4.54m |

### C1_US_EVENT

| factor | group | overnight_pnl | intraday_pnl | total_pnl |
|---|---|---|---|---|
| overnight_gap | style | -0.22m | -0.15m | -0.37m |
| st_momentum | style | 0.12m | 0.16m | 0.27m |
| size | style | 0.12m | 58,100 | 0.18m |
| ind_Communication | industry | -50,217 | -82,614 | -0.13m |
| crypto_beta | market_specific | 86,969 | 37,588 | 0.12m |
| ind_Semiconductors | industry | 92,306 | 16,224 | 0.11m |
| retail_attention | style | 17,370 | 74,905 | 92,275 |
| ind_Utilities | industry | 49,248 | 31,769 | 81,016 |
| ind_Energy | industry | 52,654 | 19,608 | 72,262 |
| ind_Consumer Discretionary | industry | 25,662 | 46,163 | 71,825 |
| beta | style | 79,338 | -12,720 | 66,618 |
| crowding | style | -28,756 | -34,437 | -63,194 |
| ind_Health Care | industry | -16,844 | -37,058 | -53,902 |
| option_expiry | event | 31,866 | 14,361 | 46,227 |
| ind_Technology | industry | -18,089 | -27,996 | -46,085 |
| ind_Industrials | industry | -23,571 | -16,067 | -39,638 |
| etf_ownership | style | -31,485 | -5,876 | -37,361 |
| in_play | event | 25,518 | 11,078 | 36,596 |
| ind_Materials | industry | 1,300 | 34,679 | 35,979 |
| stat_1 | statistical | 2,682 | 31,305 | 33,986 |
| liquidity | style | 46,046 | -12,071 | 33,976 |
| ind_Financials | industry | -20,683 | -6,737 | -27,419 |
| market | market | -979 | -24,099 | -25,078 |
| st_reversal | style | -0.29m | 0.32m | 24,853 |
| stat_2 | statistical | 40,195 | -27,829 | 12,366 |
| ind_Consumer Staples | industry | 5,731 | -15,860 | -10,129 |
| corporate_action | event | 4,169 | 3,870 | 8,038 |
| index_rebalance | event | -1,010 | -138 | -1,148 |
| volatility | style | 12,907 | -12,661 | 246 |
| earnings | event | -79 | 139 | 60 |
| TOTAL |  | 0.10m | 0.39m | 0.49m |

### D1_US_CROWDING

| factor | group | overnight_pnl | intraday_pnl | total_pnl |
|---|---|---|---|---|
| crypto_beta | market_specific | 0.72m | 0.67m | 1.38m |
| size | style | -0.36m | -0.10m | -0.46m |
| volatility | style | 42,880 | 0.36m | 0.40m |
| st_momentum | style | 24,130 | 0.32m | 0.35m |
| ind_Communication | industry | -0.10m | -0.12m | -0.23m |
| st_reversal | style | -55,143 | -0.16m | -0.21m |
| ind_Technology | industry | 0.11m | 77,055 | 0.19m |
| crowding | style | -20,092 | 0.21m | 0.19m |
| beta | style | 0.15m | 24,739 | 0.17m |
| ind_Industrials | industry | -37,980 | -67,140 | -0.11m |
| ind_Energy | industry | 56,039 | 33,290 | 89,328 |
| ind_Utilities | industry | -34,380 | -42,389 | -76,769 |
| etf_ownership | style | 32,536 | 41,720 | 74,256 |
| option_expiry | event | -25,535 | -30,974 | -56,509 |
| ind_Semiconductors | industry | 32,263 | 23,891 | 56,154 |
| ind_Financials | industry | -9,723 | -29,433 | -39,155 |
| stat_2 | statistical | -27,479 | -3,652 | -31,131 |
| ind_Consumer Staples | industry | 9,577 | 19,310 | 28,887 |
| overnight_gap | style | -76,684 | 0.10m | 26,246 |
| earnings | event | -19,772 | -5,846 | -25,618 |
| ind_Materials | industry | 2,669 | -21,783 | -19,114 |
| ind_Consumer Discretionary | industry | -2,270 | -13,962 | -16,232 |
| stat_1 | statistical | 8,553 | 613 | 9,165 |
| ind_Health Care | industry | -1,328 | 9,479 | 8,151 |
| corporate_action | event | -2,056 | -2,907 | -4,963 |
| liquidity | style | -13,924 | 17,621 | 3,697 |
| retail_attention | style | 1,826 | -4,866 | -3,040 |
| market | market | -1,258 | 3,785 | 2,527 |
| in_play | event | 681 | -1,431 | -750 |
| index_rebalance | event | 624 | 36 | 660 |
| TOTAL |  | 0.40m | 1.31m | 1.71m |

[^intraday-factors]: `overnight_factor` and `intraday_factor` broken down by factor in Appendix A (daily rows in `tables/intraday_factor_attribution.csv`).

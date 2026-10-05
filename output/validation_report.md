# Model validation report

> **Question answered:** are the risk forecasts calibrated, does attribution reconcile, and is anything missing?

## 1. Explanatory power

| index | named | hybrid |
|---|---|---|
| US | 0.294 | 0.324 |
| CN | 0.343 | 0.363 |
| CRYPTO | 0.430 | 0.448 |

| strategy | factor_share_of_hold_var | corr_factor_vs_hold |
|---|---|---|
| A1_US_STATARB | 84.1% | 0.912 |
| A2_CN_STATARB | 76.5% | 0.865 |
| B1_US_INTRADAY | 74.7% | 0.856 |
| C1_US_EVENT | 50.9% | 0.713 |
| D1_US_CROWDING | 87.7% | 0.936 |
| E1_CRYPTO_CARRY | 17.0% | 0.534 |

## 2. Calibration: bias statistics (target 1, band 1 ± √(2/T))

### Strategy portfolios (most important)

| strategy | mean_bias | within_band_pct | band | n_windows | realised_vol_ann | pred_vol_ann |
|---|---|---|---|---|---|---|
| A1_US_STATARB | 0.804 | 37.5% | 0.178 | 8 | 3.38m | 4.30m |
| A2_CN_STATARB | 0.833 | 50.0% | 0.178 | 8 | 1.90m | 2.25m |
| B1_US_INTRADAY | 0.839 | 62.5% | 0.178 | 8 | 0.46m | 0.55m |
| C1_US_EVENT | 0.930 | 100.0% | 0.178 | 8 | 2.67m | 2.70m |
| D1_US_CROWDING | 0.827 | 37.5% | 0.178 | 8 | 3.10m | 3.76m |
| E1_CRYPTO_CARRY | 0.725 | 15.4% | 0.178 | 13 | 3.35m | 4.71m |

![bias](charts/bias_A1_US_STATARB.png)

### Factors

**US**

| group | mean_bias | within_band_pct |
|---|---|---|
| event | 1.545 | 16.7% |
| industry | 1.061 | 83.8% |
| market | 1.165 | 33.3% |
| market_specific | 1.165 | 55.6% |
| statistical | 0.766 | 31.2% |
| style | 0.822 | 47.2% |
| timeseries | 1.009 | 50.0% |

**CN**

| group | mean_bias | within_band_pct |
|---|---|---|
| event | 1.191 | 50.0% |
| industry | 1.039 | 82.2% |
| market | 1.217 | 55.6% |
| market_specific | 1.011 | 100.0% |
| statistical | 0.800 | 42.9% |
| style | 0.832 | 55.6% |
| timeseries | 1.004 | 37.8% |

**CRYPTO**

| group | mean_bias | within_band_pct |
|---|---|---|
| event | – | – |
| industry | 1.056 | 73.0% |
| market | 1.088 | 35.7% |
| statistical | 0.958 | 53.8% |
| style | 0.943 | 83.9% |

### Specific risk

| index | mean_bias | within_band_pct | band | n_windows |
|---|---|---|---|---|
| US | 1.007 | 70.0% | 0.178 | 1,336 |
| CN | 1.025 | 84.3% | 0.178 | 1,335 |
| CRYPTO | 1.103 | 58.2% | 0.178 | 600 |

## 3. Benchmark comparison (challengers)

The in-house model must beat a market+industry baseline and a pure PCA model on calibration and explanatory power.

| model | n_factors | mean_cs_r2 | strategy_bias_mean | strategy_bias_mad_from_1 | strategy_within_band_pct | first_valid |
|---|---|---|---|---|---|---|
| in-house core (named + statistical) | 32 | 0.324 | 0.850 | 0.150 | 59.4% | 2024-04-01 |
| baseline: market + industry | 12 | 0.167 | 1.496 | 0.496 | 21.9% | 2024-04-01 |
| challenger: PCA (10 factors) | 11 | 0.196 | 1.205 | 0.205 | 53.1% | 2024-06-25 |

## 4. Recovery of the simulated factor returns (synthetic data only)

**US**

| factor | corr_with_true | n |
|---|---|---|
| market | 0.832 | 628 |
| ind_Technology | 0.728 | 628 |
| ind_Semiconductors | 0.620 | 628 |
| ind_Communication | 0.786 | 628 |
| ind_Consumer Discretionary | 0.698 | 628 |
| ind_Consumer Staples | 0.730 | 628 |
| ind_Health Care | 0.789 | 628 |
| ind_Financials | 0.734 | 628 |
| ind_Industrials | 0.793 | 628 |
| ind_Energy | 0.776 | 628 |
| ind_Materials | 0.709 | 628 |
| ind_Utilities | 0.779 | 628 |
| size | 0.618 | 628 |
| liquidity | 0.731 | 628 |
| volatility | 0.862 | 628 |
| st_reversal | 0.728 | 628 |
| st_momentum | 0.589 | 628 |
| overnight_gap | 0.585 | 628 |
| crowding | 0.863 | 628 |
| earnings | 0.299 | 207 |
| option_expiry | 0.510 | 30 |
| corporate_action | – | 30 |
| in_play | 0.237 | 66 |
| crypto_beta | 0.887 | 628 |
| stat_1 vs hidden theme | 0.825 | 508 |
| stat_2 vs hidden theme | 0.429 | 508 |

**CN**

| factor | corr_with_true | n |
|---|---|---|
| market | 0.890 | 606 |
| ind_Banks | 0.791 | 606 |
| ind_Non-bank Financials | 0.720 | 606 |
| ind_Electronics | 0.726 | 606 |
| ind_Computers | 0.692 | 606 |
| ind_Pharma | 0.721 | 606 |
| ind_Food & Beverage | 0.667 | 606 |
| ind_Machinery | 0.705 | 606 |
| ind_Autos | 0.749 | 606 |
| ind_Chemicals | 0.771 | 606 |
| ind_Real Estate | 0.779 | 606 |
| size | 0.648 | 606 |
| liquidity | 0.589 | 606 |
| volatility | 0.842 | 606 |
| st_reversal | 0.719 | 606 |
| st_momentum | 0.480 | 606 |
| overnight_gap | 0.539 | 606 |
| crowding | 0.615 | 606 |
| earnings | 0.082 | 130 |
| option_expiry | 0.220 | 30 |
| corporate_action | – | 37 |
| limit_hit | 0.451 | 188 |
| stat_1 vs hidden theme | 0.096 | 486 |
| stat_2 vs hidden theme | 0.044 | 486 |

## 4b. Factor selection tests (Section 2.1)

Each factor must earn its place on our own data. Core factors: drop-one marginal R² (on the affected stock-days for sparse event factors) and share of estimable days with |t| > 2. Time-series factors: share of remaining variance explained by B·g (their cross-sectional R² is understated because industry factors absorb their sector pattern). Candidates: add-one. Residual correlation reduction is across this market's strategies.

| market | factor | test | marginal_r2 | pct_days_abs_t_gt_2 | ann_vol | resid_corr_reduction | max_abs_z_on_squeeze_days | decision |
|---|---|---|---|---|---|---|---|---|
| US | beta | core (drop-one) | 0.011 | 0.319 | 5.4% | -0.002 | 2.687 | keep in core |
| US | size | core (drop-one) | 0.018 | 0.464 | 6.2% | -0.013 | 0.462 | keep in core |
| US | liquidity | core (drop-one) | 0.007 | 0.246 | 3.2% | -0.007 | 4.280 | keep in core |
| US | volatility | core (drop-one) | 0.016 | 0.448 | 5.3% | 0.027 | 4.462 | keep in core |
| US | st_reversal | core (drop-one) | 0.008 | 0.271 | 8.5% | 0.022 | 2.957 | keep in core |
| US | st_momentum | core (drop-one) | 0.006 | 0.219 | 5.2% | -0.006 | 0.956 | keep in core |
| US | overnight_gap | core (drop-one) | 0.006 | 0.184 | 5.3% | 0.021 | 1.280 | keep in core |
| US | crowding | core (drop-one) | 0.013 | 0.402 | 4.4% | -0.020 | 5.097 | keep in core |
| US | earnings | core (drop-one, affected stock-days) | 0.076 | 0.380 | 20.9% | -0.001 | 0.443 | keep in core |
| US | index_rebalance | core (drop-one, affected stock-days) | 0.262 | 0.143 | 16.3% | 0.000 | – | review: move to monitoring layer |
| US | option_expiry | core (drop-one, affected stock-days) | 0.009 | 0.222 | 13.6% | -0.002 | – | review: move to monitoring layer |
| US | corporate_action | core (drop-one, affected stock-days) | 0.027 | 0.074 | 5.8% | 0.000 | – | review: move to monitoring layer |
| US | in_play | core (drop-one, affected stock-days) | 0.083 | 0.220 | 30.0% | 0.002 | 0.319 | keep in core |
| US | crypto_beta | core (drop-one, affected stock-days) | 0.265 | 0.354 | 56.5% | 0.003 | 1.612 | keep in core |
| US | vol_shock | time-series (variance explained) | 0.020 | – | 138.5% | -0.031 | 3.495 | keep in core |
| US | liq_shock | time-series (variance explained) | 0.004 | – | 167.6% | -0.001 | 5.378 | keep in core |
| US | fx | time-series (variance explained) | 0.015 | – | 7.5% | 0.007 | 0.499 | keep in core |
| US | rates | time-series (variance explained) | 0.039 | – | 7.4% | -0.000 | 0.402 | keep in core |
| US | etf_ownership | candidate (add-one) | 0.007 | 0.269 | 4.7% | -0.003 | 1.061 | promote to core |
| US | retail_attention | candidate (add-one) | 0.006 | 0.195 | 3.8% | -0.001 | 2.280 | promote to core |
| CN | beta | core (drop-one) | 0.017 | 0.295 | 8.5% | – | 0.691 | keep in core |
| CN | size | core (drop-one) | 0.027 | 0.413 | 8.9% | – | 1.695 | keep in core |
| CN | liquidity | core (drop-one) | 0.010 | 0.158 | 4.4% | – | 3.415 | keep in core |
| CN | volatility | core (drop-one) | 0.023 | 0.405 | 7.6% | – | 0.416 | keep in core |
| CN | st_reversal | core (drop-one) | 0.013 | 0.224 | 12.8% | – | 0.167 | keep in core |
| CN | st_momentum | core (drop-one) | 0.009 | 0.147 | 7.6% | – | 0.428 | keep in core |
| CN | overnight_gap | core (drop-one) | 0.008 | 0.138 | 7.8% | – | 2.136 | keep in core |
| CN | crowding | core (drop-one) | 0.009 | 0.162 | 4.4% | – | 0.666 | keep in core |
| CN | earnings | core (drop-one, affected stock-days) | 0.096 | 0.291 | 30.1% | – | – | keep in core |
| CN | index_rebalance | core (drop-one, affected stock-days) | 0.152 | 0.000 | 18.3% | – | – | review: move to monitoring layer |
| CN | option_expiry | core (drop-one, affected stock-days) | 0.018 | 0.222 | 18.6% | – | – | review: move to monitoring layer |
| CN | corporate_action | core (drop-one, affected stock-days) | 0.138 | 0.065 | 19.6% | – | – | review: move to monitoring layer |
| CN | in_play | core (drop-one, affected stock-days) | 0.081 | 0.267 | 37.6% | – | – | keep in core |
| CN | limit_hit | core (drop-one, affected stock-days) | 0.190 | 0.194 | 31.4% | – | – | keep in core |
| CN | vol_shock | time-series (variance explained) | 0.011 | – | 129.7% | – | 3.708 | keep in core |
| CN | liq_shock | time-series (variance explained) | 0.002 | – | 148.2% | – | 5.017 | keep in core |
| CN | fx | time-series (variance explained) | 0.006 | – | 3.3% | – | 0.086 | keep in core |
| CN | rates | time-series (variance explained) | 0.010 | – | 2.4% | – | 0.409 | keep in core |
| CN | us_session | time-series (variance explained) | 0.014 | – | 20.6% | – | 1.918 | keep in core |
| CN | etf_ownership | candidate (add-one) | 0.010 | 0.178 | 6.8% | – | 1.756 | promote to core |
| CN | retail_attention | candidate (add-one) | 0.010 | 0.153 | 5.0% | – | 0.577 | promote to core |

### Time-series betas: shrinkage and stability (Section 3.4)

**US**

| factor | monthly_stability | mean_shrink_weight | corr_shrunk_vs_true | corr_raw_vs_true |
|---|---|---|---|---|
| vol_shock | 0.908 | 0.759 | 0.803 | 0.832 |
| liq_shock | 0.800 | 0.431 | 0.019 | 0.139 |
| fx | 0.940 | 0.451 | 0.835 | 0.804 |
| rates | 0.977 | 0.517 | 0.930 | 0.925 |

**CN**

| factor | monthly_stability | mean_shrink_weight | corr_shrunk_vs_true | corr_raw_vs_true |
|---|---|---|---|---|
| vol_shock | 0.891 | 0.646 | 0.570 | 0.654 |
| liq_shock | 0.787 | 0.283 | 0.223 | 0.336 |
| fx | 0.906 | 0.191 | 0.730 | 0.550 |
| rates | 0.956 | 0.193 | 0.924 | 0.672 |
| us_session | 0.924 | 0.344 | 0.729 | 0.642 |

Shrinking noisy time-series betas toward the industry average raises their correlation with the true sensitivities where individual estimates are noisiest.

### Risk-model settings in use

| index | ledoit_wolf_intensity | macro_day_multiplier |
|---|---|---|
| US | 0.250 | 1.730 |
| CN | 0.250 | 1.221 |
| CRYPTO | 0.236 | – |

## 5. Factor quality and collinearity

**US**

| factor | group | ann_vol | ann_return | t_mean | pct_days_abs_t_gt_2 | autocorr_1 |
|---|---|---|---|---|---|---|
| market | market | 0.195 | 0.217 | 1.755 | 0.716 | 0.011 |
| beta | style | 0.053 | 0.024 | 0.711 | 0.286 | -0.022 |
| size | style | 0.062 | 0.102 | 2.613 | 0.428 | 0.021 |
| liquidity | style | 0.031 | -0.025 | -1.277 | 0.226 | 0.032 |
| volatility | style | 0.052 | 0.009 | 0.275 | 0.409 | 0.026 |
| st_reversal | style | 0.084 | 0.140 | 2.647 | 0.241 | 0.010 |
| st_momentum | style | 0.052 | 0.014 | 0.433 | 0.194 | -0.030 |
| overnight_gap | style | 0.053 | -0.015 | -0.452 | 0.165 | 0.043 |
| crowding | style | 0.044 | -0.016 | -0.583 | 0.361 | -0.047 |
| earnings | event | 0.213 | 0.587 | 2.504 | 0.115 | -0.010 |
| option_expiry | event | 0.133 | -0.215 | -0.559 | 0.010 | 0.074 |
| corporate_action | event | 0.057 | -0.304 | -1.838 | 0.003 | 0.075 |
| in_play | event | 0.318 | 0.064 | 0.102 | 0.022 | -0.044 |
| crypto_beta | market_specific | 0.583 | 0.272 | 0.736 | 0.328 | 0.032 |
| vol_shock | timeseries | 1.309 | 0.007 | 0.009 | 0.000 | -0.166 |
| liq_shock | timeseries | 1.597 | 0.020 | 0.020 | 0.000 | -0.255 |
| fx | timeseries | 0.074 | -0.003 | -0.064 | 0.000 | -0.018 |
| rates | timeseries | 0.073 | 0.035 | 0.796 | 0.000 | 0.085 |
| stat_1 | statistical | 0.031 | 0.007 | 0.342 | 0.000 | 0.079 |
| stat_2 | statistical | 0.023 | 0.016 | 1.022 | 0.000 | 0.053 |

**CN**

| factor | group | ann_vol | ann_return | t_mean | pct_days_abs_t_gt_2 | autocorr_1 |
|---|---|---|---|---|---|---|
| market | market | 0.278 | 0.149 | 0.829 | 0.702 | 0.022 |
| beta | style | 0.083 | -0.038 | -0.710 | 0.261 | 0.059 |
| size | style | 0.089 | 0.033 | 0.576 | 0.376 | 0.025 |
| liquidity | style | 0.043 | 0.019 | 0.689 | 0.139 | 0.004 |
| volatility | style | 0.075 | -0.075 | -1.558 | 0.366 | 0.013 |
| st_reversal | style | 0.128 | 0.097 | 1.177 | 0.205 | -0.038 |
| st_momentum | style | 0.076 | -0.005 | -0.099 | 0.132 | 0.009 |
| overnight_gap | style | 0.076 | -0.101 | -2.049 | 0.123 | -0.028 |
| crowding | style | 0.043 | -0.027 | -0.980 | 0.138 | -0.009 |
| earnings | event | 0.313 | 0.089 | 0.205 | 0.060 | 0.081 |
| option_expiry | event | 0.194 | -0.123 | -0.219 | 0.012 | 0.092 |
| corporate_action | event | 0.185 | -0.080 | -0.166 | 0.003 | -0.225 |
| limit_hit | market_specific | 0.312 | 3.143 | 8.714 | 0.058 | 0.023 |
| vol_shock | timeseries | 1.252 | 0.055 | 0.071 | 0.000 | -0.210 |
| liq_shock | timeseries | 1.418 | 0.028 | 0.032 | 0.000 | -0.238 |
| fx | timeseries | 0.033 | -0.006 | -0.313 | 0.000 | -0.079 |
| rates | timeseries | 0.025 | -0.010 | -0.664 | 0.000 | 0.001 |
| us_session | timeseries | 0.195 | 0.189 | 1.544 | 0.000 | -0.006 |
| stat_1 | statistical | 0.039 | 0.012 | 0.421 | 0.000 | -0.002 |
| stat_2 | statistical | 0.030 | 0.014 | 0.654 | 0.000 | -0.034 |

**CRYPTO**

| factor | group | ann_vol | ann_return | t_mean | pct_days_abs_t_gt_2 | autocorr_1 |
|---|---|---|---|---|---|---|
| market | market | 0.707 | 0.347 | 0.963 | 0.676 | -0.047 |
| btc_beta | style | 0.202 | 0.035 | 0.345 | 0.194 | -0.040 |
| size | style | 0.176 | -0.015 | -0.162 | 0.101 | 0.013 |
| momentum | style | 0.301 | 0.256 | 1.671 | 0.213 | -0.037 |
| funding | style | 0.246 | 0.003 | 0.024 | 0.176 | -0.058 |
| stat_1 | statistical | 0.088 | 0.052 | 1.095 | 0.000 | 0.015 |

**VIF US** (flag > 5)

| index | mean_vif | max_vif |
|---|---|---|
| beta | 1.361 | 2.027 |
| size | 1.337 | 1.741 |
| liquidity | 1.058 | 1.143 |
| volatility | 1.073 | 1.434 |
| st_reversal | 5.447 | 27.939 |
| st_momentum | 2.915 | 12.660 |
| overnight_gap | 3.098 | 9.052 |
| crowding | 1.048 | 1.300 |

**VIF CN** (flag > 5)

| index | mean_vif | max_vif |
|---|---|---|
| beta | 1.247 | 1.706 |
| size | 1.259 | 2.049 |
| liquidity | 1.064 | 1.168 |
| volatility | 1.098 | 1.331 |
| st_reversal | 5.225 | 11.616 |
| st_momentum | 2.836 | 6.025 |
| overnight_gap | 3.137 | 5.609 |
| crowding | 1.033 | 1.070 |

**Exposure stability US** (day-on-day cross-sectional correlation)

| index | day_on_day_corr |
|---|---|
| beta | 0.996 |
| size | 1.000 |
| liquidity | 0.998 |
| volatility | 0.966 |
| st_reversal | 0.778 |
| st_momentum | 0.650 |
| overnight_gap | 0.782 |
| crowding | 0.978 |

**Exposure stability CN** (day-on-day cross-sectional correlation)

| index | day_on_day_corr |
|---|---|
| beta | 0.997 |
| size | 1.000 |
| liquidity | 0.998 |
| volatility | 0.967 |
| st_reversal | 0.781 |
| st_momentum | 0.653 |
| overnight_gap | 0.780 |
| crowding | 0.932 |

## 6. Missing-factor tests

### Residual correlation across strategies

Named factors only:

| a | b | rho | p_value | flag |
|---|---|---|---|---|
| A1_US_STATARB | D1_US_CROWDING | 0.241 | 0.000 | yes |
| A1_US_STATARB | C1_US_EVENT | 0.113 | 0.006 | no |
| B1_US_INTRADAY | D1_US_CROWDING | -0.105 | 0.010 | no |
| B1_US_INTRADAY | E1_CRYPTO_CARRY | 0.076 | 0.066 | no |
| A2_CN_STATARB | D1_US_CROWDING | -0.072 | 0.081 | no |
| B1_US_INTRADAY | C1_US_EVENT | 0.067 | 0.105 | no |
| D1_US_CROWDING | E1_CRYPTO_CARRY | -0.066 | 0.112 | no |
| C1_US_EVENT | D1_US_CROWDING | 0.047 | 0.252 | no |

Core model (named + statistical):

| a | b | rho | p_value | flag |
|---|---|---|---|---|
| A1_US_STATARB | D1_US_CROWDING | 0.189 | 0.000 | yes |
| B1_US_INTRADAY | D1_US_CROWDING | -0.099 | 0.016 | no |
| B1_US_INTRADAY | C1_US_EVENT | 0.074 | 0.074 | no |
| B1_US_INTRADAY | E1_CRYPTO_CARRY | 0.072 | 0.082 | no |
| A1_US_STATARB | C1_US_EVENT | 0.067 | 0.103 | no |
| A2_CN_STATARB | D1_US_CROWDING | -0.058 | 0.160 | no |
| A1_US_STATARB | A2_CN_STATARB | -0.049 | 0.236 | no |
| D1_US_CROWDING | E1_CRYPTO_CARRY | -0.040 | 0.335 | no |

### PCA on US named-model residuals (last 250 days, 287 stocks)

Marchenko-Pastur edge 4.29; eigenvalues above edge: **7**; after statistical factors: 6.

| index | eigenvalue |
|---|---|
| 1.000 | 8.269 |
| 2.000 | 6.336 |
| 3.000 | 5.924 |
| 4.000 | 5.310 |
| 5.000 | 5.010 |

| pc | candidate | corr |
|---|---|---|
| 1 | theme:AI infrastructure | -0.575 |
| 1 | slow:value | 0.082 |
| 1 | sector:Communication | 0.072 |
| 2 | slow:value | 0.146 |
| 2 | slow:earnings_yield | 0.095 |
| 2 | slow:momentum_12_1 | -0.092 |
| 3 | slow:value | -0.246 |
| 3 | slow:earnings_yield | -0.221 |
| 3 | theme:AI infrastructure | 0.206 |
| 4 | slow:value | -0.272 |
| 4 | slow:earnings_yield | -0.187 |
| 4 | theme:AI infrastructure | -0.153 |
| 5 | slow:value | -0.171 |
| 5 | slow:momentum_12_1 | 0.146 |
| 5 | slow:earnings_yield | -0.137 |

### PCA on CN named-model residuals (last 250 days, 152 stocks)

Marchenko-Pastur edge 3.17; eigenvalues above edge: **3**; after statistical factors: 2.

| index | eigenvalue |
|---|---|
| 1.000 | 3.861 |
| 2.000 | 3.566 |
| 3.000 | 3.464 |
| 4.000 | 3.095 |
| 5.000 | 2.915 |

| pc | candidate | corr |
|---|---|---|
| 1 | slow:momentum_12_1 | 0.258 |
| 1 | slow:value | -0.153 |
| 1 | slow:long_term_reversal | -0.145 |
| 2 | slow:value | -0.147 |
| 2 | slow:momentum_12_1 | -0.097 |
| 2 | slow:earnings_yield | -0.086 |
| 3 | slow:earnings_yield | -0.310 |
| 3 | slow:value | -0.296 |
| 3 | slow:long_term_reversal | -0.129 |
| 4 | slow:momentum_12_1 | -0.305 |
| 4 | slow:value | 0.149 |
| 4 | slow:earnings_yield | 0.147 |
| 5 | slow:long_term_reversal | 0.178 |
| 5 | slow:earnings_yield | 0.145 |
| 5 | shortable | 0.095 |

### Shared residual shocks (≥3 strategies below -2σ on the same day)

None.

## 7. Regimes and cross-market structure

- Regime classification accuracy vs simulated truth: 85.6%.

![regimes](charts/regimes.png)

| leader | follower | corr_same_day | corr_leader_lag1 |
|---|---|---|---|
| US:market | CN:market | -0.016 | 0.165 |
| US:market | CRYPTO:market | 0.046 | 0.006 |
| CRYPTO:market | US:crypto_beta | 0.656 | 0.026 |
| US:crypto_beta | CRYPTO:market | 0.656 | 0.017 |

CN market follows the previous US session; the global layer's Newey-West lag term captures this.

## 8. Historical event replay

Did forecasts flag the risk beforehand, and does attribution explain the loss afterwards?

| episode | date | strategy | pred_vol_t-1 | pred_vol_month_before | forecast_rose_pct | hold_pnl | z_score | factor | specific | trading_and_costs | factor_share_of_loss |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Global carry-trade unwind | 2024-08-05 | A1_US_STATARB | 274,327 | 293,094 | -6.403 | -0.52m | -1.879 | -0.78m | 0.26m | -51,013 | 150.6% |
| Global carry-trade unwind | 2024-08-05 | B1_US_INTRADAY | 45,312 | 33,023 | 37.216 | -80,709 | -1.781 | -0.12m | 42,635 | -0.32m | 152.3% |
| Global carry-trade unwind | 2024-08-05 | C1_US_EVENT | 139,542 | 255,899 | -45.470 | 0.77m | 5.551 | 0.45m | 0.33m | -0.13m | – |
| Global carry-trade unwind | 2024-08-05 | D1_US_CROWDING | 215,212 | 189,795 | 13.392 | -0.35m | -1.633 | -0.20m | -0.16m | -51,847 | 57.6% |
| Quant deleveraging | 2025-03-11 | A1_US_STATARB | 176,265 | 228,352 | -22.810 | -0.34m | -1.911 | -0.23m | -0.12m | -0.13m | 68.1% |
| Quant deleveraging | 2025-03-11 | B1_US_INTRADAY | 31,572 | 29,408 | 7.357 | -49,593 | -1.571 | -38,507 | -10,838 | -0.16m | 77.6% |
| Quant deleveraging | 2025-03-11 | C1_US_EVENT | 202,744 | 180,741 | 12.174 | 0.18m | 0.871 | 0.27m | -68,839 | -92 | – |
| Quant deleveraging | 2025-03-11 | D1_US_CROWDING | 200,389 | 197,406 | 1.511 | -0.48m | -2.395 | -0.40m | -85,122 | -21,111 | 82.9% |
| Tariff shock / CN limit-down cascade | 2025-04-07 | A1_US_STATARB | 251,345 | 290,459 | -13.466 | -0.40m | -1.594 | -0.27m | -76,026 | -0.21m | 68.3% |
| Tariff shock / CN limit-down cascade | 2025-04-07 | B1_US_INTRADAY | 36,417 | 36,166 | 0.695 | -0.10m | -2.855 | -0.12m | 11,089 | -0.51m | 114.3% |
| Tariff shock / CN limit-down cascade | 2025-04-07 | C1_US_EVENT | 223,935 | 226,846 | -1.283 | 0.61m | 2.729 | 0.37m | 0.25m | -693 | – |
| Tariff shock / CN limit-down cascade | 2025-04-07 | D1_US_CROWDING | 220,790 | 248,049 | -10.989 | 0.69m | 3.122 | 0.80m | -91,071 | -43,482 | – |
| Crypto liquidation cascade | 2025-10-10 | A1_US_STATARB | 266,723 | 244,423 | 9.123 | -1.01m | -3.786 | -1.11m | 0.10m | 40,814 | 109.6% |
| Crypto liquidation cascade | 2025-10-10 | B1_US_INTRADAY | 29,906 | 33,154 | -9.797 | -0.13m | -4.513 | -0.16m | 30,792 | 62,927 | 120.3% |
| Crypto liquidation cascade | 2025-10-10 | C1_US_EVENT | 149,079 | 171,102 | -12.871 | 90,070 | 0.604 | -0.11m | 0.18m | -1,014 | – |
| Crypto liquidation cascade | 2025-10-10 | D1_US_CROWDING | 193,094 | 217,591 | -11.259 | -0.59m | -3.040 | -0.52m | -64,972 | -31,936 | 87.8% |
| Momentum/value rotation | 2025-11-10 | A1_US_STATARB | 317,592 | 374,084 | -15.101 | -0.13m | -0.406 | -70,416 | 26,770 | -0.16m | 54.6% |
| Momentum/value rotation | 2025-11-10 | B1_US_INTRADAY | 43,198 | 40,438 | 6.826 | 63,107 | 1.461 | 21,571 | 28,463 | 0.34m | – |
| Momentum/value rotation | 2025-11-10 | C1_US_EVENT | 159,244 | 188,265 | -15.415 | 0.22m | 1.365 | 0.15m | 0.15m | -12,124 | – |
| Momentum/value rotation | 2025-11-10 | D1_US_CROWDING | 281,104 | 276,802 | 1.554 | 0.34m | 1.214 | 0.16m | 0.21m | 3,011 | – |
| Retail short squeeze | 2026-01-27 | A1_US_STATARB | 315,539 | 254,169 | 24.145 | 0.22m | 0.696 | -0.15m | 0.36m | -45,818 | – |
| Retail short squeeze | 2026-01-27 | B1_US_INTRADAY | 39,915 | 32,159 | 24.117 | 43,868 | 1.099 | 8,454 | 30,696 | -57,867 | – |
| Retail short squeeze | 2026-01-27 | C1_US_EVENT | 700,814 | 125,772 | 457 | 1.03m | 1.466 | 0.61m | 0.39m | -0.22m | – |
| Retail short squeeze | 2026-01-27 | D1_US_CROWDING | 256,427 | 237,547 | 7.948 | -0.17m | -0.682 | -0.13m | -16,964 | -9,240 | 74.7% |
| Global carry-trade unwind | 2024-08-05 | A2_CN_STATARB | 110,426 | 112,062 | -1.460 | 95,921 | 0.869 | -63,746 | 0.16m | -97,916 | – |
| Quant deleveraging | 2025-03-11 | A2_CN_STATARB | 85,487 | 141,617 | -39.635 | 38,793 | 0.454 | 68,478 | -23,797 | -96,384 | – |
| Tariff shock / CN limit-down cascade | 2025-04-07 | A2_CN_STATARB | 132,116 | 146,296 | -9.693 | -0.16m | -1.195 | -81,551 | -79,051 | -67,013 | 51.6% |
| Momentum/value rotation | 2025-11-10 | A2_CN_STATARB | 168,533 | 142,677 | 18.122 | -22,307 | -0.132 | -26,080 | 9,968 | -63,174 | 116.9% |
| Global carry-trade unwind | 2024-08-05 | E1_CRYPTO_CARRY | 264,988 | 234,087 | 13.201 | 0.69m | 2.599 | -0.46m | 1.14m | -0.42m | – |
| Tariff shock / CN limit-down cascade | 2025-04-07 | E1_CRYPTO_CARRY | 253,982 | 245,466 | 3.469 | 0.22m | 0.876 | 0.18m | 45,424 | 50,993 | – |
| Crypto liquidation cascade | 2025-10-10 | E1_CRYPTO_CARRY | 345,680 | 245,387 | 40.872 | 0.29m | 0.848 | 38,744 | 0.25m | -90,673 | – |

## 8b. Intraday model

### Seasonality normalisation

Bar-level bias statistics of start-of-bar holdings P&L. With the U-shaped profile the bias is flat across the day (low dispersion); a flat profile over-forecasts midday and under-forecasts the open and close.

| strategy | mean_seasonal | dispersion_seasonal | mean_flat | dispersion_flat |
|---|---|---|---|---|
| A1_US_STATARB | 0.725 | 0.043 | 0.717 | 0.142 |
| B1_US_INTRADAY | 0.754 | 0.055 | 0.748 | 0.163 |
| C1_US_EVENT | 0.761 | 0.088 | 0.753 | 0.156 |
| D1_US_CROWDING | 0.720 | 0.083 | 0.707 | 0.123 |

![seasonality](charts/seasonality_bias_A1.png)

![profile](charts/intraday_vol_profile.png)

### Asynchronous trading (Epps effect)

Average stock beta to index futures: daily 0.85, concurrent 30-minute 0.78, lag-corrected (Dimson) 1.00. Concurrent intraday betas are biased toward zero; intraday exposures use Dimson betas shrunk toward the daily beta.

### Macro announcement bars

| date | event | release | bar | abs_futures_move_bps | typical_same_bar_bps |
|---|---|---|---|---|---|
| 2026-07-08 | CPI | 08:30 | 0 | 17.157 | 33.663 |
| 2026-07-22 | FOMC decision | 14:00 | 10 | 41.934 | 13.978 |
| 2026-08-07 | Nonfarm payrolls | 08:30 | 0 | 4.023 | 33.885 |
| 2026-08-12 | CPI | 08:30 | 0 | 13.027 | 33.733 |
| 2026-09-04 | Nonfarm payrolls | 08:30 | 0 | 53.674 | 33.044 |
| 2026-09-09 | CPI | 08:30 | 0 | 70.667 | 32.756 |
| 2026-09-16 | FOMC decision | 14:00 | 10 | 18.121 | 14.382 |

## 9. Usefulness scorecard (Section 4)

| dimension | metric | result |
|---|---|---|
| Calibration | strategy bias within band | 50% of windows; mean bias 0.83 |
| Explanatory power | share of holding-P&L variance explained by factors | median 76% |
| Reconciliation | attribution vs official P&L | 99.83% of strategy-days within tolerance |
| Intraday reconciliation | bar-level vs daily MTM | max |diff| $0 |
| Stability | style exposure day-on-day corr (US) | 0.89 |
| Early warning | drift alerts / release changes flagged | 119 alerts; 28 material release changes |
| Decision impact / adoption | documented decisions, report usage | tracked in production (decision log), not measurable on synthetic data |

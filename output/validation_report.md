# Model validation report

> **Question answered:** are the risk forecasts calibrated, does attribution reconcile, and is anything missing?

## 1. Explanatory power

| index | named | hybrid |
|---|---|---|
| US | 0.308 | 0.337 |
| CN | 0.363 | 0.381 |
| CRYPTO | 0.430 | 0.448 |

| strategy | factor_share_of_hold_var | corr_factor_vs_hold |
|---|---|---|
| A1_US_STATARB | 84.3% | 0.914 |
| A2_CN_STATARB | 77.0% | 0.868 |
| B1_US_INTRADAY | 76.0% | 0.865 |
| C1_US_EVENT | 52.4% | 0.720 |
| D1_US_CROWDING | 87.8% | 0.937 |
| E1_CRYPTO_CARRY | 17.0% | 0.534 |

## 2. Calibration: bias statistics (target 1, band 1 ± √(2/T))

### Strategy portfolios (most important)

| strategy | mean_bias | within_band_pct | band | n_windows | realised_vol_ann | pred_vol_ann |
|---|---|---|---|---|---|---|
| A1_US_STATARB | 0.918 | 87.5% | 0.178 | 8 | 3.38m | 3.81m |
| A2_CN_STATARB | 0.907 | 62.5% | 0.178 | 8 | 1.90m | 2.05m |
| B1_US_INTRADAY | 0.897 | 87.5% | 0.178 | 8 | 0.46m | 0.51m |
| C1_US_EVENT | 0.988 | 87.5% | 0.178 | 8 | 2.67m | 2.55m |
| D1_US_CROWDING | 0.951 | 87.5% | 0.178 | 8 | 3.10m | 3.29m |
| E1_CRYPTO_CARRY | 0.906 | 92.3% | 0.178 | 13 | 3.35m | 3.73m |

![bias](charts/bias_A1_US_STATARB.png)

### Factors

**US**

| group | mean_bias | within_band_pct |
|---|---|---|
| event | 1.055 | 0.0% |
| industry | 1.042 | 93.9% |
| market | 1.134 | 55.6% |
| market_specific | 1.110 | 66.7% |
| slow | 1.011 | 86.7% |
| statistical | 0.861 | 68.8% |
| style | 0.869 | 71.1% |
| timeseries | 0.948 | 30.6% |

**CN**

| group | mean_bias | within_band_pct |
|---|---|---|
| event | 0.937 | 50.0% |
| industry | 1.022 | 93.3% |
| market | 1.152 | 66.7% |
| market_specific | 0.996 | 100.0% |
| slow | 0.997 | 95.6% |
| statistical | 0.883 | 85.7% |
| style | 0.862 | 71.1% |
| timeseries | 0.954 | 40.0% |

**CRYPTO**

| group | mean_bias | within_band_pct |
|---|---|---|
| event | – | – |
| industry | 1.020 | 78.7% |
| market | 1.382 | 40.0% |
| statistical | 1.001 | 61.5% |
| style | 0.960 | 68.3% |

### Specific risk

| index | mean_bias | within_band_pct | band | n_windows |
|---|---|---|---|---|
| US | 0.999 | 68.0% | 0.178 | 1,336 |
| CN | 0.992 | 79.8% | 0.178 | 1,335 |
| CRYPTO | 1.001 | 45.0% | 0.178 | 600 |

## 3. Benchmark comparison (challengers)

The in-house model must beat a market+industry baseline and a pure PCA model on calibration and explanatory power.

| model | n_factors | mean_cs_r2 | strategy_bias_mean | strategy_bias_mad_from_1 | strategy_within_band_pct | first_valid |
|---|---|---|---|---|---|---|
| in-house core (named + statistical) | 34 | 0.337 | 0.938 | 0.062 | 87.5% | 2024-04-01 |
| baseline: market + industry | 12 | 0.167 | 1.497 | 0.497 | 21.9% | 2024-04-01 |
| challenger: PCA (10 factors) | 11 | 0.196 | 1.206 | 0.206 | 53.1% | 2024-06-25 |

## 4. Recovery of the simulated factor returns (synthetic data only)

**US**

| factor | corr_with_true | n |
|---|---|---|
| market | 0.835 | 628 |
| ind_Technology | 0.723 | 628 |
| ind_Semiconductors | 0.621 | 628 |
| ind_Communication | 0.789 | 628 |
| ind_Consumer Discretionary | 0.695 | 628 |
| ind_Consumer Staples | 0.723 | 628 |
| ind_Health Care | 0.788 | 628 |
| ind_Financials | 0.727 | 628 |
| ind_Industrials | 0.791 | 628 |
| ind_Energy | 0.788 | 628 |
| ind_Materials | 0.718 | 628 |
| ind_Utilities | 0.782 | 628 |
| size | 0.612 | 628 |
| liquidity | 0.740 | 628 |
| volatility | 0.861 | 628 |
| st_reversal | 0.722 | 628 |
| st_momentum | 0.588 | 628 |
| overnight_gap | 0.580 | 628 |
| crowding | 0.858 | 628 |
| retail_attention | 0.702 | 628 |
| earnings | 0.292 | 207 |
| option_expiry | 0.519 | 30 |
| corporate_action | – | 30 |
| in_play | 0.256 | 66 |
| crypto_beta | 0.888 | 628 |
| stat_1 vs hidden theme | 0.819 | 508 |
| stat_2 vs hidden theme | 0.233 | 508 |

**CN**

| factor | corr_with_true | n |
|---|---|---|
| market | 0.894 | 606 |
| ind_Banks | 0.796 | 606 |
| ind_Non-bank Financials | 0.720 | 606 |
| ind_Electronics | 0.724 | 606 |
| ind_Computers | 0.695 | 606 |
| ind_Pharma | 0.728 | 606 |
| ind_Food & Beverage | 0.677 | 606 |
| ind_Machinery | 0.705 | 606 |
| ind_Autos | 0.756 | 606 |
| ind_Chemicals | 0.768 | 606 |
| ind_Real Estate | 0.784 | 606 |
| size | 0.634 | 606 |
| liquidity | 0.590 | 606 |
| volatility | 0.841 | 606 |
| st_reversal | 0.718 | 606 |
| st_momentum | 0.489 | 606 |
| overnight_gap | 0.536 | 606 |
| crowding | 0.622 | 606 |
| retail_attention | 0.682 | 606 |
| earnings | 0.094 | 130 |
| option_expiry | 0.393 | 30 |
| corporate_action | – | 37 |
| limit_hit | 0.462 | 188 |
| stat_1 vs hidden theme | 0.074 | 486 |
| stat_2 vs hidden theme | 0.031 | 486 |

## 4b. Factor selection tests (Section 2.1)

Each factor must earn its place on our own data. Core factors: drop-one marginal R² (on the affected stock-days for sparse event factors) and share of estimable days with |t| > 2. Time-series factors: share of remaining variance explained by B·g (their cross-sectional R² is understated because industry factors absorb their sector pattern). Candidates: add-one. Residual correlation reduction is across this market's strategies.

| market | factor | test | marginal_r2 | pct_days_abs_t_gt_2 | ann_vol | resid_corr_reduction | max_abs_z_on_squeeze_days | decision |
|---|---|---|---|---|---|---|---|---|
| US | beta | core (drop-one) | 0.011 | 0.324 | 5.5% | -0.004 | 2.474 | keep in core |
| US | size | core (drop-one) | 0.018 | 0.476 | 6.2% | -0.014 | 0.230 | keep in core |
| US | liquidity | core (drop-one) | 0.007 | 0.253 | 3.2% | -0.006 | 4.364 | keep in core |
| US | volatility | core (drop-one) | 0.016 | 0.446 | 5.3% | 0.028 | 4.374 | keep in core |
| US | st_reversal | core (drop-one) | 0.008 | 0.274 | 8.5% | 0.020 | 2.866 | keep in core |
| US | st_momentum | core (drop-one) | 0.006 | 0.211 | 5.2% | -0.006 | 0.818 | keep in core |
| US | overnight_gap | core (drop-one) | 0.006 | 0.177 | 5.3% | 0.021 | 1.301 | keep in core |
| US | crowding | core (drop-one) | 0.013 | 0.407 | 4.4% | -0.022 | 5.295 | keep in core |
| US | etf_ownership | core (drop-one) | 0.007 | 0.267 | 3.2% | -0.003 | 0.997 | keep in core |
| US | retail_attention | core (drop-one) | 0.006 | 0.198 | 2.9% | -0.001 | 2.156 | keep in core |
| US | earnings | core (drop-one, affected stock-days) | 0.076 | 0.401 | 20.8% | -0.001 | 0.378 | keep in core |
| US | index_rebalance | core (drop-one, affected stock-days) | 0.089 | 0.000 | 13.9% | -0.000 | – | review: move to monitoring layer |
| US | option_expiry | core (drop-one, affected stock-days) | 0.006 | 0.111 | 10.8% | 0.000 | – | review: move to monitoring layer |
| US | corporate_action | core (drop-one, affected stock-days) | 0.025 | 0.074 | 5.6% | 0.000 | – | review: move to monitoring layer |
| US | in_play | core (drop-one, affected stock-days) | 0.084 | 0.220 | 30.3% | 0.001 | 0.981 | keep in core |
| US | crypto_beta | core (drop-one, affected stock-days) | 0.264 | 0.363 | 56.4% | 0.001 | 1.621 | keep in core |
| US | vol_shock | time-series (variance explained) | 0.023 | – | 138.5% | -0.027 | 3.495 | keep in core |
| US | liq_shock | time-series (variance explained) | 0.005 | – | 110.8% | 0.006 | 5.456 | keep in core |
| US | fx | time-series (variance explained) | 0.015 | – | 7.5% | 0.007 | 0.499 | keep in core |
| US | rates | time-series (variance explained) | 0.039 | – | 7.4% | -0.002 | 0.402 | keep in core |
| CN | beta | core (drop-one) | 0.017 | 0.300 | 8.5% | – | 0.800 | keep in core |
| CN | size | core (drop-one) | 0.027 | 0.420 | 9.2% | – | 1.606 | keep in core |
| CN | liquidity | core (drop-one) | 0.009 | 0.158 | 4.4% | – | 3.588 | keep in core |
| CN | volatility | core (drop-one) | 0.023 | 0.387 | 7.6% | – | 0.381 | keep in core |
| CN | st_reversal | core (drop-one) | 0.013 | 0.231 | 12.8% | – | 0.252 | keep in core |
| CN | st_momentum | core (drop-one) | 0.008 | 0.140 | 7.7% | – | 0.518 | keep in core |
| CN | overnight_gap | core (drop-one) | 0.008 | 0.140 | 7.8% | – | 1.918 | keep in core |
| CN | crowding | core (drop-one) | 0.009 | 0.156 | 4.4% | – | 0.469 | keep in core |
| CN | etf_ownership | core (drop-one) | 0.010 | 0.176 | 4.9% | – | 1.846 | keep in core |
| CN | retail_attention | core (drop-one) | 0.010 | 0.158 | 4.5% | – | 0.424 | keep in core |
| CN | earnings | core (drop-one, affected stock-days) | 0.095 | 0.299 | 30.4% | – | – | keep in core |
| CN | index_rebalance | core (drop-one, affected stock-days) | 0.257 | 0.286 | 27.8% | – | – | keep in core |
| CN | option_expiry | core (drop-one, affected stock-days) | 0.009 | 0.000 | 13.2% | – | – | review: move to monitoring layer |
| CN | corporate_action | core (drop-one, affected stock-days) | 0.144 | 0.129 | 19.8% | – | – | review: move to monitoring layer |
| CN | in_play | core (drop-one, affected stock-days) | 0.036 | 0.000 | – | – | – | review: move to monitoring layer |
| CN | limit_hit | core (drop-one, affected stock-days) | 0.193 | 0.194 | 31.7% | – | – | keep in core |
| CN | vol_shock | time-series (variance explained) | 0.012 | – | 129.7% | – | 3.708 | keep in core |
| CN | liq_shock | time-series (variance explained) | 0.003 | – | 107.3% | – | 3.715 | keep in core |
| CN | fx | time-series (variance explained) | 0.006 | – | 3.3% | – | 0.086 | keep in core |
| CN | rates | time-series (variance explained) | 0.010 | – | 2.4% | – | 0.409 | keep in core |
| CN | us_session | time-series (variance explained) | 0.014 | – | 20.6% | – | 1.918 | keep in core |

### Time-series betas: shrinkage and stability (Section 3.4)

**US**

| factor | monthly_stability | mean_shrink_weight | corr_shrunk_vs_true | corr_raw_vs_true |
|---|---|---|---|---|
| vol_shock | 0.911 | 0.775 | 0.806 | 0.834 |
| liq_shock | 0.801 | 0.407 | 0.017 | 0.110 |
| fx | 0.940 | 0.447 | 0.835 | 0.804 |
| rates | 0.977 | 0.518 | 0.930 | 0.925 |

**CN**

| factor | monthly_stability | mean_shrink_weight | corr_shrunk_vs_true | corr_raw_vs_true |
|---|---|---|---|---|
| vol_shock | 0.893 | 0.644 | 0.567 | 0.656 |
| liq_shock | 0.781 | 0.271 | 0.232 | 0.381 |
| fx | 0.907 | 0.192 | 0.732 | 0.550 |
| rates | 0.956 | 0.191 | 0.924 | 0.672 |
| us_session | 0.925 | 0.350 | 0.729 | 0.641 |

Shrinking noisy time-series betas toward the industry average raises their correlation with the true sensitivities where individual estimates are noisiest.

### Risk-model settings in use

| index | ledoit_wolf_intensity | macro_day_multiplier |
|---|---|---|
| US | 0.398 | 1.594 |
| CN | 0.400 | 1.175 |
| CRYPTO | 0.257 | – |

## 5. Factor quality and collinearity

**US**

| factor | group | ann_vol | ann_return | t_mean | pct_days_abs_t_gt_2 | autocorr_1 |
|---|---|---|---|---|---|---|
| market | market | 0.195 | 0.215 | 1.743 | 0.742 | 0.004 |
| beta | style | 0.053 | 0.031 | 0.927 | 0.292 | -0.025 |
| size | style | 0.062 | 0.104 | 2.644 | 0.444 | 0.016 |
| liquidity | style | 0.031 | -0.023 | -1.165 | 0.229 | 0.039 |
| volatility | style | 0.052 | 0.007 | 0.207 | 0.406 | 0.016 |
| st_reversal | style | 0.084 | 0.156 | 2.938 | 0.244 | 0.019 |
| st_momentum | style | 0.051 | 0.011 | 0.340 | 0.186 | -0.017 |
| overnight_gap | style | 0.052 | -0.015 | -0.450 | 0.160 | 0.044 |
| crowding | style | 0.043 | -0.016 | -0.596 | 0.367 | -0.056 |
| etf_ownership | style | 0.032 | -0.030 | -1.455 | 0.242 | 0.071 |
| retail_attention | style | 0.028 | -0.009 | -0.515 | 0.177 | -0.022 |
| earnings | event | 0.211 | 0.576 | 2.470 | 0.120 | 0.005 |
| option_expiry | event | 0.104 | -0.166 | -0.550 | 0.004 | -0.028 |
| corporate_action | event | 0.056 | -0.320 | -1.987 | 0.003 | 0.139 |
| in_play | event | 0.324 | -0.149 | -0.235 | 0.022 | -0.029 |
| crypto_beta | market_specific | 0.581 | 0.262 | 0.711 | 0.337 | 0.040 |
| vol_shock | timeseries | 1.309 | 0.007 | 0.009 | 0.000 | -0.166 |
| liq_shock | timeseries | 1.079 | 0.011 | 0.017 | 0.000 | 0.010 |
| fx | timeseries | 0.074 | -0.003 | -0.064 | 0.000 | -0.018 |
| rates | timeseries | 0.073 | 0.035 | 0.796 | 0.000 | 0.085 |
| stat_1 | statistical | 0.030 | 0.001 | 0.053 | 0.000 | 0.078 |
| stat_2 | statistical | 0.022 | 0.018 | 1.176 | 0.000 | 0.001 |

**CN**

| factor | group | ann_vol | ann_return | t_mean | pct_days_abs_t_gt_2 | autocorr_1 |
|---|---|---|---|---|---|---|
| market | market | 0.278 | 0.146 | 0.816 | 0.717 | 0.022 |
| beta | style | 0.083 | -0.034 | -0.627 | 0.264 | 0.053 |
| size | style | 0.092 | 0.035 | 0.599 | 0.381 | 0.017 |
| liquidity | style | 0.044 | 0.024 | 0.847 | 0.142 | 0.023 |
| volatility | style | 0.075 | -0.074 | -1.535 | 0.348 | 0.005 |
| st_reversal | style | 0.128 | 0.106 | 1.292 | 0.214 | -0.019 |
| st_momentum | style | 0.076 | -0.011 | -0.228 | 0.124 | 0.034 |
| overnight_gap | style | 0.077 | -0.094 | -1.909 | 0.126 | -0.010 |
| crowding | style | 0.043 | -0.029 | -1.030 | 0.135 | -0.000 |
| etf_ownership | style | 0.049 | -0.018 | -0.562 | 0.162 | -0.012 |
| retail_attention | style | 0.044 | 0.027 | 0.960 | 0.144 | 0.029 |
| earnings | event | 0.315 | 0.065 | 0.148 | 0.060 | 0.084 |
| option_expiry | event | 0.135 | -0.392 | -1.002 | 0.000 | 0.060 |
| corporate_action | event | 0.188 | -0.125 | -0.255 | 0.006 | -0.256 |
| limit_hit | market_specific | 0.314 | 3.130 | 8.605 | 0.058 | 0.026 |
| vol_shock | timeseries | 1.252 | 0.055 | 0.071 | 0.000 | -0.210 |
| liq_shock | timeseries | 1.031 | 0.022 | 0.035 | 0.000 | 0.005 |
| fx | timeseries | 0.033 | -0.006 | -0.313 | 0.000 | -0.079 |
| rates | timeseries | 0.025 | -0.010 | -0.664 | 0.000 | 0.001 |
| us_session | timeseries | 0.195 | 0.189 | 1.544 | 0.000 | -0.006 |
| stat_1 | statistical | 0.037 | 0.008 | 0.291 | 0.000 | -0.023 |
| stat_2 | statistical | 0.031 | 0.026 | 1.182 | 0.000 | 0.006 |

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
| beta | 1.375 | 2.054 |
| size | 1.395 | 1.810 |
| liquidity | 1.073 | 1.163 |
| volatility | 1.082 | 1.449 |
| st_reversal | 5.504 | 28.097 |
| st_momentum | 2.944 | 12.765 |
| overnight_gap | 3.126 | 9.110 |
| crowding | 1.060 | 1.573 |
| etf_ownership | 1.105 | 1.244 |
| retail_attention | 1.064 | 1.388 |

**VIF CN** (flag > 5)

| index | mean_vif | max_vif |
|---|---|---|
| beta | 1.269 | 1.713 |
| size | 1.299 | 2.061 |
| liquidity | 1.088 | 1.204 |
| volatility | 1.115 | 1.355 |
| st_reversal | 5.310 | 11.708 |
| st_momentum | 2.889 | 6.040 |
| overnight_gap | 3.184 | 5.622 |
| crowding | 1.044 | 1.136 |
| etf_ownership | 1.120 | 1.244 |
| retail_attention | 1.073 | 1.211 |

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
| etf_ownership | 0.999 |
| retail_attention | 0.138 |

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
| etf_ownership | 0.999 |
| retail_attention | 0.060 |

## 6. Missing-factor tests

### Residual correlation across strategies

Named factors only:

| a | b | rho | p_value | flag |
|---|---|---|---|---|
| A1_US_STATARB | D1_US_CROWDING | 0.239 | 0.000 | yes |
| A1_US_STATARB | C1_US_EVENT | 0.142 | 0.001 | no |
| B1_US_INTRADAY | D1_US_CROWDING | -0.114 | 0.005 | no |
| A2_CN_STATARB | D1_US_CROWDING | -0.090 | 0.028 | no |
| B1_US_INTRADAY | E1_CRYPTO_CARRY | 0.069 | 0.095 | no |
| B1_US_INTRADAY | C1_US_EVENT | 0.067 | 0.103 | no |
| D1_US_CROWDING | E1_CRYPTO_CARRY | -0.057 | 0.168 | no |
| A1_US_STATARB | A2_CN_STATARB | -0.046 | 0.261 | no |

Core model (named + statistical):

| a | b | rho | p_value | flag |
|---|---|---|---|---|
| A1_US_STATARB | D1_US_CROWDING | 0.187 | 0.000 | yes |
| B1_US_INTRADAY | D1_US_CROWDING | -0.107 | 0.010 | no |
| A1_US_STATARB | C1_US_EVENT | 0.087 | 0.034 | no |
| A2_CN_STATARB | D1_US_CROWDING | -0.077 | 0.063 | no |
| B1_US_INTRADAY | C1_US_EVENT | 0.073 | 0.077 | no |
| B1_US_INTRADAY | E1_CRYPTO_CARRY | 0.070 | 0.091 | no |
| A1_US_STATARB | A2_CN_STATARB | -0.043 | 0.293 | no |
| A2_CN_STATARB | B1_US_INTRADAY | 0.036 | 0.382 | no |

### PCA on US named-model residuals (last 250 days, 287 stocks)

Marchenko-Pastur edge 4.29; eigenvalues above edge: **7**; after statistical factors: 6.

| index | eigenvalue |
|---|---|
| 1.000 | 8.342 |
| 2.000 | 6.301 |
| 3.000 | 5.893 |
| 4.000 | 5.397 |
| 5.000 | 4.921 |

| pc | candidate | corr |
|---|---|---|
| 1 | theme:AI infrastructure | -0.575 |
| 1 | slow:value | 0.082 |
| 1 | sector:Communication | 0.072 |
| 2 | slow:value | -0.104 |
| 2 | slow:momentum_12_1 | 0.092 |
| 2 | slow:earnings_yield | -0.054 |
| 3 | slow:value | -0.284 |
| 3 | slow:earnings_yield | -0.247 |
| 3 | theme:AI infrastructure | 0.198 |
| 4 | slow:value | -0.268 |
| 4 | slow:earnings_yield | -0.187 |
| 4 | theme:AI infrastructure | -0.159 |
| 5 | slow:value | -0.147 |
| 5 | slow:earnings_yield | -0.115 |
| 5 | sector:Financials | -0.089 |

### PCA on CN named-model residuals (last 250 days, 152 stocks)

Marchenko-Pastur edge 3.17; eigenvalues above edge: **2**; after statistical factors: 1.

| index | eigenvalue |
|---|---|
| 1.000 | 3.819 |
| 2.000 | 3.490 |
| 3.000 | 3.128 |
| 4.000 | 3.003 |
| 5.000 | 2.942 |

| pc | candidate | corr |
|---|---|---|
| 1 | slow:momentum_12_1 | -0.270 |
| 1 | shortable | 0.137 |
| 1 | slow:long_term_reversal | 0.085 |
| 2 | slow:value | -0.387 |
| 2 | slow:earnings_yield | -0.376 |
| 2 | slow:long_term_reversal | -0.164 |
| 3 | slow:momentum_12_1 | -0.259 |
| 3 | sector:Autos | 0.101 |
| 3 | slow:earnings_yield | 0.085 |
| 4 | slow:momentum_12_1 | -0.089 |
| 4 | shortable | -0.069 |
| 4 | slow:long_term_reversal | -0.060 |
| 5 | slow:long_term_reversal | -0.101 |
| 5 | sector:Non-bank Financials | 0.099 |
| 5 | sector:Real Estate | -0.069 |

### Shared residual shocks (≥3 strategies below -2σ on the same day)

None.

## 7. Regimes and cross-market structure

- Regime classification accuracy vs simulated truth: 87.5%.

![regimes](charts/regimes.png)

| leader | follower | corr_same_day | corr_leader_lag1 | corr_same_day_synchronised | corr_weekly |
|---|---|---|---|---|---|
| US:market | CN:market | -0.002 | 0.161 | 0.193 | 0.094 |
| US:market | CRYPTO:market | 0.051 | 0.012 | 0.051 | 0.054 |
| CRYPTO:market | US:crypto_beta | 0.656 | 0.026 | 0.656 | 0.773 |
| US:crypto_beta | CRYPTO:market | 0.656 | 0.020 | 0.656 | 0.773 |

CN market follows the previous US session; the global layer synchronises CN returns to the US close (Burns, Engle and Mezrich 1998) before estimating cross-market correlations.

## 8. Historical event replay

Did forecasts flag the risk beforehand, and does attribution explain the loss afterwards?

| episode | date | strategy | pred_vol_t-1 | pred_vol_month_before | forecast_rose_pct | hold_pnl | z_score | factor | specific | trading_and_costs | factor_share_of_loss |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Global carry-trade unwind | 2024-08-05 | A1_US_STATARB | 238,809 | 265,213 | -9.956 | -0.52m | -2.158 | -0.78m | 0.27m | -51,013 | 151.6% |
| Global carry-trade unwind | 2024-08-05 | B1_US_INTRADAY | 41,613 | 31,634 | 31.546 | -80,709 | -1.940 | -0.13m | 44,009 | -0.32m | 155.5% |
| Global carry-trade unwind | 2024-08-05 | C1_US_EVENT | 120,316 | 239,369 | -49.736 | 0.77m | 6.438 | 0.40m | 0.38m | -0.13m | – |
| Global carry-trade unwind | 2024-08-05 | D1_US_CROWDING | 191,491 | 163,056 | 17.438 | -0.35m | -1.836 | -0.20m | -0.16m | -51,847 | 57.2% |
| Quant deleveraging | 2025-03-11 | A1_US_STATARB | 158,181 | 201,449 | -21.478 | -0.34m | -2.130 | -0.22m | -0.13m | -0.13m | 65.5% |
| Quant deleveraging | 2025-03-11 | B1_US_INTRADAY | 29,080 | 27,131 | 7.182 | -49,593 | -1.705 | -37,119 | -11,547 | -0.16m | 74.8% |
| Quant deleveraging | 2025-03-11 | C1_US_EVENT | 191,570 | 162,569 | 17.839 | 0.18m | 0.922 | 0.24m | -44,816 | -92 | – |
| Quant deleveraging | 2025-03-11 | D1_US_CROWDING | 155,623 | 164,783 | -5.559 | -0.48m | -3.083 | -0.40m | -89,778 | -21,111 | 82.4% |
| Tariff shock / CN limit-down cascade | 2025-04-07 | A1_US_STATARB | 235,340 | 271,597 | -13.349 | -0.40m | -1.702 | -0.32m | -41,481 | -0.21m | 80.6% |
| Tariff shock / CN limit-down cascade | 2025-04-07 | B1_US_INTRADAY | 36,004 | 33,933 | 6.102 | -0.10m | -2.887 | -0.11m | 6,694 | -0.51m | 106.2% |
| Tariff shock / CN limit-down cascade | 2025-04-07 | C1_US_EVENT | 218,645 | 215,771 | 1.332 | 0.61m | 2.795 | 0.42m | 0.19m | -693 | – |
| Tariff shock / CN limit-down cascade | 2025-04-07 | D1_US_CROWDING | 198,110 | 218,538 | -9.348 | 0.69m | 3.479 | 0.77m | -66,421 | -43,482 | – |
| Crypto liquidation cascade | 2025-10-10 | A1_US_STATARB | 225,961 | 212,611 | 6.279 | -1.01m | -4.469 | -1.09m | 88,767 | 40,814 | 107.9% |
| Crypto liquidation cascade | 2025-10-10 | B1_US_INTRADAY | 27,577 | 30,368 | -9.192 | -0.13m | -4.894 | -0.16m | 32,129 | 62,927 | 121.9% |
| Crypto liquidation cascade | 2025-10-10 | C1_US_EVENT | 137,098 | 169,261 | -19.002 | 90,070 | 0.657 | -0.13m | 0.19m | -1,014 | – |
| Crypto liquidation cascade | 2025-10-10 | D1_US_CROWDING | 172,395 | 190,430 | -9.471 | -0.59m | -3.405 | -0.51m | -69,832 | -31,936 | 87.3% |
| Momentum/value rotation | 2025-11-10 | A1_US_STATARB | 268,098 | 324,927 | -17.490 | -0.13m | -0.481 | -70,209 | 40,586 | -0.16m | 54.5% |
| Momentum/value rotation | 2025-11-10 | B1_US_INTRADAY | 40,192 | 37,807 | 6.309 | 63,107 | 1.570 | 24,231 | 24,481 | 0.34m | – |
| Momentum/value rotation | 2025-11-10 | C1_US_EVENT | 139,687 | 175,684 | -20.490 | 0.22m | 1.556 | 0.17m | 0.13m | -12,124 | – |
| Momentum/value rotation | 2025-11-10 | D1_US_CROWDING | 248,519 | 241,426 | 2.938 | 0.34m | 1.373 | 0.16m | 0.22m | 3,011 | – |
| Retail short squeeze | 2026-01-27 | A1_US_STATARB | 298,854 | 221,721 | 34.788 | 0.22m | 0.734 | -0.17m | 0.40m | -45,818 | – |
| Retail short squeeze | 2026-01-27 | B1_US_INTRADAY | 37,105 | 28,816 | 28.768 | 43,868 | 1.182 | 15,143 | 18,402 | -57,867 | – |
| Retail short squeeze | 2026-01-27 | C1_US_EVENT | 679,120 | 120,893 | 462 | 1.03m | 1.513 | 0.55m | 0.50m | -0.22m | – |
| Retail short squeeze | 2026-01-27 | D1_US_CROWDING | 238,239 | 202,349 | 17.737 | -0.17m | -0.734 | -0.14m | 4,467 | -9,240 | 81.1% |
| Global carry-trade unwind | 2024-08-05 | A2_CN_STATARB | 100,970 | 100,679 | 0.289 | 95,921 | 0.950 | -74,472 | 0.17m | -97,916 | – |
| Quant deleveraging | 2025-03-11 | A2_CN_STATARB | 81,997 | 130,164 | -37.005 | 38,793 | 0.473 | 58,812 | -10,192 | -96,384 | – |
| Tariff shock / CN limit-down cascade | 2025-04-07 | A2_CN_STATARB | 124,423 | 141,858 | -12.291 | -0.16m | -1.269 | -30,525 | -0.13m | -67,013 | 19.3% |
| Momentum/value rotation | 2025-11-10 | A2_CN_STATARB | 143,795 | 128,738 | 11.696 | -22,307 | -0.155 | 11,711 | -9,584 | -63,174 | -52.5% |
| Global carry-trade unwind | 2024-08-05 | E1_CRYPTO_CARRY | 213,500 | 176,846 | 20.726 | 0.69m | 3.226 | -0.46m | 1.15m | -0.42m | – |
| Tariff shock / CN limit-down cascade | 2025-04-07 | E1_CRYPTO_CARRY | 213,733 | 193,671 | 10.359 | 0.22m | 1.042 | 0.18m | 40,011 | 50,993 | – |
| Crypto liquidation cascade | 2025-10-10 | E1_CRYPTO_CARRY | 260,861 | 190,781 | 36.733 | 0.29m | 1.124 | 38,744 | 0.25m | -90,673 | – |

## 8b. Intraday model

### Seasonality normalisation

Bar-level bias statistics of start-of-bar holdings P&L. With the U-shaped profile the bias is flat across the day (low dispersion); a flat profile over-forecasts midday and under-forecasts the open and close.

| strategy | mean_seasonal | dispersion_seasonal | mean_flat | dispersion_flat |
|---|---|---|---|---|
| A1_US_STATARB | 0.843 | 0.047 | 0.835 | 0.167 |
| B1_US_INTRADAY | 0.801 | 0.057 | 0.794 | 0.170 |
| C1_US_EVENT | 0.795 | 0.090 | 0.787 | 0.165 |
| D1_US_CROWDING | 0.794 | 0.093 | 0.780 | 0.136 |

![seasonality](charts/seasonality_bias_A1.png)

![profile](charts/intraday_vol_profile.png)

### Asynchronous trading (Epps effect)

Average stock beta to index futures: daily 0.85, concurrent 30-minute 0.78, lag-corrected (Dimson) 1.00 (same bar 0.78 + next bar 0.22). Concurrent intraday betas are biased toward zero. Intraday exposures use the two Dimson parts separately: the same-bar part shrunk toward the daily beta and the next-bar part toward zero, so each bar removes the futures response that actually lands in it.

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
| Calibration | strategy bias within band | 84% of windows; mean bias 0.93 |
| Explanatory power | share of holding-P&L variance explained by factors | median 77% |
| Reconciliation | attribution vs official P&L | 99.83% of strategy-days within tolerance |
| Intraday reconciliation | bar-level vs daily MTM | max |diff| $0 |
| Stability | style exposure day-on-day corr (US) | 0.83 |
| Early warning | drift alerts / release changes flagged | 117 alerts; 28 material release changes |
| Decision impact / adoption | documented decisions, report usage | tracked in production (decision log), not measurable on synthetic data |

"""Risk-model calibration against the simulator's true covariance (synthetic data only).

    python run_calibration.py            # ablation, cause checks, pre-calibration vs current settings
    python run_calibration.py --tune     # also re-tune the risk-model parameters (~15 min)

Writes output/calibration_report.md, output/tables/calibration_*.csv and two charts.  Only the
risk layer is rebuilt per configuration; exposures and factor returns are estimated once.
"""
import argparse
import time
import warnings
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from factor_framework import calibration as cb
from factor_framework.attribution import PnLAttributor
from factor_framework.config import DATA_DIR, MODEL, OUTPUT_DIR, SPECIFIC_RISK_EVENTS
from factor_framework.data_loader import load_crypto_panel, load_equity_panel, load_trading
from factor_framework.estimation import estimate_local_model
from factor_framework.exposures import CryptoExposureBuilder, EquityExposureBuilder
from factor_framework.reporting import SERIES, md_table, plt

EVENT_FACTORS = {"US": SPECIFIC_RISK_EVENTS, "CN": SPECIFIC_RISK_EVENTS, "CRYPTO": ("token_unlock",)}
GROUPS = ["strategy", "random long/short", "cap-weighted long", "optimised: min variance", "optimised: random alpha"]


def setup(data_dir: Path):
    us, cn, cp = load_equity_panel("US", data_dir), load_equity_panel("CN", data_dir), load_crypto_panel(data_dir)
    td = load_trading(data_dir)
    btc = np.log1p(cp.ret["BTC"]).fillna(0)
    models = {"US": estimate_local_model("US", EquityExposureBuilder(us, btc).build(), us.ret, us.ret_on, us.ret_id),
              "CN": estimate_local_model("CN", EquityExposureBuilder(cn).build(), cn.ret, cn.ret_on, cn.ret_id),
              "CRYPTO": estimate_local_model("CRYPTO", CryptoExposureBuilder(cp).build(), cp.ret, n_stat=1)}
    panels = {"US": us, "CN": cn, "CRYPTO": cp}
    att = PnLAttributor(panels, models, td)
    books = {m: {} for m in models}
    for s in td.strategies.strategy:
        b = att.book(s)
        books[b.market][s] = b
    return models, panels, books, pd.Timestamp(td.official_pnl.date.min())


def by_group(sm: pd.DataFrame) -> pd.DataFrame:
    g = sm.assign(lr=np.log(sm.pred_over_true)).groupby("group")
    return pd.DataFrame({"forecast / true": g.lr.mean().pipe(np.exp), "log RMS error": g.log_rmse.mean()}).reindex(GROUPS)


def config_rows(cal: cb.Calibrator, configs: dict) -> pd.DataFrame:
    rows = []
    for name, cfg in configs.items():
        t0 = time.time()
        s, sm = cal.scores(cfg), cal.summary(cal.evaluate(cfg))
        g = by_group(sm)["forecast / true"]
        rows.append({"config": name, "truth error (fit)": s["fit"]["truth_log_rmse"],
                     "truth error (test)": s["test"]["truth_log_rmse"], "|log bias|": s["all"]["truth_abs_log_bias"],
                     "realised Q": s["all"]["realised_q"], **{f"f/t {k}": g[k] for k in GROUPS}})
        print(f"  {name:34s} {time.time() - t0:5.1f}s  error {s['all']['truth_log_rmse']:.4f}", flush=True)
    return pd.DataFrame(rows)


def strategy_table(cal: cb.Calibrator, configs: dict) -> pd.DataFrame:
    out = []
    for name, cfg in configs.items():
        sm = cal.summary(cal.evaluate(cfg))
        s = sm[sm.group == "strategy"].set_index("portfolio")
        out.append(pd.DataFrame({"config": name, "forecast / true": s.pred_over_true,
                                 "factor forecast / true": s.factor_pred_over_true,
                                 "realised bias": s.bias_realised, "bias if forecast were true": s.bias_if_true}))
    return pd.concat(out).reset_index().rename(columns={"portfolio": "strategy"})


def chart(cal: cb.Calibrator, pre, cur, strategy: str, path: Path):
    a, b = cal.evaluate(pre), cal.evaluate(cur)
    a, b = a[a.portfolio == strategy].set_index("date"), b[b.portfolio == strategy].set_index("date")
    fig, ax = plt.subplots(figsize=(9, 3.4))
    k = np.sqrt(252) / 1e6
    ax.plot(a.index, a.true_vol * k, color="#555555", lw=1.4, label="true vol (simulator)")
    ax.plot(a.index, a.pred_vol * k, color=SERIES[1], lw=1.1, label="forecast, pre-calibration")
    ax.plot(b.index, b.pred_vol * k, color=SERIES[0], lw=1.1, label="forecast, calibrated")
    ax.set_ylabel("annualised vol, USD m")
    ax.set_title(f"{strategy}: forecast vs true volatility", loc="left")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DATA_DIR)
    ap.add_argument("--out", type=Path, default=OUTPUT_DIR)
    ap.add_argument("--tune", action="store_true", help="re-run the parameter search")
    args = ap.parse_args()
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    tables, charts = args.out / "tables", args.out / "charts"
    tables.mkdir(parents=True, exist_ok=True); charts.mkdir(parents=True, exist_ok=True)

    print("Estimating factor models (once)")
    models, panels, books, start = setup(args.data)
    print("Rebuilding the true covariance from the simulator")
    cal = cb.Calibrator(models, panels, books, EVENT_FACTORS, start)
    pre = replace(MODEL, **cb.PRE_CALIBRATION)
    cur = MODEL

    # truth sanity check: realised / true vol should have unit spread
    ev0 = cal.evaluate(pre)
    sanity = (ev0.assign(z=ev0.realised / ev0.true_vol).groupby(["market", "group"]).z
              .agg(lambda z: z.std()).unstack("group").reindex(columns=GROUPS))

    if args.tune:
        print("Tuning (coordinate descent on the fit half)")
        cur, log = cal.tune(replace(MODEL, denoise_factor_cov=True, specific_leverage_adj=True, macro_per_factor=True))
        log.to_csv(tables / "calibration_tuning_log.csv", index=False)
    changed = {k: getattr(cur, k) for k in cb.PRE_CALIBRATION if getattr(cur, k) != cb.PRE_CALIBRATION[k]}
    tuned_note = f"Current settings that differ from pre-calibration: `{changed}`"
    print(tuned_note)

    print("Pre-calibration vs current")
    head = config_rows(cal, {"pre-calibration": pre, "current": cur})
    strat = strategy_table(cal, {"pre-calibration": pre, "current": cur})
    print("Ablation of the current settings")
    abl = config_rows(cal, cb.ablations(cur))
    print("Suspected causes: Ledoit-Wolf cap and macro-day uplift")
    lw = config_rows(cal, {f"lw_max = {v}": replace(cur, lw_max=v) for v in (0.0, 0.1, 0.25, 0.4, 0.6, 1.0)})
    macro = config_rows(cal, {
        "no uplift": replace(cur, macro_mult_cap=1.0),
        "one uplift (market's) for all, cap 3": replace(cur, macro_per_factor=False, macro_mult_cap=3.0),
        "per factor, cap 3": replace(cur, macro_per_factor=True, macro_mult_cap=3.0),
        "per factor, cap 6": replace(cur, macro_per_factor=True, macro_mult_cap=6.0)})
    risk_cur = cb.build_risk(models, panels, replace(cur, macro_per_factor=True, macro_mult_cap=10.0), EVENT_FACTORS)
    uplift = pd.concat({m: risk_cur[m].macro_uplift for m in ("US", "CN")}).reset_index()
    uplift.columns = ["market", "factor", "macro days", "estimated ratio", "applied (shrunk)"]
    uplift["simulated truth"] = [cb.TRUE_MACRO_UPLIFT.get(m, {}).get(f, np.nan) for m, f in zip(uplift.market, uplift.factor)]

    for name, df in (("headline", head), ("strategies", strat), ("ablation", abl), ("ledoit_wolf", lw),
                     ("macro", macro), ("macro_uplift", uplift), ("truth_sanity", sanity.reset_index())):
        df.to_csv(tables / f"calibration_{name}.csv", index=False)
    for s in ("A1_US_STATARB", "E1_CRYPTO_CARRY"):
        chart(cal, pre, cur, s, charts / f"calibration_{s}.png")
    write_report(args.out / "calibration_report.md", cal, cur, head, strat, abl, lw, macro, uplift, sanity, tuned_note)
    print(f"-> {args.out / 'calibration_report.md'}")


def write_report(path, cal, cur, head, strat, abl, lw, macro, uplift, sanity, tuned_note):
    num = {c: "num" for c in head.columns}
    s_pre = strat[strat.config == "pre-calibration"].drop(columns="config").set_index("strategy")
    s_cur = strat[strat.config == "current"].drop(columns="config").set_index("strategy")
    st = pd.DataFrame({"forecast / true, pre": s_pre["forecast / true"], "forecast / true, now": s_cur["forecast / true"],
                       "factor part, pre": s_pre["factor forecast / true"], "factor part, now": s_cur["factor forecast / true"],
                       "realised bias, pre": s_pre["realised bias"], "realised bias, now": s_cur["realised bias"],
                       "bias if forecast = truth": s_cur["bias if forecast were true"]})
    lines = [
        "# Risk-model calibration against the true covariance", "",
        "> **Question answered:** how far are the risk forecasts from the true risk, which layer of the risk "
        "model causes the gap, and which settings close it?  Synthetic data only: the simulator's true "
        "conditional covariance is rebuilt and compared with the forecast for every test portfolio, every day.",
        "",
        "## 1. Method", "",
        "* **Truth.** The generator is re-run with its seed (bit-for-bit identical to `data/`), keeping the true "
        "exposures. Each day's true covariance is A Ω Aᵀ + D: GJR-GARCH market variance, the regime as a mixture "
        "over yesterday's regime, macro-day scalings, the ×3 ETF-flow vol on rebalance days, BTC variance over the "
        "calendar gap, and the coupled block (market, reversal, liquidity, crowding, vol shock, liquidity shock) "
        "integrated by Monte Carlo from the simulator's equations. Stress shocks are surprises, not variance.",
        "* **Test portfolios.** The six strategy books; 10 random dollar-neutral portfolios per market; the "
        "cap-weighted market; and portfolios *optimised with the model being tested* (minimum variance and "
        "mean-variance optimal for 5 random alphas, every 5th day). Hedged books expose over-forecasts and "
        "optimised portfolios expose under-forecasts, so a setting cannot win by moving the level alone.",
        "* **Scores.** *Forecast / true* is the geometric mean of predicted ÷ true vol (1 = unbiased). "
        "*Truth error* is the RMS of log(predicted ÷ true vol): bias and timing together. Groups are weighted "
        "equally. *Fit* is the first half of the period (used to choose settings) and *test* is the second half. "
        "*Realised Q* = mean(z² − ln z²) with z = realised ÷ forecast: lower is better. It is the only "
        "yardstick available on real data, and it is noisy.",
        "",
        "Truth check: std(realised ÷ true vol) should be about 1 for every portfolio type (China slightly lower "
        "because price limits clip returns):", "",
        md_table(sanity.round(3), index=True), "",
        "## 2. Pre-calibration vs current settings", "",
        md_table(head, num), "", tuned_note, "",
        "### Strategy books", "",
        md_table(st, index=True), "",
        "*Factor part* compares the model's factor variance with the true factor variance. The two use different "
        "factor sets (the hidden theme sits in the statistical factors, for example), so read it as a direction, "
        "not an exact split.", "",
        "![A1](charts/calibration_A1_US_STATARB.png)", "",
        "![E1](charts/calibration_E1_CRYPTO_CARRY.png)", "",
        "## 3. What each layer contributes (ablation of the current settings)", "",
        md_table(abl, num), "",
        "## 4. The two suspected causes", "",
        "### Ledoit-Wolf shrinkage of factor correlations", "",
        md_table(lw, num), "",
        "### Macro-day uplift", "",
        md_table(macro, num), "",
        "Estimated macro-day variance ratios (end of sample, before the cap) against the simulator's scalings:", "",
        md_table(uplift), "",
        "## 5. Factor-return sampling noise and specific-risk leverage", "",
        "Each day's factor returns come from a regression on 300 (US), 160 (CN) or 40 (crypto) names, so they "
        "carry sampling noise Q e, where Q is the regression projection and e the specific returns. A covariance "
        "estimated from those returns counts Q D Qᵀ as factor risk, although it is specific risk that the book "
        "already pays for in its specific term. A factor-tilted book cannot diversify it away, so its risk is "
        "over-forecast. The same regression pulls each name's fit toward its own return, so residuals understate "
        "specific variance by about the leverage K/N. `denoise_factor_cov` subtracts the EWMA of Q D Qᵀ from the "
        "factor covariance. `specific_leverage_adj` divides squared residuals by their expected shrinkage κᵢ = "
        "Σⱼ Mᵢⱼ² dⱼ / dᵢ, with M = I − X Q. The validation report's factor bias statistic adds the noise back, "
        "because it tests F against the *estimated* factor returns.", "",
        "## 6. Not closed by these settings", "",
        "* The US stat-arb and intraday books stay over-forecast. Their model exposures to reversal, overnight "
        "gap and the time-series shocks exceed their true exposures, because exposures are estimated with "
        "error (time-series betas, descriptor definitions). Exposure noise adds to forecast risk in the same "
        "way factor-return noise does, but needs a model of the exposure error before it can be removed.",
        "* Optimised portfolios' *factor* risk is under-forecast: the optimiser finds the directions the model "
        "misses (the hidden theme, crypto linkage). Their total is close to the truth only because specific "
        "risk is slightly high.",
        "* The settings are tuned on one simulated history. On real data only the realised Q-statistic and "
        "bias statistics are available, and their direction agrees with the truth score here.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"done in {time.time() - t0:.0f}s")

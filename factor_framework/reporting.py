"""Layer 7 - Reporting (Section 3.7).

One source of truth, three audiences.  Every report opens with the decision it
supports, shows uncertainty where it matters (Sharpe confidence intervals,
noisy short windows) and drills down firm -> team -> strategy -> factor.

Outputs (in ``output/``):
  risk_report.md          Risk / Middle Office
  pm_report.md            Quant traders / PMs
  management_summary.md   Senior management / capital allocation
  validation_report.md    Model validation and usefulness scorecard
  charts/*.png            Figures referenced by the reports
  tables/*.csv            Every table, for drill-down
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from .attribution import COMPONENTS  # noqa: E402
from .config import TRADING_DAYS  # noqa: E402
from .diagnostics import SURROGATE_MIN_R2_OOS  # noqa: E402

# Validated reference palette (dataviz skill): fixed categorical order, recessive chrome
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
DIVERGING = LinearSegmentedColormap.from_list("div", ["#184f95", "#6da7ec", "#f0efec", "#ec835a", "#d03b3b"])
STATUS_ICON = {"OK": "OK", "WARN": "WARN ⚠", "BREACH": "BREACH ⛔"}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False,
    "axes.spines.right": False, "font.size": 9, "axes.titlesize": 11, "axes.titleweight": "bold",
    "axes.titlecolor": INK, "legend.frameon": False, "lines.linewidth": 2,
})


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def _fmt(v, kind="num"):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "–"
    if isinstance(v, (bool, np.bool_)):
        return "yes" if v else "no"
    if isinstance(v, (int, np.integer)):
        return f"{v:,}"
    if isinstance(v, (float, np.floating)):
        if kind == "usd":
            return f"{v / 1e6:,.2f}m" if abs(v) >= 1e5 else f"{v:,.0f}"
        if kind == "pct":
            return f"{v * 100:.1f}%"
        return f"{v:,.3f}" if abs(v) < 100 else f"{v:,.0f}"
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    return str(v)


def md_table(df: pd.DataFrame, kinds: dict | None = None, index: bool = False, max_rows: int = 60) -> str:
    kinds = kinds or {}
    d = df.reset_index() if index else df
    d = d.head(max_rows)
    cols = list(d.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in d.iterrows():
        out.append("| " + " | ".join(_fmt(r[c], kinds.get(c, "num")) for c in cols) + " |")
    return "\n".join(out)


def sharpe_ci(x: pd.Series, periods: int = TRADING_DAYS) -> tuple[float, float, float]:
    """Annualised Sharpe with Lo (2002) iid standard error -> 95% CI."""
    x = x.dropna()
    if len(x) < 20 or x.std() == 0:
        return np.nan, np.nan, np.nan
    sr_d = x.mean() / x.std()
    se_d = np.sqrt((1 + 0.5 * sr_d ** 2) / len(x))
    k = np.sqrt(periods)
    return sr_d * k, (sr_d - 1.96 * se_d) * k, (sr_d + 1.96 * se_d) * k


def _save(fig, path: Path):
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def _datefmt(ax):
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
def chart_cum_attribution(daily: pd.DataFrame, strategy: str, path: Path):
    d = daily.xs(strategy, level="strategy")
    groups = {
        "Factor": d.factor, "Residual (specific + slow)": d.specific + d.slow_factor,
        "Trading at decision": d.trading, "Execution costs": d.delay_cost + d.impact_cost + d.commissions,
        "Financing, borrow, funding": d.financing + d.borrow + d.funding, "FX": d.fx,
        "Basis (perp vs spot)": d.basis,
    }
    fig, ax = plt.subplots(figsize=(8, 3.8))
    for i, (k, v) in enumerate(groups.items()):
        if v.abs().sum() == 0:
            continue
        c = v.cumsum() / 1e6
        ax.plot(c.index, c.values, color=SERIES[i], label=k)
    tot = d.total_attributed.cumsum() / 1e6
    ax.plot(tot.index, tot.values, color=INK, lw=2.2, label="Total")
    ax.text(tot.index[-1], tot.values[-1], f"  {tot.values[-1]:.1f}m", color=INK, va="center", fontsize=8)
    ax.axhline(0, color=AXIS, lw=0.8)
    ax.set_title(f"{strategy}: cumulative P&L attribution (USD m)", loc="left")
    ax.legend(loc="upper left", fontsize=7.5, ncol=2)
    _datefmt(ax)
    _save(fig, path)


def chart_heatmap(corr: pd.DataFrame, title: str, path: Path):
    fig, ax = plt.subplots(figsize=(6.2, 5))
    im = ax.imshow(corr.values, cmap=DIVERGING, vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr)), [c.replace("_", " ") for c in corr.columns], rotation=40, ha="right", fontsize=7.5)
    ax.set_yticks(range(len(corr)), [c.replace("_", " ") for c in corr.index], fontsize=7.5)
    ax.grid(False)
    for i in range(len(corr)):
        for j in range(len(corr)):
            v = corr.values[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=7,
                    color="#ffffff" if abs(v) > 0.6 else INK)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    ax.set_title(title, loc="left")
    _save(fig, path)


def chart_factor_cum(fr: pd.DataFrame, factors: list, title: str, path: Path):
    fig, ax = plt.subplots(figsize=(8, 3.8))
    for i, f in enumerate(factors[:8]):
        c = fr[f].fillna(0).cumsum() * 100
        ax.plot(c.index, c.values, color=SERIES[i], label=f.replace("_", " "), lw=1.6)
    ax.axhline(0, color=AXIS, lw=0.8)
    ax.set_ylabel("cumulative return (%)")
    ax.set_title(title, loc="left")
    ax.legend(fontsize=7.5, ncol=2, loc="upper left")
    _datefmt(ax)
    _save(fig, path)


def chart_regimes(reg: pd.DataFrame, mkt: pd.Series, path: Path):
    fig, ax = plt.subplots(figsize=(8, 3.2))
    vol = mkt.rolling(20).std().reindex(reg.index) * np.sqrt(TRADING_DAYS) * 100
    stress = reg.regime == reg.regime.max()
    ax.fill_between(reg.index, 0, vol.max() * 1.05, where=stress.values, color="#e1e0d9", step="mid",
                    label="Detected stress regime", lw=0)
    ax.plot(vol.index, vol.values, color=SERIES[0], label="US market factor vol, 20d (ann. %)")
    ax.set_ylim(0, vol.max() * 1.05)
    ax.set_title("Regime detection (Gaussian mixture on market-state features)", loc="left")
    ax.legend(fontsize=7.5, loc="upper left")
    _datefmt(ax)
    _save(fig, path)


def chart_vol_profile(prof: pd.Series, path: Path):
    fig, ax = plt.subplots(figsize=(6.5, 3))
    labels = [f"{9 + (30 + 30 * b) // 60}:{(30 + 30 * b) % 60:02d}" for b in prof.index]
    ax.bar(range(len(prof)), prof.values * 1e4, color=SERIES[0], width=0.7)
    ax.set_xticks(range(len(prof)), labels, rotation=45, fontsize=7.5)
    ax.set_ylabel("mean |bar return| (bps)")
    ax.set_title("US intraday volatility profile (30-minute bars, bar end time)", loc="left")
    ax.grid(axis="x", visible=False)
    _save(fig, path)


def chart_exposure(ex: pd.DataFrame, strategy: str, factor: str, release: pd.Timestamp | None, path: Path):
    s = ex[(ex.strategy == strategy) & (ex.factor == factor)].set_index("date").exposure_pct_gmv
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.plot(s.index, s.values, color=SERIES[0], lw=1.4, label=f"{factor} exposure (std units per $ gross)")
    ax.plot(s.index, s.rolling(20).mean().values, color=INK, lw=1.6, label="20-day mean")
    if release is not None:
        ax.axvline(release, color=SERIES[1], lw=1.5, ls="--")
        ax.text(release, ax.get_ylim()[1], " model release", color=INK2, fontsize=8, va="top")
    ax.axhline(0, color=AXIS, lw=0.8)
    ax.set_title(f"{strategy}: {factor} exposure through time", loc="left")
    ax.legend(fontsize=7.5, loc="upper left")
    _datefmt(ax)
    _save(fig, path)


def chart_firm_risk(fr: pd.DataFrame, path: Path):
    cols = [c for c in fr.columns if c.startswith("contrib_")]
    fig, ax = plt.subplots(figsize=(8, 3.4))
    for i, c in enumerate(cols):
        ax.plot(fr.index, fr[c] * np.sqrt(TRADING_DAYS) / 1e6, color=SERIES[i], lw=1.4, label=c.replace("contrib_", ""))
    ax.plot(fr.index, fr.firm_vol * np.sqrt(TRADING_DAYS) / 1e6, color=INK, lw=2, label="Firm total")
    ax.set_ylabel("annualised vol (USD m)")
    ax.set_title("Firm predicted risk and contribution by local model", loc="left")
    ax.legend(fontsize=7.5, ncol=5, loc="upper left")
    _datefmt(ax)
    _save(fig, path)


def chart_bias(series: pd.DataFrame, strategy: str, path: Path):
    s = series.loc[strategy].dropna()
    fig, ax = plt.subplots(figsize=(8, 3))
    pnl = s.hold_pnl / 1e3
    ax.plot(pnl.index, pnl.values, color=MUTED, lw=0.8, label="Daily holding P&L (USD k)")
    ax.plot(s.index, 2 * s.pred_vol / 1e3, color=SERIES[0], lw=1.5, label="±2 × predicted vol")
    ax.plot(s.index, -2 * s.pred_vol / 1e3, color=SERIES[0], lw=1.5)
    ax.set_title(f"{strategy}: realised P&L vs risk forecast", loc="left")
    ax.legend(fontsize=7.5, loc="upper left")
    _datefmt(ax)
    _save(fig, path)


def chart_crowding(hist: pd.DataFrame, title: str, path: Path, n: int = 5):
    if hist is None or not len(hist):
        return
    top = hist.groupby("factor").z.last().abs().sort_values(ascending=False).head(n).index
    fig, ax = plt.subplots(figsize=(8, 3.2))
    for i, f in enumerate(top):
        g = hist[hist.factor == f].set_index("date").z
        ax.plot(g.index, g.values, color=SERIES[i], lw=1.4, label=f.replace("_", " "))
    ax.axhline(2.0, color=SERIES[7], lw=1, ls="--")
    ax.text(0.99, 2.05, "alert threshold", color=INK2, fontsize=8, va="bottom", ha="right",
            transform=ax.get_yaxis_transform())
    ax.axhline(0, color=AXIS, lw=0.8)
    ax.set_ylabel("comomentum z-score")
    ax.set_title(title, loc="left")
    ax.legend(fontsize=7.5, ncol=n, loc="upper left")
    _datefmt(ax)
    _save(fig, path)


def chart_seasonality_bias(sb: pd.DataFrame, strategy: str, path: Path):
    g = sb[sb.strategy == strategy]
    if not len(g):
        return
    fig, ax = plt.subplots(figsize=(6.5, 3))
    x = np.arange(len(g))
    ax.bar(x - 0.18, g.bias_flat.values, width=0.34, color=SERIES[1], label="flat intraday profile")
    ax.bar(x + 0.18, g.bias_seasonal.values, width=0.34, color=SERIES[0], label="U-shaped seasonal profile")
    ax.set_xticks(x, [f"{9 + (30 + 30 * b) // 60}:{(30 + 30 * b) % 60:02d}" for b in g.bar], rotation=45, fontsize=7.5)
    ax.set_ylabel("bias statistic by bar")
    ax.set_title(f"{strategy}: bar-level risk forecast bias", loc="left")
    ax.legend(fontsize=7.5, loc="upper center", ncol=2)
    ax.grid(axis="x", visible=False)
    _save(fig, path)


# --------------------------------------------------------------------------- #
# Summary tables
# --------------------------------------------------------------------------- #
def strategy_scorecard(res) -> pd.DataFrame:
    d = res.att.by_reporting_day()
    rows = []
    for s, g in d.groupby(level="strategy"):
        g = g.droplevel("strategy")
        raw, lo, hi = sharpe_ci(g.total_attributed)
        resid = g.specific + g.slow_factor
        rs, rlo, rhi = sharpe_ci(resid)
        alpha_net = g.total_attributed - g.factor - g.fx
        an, _, _ = sharpe_ci(alpha_net)
        gmv = res.att.daily.xs(s, level="strategy").gmv_eod.mean()
        rows.append({"strategy": s, "team": res.trading.team_of(s), "avg_gmv": gmv,
                     "total_pnl": g.total_attributed.sum(), "sharpe": raw, "sharpe_95ci": f"[{lo:.2f}, {hi:.2f}]",
                     "residual_sharpe": rs, "residual_95ci": f"[{rlo:.2f}, {rhi:.2f}]",
                     "net_alpha_sharpe": an, "factor_pnl": g.factor.sum(),
                     "cost_pnl": (g.delay_cost + g.impact_cost + g.commissions).sum()})
    return pd.DataFrame(rows)


def latest_exposures(res) -> pd.DataFrame:
    ex = res.att.exposures
    rows = []
    for s, g in ex.groupby("strategy"):
        last = g.date.max()
        e = g[g.date == last].set_index("factor").exposure_pct_gmv
        b = res.att.books[s]
        t = b.dates.get_loc(last)
        rm = res.risk[b.market]
        pr = rm.portfolio(t, b.h.values[t])
        gmv = np.abs(b.h.values[t]).sum()
        style = [f for f in e.index if res.models[b.market].expo.groups.get(f) == "style"]
        top = e[style].abs().sort_values(ascending=False).head(3).index
        rows.append({"strategy": s, "as_of": last, "gross": gmv, "net_pct": e.get("net", np.nan),
                     "beta_adj_net_pct": e.get("beta_adj_net", np.nan),
                     "top_styles": ", ".join(f"{f} {e[f]:+.2f}" for f in top),
                     "stat_1": e.get("stat_1", np.nan),
                     "pred_vol_ann_pct_gmv": pr.total_vol * np.sqrt(TRADING_DAYS) / gmv if gmv else np.nan,
                     "factor_risk_share": pr.factor_vol ** 2 / pr.total_vol ** 2})
    return pd.DataFrame(rows)


def hedge_suggestions(res, n: int = 2) -> pd.DataFrame:
    """Risk reduction from neutralising each strategy's largest unintended exposures."""
    rows = []
    for s, b in res.att.books.items():
        rm = res.risk[b.market]
        last = res.att.daily.xs(s, level="strategy").index.max()
        t = b.dates.get_loc(last)
        h = b.h.values[t]
        if np.abs(h).sum() == 0:
            continue
        pr = rm.portfolio(t, h)
        x = pr.exposures.copy()
        g = res.models[b.market].expo.groups
        cand = [f for f in x.index if g.get(f) in ("style", "market", "statistical")]
        F = pd.DataFrame(rm.F[t], index=rm.factors, columns=rm.factors)
        contrib = pr.factor_contrib[cand].sort_values(ascending=False).head(n)
        for f in contrib.index:
            x2 = x.copy(); x2[f] = 0
            v2 = np.sqrt(x2 @ F @ x2 + pr.specific_vol ** 2)
            hedge = "index futures / beta hedge" if f in ("market", "beta", "btc_beta") else "optimizer constraint"
            rows.append({"strategy": s, "factor": f, "exposure_usd_per_unit": x[f],
                         "risk_contrib_pct": pr.factor_contrib[f] / pr.total_vol,
                         "vol_reduction_pct": 1 - v2 / pr.total_vol, "suggested_tool": hedge})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
def _surrogate_section(sur: dict) -> list[str]:
    """PM-report block for the XGBoost weight surrogate. SHAP values are shown in bp of GMV."""
    fit = sur["fit"].copy()
    lines = [f"**What the model is effectively selecting on** (XGBoost surrogate of position weight / GMV; "
             f"R² {sur['r2_is']:.2f} in sample, {sur['r2_oos']:.2f} out of sample on the last 30% of dates)", ""]
    if not sur["reliable"]:
        lines += [f"*The surrogate does not generalise (out-of-sample R² below "
                  f"{SURROGATE_MIN_R2_OOS:.2f}): the attributions below describe an overfit model and are not "
                  f"used to propose factors.*", ""]
    imp = sur["importance"].head(8).copy()
    imp["mean_abs_shap_bp"] = imp.mean_abs_shap * 1e4
    lines += [md_table(imp[["feature", "mean_abs_shap_bp", "shap_share", "perm_importance", "maps_to_core_factor"]],
                       {"shap_share": "pct"}), "",
              "Grouped by core factor (SHAP summed within a group, so correlated inputs are not split): " + "; ".join(
                  f"{r.group} {r.shap_share:.0%}" for r in sur["by_factor"].head(5).itertuples()), "",
              "Strongest interactions (mean |SHAP interaction|, bp): " + "; ".join(
                  f"{r.a} × {r.b} = {r.mean_abs_interaction * 1e4:.1f}" for r in sur["interactions"].head(3).itertuples()),
              "",
              "Fit by target (linear = ridge on the same features; trees adding little over linear means the "
              "selection is close to a linear screen):", "",
              md_table(fit), ""]
    return lines


SHAP_XCHECK_MIN_CORR = 0.3        # daily linear-vs-SHAP correlation below this is a disagreement ...
SHAP_XCHECK_MATERIAL = 0.02       # ... when the bucket's P&L is at least this share of |holdings P&L|


def _signed_usd(v: float) -> str:
    return ("+" if v >= 0 else "-") + _fmt(abs(float(v)), "usd")


def _shap_xcheck_flags(sa: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Buckets where the two attributions disagree, and characteristics outside the core model that earn P&L."""
    c = sa["comparison"]
    total = abs(c.loc[c.bucket == "total", "linear_usd"].iloc[0]) or 1.0
    big = np.maximum(c.linear_usd.abs(), c.shap_usd.abs()) >= SHAP_XCHECK_MATERIAL * total
    disagree = c[big & (c.daily_corr < SHAP_XCHECK_MIN_CORR) & (c.bucket != "total")]
    unmapped = c[big & c.bucket.str.startswith("unmapped:")]
    return disagree, unmapped


def _shap_attribution_section(sa: dict) -> list[str]:
    """PM-report block: SHAP attribution next to the official linear attribution (USD over the live window)."""
    c = sa["comparison"]
    c = c[(c.linear_usd.abs() + c.shap_usd.abs()) > 0]
    lines = ["**SHAP cross-check of the linear attribution** (return surrogate: per-date additive XGBoost, "
             f"cross-fitted R² {sa['return_r2_crossfit']:.3f} vs {sa['return_r2_crossfit_ridge']:.3f} for a "
             f"cross-fitted linear model on the same features and {sa['return_r2_linear_model']:.3f} in-sample for "
             "the factor model). Both columns add up to the same holdings P&L. The cross-fitted surrogate cannot "
             "absorb a stock's own return, so its characteristic buckets are smaller and its residual larger: "
             "read agreement from the daily correlation and sign, not the size of the totals.", "",
             md_table(c[["bucket", "linear_usd", "shap_usd", "diff_usd", "daily_corr"]],
                      {"linear_usd": "usd", "shap_usd": "usd", "diff_usd": "usd"}), ""]
    disagree, unmapped = _shap_xcheck_flags(sa)
    if len(disagree):
        lines += ["Disagreement (daily correlation below "
                  f"{SHAP_XCHECK_MIN_CORR:.1f} on a material bucket): " + "; ".join(
                      f"{r.bucket} (corr {r.daily_corr:+.2f})" for r in disagree.itertuples()), ""]
    d = sa["decision"].drop(["residual", "outside_estu"], errors="ignore")
    d = d.reindex(d.abs().sort_values(ascending=False).index).head(5)
    note = "" if sa["weight_reliable"] else " *Weight surrogate does not generalise; treat as indicative only.*"
    lines += ["Decision view (weight-side SHAP: P&L of the slice of the book each characteristic explains; "
              f"unexplained weights {_signed_usd(sa['decision'].get('residual', np.nan))}): " + "; ".join(
                  f"{k} {_signed_usd(v)}" for k, v in d.items()) + "." + note, ""]
    return lines


def intraday_factor_detail(res) -> pd.DataFrame:
    """Per-factor split of the intraday buckets `overnight_factor` and `intraday_factor`, one row per
    (date, strategy, factor).  Index futures and order flow are separate buckets and not included."""
    fd = res.intraday.factor_detail
    groups = res.models["US"].expo.groups          # the intraday layer runs on the US model
    return fd.assign(group=fd.factor.map(groups), total_pnl=fd.overnight_pnl + fd.intraday_pnl)


def _intraday_factor_appendix(res) -> list[str]:
    """PM-report appendix: intraday factor P&L by factor and strategy (USD over the intraday window)."""
    if res.intraday is None or not len(res.intraday.factor_detail):
        return []
    fd = intraday_factor_detail(res)
    cols = ["overnight_pnl", "intraday_pnl", "total_pnl"]
    lines = ["## Appendix A: intraday factor P&L by factor", "",
             f"Split of `overnight_factor` and `intraday_factor` from the intraday decomposition, summed over the last "
             f"{fd.date.nunique()} days of 30-minute bars. Factor returns are re-estimated bar by bar on the daily "
             "exposures, so these are not the daily factor P&L figures. Index futures and order flow are separate "
             "buckets and are not shown. Factors with no P&L are omitted. Daily rows: "
             "`tables/intraday_factor_attribution.csv`.", ""]
    for s, g in fd.groupby("strategy", sort=False):
        t = g.groupby("factor", sort=False).agg(group=("group", "first"), **{c: (c, "sum") for c in cols})
        t = t[t[cols].abs().sum(axis=1) > 0].sort_values("total_pnl", key=np.abs, ascending=False)
        t.loc["TOTAL"] = ["", *t[cols].sum()]
        lines += [f"### {s}", "", md_table(t, {c: "usd" for c in cols}, index=True), ""]
    return lines


def _findings(res, score: pd.DataFrame, lat: pd.DataFrame) -> list[str]:
    out = []
    D = res.diagnostics
    for s, sa in D.get("shap_attribution", {}).items():
        disagree, unmapped = _shap_xcheck_flags(sa)
        if len(disagree):
            out.append(f"**{s}**: linear and SHAP attribution disagree on " + ", ".join(
                f"{r.bucket} (daily corr {r.daily_corr:+.2f}; linear {_signed_usd(r.linear_usd)}, "
                f"SHAP {_signed_usd(r.shap_usd)})" for r in disagree.itertuples()) + ".")
        if len(unmapped):
            out.append(f"**{s}** earns P&L through characteristics outside the core model (SHAP return side): " +
                       ", ".join(f"{r.bucket.split(':', 1)[1]} {_signed_usd(r.shap_usd)}" for r in unmapped.itertuples())
                       + ".")
    for s, sur in D.get("surrogate", {}).items():
        if sur["candidate_factors"] and sur["reliable"]:
            out.append(f"**{s}** selects on characteristics outside the core model: "
                       f"{', '.join(sur['candidate_factors'])} (XGBoost surrogate out-of-sample R² {sur['r2_oos']:.2f}; "
                       f"mean |SHAP|).")
    pca = D.get("residual_pca", {}).get("US")
    if pca is not None:
        a = pca["associations"]
        a1 = a[a.pc == 1].iloc[0]
        out.append(f"US named-model residuals have {pca['n_above_edge']} eigenvalue(s) above the Marchenko-Pastur "
                   f"edge; PC1 is most associated with **{a1.candidate}** (corr {a1['corr']:+.2f}). "
                   "Recommendation: promote it to an explicit core factor through governance.")
    rc = D.get("resid_corr_named")
    if rc is not None and (rc.flag & (rc.rho > 0)).any():
        top = rc[rc.flag & (rc.rho > 0)].iloc[0]
        rc2 = D["resid_corr_core"].set_index(["a", "b"]).rho.get((top.a, top.b), np.nan)
        po = D["overlap"]["position_overlap"].loc[top.a, top.b]
        if top.rho - rc2 > 0.1:
            why = "most of it was a missing common factor, now captured by the statistical factors"
        elif po > 0.1:
            why = (f"it survives the statistical factors, so it is shared idiosyncratic bets rather than a missing "
                   f"factor (average position cosine overlap {po:+.2f}) - the two books are partly the same alpha")
        else:
            why = (f"neither statistical factors nor position overlap ({po:+.2f}) explain it - the books likely "
                   "trade a common signal at different horizons; review jointly before adding capital to either")
        out.append(f"Residual P&L of **{top.a}** and **{top.b}** is correlated ({top.rho:+.2f} named-only, "
                   f"{rc2:+.2f} with statistical factors): {why}.")
    for r in lat.itertuples():
        if abs(r.beta_adj_net_pct) > 0.05 and abs(r.net_pct) < 0.05:
            out.append(f"**{r.strategy}** is dollar-neutral (net {r.net_pct:+.1%}) but beta-adjusted net "
                       f"{r.beta_adj_net_pct:+.1%} of gross.")
    rel = D.get("releases")
    if rel is not None and len(rel):
        top = rel[rel.material].assign(a=lambda x: x.t_stat.abs()).sort_values("a", ascending=False)
        top = top[~top.factor.isin(["beta_adj_net", "vol_shock", "liq_shock", "fx", "rates", "us_session"])]
        top = top.groupby("strategy").head(1)
        for r in top.itertuples():
            out.append(f"Model release **{r.strategy} {r.version}** ({r.release_date:%Y-%m-%d}) most changed "
                       f"`{r.factor}` exposure {r.before:+.2f} -> {r.after:+.2f} (t={r.t_stat:.1f}).")
    ss = D.get("shock_sensitivities")
    if ss is not None and len(ss):
        v = ss[(ss.shock == "vol_shock") & (ss.empirical_t < -3)].sort_values("empirical_pnl_3sd")
        for r in v.head(2).itertuples():
            agree = r.model_pnl_3sd < 0 and abs(r.model_pnl_3sd) >= 0.7 * abs(r.empirical_pnl_3sd)
            tail = ("consistent with the risk model" if agree else
                    f"while the Gaussian risk model implies {r.model_pnl_3sd / 1e3:+,.0f}k - liquidity-provision "
                    "losses cluster in stress, so shock limits use the worse of the two")
            out.append(f"**{r.strategy}** is short volatility: a 3-sigma implied-vol shock has historically cost "
                       f"{-r.empirical_pnl_3sd / 1e3:,.0f}k (t={r.empirical_t:.1f}), {tail}.")
    ep = getattr(res.intraday, "epps_books", None) if res.intraday is not None else None
    if ep is not None and len(ep):
        g = ep.groupby("strategy")[["beta_concurrent", "beta_dimson"]].mean()
        g["gap"] = g.beta_dimson - g.beta_concurrent
        r = g.sort_values("gap").iloc[-1]
        if r.gap > 0.02:
            out.append(f"**{g.sort_values('gap').index[-1]}** looks intraday beta-neutral on "
                       f"concurrent 30-minute betas ({r.beta_concurrent:+.3f} per $ gross) but carries "
                       f"{r.beta_dimson:+.3f} on lag-corrected betas (Epps effect) - hedge with Dimson betas.")
    ic = res.stress.get("internal_crowding", {}).get("summary")
    if ic is not None and len(ic):
        for r in ic.itertuples():
            out.append(f"Internal crowding ({r.market}): {r.names_2plus_teams_same_side} names are held on the same "
                       f"side by two or more teams ({r.gross_in_shared_names_pct:.0%} of firm gross); exiting together "
                       f"costs {r.crowding_premium_usd / 1e3:,.0f}k more than each team exiting alone.")
    fc = D.get("factor_crowding", {})
    for m, d in fc.items():
        crowded = d["latest"][d["latest"].crowded]
        if len(crowded):
            out.append(f"Factor-level crowding ({m}): " + ", ".join(
                f"`{r.factor}` comomentum z={r.z:.1f}" for r in crowded.itertuples())
                       + " - stress shocks on these factors are scaled up.")
    fs = res.validation.get("factor_selection")
    if fs is not None and len(fs):
        promo = fs[fs.decision == "promote to core"]
        demo = fs[fs.decision.str.startswith("review")]
        if len(promo):
            out.append("Factor selection: candidates passing the tests on our data - " + ", ".join(
                f"`{r.factor}` ({r.market})" for r in promo.itertuples()) + "; promotion is a governance decision.")
        if len(demo):
            out.append("Factor selection: core factors failing the tests (review for the monitoring layer) - " + ", ".join(
                f"`{r.factor}` ({r.market})" for r in demo.itertuples()) + ".")
    for r in score.itertuples():
        if r.sharpe < 1 and r.residual_sharpe > r.sharpe + 0.5:
            out.append(f"**{r.strategy}** raw Sharpe {r.sharpe:.2f} understates skill: residual Sharpe "
                       f"{r.residual_sharpe:.2f} - factor P&L {r.factor_pnl / 1e6:+.1f}m is a drag.")
    return out


def write_risk_report(res, out: Path, charts: Path) -> str:
    L = res.limits
    cur = L["current"]
    lat = latest_exposures(res)
    fr = res.firm_risk_last
    asof = res.att.daily.index.get_level_values(0).max()
    lines = [f"# Risk & Middle Office report - as of {asof:%Y-%m-%d}", "",
             "> **Decisions supported:** limit enforcement, escalation, de-risking during stress, new-strategy approval.", ""]
    if fr is not None:
        gross = lat.gross.sum()
        lines += ["## Firm risk", "",
                  f"- Gross exposure: **{gross / 1e6:,.1f}m USD**; predicted daily vol **{fr.total_vol / 1e6:,.2f}m** "
                  f"(annualised {fr.total_vol * np.sqrt(TRADING_DAYS) / 1e6:,.1f}m, "
                  f"{fr.total_vol * np.sqrt(TRADING_DAYS) / gross:.1%} of gross); 1-day 99% normal VaR "
                  f"**{2.33 * fr.total_vol / 1e6:,.2f}m**.",
                  f"- Diversification benefit across local models: {fr.diversification / 1e6:,.2f}m daily vol.", "",
                  md_table(pd.DataFrame({"standalone_daily_vol": fr.standalone_vol,
                                         "contribution_daily_vol": fr.contribution,
                                         "share": fr.contribution / fr.total_vol}),
                           {"standalone_daily_vol": "usd", "contribution_daily_vol": "usd", "share": "pct"}, index=True),
                  "", "![firm risk](charts/firm_risk.png)", ""]
        top = fr.factor_contrib.abs().sort_values(ascending=False).head(10).index
        lines += ["### Top firm-level factor risk contributors", "",
                  md_table(pd.DataFrame({"contribution_daily_vol": fr.factor_contrib[top],
                                         "share_of_firm_vol": fr.factor_contrib[top] / fr.total_vol}),
                           {"contribution_daily_vol": "usd", "share_of_firm_vol": "pct"}, index=True), ""]
    lines += ["## Limit status (latest day)", ""]
    alert = cur[(cur.status != "OK")].copy()
    alert["status"] = alert.status.map(STATUS_ICON)
    lines += [md_table(alert[["strategy", "limit", "value", "limit_value", "utilisation", "status", "soft"]],
                       {"utilisation": "pct"}) if len(alert) else "All hard limits within 80% utilisation.", ""]
    br = L["breaches"]
    lines += ["### Hard-limit breach episodes (history)", "",
              md_table(br.tail(25), {"utilisation": "pct"}) if len(br) else "None.", ""]
    lines += ["## Strategy exposures", "",
              md_table(lat, {"gross": "usd", "net_pct": "pct", "beta_adj_net_pct": "pct",
                             "pred_vol_ann_pct_gmv": "pct", "factor_risk_share": "pct"}), "",
              "Style exposures are in cross-sectional standard deviations per dollar of gross.", ""]
    D = res.diagnostics
    ss = D.get("shock_sensitivities")
    if ss is not None and len(ss):
        tab = ss.pivot(index="strategy", columns="shock", values="empirical_pnl_3sd")
        mod = ss.pivot(index="strategy", columns="shock", values="model_pnl_3sd")
        tab.columns = [f"{c} (empirical)" for c in tab.columns]
        mod.columns = [f"{c} (model)" for c in mod.columns]
        both = pd.concat([mod, tab], axis=1)
        both = both[sorted(both.columns)]
        mm = res.risk["US"].macro_mult.dropna()
        lines += ["## Market-wide shock exposures (time-series factors)", "",
                  "Expected P&L (USD) for a 3-sigma move in each shock. *Model*: E[P&L | shock] from the factor "
                  "covariance (includes co-moving factors such as reversal). *Empirical*: regression of daily P&L on "
                  "the shock. Reversal books earn a liquidity premium and lose when volatility spikes or liquidity "
                  "evaporates, even when every cross-sectional exposure looks neutral (Nagel 2012).", "",
                  md_table(both, {c: "usd" for c in both.columns}, index=True), "",
                  f"- Scheduled macro announcements scale macro-sensitive factor variance by a learned multiplier "
                  f"(latest {mm.iloc[-1]:.2f}x on US macro days)." if len(mm) else "", ""]
    S = res.stress
    hyp = S["hypothetical"].pivot(index="scenario", columns="strategy", values="pnl_usd")
    hyp["FIRM"] = hyp.sum(axis=1)
    hyp["FIRM (crowding-scaled)"] = S["hypothetical"].groupby("scenario").pnl_usd_crowding_scaled.sum()
    lines += ["## Stress tests (current holdings, USD)", "", "### Hypothetical factor scenarios", "",
              "The last column scales shocks on factors the crowding monitor flags as crowded.", "",
              md_table(hyp.round(0), {c: "usd" for c in hyp.columns}, index=True), ""]
    if len(S["historical_factor"]):
        h2 = S["historical_factor"].pivot_table(index=["episode", "date"], columns="strategy", values="pnl_usd")
        lines += ["### Historical factor replay (embedded stress days)", "",
                  md_table(h2, {c: "usd" for c in h2.columns}, index=True), ""]
    if len(S["stock_level"]):
        h3 = S["stock_level"].pivot_table(index=["episode", "date"], columns="strategy", values="pnl_usd")
        lines += ["### Model-free replay (actual stock returns of the stress day on today's holdings)", "",
                  md_table(h3, {c: "usd" for c in h3.columns}, index=True), ""]
    lines += ["### Liquidity stress (20% ADV participation, 3x spreads)", "",
              md_table(S["liquidity"], {"gmv_usd": "usd", "pct_gmv_liquid_1d": "pct", "pct_gmv_over_5d": "pct",
                                        "stressed_liquidation_cost_usd": "usd"}), ""]
    # ---- crowding at three levels ----
    lines += ["## Crowding", "", "### 1. Short-side crowding (core factor)", "",
              "Composite of short interest / float, days-to-cover, prime-broker borrow fee, borrow scarcity and "
              "lending utilisation; lagged to publication, standardised within market, cleaned of size, volatility "
              "and liquidity.", ""]
    fs = res.validation.get("factor_selection")
    if fs is not None:
        cr = fs[fs.factor == "crowding"][["market", "marginal_r2", "pct_days_abs_t_gt_2", "ann_vol",
                                          "resid_corr_reduction", "max_abs_z_on_squeeze_days", "decision"]]
        cov = {m: res.models[m].expo.extras.get("crowding_coverage", pd.Series([np.nan])).iloc[-1] for m in ("US", "CN")}
        cr = cr.assign(coverage=cr.market.map(cov))
        lines += [md_table(cr, {"ann_vol": "pct", "coverage": "pct"}), "",
                  "Coverage below 100% (CN) reflects names that cannot be borrowed; they score neutral.", ""]
    lines += ["### 2. Factor-level crowding (monitoring indicator)", "",
              "Comomentum: average pairwise correlation of residual returns within each factor's top and bottom "
              "decile over 60 days (Lou and Polk), plus short interest in the short leg relative to the universe "
              "(Hanson and Sunderam). Flagged factors get larger stress shocks.", ""]
    for m, d in D.get("factor_crowding", {}).items():
        lines += [f"**{m}**", "", md_table(d["latest"], {"stress_multiplier": "num"}), ""]
    lines += ["![crowding](charts/crowding_monitor_US.png)", ""]
    ic = S.get("internal_crowding", {})
    if ic and len(ic.get("summary", [])):
        lines += ["### 3. Internal crowding (liquidity stress)", "",
                  "Firm-wide positions summed across teams. No single team can see this risk.", "",
                  md_table(ic["summary"], {"firm_gross_usd": "usd", "gross_in_shared_names_pct": "pct",
                                           "standalone_exit_cost_usd": "usd", "joint_exit_cost_usd": "usd",
                                           "crowding_premium_usd": "usd"}), "",
                  "**Largest firm positions relative to volume**", "",
                  md_table(ic["top_names"], {"firm_net_usd": "usd", "firm_gross_usd": "usd", "pct_adv": "pct"}), ""]
    dr = D["drift"]
    lines += ["## Exposure drift alerts (last 90 days)", ""]
    if len(dr):
        recent = dr[dr.date > asof - pd.Timedelta(days=90)]
        lines += [md_table(recent) if len(recent) else "None in the last 90 days.", ""]
    rel = D["releases"]
    if len(rel):
        lines += ["## Model releases: material exposure changes (|t| > 3)", "",
                  md_table(rel[rel.material][["strategy", "version", "release_date", "factor", "before", "after", "t_stat"]]), ""]
    st = D["overlap"]["stacking"]
    lines += ["## Cross-team stacking (30-day average exposures on shared factor names)", "",
              "Stacking ratio near 1 = teams hold the same tilt; near 0 = they offset.", "",
              md_table(st[st.index.isin(["beta_adj_net", "st_reversal", "crowding", "volatility", "liquidity",
                                         "size", "stat_1", "beta", "st_momentum"])],
                       {"firm_exposure_usd": "usd", "sum_abs_strategy": "usd", "stacking_ratio": "pct"}, index=True), ""]
    rec = res.recon
    bk = rec[rec["break"]].reset_index()
    lines += ["## Reconciliation to official P&L", "",
              f"- Strategy-days reconciled: {len(rec):,}; within tolerance: {(~rec['break']).mean():.2%}; "
              f"median |unexplained| ${rec.unexplained.abs().median():,.0f}.", "",
              md_table(bk, {"official": "usd", "total_attributed": "usd", "unexplained": "usd", "tolerance": "usd"})
              if len(bk) else "No breaks.", ""]
    dq = res.panels["US"].data_issues
    lines += ["## Data quality", "",
              f"- US: {len(dq)} flagged observations; CN: {len(res.panels['CN'].data_issues)} flagged observations "
              "(large moves without corporate action - verified against resumption-from-suspension and stress days).", ""]
    txt = "\n".join(lines)
    (out / "risk_report.md").write_text(txt, encoding="utf-8", newline="\n")
    return txt


def write_pm_report(res, out: Path, charts: Path) -> str:
    d = res.att.daily
    asof = d.index.get_level_values(0).max()
    lines = [f"# PM attribution report - as of {asof:%Y-%m-%d}", "",
             "> **Decisions supported:** hedges and optimizer constraints, model-release approval, capacity and cost management.",
             "", "Short-window attribution (20 days) is noisy - read it alongside the since-inception columns.", ""]
    hs = hedge_suggestions(res)
    for s in res.att.books:
        g = d.xs(s, level="strategy")
        last20 = g.iloc[-20:]
        comp = pd.DataFrame({"since_inception": g[COMPONENTS].sum(), "last_20d": last20[COMPONENTS].sum()})
        comp.loc["TOTAL attributed"] = [g.total_attributed.sum(), last20.total_attributed.sum()]
        comp.loc["official"] = [g.official.sum(), last20.official.sum()]
        fp = res.att.factor_pnl[res.att.factor_pnl.strategy == s].groupby("factor").pnl.sum()
        fp = fp[fp.abs() > 0].sort_values(key=np.abs, ascending=False).head(8)
        traded = g.traded_usd.sum()
        costs = pd.Series({"delay (decision -> arrival)": -g.delay_cost.sum(), "impact (arrival -> fill)": -g.impact_cost.sum(),
                           "commissions & fees": -g.commissions.sum()})
        lines += [f"## {s} ({res.trading.team_of(s)})", "",
                  f"![attribution](charts/attribution_{s}.png)", "",
                  md_table(comp, {"since_inception": "usd", "last_20d": "usd"}, index=True), "",
                  "**Largest factor P&L contributors (since inception)**", "",
                  md_table(fp.rename("pnl_usd").to_frame(), {"pnl_usd": "usd"}, index=True), "",
                  f"**Execution costs:** {costs.sum() / traded * 1e4:.2f} bps of {traded / 1e9:,.1f}bn traded "
                  f"(delay {costs.iloc[0] / traded * 1e4:.2f}, impact {costs.iloc[1] / traded * 1e4:.2f}, "
                  f"fees {costs.iloc[2] / traded * 1e4:.2f} bps).", ""]
        if res.intraday is not None and s in res.intraday.attribution.index.get_level_values(1):
            ia = res.intraday.attribution.xs(s, level="strategy")
            lines += [f"**Intraday decomposition (last {len(ia)} days, 30-minute bars)**[^intraday-factors]", "",
                      md_table(ia.sum().to_frame("usd").T, {c: "usd" for c in ia.columns}), "",
                      f"Intraday vs daily reconciliation: max |diff| ${ia.reconciliation_diff.abs().max():,.0f} per day. "
                      "Futures = index-futures market factor (intraday beta); order flow = imbalance factor "
                      "(attribution only).", ""]
            ep = res.intraday.epps_books
            ep = ep[ep.strategy == s] if len(ep) else ep
            if len(ep):
                lines += [f"**Intraday beta at peak position** (per $ gross): concurrent 30-minute "
                          f"{ep.beta_concurrent.mean():+.3f}, lag-corrected (Dimson) {ep.beta_dimson.mean():+.3f}, "
                          f"daily {ep.beta_daily.mean():+.3f}. A gap between the first two is the Epps effect.", ""]
        ssd = res.diagnostics.get("shock_sensitivities")
        if ssd is not None and len(ssd[ssd.strategy == s]):
            r = ssd[ssd.strategy == s].set_index("shock")
            lines += ["**Market-wide shock sensitivity (3-sigma, USD):** " + "; ".join(
                f"{k} model {v.model_pnl_3sd / 1e3:+,.0f}k / empirical {v.empirical_pnl_3sd / 1e3:+,.0f}k"
                for k, v in r.iterrows()), ""]
        mx = res.diagnostics.get("monitor_exposures")
        if mx is not None and len(mx) and s in set(mx.strategy):
            last = mx[mx.strategy == s]
            last = last[last.date == last.date.max()].set_index("factor").exposure_pct_gmv
            lines += ["**Candidate / background monitor exposures** (std units per $ gross, not attributed): " +
                      ", ".join(f"{k} {v:+.2f}" for k, v in last.items()), ""]
        h = hs[hs.strategy == s]
        if len(h):
            lines += ["**Hedging / neutralisation candidates**", "",
                      md_table(h.drop(columns="strategy"), {"exposure_usd_per_unit": "usd", "risk_contrib_pct": "pct",
                                                            "vol_reduction_pct": "pct"}), ""]
        sur = res.diagnostics.get("surrogate", {}).get(s)
        if sur:
            lines += _surrogate_section(sur)
        sa = res.diagnostics.get("shap_attribution", {}).get(s)
        if sa:
            lines += _shap_attribution_section(sa)
        rel = res.diagnostics["releases"]
        rel = rel[(rel.strategy == s)]
        if len(rel):
            lines += ["**Model release comparison (20 days before vs after)**", "",
                      md_table(rel[["version", "release_date", "factor", "before", "after", "t_stat", "material"]]), ""]
    cc = res.diagnostics.get("crosscheck")
    if cc is not None and len(cc):
        agg = cc.groupby("factor")[["returns_based", "holdings_based"]].mean()
        lines += ["## Returns-based cross-check (C1_US_EVENT)", "",
                  "Holdings-based exposures vs a rolling regression of strategy returns on factor returns (Sharpe 1992). "
                  "Agreement in sign confirms the holdings pipeline; the returns-based estimates are noisier and lag.", "",
                  md_table(agg, index=True), ""]
    appendix = _intraday_factor_appendix(res)
    if appendix:
        lines += appendix
        lines += ["[^intraday-factors]: `overnight_factor` and `intraday_factor` broken down by factor in "
                  "Appendix A (daily rows in `tables/intraday_factor_attribution.csv`).", ""]
    txt = "\n".join(lines)
    (out / "pm_report.md").write_text(txt, encoding="utf-8", newline="\n")
    return txt


def write_management_summary(res, out: Path) -> str:
    score = strategy_scorecard(res)
    lat = latest_exposures(res)
    ov = res.diagnostics["overlap"]
    asof = res.att.daily.index.get_level_values(0).max()
    team = score.groupby("team")[["avg_gmv", "total_pnl", "factor_pnl", "cost_pnl"]].sum()
    lines = [f"# Management summary - as of {asof:%Y-%m-%d}", "",
             "> **Decisions supported:** capital and risk budgets per team, strategy shutdowns, firm risk appetite.", "",
             "## Key findings", ""] + [f"- {f}" for f in _findings(res, score, lat)] + [
             "", "## Are we paying for alpha or for factor exposure?", "",
             "Residual Sharpe uses only the non-factor part of holding P&L; 95% confidence intervals (Lo 2002) show "
             "how much of the difference is noise.", "",
             md_table(score, {"avg_gmv": "usd", "total_pnl": "usd", "factor_pnl": "usd", "cost_pnl": "usd"}), "",
             "### By team", "", md_table(team, {c: "usd" for c in team.columns}, index=True), "",
             "## How diversified are we really?", "",
             f"- Effective number of independent bets (total P&L, participation ratio): "
             f"**{ov['enb_total']['participation_ratio']:.1f}** of {ov['enb_total']['n']} strategies; "
             f"on residual P&L: **{ov['enb_residual']['participation_ratio']:.1f}**.",
             f"- Cluster order (similar strategies adjacent): {' → '.join(ov['cluster_order'])}.", "",
             "![overlap](charts/overlap_total.png)", "",
             "![residual overlap](charts/overlap_residual_named.png)", "",
             "## Risk budget usage", "",
             md_table(lat[["strategy", "gross", "pred_vol_ann_pct_gmv", "factor_risk_share", "beta_adj_net_pct"]],
                      {"gross": "usd", "pred_vol_ann_pct_gmv": "pct", "factor_risk_share": "pct", "beta_adj_net_pct": "pct"}), ""]
    hyp = res.stress["hypothetical"].groupby("scenario")[["pnl_usd", "pnl_usd_crowding_scaled"]].sum().sort_values("pnl_usd")
    hyp.columns = ["firm_pnl_usd", "crowding_scaled_usd"]
    lines += ["## Firm-level tail risk (hypothetical scenarios on current holdings)", "",
              md_table(hyp, {c: "usd" for c in hyp.columns}, index=True), ""]
    txt = "\n".join(lines)
    (out / "management_summary.md").write_text(txt, encoding="utf-8", newline="\n")
    return txt


def write_validation_report(res, out: Path) -> str:
    V, D = res.validation, res.diagnostics
    lines = ["# Model validation report", "",
             "> **Question answered:** are the risk forecasts calibrated, does attribution reconcile, and is anything missing?", "",
             "## 1. Explanatory power", "", md_table(V["r2"], index=True), "",
             md_table(V["explained"], {"factor_share_of_hold_var": "pct"}), "",
             "## 2. Calibration: bias statistics (target 1, band 1 ± √(2/T))", "", "### Strategy portfolios (most important)", "",
             md_table(V["portfolio_bias"], {"within_band_pct": "pct", "realised_vol_ann": "usd", "pred_vol_ann": "usd"}), "",
             "![bias](charts/bias_A1_US_STATARB.png)", "", "### Factors", ""]
    for m, fb in V["factor_bias"].items():
        g = fb.groupby("group")[["mean_bias", "within_band_pct"]].mean()
        lines += [f"**{m}**", "", md_table(g, {"within_band_pct": "pct"}, index=True), ""]
    lines += ["### Specific risk", "", md_table(pd.DataFrame(V["specific_bias"]).T, {"within_band_pct": "pct"}, index=True), ""]
    lines += ["## 3. Benchmark comparison (challengers)", "",
              "The in-house model must beat a market+industry baseline and a pure PCA model on calibration and explanatory power.", "",
              md_table(V["challengers"], {"strategy_within_band_pct": "pct"}), ""]
    if "truth" in V:
        lines += ["## 4. Recovery of the simulated factor returns (synthetic data only)", ""]
        for m, t in V["truth"].items():
            lines += [f"**{m}**", "", md_table(t), ""]
    fs = V.get("factor_selection")
    if fs is not None and len(fs):
        lines += ["## 4b. Factor selection tests (Section 2.1)", "",
                  "Each factor must earn its place on our own data. Core factors: drop-one marginal R² (on the "
                  "affected stock-days for sparse event factors) and share of estimable days with |t| > 2. "
                  "Time-series factors: share of remaining variance explained by B·g (their cross-sectional R² is "
                  "understated because industry factors absorb their sector pattern). Candidates: add-one. Residual "
                  "correlation reduction is across this market's strategies.", "",
                  md_table(fs, {"ann_vol": "pct"}), ""]
    tb = V.get("ts_betas")
    if tb:
        lines += ["### Time-series betas: shrinkage and stability (Section 3.4)", ""]
        for m, t in tb.items():
            lines += [f"**{m}**", "", md_table(t), ""]
        lines += ["Shrinking noisy time-series betas toward the industry average raises their correlation with the "
                  "true sensitivities where individual estimates are noisiest.", ""]
    rmd = pd.DataFrame({m: {"ledoit_wolf_intensity": res.risk[m].shrinkage.dropna().mean(),
                            "macro_day_multiplier": res.risk[m].macro_mult.dropna().mean()}
                        for m in res.risk}).T
    lines += ["### Risk-model settings in use", "", md_table(rmd, index=True), ""]
    lines += ["## 5. Factor quality and collinearity", ""]
    for m, q in V["factor_quality"].items():
        lines += [f"**{m}**", "", md_table(q[q.group != "industry"]), ""]
    for m, v in V["vif"].items():
        lines += [f"**VIF {m}** (flag > 5)", "", md_table(v, index=True), ""]
    for m, s in V["stability"].items():
        lines += [f"**Exposure stability {m}** (day-on-day cross-sectional correlation)", "",
                  md_table(s.to_frame(), index=True), ""]
    lines += ["## 6. Missing-factor tests", "", "### Residual correlation across strategies", "",
              "Named factors only:", "", md_table(D["resid_corr_named"].head(8)), "",
              "Core model (named + statistical):", "", md_table(D["resid_corr_core"].head(8)), ""]
    for m, p in D["residual_pca"].items():
        lines += [f"### PCA on {m} named-model residuals (last {p['T']} days, {p['N']} stocks)", "",
                  f"Marchenko-Pastur edge {p['mp_edge']:.2f}; eigenvalues above edge: **{p['n_above_edge']}**; "
                  f"after statistical factors: {D['residual_pca_core'][m]['n_above_edge']}.", "",
                  md_table(p["eigenvalues"].head(5).to_frame("eigenvalue"), index=True), "",
                  md_table(p["associations"]), ""]
    ss = D["shared_shocks"]
    lines += ["### Shared residual shocks (≥3 strategies below -2σ on the same day)", "",
              md_table(ss.reset_index(), {"residual_pnl": "usd"}) if len(ss) else "None.", ""]
    lines += ["## 7. Regimes and cross-market structure", "",
              f"- Regime classification accuracy vs simulated truth: {V.get('regime_accuracy', np.nan):.1%}.", "",
              "![regimes](charts/regimes.png)", "", md_table(D["lead_lag"]), "",
              "CN market follows the previous US session; the global layer's Newey-West lag term captures this.", ""]
    if "event_replay" in V:
        lines += ["## 8. Historical event replay", "",
                  "Did forecasts flag the risk beforehand, and does attribution explain the loss afterwards?", "",
                  md_table(V["event_replay"], {"hold_pnl": "usd", "factor": "usd", "specific": "usd",
                                               "trading_and_costs": "usd", "factor_share_of_loss": "pct"}), ""]
    if res.intraday is not None:
        I = res.intraday
        sb = I.seasonality_bias
        if len(sb):
            g = sb.groupby("strategy").agg(mean_seasonal=("bias_seasonal", "mean"),
                                           dispersion_seasonal=("bias_seasonal", "std"),
                                           mean_flat=("bias_flat", "mean"), dispersion_flat=("bias_flat", "std"))
            lines += ["## 8b. Intraday model", "", "### Seasonality normalisation", "",
                      "Bar-level bias statistics of start-of-bar holdings P&L. With the U-shaped profile the bias is "
                      "flat across the day (low dispersion); a flat profile over-forecasts midday and under-forecasts "
                      "the open and close.", "", md_table(g, index=True), "",
                      "![seasonality](charts/seasonality_bias_A1.png)", "", "![profile](charts/intraday_vol_profile.png)", ""]
        b = I.betas.dropna()
        if len(b):
            lines += ["### Asynchronous trading (Epps effect)", "",
                      f"Average stock beta to index futures: daily {b.daily_beta.mean():.2f}, concurrent 30-minute "
                      f"{b.concurrent_30m.mean():.2f}, lag-corrected (Dimson) {b.dimson_30m.mean():.2f} "
                      f"(same bar {b.dimson_b0_30m.mean():.2f} + next bar {b.dimson_b1_30m.mean():.2f}). Concurrent "
                      "intraday betas are biased toward zero. Intraday exposures use the two Dimson parts separately: "
                      "the same-bar part shrunk toward the daily beta and the next-bar part toward zero, so each bar "
                      "removes the futures response that actually lands in it.", ""]
        if len(I.macro_bars):
            lines += ["### Macro announcement bars", "", md_table(I.macro_bars), ""]
    rec = res.recon
    ia = res.intraday.attribution if res.intraday is not None else pd.DataFrame()
    pb = V["portfolio_bias"]
    lines += ["## 9. Usefulness scorecard (Section 4)", "",
              md_table(pd.DataFrame([
                  {"dimension": "Calibration", "metric": "strategy bias within band",
                   "result": f"{pb.within_band_pct.mean():.0%} of windows; mean bias {pb.mean_bias.mean():.2f}"},
                  {"dimension": "Explanatory power", "metric": "share of holding-P&L variance explained by factors",
                   "result": f"median {V['explained'].factor_share_of_hold_var.median():.0%}"},
                  {"dimension": "Reconciliation", "metric": "attribution vs official P&L",
                   "result": f"{(~rec['break']).mean():.2%} of strategy-days within tolerance"},
                  {"dimension": "Intraday reconciliation", "metric": "bar-level vs daily MTM",
                   "result": f"max |diff| ${ia.reconciliation_diff.abs().max():,.0f}" if len(ia) else "–"},
                  {"dimension": "Stability", "metric": "style exposure day-on-day corr (US)",
                   "result": f"{V['stability']['US'].mean():.2f}"},
                  {"dimension": "Early warning", "metric": "drift alerts / release changes flagged",
                   "result": f"{len(D['drift'])} alerts; {int(D['releases'].material.sum()) if len(D['releases']) else 0} material release changes"},
                  {"dimension": "Decision impact / adoption", "metric": "documented decisions, report usage",
                   "result": "tracked in production (decision log), not measurable on synthetic data"},
              ])), ""]
    txt = "\n".join(lines)
    (out / "validation_report.md").write_text(txt, encoding="utf-8", newline="\n")
    return txt


def write_all(res, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    charts, tables = out / "charts", out / "tables"
    charts.mkdir(exist_ok=True); tables.mkdir(exist_ok=True)
    att = res.att
    for s in att.books:
        chart_cum_attribution(att.daily, s, charts / f"attribution_{s}.png")
    ov = res.diagnostics["overlap"]
    order = ov["cluster_order"]
    chart_heatmap(ov["corr_total"].loc[order, order], "Strategy P&L correlation (clustered)", charts / "overlap_total.png")
    chart_heatmap(ov["corr_residual_named_only"].loc[order, order],
                  "Residual P&L correlation, named factors only", charts / "overlap_residual_named.png")
    us = res.models["US"]
    chart_factor_cum(us.factor_returns, ["market", "st_reversal", "crowding", "volatility", "liquidity",
                                         "size", "stat_1", "crypto_beta"], "US core factor returns (cumulative)",
                     charts / "factors_US.png")
    chart_regimes(res.diagnostics["regimes"], us.factor_returns["market"], charts / "regimes.png")
    if res.intraday is not None:
        chart_vol_profile(res.intraday.vol_profile, charts / "intraday_vol_profile.png")
    rel = res.trading.releases.set_index("strategy").release_date
    chart_exposure(att.exposures, "D1_US_CROWDING", "volatility", rel.get("D1_US_CROWDING"), charts / "exposure_D1_volatility.png")
    chart_exposure(att.exposures, "C1_US_EVENT", "beta_adj_net", rel.get("C1_US_EVENT"), charts / "exposure_C1_beta.png")
    if len(res.firm_risk):
        chart_firm_risk(res.firm_risk, charts / "firm_risk.png")
    chart_bias(res.validation["portfolio_bias_series"], "A1_US_STATARB", charts / "bias_A1_US_STATARB.png")
    fc = res.diagnostics.get("factor_crowding", {})
    if "US" in fc:
        chart_crowding(fc["US"]["history"], "US factor-level crowding (comomentum z-score)", charts / "crowding_monitor_US.png")
    if res.intraday is not None:
        chart_seasonality_bias(res.intraday.seasonality_bias, "A1_US_STATARB", charts / "seasonality_bias_A1.png")

    # tables
    att.daily.to_csv(tables / "attribution_daily.csv")
    att.exposures[att.exposures.date >= att.exposures.date.max() - pd.Timedelta(days=90)].to_csv(
        tables / "exposures_last_90d.csv", index=False)
    res.recon.to_csv(tables / "reconciliation.csv")
    res.limits["history"].to_csv(tables / "limit_history.csv", index=False)
    res.limits["breaches"].to_csv(tables / "limit_breaches.csv", index=False)
    for k, v in res.stress.items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                vv.to_csv(tables / f"stress_{k}_{kk}.csv", index=False)
        else:
            v.to_csv(tables / f"stress_{k}.csv", index=False)
    V, D = res.validation, res.diagnostics
    if "factor_selection" in V:
        V["factor_selection"].to_csv(tables / "factor_selection.csv", index=False)
    for m, t in V.get("ts_betas", {}).items():
        t.to_csv(tables / f"ts_beta_checks_{m}.csv", index=False)
    if "shock_sensitivities" in D:
        D["shock_sensitivities"].to_csv(tables / "shock_sensitivities.csv", index=False)
    for m, d in D.get("factor_crowding", {}).items():
        d["history"].to_csv(tables / f"factor_crowding_{m}.csv", index=False)
    mx = D.get("monitor_exposures")
    if mx is not None and len(mx):
        mx[mx.date >= mx.date.max() - pd.Timedelta(days=90)].to_csv(tables / "monitor_exposures_last_90d.csv", index=False)
    for m, fm in res.models.items():
        fm.factor_returns.to_csv(tables / f"factor_returns_{m}.csv")
        if fm.slow_returns is not None:
            fm.slow_returns.to_csv(tables / f"slow_factor_returns_{m}.csv")
    res.firm_risk.to_csv(tables / "firm_risk.csv")
    res.validation["portfolio_bias"].to_csv(tables / "bias_portfolios.csv", index=False)
    res.validation["challengers"].to_csv(tables / "challengers.csv", index=False)
    res.diagnostics["drift"].to_csv(tables / "drift_alerts.csv", index=False)
    res.diagnostics["releases"].to_csv(tables / "release_comparison.csv", index=False)
    strategy_scorecard(res).to_csv(tables / "strategy_scorecard.csv", index=False)
    if res.intraday is not None:
        res.intraday.attribution.to_csv(tables / "intraday_attribution.csv")
        intraday_factor_detail(res).to_csv(tables / "intraday_factor_attribution.csv", index=False)
        res.intraday.betas.to_csv(tables / "intraday_betas.csv")
        res.intraday.seasonality_bias.to_csv(tables / "intraday_seasonality_bias.csv", index=False)
        res.intraday.macro_bars.to_csv(tables / "intraday_macro_bars.csv", index=False)
    for s, sur in res.diagnostics["surrogate"].items():
        sur["importance"].to_csv(tables / f"surrogate_importance_{s}.csv", index=False)
        sur["fit"].to_csv(tables / f"surrogate_fit_{s}.csv", index=False)
        sur["interactions"].to_csv(tables / f"surrogate_interactions_{s}.csv", index=False)
        sur["shap_values"].to_csv(tables / f"surrogate_shap_{s}.csv.gz", index=False)
    for s, sa in res.diagnostics.get("shap_attribution", {}).items():
        sa["comparison"].to_csv(tables / f"shap_attribution_comparison_{s}.csv", index=False)
        sa["matrix"].to_csv(tables / f"shap_pnl_matrix_{s}.csv")
        sa["daily_shap"].to_csv(tables / f"shap_attribution_daily_{s}.csv")
    for m, rs in res.diagnostics.get("return_surrogate", {}).items():
        rs.fit.set_index(res.panels[m].dates[rs.fit.index]).to_csv(tables / f"return_surrogate_fit_{m}.csv")

    write_risk_report(res, out, charts)
    write_pm_report(res, out, charts)
    write_management_summary(res, out)
    write_validation_report(res, out)

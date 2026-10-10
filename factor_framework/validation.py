"""Validation (Section 3.6): statistical validity, missing factors, challengers.

* Bias statistics: std(realised / forecast) over rolling windows, with the
  confidence band 1 +/- sqrt(2/T); computed for factors, stocks and - most
  importantly - the actual strategy portfolios.
* Explanatory power: cross-sectional R^2 and share of strategy P&L variance
  explained by factors.
* Factor quality: t-stats, share of days |t|>2, autocorrelation; VIFs.
* Exposure stability: day-on-day cross-sectional correlation of exposures.
* Challengers: market+industry baseline and a pure PCA statistical model must
  be beaten on calibration and explanatory power.
* Event replay: did forecasts flag the risk before, and does attribution
  explain the loss after?
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .attribution import AttributionResult
from .config import MODEL, TRADING_DAYS, ModelConfig
from .estimation import CrossSectionalRegression, FactorModel
from .exposures import ExposureSet
from .risk_model import RiskModel, RiskModelBuilder


def bias_stat(z: pd.Series, window: int) -> pd.Series:
    """Non-overlapping-window bias statistic of standardised outcomes z = realised / forecast."""
    z = z.dropna()
    out = {}
    for start in range(0, len(z) - window + 1, window):
        seg = z.iloc[start:start + window]
        out[seg.index[-1]] = seg.std()
    return pd.Series(out, dtype=float)


def summarize_bias(b: pd.Series, window: int) -> dict:
    band = np.sqrt(2 / window)
    return {"mean_bias": b.mean(), "within_band_pct": ((b - 1).abs() <= band).mean() if len(b) else np.nan,
            "band": band, "n_windows": len(b)}


# --------------------------------------------------------------------------- #
def factor_bias(fm: FactorModel, rm: RiskModel, window: int = MODEL.bias_window) -> pd.DataFrame:
    vol = pd.DataFrame(np.sqrt(np.clip(np.einsum("tkk->tk", np.nan_to_num(rm.F)), 0, None)),
                       index=rm.dates, columns=rm.factors).replace(0, np.nan)
    rows = []
    for f in rm.factors:
        z = fm.factor_returns[f] / vol[f]
        z = z[fm.factor_returns[f] != 0]
        b = bias_stat(z, window)
        rows.append({"factor": f, "group": rm.groups[f], **summarize_bias(b, window)})
    return pd.DataFrame(rows)


def specific_bias(fm: FactorModel, rm: RiskModel, window: int = MODEL.bias_window, sample: int = 150, seed: int = 0) -> dict:
    z = fm.resid / np.sqrt(pd.DataFrame(rm.spec_var, index=rm.dates, columns=rm.tickers))
    rng = np.random.default_rng(seed)
    cols = rng.choice(z.columns, min(sample, z.shape[1]), replace=False)
    bs = pd.concat([bias_stat(z[c], window) for c in cols])
    return summarize_bias(bs, window)


def portfolio_bias(att: AttributionResult, rms: dict, window: int = MODEL.bias_window) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bias of strategy holding P&L vs predicted vol of start-of-day holdings."""
    rows, series = [], {}
    for s, b in att.books.items():
        rm = rms[b.market]
        pnl = (b.h * b.ret).sum(axis=1)
        pred = pd.Series(np.nan, index=b.dates)
        for t in range(len(b.dates)):
            h = b.h.values[t]
            if np.abs(h).sum() == 0 or not np.isfinite(rm.F[t]).all():
                continue
            pred.iloc[t] = rm.portfolio(t, h).total_vol
        z = (pnl / pred).replace([np.inf, -np.inf], np.nan)
        series[s] = pd.DataFrame({"hold_pnl": pnl, "pred_vol": pred, "z": z})
        bs = bias_stat(z, window)
        rows.append({"strategy": s, **summarize_bias(bs, window),
                     "realised_vol_ann": pnl[pred.notna()].std() * np.sqrt(TRADING_DAYS),
                     "pred_vol_ann": pred.mean() * np.sqrt(TRADING_DAYS)})
    return pd.DataFrame(rows), pd.concat(series, names=["strategy", "date"])


def factor_quality(fm: FactorModel) -> pd.DataFrame:
    f = fm.factor_returns
    t = fm.tstats.reindex(columns=f.columns)
    rows = []
    for c in f.columns:
        x = f[c].dropna()
        x = x[x != 0]
        if len(x) < 20:
            continue
        rows.append({"factor": c, "group": fm.expo.groups[c], "ann_vol": x.std() * np.sqrt(TRADING_DAYS),
                     "ann_return": x.mean() * TRADING_DAYS, "t_mean": x.mean() / x.std() * np.sqrt(len(x)),
                     "pct_days_abs_t_gt_2": (t[c].abs() > 2).mean() if c in t else np.nan,
                     "autocorr_1": x.autocorr(1)})
    return pd.DataFrame(rows)


def vif(expo: ExposureSet, every: int = 10) -> pd.DataFrame:
    style = expo.factors_in("style")
    k = expo.idx(style)
    out = []
    for t in range(0, len(expo.dates), every):
        m = expo.estu.values[t]
        X = expo.X[t][m][:, k]
        if m.sum() < 50 or not np.isfinite(X).all():
            continue
        C = np.corrcoef(X.T)
        try:
            out.append(np.diag(np.linalg.inv(C)))
        except np.linalg.LinAlgError:
            continue
    v = pd.DataFrame(out, columns=style)
    return pd.DataFrame({"mean_vif": v.mean(), "max_vif": v.max()})


def exposure_stability(expo: ExposureSet) -> pd.Series:
    style = expo.factors_in("style")
    k = expo.idx(style)
    vals = {f: [] for f in style}
    for t in range(1, len(expo.dates)):
        m = expo.estu.values[t] & expo.estu.values[t - 1]
        if m.sum() < 30:
            continue
        a, b = expo.X[t][m][:, k], expo.X[t - 1][m][:, k]
        for j, f in enumerate(style):
            if a[:, j].std() > 0 and b[:, j].std() > 0:
                vals[f].append(np.corrcoef(a[:, j], b[:, j])[0, 1])
    return pd.Series({f: np.mean(v) for f, v in vals.items()}, name="day_on_day_corr")


def explained_share(att: AttributionResult) -> pd.DataFrame:
    d = att.daily
    rows = []
    for s, g in d.groupby(level="strategy"):
        hold = g.hold_pnl
        unexplained = g.specific + g.basis
        rows.append({"strategy": s, "factor_share_of_hold_var": 1 - unexplained.var() / hold.var() if hold.var() > 0 else np.nan,
                     "corr_factor_vs_hold": g.factor.corr(hold)})
    return pd.DataFrame(rows)


def truth_recovery(fm: FactorModel, truth: pd.DataFrame, mapping: dict | None = None) -> pd.DataFrame:
    mapping = mapping or {}
    rows = []
    for f in fm.factor_returns.columns:
        tf = mapping.get(f, f)
        if tf in truth:
            a = pd.concat([fm.factor_returns[f], truth[tf]], axis=1).dropna()
            a = a[a.iloc[:, 0] != 0]
            if len(a) > 20:
                rows.append({"factor": f, "corr_with_true": a.corr().iloc[0, 1], "n": len(a)})
    if "theme" in truth:
        for c in [c for c in fm.factor_returns.columns if c.startswith("stat_")]:
            a = pd.concat([fm.factor_returns[c], truth["theme"]], axis=1).dropna()
            rows.append({"factor": f"{c} vs hidden theme", "corr_with_true": abs(a.corr().iloc[0, 1]), "n": len(a)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Challenger models
# --------------------------------------------------------------------------- #
class PCAModel:
    """Pure statistical challenger: rolling PCA factors, exposures from trailing window."""

    def __init__(self, k: int = 10, window: int = 250, min_window: int = 120):
        self.k, self.window, self.min_window = k, window, min_window

    def fit(self, expo: ExposureSet, returns: pd.DataFrame) -> FactorModel:
        R = returns.reindex(index=expo.dates, columns=expo.tickers).values
        T, N = R.shape
        X = np.full((T, N, self.k + 1), np.nan)
        F = np.full((T, self.k + 1), np.nan)
        U = np.full((T, N), np.nan)
        r2 = np.full(T, np.nan)
        W = np.nan_to_num(expo.reg_weight.values)
        for t in range(self.min_window, T):
            win = R[max(0, t - self.window):t]
            cover = np.isfinite(win).mean(0)
            cols = expo.estu.values[t] & (cover > 0.8)
            if cols.sum() < 3 * self.k:
                continue
            with np.errstate(invalid="ignore"):
                A = np.nan_to_num(win - np.nanmean(win, 0))
            sd = A.std(0); sd[sd == 0] = np.inf
            u_, s_, vt = np.linalg.svd(A[:, cols] / sd[cols], full_matrices=False)
            pcs = u_[:, :self.k]
            load = np.nan_to_num((A / sd).T @ pcs * sd[:, None])
            Xt = np.column_stack([np.ones(N), load])
            X[t] = np.where((cover > 0.5)[:, None], Xt, np.nan)
            y = R[t]
            ok = cols & np.isfinite(y)
            sw = np.sqrt(W[t][ok])
            f, *_ = np.linalg.lstsq(Xt[ok] * sw[:, None], y[ok] * sw, rcond=None)
            F[t] = f
            v = np.isfinite(y) & (cover > 0.5)
            U[t, v] = y[v] - Xt[v] @ f
            yb = np.average(y[ok], weights=W[t][ok])
            r2[t] = 1 - np.sum(W[t][ok] * U[t, ok] ** 2) / np.sum(W[t][ok] * (y[ok] - yb) ** 2)
        names = ["market"] + [f"pc_{j + 1}" for j in range(self.k)]
        e2 = ExposureSet(model=f"{expo.model}-PCA", dates=expo.dates, tickers=expo.tickers, factors=names,
                         groups={"market": "market", **{n: "statistical" for n in names[1:]}}, X=X,
                         estu=expo.estu, reg_weight=expo.reg_weight, cap=expo.cap, beta_pred=expo.beta_pred,
                         industries=[])
        idx = expo.dates
        r2s = pd.Series(r2, index=idx)
        return FactorModel(name=e2.model, expo=e2, returns=returns, factor_returns=pd.DataFrame(F, idx, names),
                           resid=pd.DataFrame(U, idx, expo.tickers), resid_named=pd.DataFrame(U, idx, expo.tickers),
                           r2_named=r2s, r2_hybrid=r2s, tstats=pd.DataFrame(index=idx),
                           stat_var_share=pd.DataFrame(index=idx))


def baseline_model(fm: FactorModel) -> FactorModel:
    e = fm.expo
    keep = ["market"] + e.industries
    sub = ExposureSet(model=f"{e.model}-baseline", dates=e.dates, tickers=e.tickers, factors=keep,
                      groups={k: e.groups[k] for k in keep}, X=e.X[:, :, e.idx(keep)], estu=e.estu,
                      reg_weight=e.reg_weight, cap=e.cap, beta_pred=e.beta_pred, industries=e.industries)
    out = CrossSectionalRegression(sub).fit(fm.returns)
    return FactorModel(name=sub.model, expo=sub, returns=fm.returns, factor_returns=out.factor_returns,
                       resid=out.resid, resid_named=out.resid, r2_named=out.r2, r2_hybrid=out.r2,
                       tstats=out.tstats, stat_var_share=pd.DataFrame(index=e.dates))


def challenger_comparison(fm: FactorModel, rm: RiskModel, att: AttributionResult, market: str,
                          cfg: ModelConfig = MODEL) -> pd.DataFrame:
    models = {"in-house core (named + statistical)": (fm, rm)}
    b = baseline_model(fm)
    models["baseline: market + industry"] = (b, RiskModelBuilder(b, cfg).build())
    p = PCAModel().fit(fm.expo, fm.returns)
    models["challenger: PCA (10 factors)"] = (p, RiskModelBuilder(p, cfg).build())
    rows = []
    books = {s: bk for s, bk in att.books.items() if bk.market == market}
    for name, (m, r) in models.items():
        sub = AttributionResult(att.daily, att.factor_pnl, att.exposures, books)
        pb, _ = portfolio_bias(sub, {market: r})
        start = m.r2_named.first_valid_index()
        rows.append({"model": name, "n_factors": len(m.factor_returns.columns),
                     "mean_cs_r2": m.r2_hybrid.loc[pd.Timestamp("2024-07-01"):].mean(),
                     "strategy_bias_mean": pb.mean_bias.mean(),
                     "strategy_bias_mad_from_1": (pb.mean_bias - 1).abs().mean(),
                     "strategy_within_band_pct": pb.within_band_pct.mean(),
                     "first_valid": start})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Event replay
# --------------------------------------------------------------------------- #
def event_replay(att: AttributionResult, bias_series: pd.DataFrame, episodes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    d = att.daily
    for ep in episodes.itertuples():
        for s, b in att.books.items():
            mkt = b.market
            if ep.market != mkt:
                continue
            k = b.dates.searchsorted(ep.date)
            if k >= len(b.dates) or (b.dates[k], s) not in d.index:
                continue
            date = b.dates[k]
            bs = bias_series.loc[s]
            pred_now = bs.pred_vol.get(date, np.nan)
            pred_before = bs.pred_vol.iloc[max(0, k - 25):max(1, k - 5)].mean()
            row = d.loc[(date, s)]
            rows.append({"episode": ep.episode, "date": date.date(), "strategy": s,
                         "pred_vol_t-1": pred_now, "pred_vol_month_before": pred_before,
                         "forecast_rose_pct": (pred_now / pred_before - 1) * 100 if pred_before else np.nan,
                         "hold_pnl": row.hold_pnl, "z_score": row.hold_pnl / pred_now if pred_now else np.nan,
                         "factor": row.factor, "specific": row.specific, "trading_and_costs":
                             row.trading + row.delay_cost + row.impact_cost + row.commissions,
                         "factor_share_of_loss": row.factor / row.hold_pnl if row.hold_pnl < 0 else np.nan})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Factor selection tests (Section 2.1): does each factor earn its place?
# --------------------------------------------------------------------------- #
def _with_candidate(expo: ExposureSet, name: str) -> ExposureSet:
    from dataclasses import replace
    Xc = np.where(np.all(np.isfinite(expo.X), 2), np.nan_to_num(expo.candidates[name]), np.nan)[..., None]
    return replace(expo, X=np.concatenate([expo.X, Xc], 2), factors=list(expo.factors) + [name],
                   groups={**expo.groups, name: "style"})


def factor_selection(fm: FactorModel, att: AttributionResult, market: str, start: pd.Timestamp,
                     episodes: pd.DataFrame | None = None, cfg: ModelConfig = MODEL) -> pd.DataFrame:
    """Drop-one tests for core factors and add-one tests for candidates, on our own data:
    marginal cross-sectional R^2 (on raw returns), significance (share of days |t|>2), and the
    change in residual P&L correlation across this market's strategies.  Time-series factors
    are tested the same way by removing their B g term."""
    from .estimation import ts_component
    e = fm.expo
    t0 = int(e.dates.searchsorted(start))
    R = fm.returns.reindex(index=e.dates, columns=e.tickers)
    G, Bg = ts_component(e)
    W = e.reg_weight.reindex(index=e.dates, columns=e.tickers)
    books = {s: b for s, b in att.books.items() if b.market == market}
    ts = e.factors_in("timeseries")

    def metrics(U):
        m = e.estu & R.notna() & U.notna()
        m.iloc[:t0] = False
        yb = (R * W).where(m).sum(axis=1) / W.where(m).sum(axis=1)
        r2 = 1 - (W * U ** 2).where(m).sum(axis=1) / (W * R.sub(yb, axis=0) ** 2).where(m).sum(axis=1)
        pnl = pd.DataFrame({s: (b.h.values * np.nan_to_num(U.values)).sum(1) for s, b in books.items()},
                           index=e.dates).iloc[t0:]
        c = pnl.corr().values
        off = np.abs(c[~np.eye(len(c), dtype=bool)]).mean() if len(c) > 1 else np.nan
        return r2.iloc[t0:].mean(), off

    reg = CrossSectionalRegression(e, cfg)
    cs = e.cs_factors()
    base = reg.fit(R - Bg, cs, t_start=t0)
    r2_b, rc_b = metrics(base.resid)
    squeeze = []
    if episodes is not None and len(episodes):
        squeeze = list(episodes[(episodes.market == market)
                                & episodes.episode.str.contains("squeeze|deleveraging", case=False)].date)
    rows = []
    tests = [f for f in cs if e.groups[f] in ("style", "event", "market_specific")] + ts + list(e.candidates)
    for f in tests:
        if f in e.candidates:
            ex = _with_candidate(e, f)
            out = CrossSectionalRegression(ex, cfg).fit(R - Bg, cs + [f], t_start=t0)
            r2_v, rc_v = metrics(out.resid)
            fr, tt = out.factor_returns[f], out.tstats[f]
            dr2, drc, kind = r2_v - r2_b, rc_b - rc_v, "candidate (add-one)"
        elif f in ts:
            # share of the remaining (post-factor) variance that the shock term B_k g_k explains,
            # holding the cross-sectional fit fixed; cross-sectional R^2 understates time-series
            # factors because industry factors absorb their average sector pattern each day
            Bk = pd.DataFrame(np.nan_to_num(e.X[:, :, e.factors.index(f)]) * G[f].fillna(0).values[:, None],
                              index=e.dates, columns=e.tickers)
            U_full = base.resid
            U_k = U_full + Bk
            m = e.estu & U_full.notna()
            m.iloc[:t0] = False
            dr2 = 1 - (W * U_full ** 2).where(m).sum().sum() / (W * U_k ** 2).where(m).sum().sum()
            _, rc_v = metrics(U_k)
            drc = rc_v - rc_b
            fr, tt = G[f], pd.Series(np.nan, index=e.dates)
            kind = "time-series (variance explained)"
        else:
            out = reg.fit(R - Bg, [c for c in cs if c != f], t_start=t0)
            r2_v, rc_v = metrics(out.resid)
            fr, tt = base.factor_returns[f], base.tstats[f]
            dr2, drc, kind = r2_b - r2_v, rc_v - rc_b, "core (drop-one)"
            if e.groups[f] in ("event", "market_specific"):
                # sparse factors: explanatory power on the stock-days they apply to
                aff = pd.DataFrame(np.nan_to_num(e.X[:, :, e.factors.index(f)]) != 0, index=e.dates,
                                   columns=e.tickers) & e.estu & base.resid.notna() & out.resid.notna()
                aff.iloc[:t0] = False
                den = (W * out.resid ** 2).where(aff).sum().sum()
                dr2 = 1 - (W * base.resid ** 2).where(aff).sum().sum() / den if den > 0 else np.nan
                kind = "core (drop-one, affected stock-days)"
        x = fr.iloc[t0:].dropna()
        x = x[x != 0]
        ta = tt.iloc[t0:].dropna()                    # days on which the factor was estimable
        sig = (ta.abs() > 2).mean() if len(ta) else np.nan
        sq = np.nan
        if squeeze and len(x) > 30:
            sd = x.std()
            sq = np.nanmax([abs(fr.get(d, np.nan)) / sd for d in squeeze]) if sd > 0 else np.nan
        if "affected" in kind:
            # a dummy touching few stocks fits them almost exactly, so sparse factors must also
            # be significant - no override on R^2 alone
            passes = bool(dr2 >= cfg.selection_min_dr2_event and sig >= cfg.selection_min_sig)
        else:
            thr = cfg.selection_min_dr2
            passes = bool((dr2 >= thr and (np.isnan(sig) or sig >= cfg.selection_min_sig))
                          or dr2 >= 3 * thr or (np.isfinite(drc) and drc >= 0.01))
        if kind.startswith("candidate"):
            decision = "promote to core" if passes else "keep in monitoring layer"
        else:
            decision = "keep in core" if passes else "review: move to monitoring layer"
        rows.append({"market": market, "factor": f, "test": kind, "marginal_r2": dr2, "pct_days_abs_t_gt_2": sig,
                     "ann_vol": x.std() * np.sqrt(TRADING_DAYS) if len(x) else np.nan,
                     "resid_corr_reduction": drc, "max_abs_z_on_squeeze_days": sq, "decision": decision})
    return pd.DataFrame(rows)


def ts_beta_checks(fm: FactorModel, truth_loadings: pd.DataFrame | None = None) -> pd.DataFrame:
    """Stability (cross-sectional correlation of B_t with B_{t-21}), average shrinkage weight,
    and - on synthetic data - correlation of shrunk vs raw betas with the true sensitivities."""
    e = fm.expo
    rows = []
    T = len(e.dates)
    for j, k in enumerate(e.factors_in("timeseries")):
        B = e.X[:, :, e.factors.index(k)]
        stab = []
        for t in range(150, T, 21):
            m = e.estu.values[t] & np.isfinite(B[t]) & np.isfinite(B[t - 21])
            if m.sum() > 30 and B[t][m].std() > 0 and B[t - 21][m].std() > 0:
                stab.append(np.corrcoef(B[t][m], B[t - 21][m])[0, 1])
        row = {"factor": k, "monthly_stability": np.mean(stab) if stab else np.nan,
               "mean_shrink_weight": e.extras["ts_shrink_weight"][k].iloc[150:].mean()}
        if truth_loadings is not None and k in truth_loadings:
            m = e.estu.values[-1]
            tl = truth_loadings[k].reindex(e.tickers).values
            raw = e.extras["ts_raw_betas"][-2, :, j]
            ok = m & np.isfinite(raw)
            row["corr_shrunk_vs_true"] = np.corrcoef(B[-1][ok], tl[ok])[0, 1]
            row["corr_raw_vs_true"] = np.corrcoef(raw[ok], tl[ok])[0, 1]
        rows.append(row)
    return pd.DataFrame(rows)

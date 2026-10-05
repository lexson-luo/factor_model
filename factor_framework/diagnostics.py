"""Layer 6 - Diagnostics: discovery around the linear core (Section 3.2).

The rule: anything found here that matters is turned into an explicit factor
or interaction term in the linear model.  The ML outputs are *never* used as
official attribution.

* Surrogate model: gradient boosting mapping position weights to stock
  characteristics (what is the black box effectively selecting on?), with
  permutation importance, partial dependence and Friedman's H for interactions.
* Overlap: P&L / residual correlation, hierarchical clustering, position
  overlap, effective number of bets, cross-team exposure stacking.
* Regime detection: Gaussian mixture on market-state features.
* Missing-factor tests: residual correlation across teams, PCA on residuals
  vs the Marchenko-Pastur edge, shared residual shocks.
* Drift: exposure change alerts and model-release before/after comparison.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import partial_dependence, permutation_importance
from sklearn.mixture import GaussianMixture

from .attribution import AttributionResult
from .data_loader import EquityPanel
from .estimation import FactorModel

FEATURE_TO_FACTOR = {
    "reversal_5d": "st_reversal", "volatility_20d": "volatility", "log_turnover": "liquidity",
    "relative_tick": "liquidity", "log_mcap": "size", "short_interest": "crowding", "borrow_fee": "crowding",
    "utilisation": "crowding", "beta": "beta", "earnings_today": "earnings", "in_play": "in_play",
    "gap_5d": "overnight_gap", "intraday_mom_3d": "st_momentum", "sector": "industry",
    "etf_ownership": None, "retail_share": None, "theme_tag": None, "shortable": None,
}


# --------------------------------------------------------------------------- #
# Surrogate model
# --------------------------------------------------------------------------- #
def _surrogate_frame(book, panel: EquityPanel, fm: FactorModel, every: int = 5) -> pd.DataFrame:
    d = fm.expo.descriptors
    h = book.h
    gmv = h.abs().sum(axis=1)
    dates = [t for t in range(len(panel.dates)) if gmv.iloc[t] > 0][::every]
    theme = (panel.ref.theme_tag != "").astype(float).values
    sector = pd.Categorical(panel.ref.sector).codes.astype(float)
    src = {
        "reversal_5d": "st_reversal", "volatility_20d": "volatility", "log_turnover": "liq_turnover",
        "relative_tick": "liq_tick", "log_mcap": "size", "short_interest": "crowd_si_float",
        "borrow_fee": "crowd_borrow_fee", "utilisation": "crowd_utilisation", "beta": "beta",
        "earnings_today": "earnings", "in_play": "in_play", "gap_5d": "overnight_gap",
        "intraday_mom_3d": "st_momentum", "etf_ownership": "etf_ownership", "retail_share": "retail_attention",
    }
    feats = {k: d[v] for k, v in src.items() if v in d}
    rows = []
    for t in dates:
        m = fm.expo.estu.values[t]
        blk = {k: v.values[t][m] for k, v in feats.items()}
        blk["sector"] = sector[m]
        blk["theme_tag"] = theme[m]
        blk["shortable"] = panel.ref.shortable.values[m].astype(float)
        blk["weight"] = h.values[t][m] / gmv.iloc[t]
        blk["t"] = np.full(m.sum(), t)
        rows.append(pd.DataFrame(blk))
    return pd.concat(rows, ignore_index=True)


def friedman_h(model, X: pd.DataFrame, a: str, b: str, grid: int = 8) -> float:
    pa = partial_dependence(model, X, [a], grid_resolution=grid, kind="average")
    pb = partial_dependence(model, X, [b], grid_resolution=grid, kind="average")
    pab = partial_dependence(model, X, [a, b], grid_resolution=grid, kind="average")
    fa = pa["average"][0]; fb = pb["average"][0]; fab = pab["average"][0]
    fa = fa - fa.mean(); fb = fb - fb.mean(); fab = fab - fab.mean()
    if fab.shape != (len(fa), len(fb)):
        return np.nan
    inter = fab - fa[:, None] - fb[None, :]
    den = np.sum(fab ** 2)
    return float(np.sqrt(np.sum(inter ** 2) / den)) if den > 0 else np.nan


def surrogate_model(strategy: str, book, panel: EquityPanel, fm: FactorModel, seed: int = 0) -> dict:
    df = _surrogate_frame(book, panel, fm).replace([np.inf, -np.inf], np.nan)
    feats = [c for c in df.columns if c not in ("weight", "t")]
    split = df.t.quantile(0.7)
    tr, te = df[df.t <= split], df[df.t > split]
    y_scale = df.weight.abs().mean()
    model = HistGradientBoostingRegressor(max_depth=4, max_iter=250, learning_rate=0.05,
                                          l2_regularization=1.0, random_state=seed,
                                          categorical_features=[feats.index("sector")])
    model.fit(tr[feats], tr.weight / y_scale)
    r2_oos = model.score(te[feats], te.weight / y_scale)
    sample = te.sample(min(len(te), 6000), random_state=seed)
    pi = permutation_importance(model, sample[feats], sample.weight / y_scale, n_repeats=5, random_state=seed)
    imp = pd.DataFrame({"feature": feats, "importance": pi.importances_mean, "std": pi.importances_std})
    imp["maps_to_core_factor"] = imp.feature.map(FEATURE_TO_FACTOR)
    imp = imp.sort_values("importance", ascending=False).reset_index(drop=True)
    top = [f for f in imp.feature.head(4) if f != "sector"][:3]
    pdp = {}
    for f in top:
        r = partial_dependence(model, sample[feats], [f], grid_resolution=15, kind="average")
        pdp[f] = pd.Series(r["average"][0] * y_scale, index=r["grid_values"][0])
    inter = []
    cand = [f for f in imp.feature.head(5) if f != "sector"]
    if "log_turnover" not in cand:
        cand.append("log_turnover")
    for i in range(len(cand)):
        for j in range(i + 1, len(cand)):
            inter.append({"a": cand[i], "b": cand[j],
                          "friedman_h": friedman_h(model, sample[feats].head(1500), cand[i], cand[j])})
    inter = pd.DataFrame(inter).sort_values("friedman_h", ascending=False)
    thresh = 0.1 * imp.importance.max()
    unnamed = imp[(imp.maps_to_core_factor.isna()) & (imp.importance > thresh)].feature.tolist()
    shap_vals = None
    try:   # optional dependency
        import shap  # noqa: F401
        expl = shap.TreeExplainer(model)
        sv = expl.shap_values(sample[feats].head(1000))
        shap_vals = pd.Series(np.abs(sv).mean(0), index=feats).sort_values(ascending=False)
    except Exception:
        pass
    return {"strategy": strategy, "r2_oos": r2_oos, "importance": imp, "partial_dependence": pdp,
            "interactions": inter, "candidate_factors": unnamed, "shap": shap_vals}


# --------------------------------------------------------------------------- #
# Overlap, clustering, effective number of bets
# --------------------------------------------------------------------------- #
def effective_number_of_bets(corr: pd.DataFrame) -> dict:
    lam = np.clip(np.linalg.eigvalsh(corr.values), 0, None)
    p = lam / lam.sum()
    return {"participation_ratio": lam.sum() ** 2 / np.sum(lam ** 2),
            "entropy": float(np.exp(-np.sum(p[p > 0] * np.log(p[p > 0])))), "n": len(lam)}


def strategy_overlap(att: AttributionResult) -> dict:
    d = att.by_reporting_day()
    total = d["total_attributed"].unstack()
    resid = d["specific"].unstack()
    stat = att.factor_pnl[att.factor_pnl.group == "statistical"].copy()
    stat["report_date"] = stat.date + pd.offsets.BDay(0)
    stat = stat.groupby(["report_date", "strategy"]).pnl.sum().unstack().reindex(resid.index).fillna(0)
    resid_named = resid + d["slow_factor"].unstack() + stat.reindex(columns=resid.columns).fillna(0)
    c_tot, c_res, c_named = total.corr(), resid.corr(), resid_named.corr()
    dist = np.sqrt(np.clip(0.5 * (1 - c_tot.values), 0, None))
    np.fill_diagonal(dist, 0)
    Z = linkage(squareform(dist, checks=False), "average")
    order = [c_tot.index[i] for i in leaves_list(Z)]
    # position overlap (signed cosine similarity, same market only)
    names = list(att.books)
    pos = pd.DataFrame(np.nan, index=names, columns=names)
    for a in names:
        for b in names:
            A, B = att.books[a], att.books[b]
            if A.market != B.market:
                continue
            ha, hb = A.h.values, B.h.values
            na, nb = np.linalg.norm(ha, axis=1), np.linalg.norm(hb, axis=1)
            ok = (na > 0) & (nb > 0)
            pos.loc[a, b] = np.mean((ha[ok] * hb[ok]).sum(axis=1) / (na[ok] * nb[ok])) if ok.any() else np.nan
    # exposure stacking on common factor names
    ex = att.exposures
    last = ex.date.max()
    recent = ex[ex.date > last - pd.Timedelta(days=30)]
    st = recent.groupby(["strategy", "factor"]).exposure_usd.mean().unstack(0)
    firm = st.sum(axis=1)
    stack = pd.DataFrame({"firm_exposure_usd": firm, "sum_abs_strategy": st.abs().sum(axis=1)})
    stack["stacking_ratio"] = stack.firm_exposure_usd.abs() / stack.sum_abs_strategy.replace(0, np.nan)
    return {"corr_total": c_tot, "corr_residual": c_res, "corr_residual_named_only": c_named,
            "cluster_order": order, "linkage": Z, "position_overlap": pos,
            "enb_total": effective_number_of_bets(c_tot), "enb_residual": effective_number_of_bets(c_res),
            "stacking": stack.sort_values("sum_abs_strategy", ascending=False)}


# --------------------------------------------------------------------------- #
# Regimes
# --------------------------------------------------------------------------- #
def detect_regimes(fm: FactorModel, n_states: int = 2, seed: int = 0) -> pd.DataFrame:
    f = fm.factor_returns
    r = fm.returns
    style = [c for c in f.columns if fm.expo.groups.get(c) == "style"]
    feat = pd.DataFrame({
        "mkt_vol": np.log(f["market"].rolling(20).std()),
        "style_vol": np.log(np.sqrt((f[style] ** 2).mean(axis=1)).rolling(20).mean()),
        "dispersion": np.log(r.std(axis=1).rolling(10).mean()),
        "avg_corr": (r.mean(axis=1).rolling(20).var() / r.var(0).mean()).clip(1e-6),
    }).dropna()
    feat["avg_corr"] = np.log(feat["avg_corr"])
    Zs = (feat - feat.mean()) / feat.std()
    gm = GaussianMixture(n_states, covariance_type="full", random_state=seed, n_init=5).fit(Zs)
    lab = gm.predict(Zs)
    prob = gm.predict_proba(Zs)
    order = np.argsort([feat.mkt_vol[lab == k].mean() for k in range(n_states)])
    remap = {old: new for new, old in enumerate(order)}
    out = feat.copy()
    out["regime"] = [remap[x] for x in lab]
    out["p_stress"] = prob[:, order[-1]]
    return out


# --------------------------------------------------------------------------- #
# Missing-factor tests
# --------------------------------------------------------------------------- #
def residual_correlation_test(corr: pd.DataFrame, n_obs: int, rho_flag: float = 0.15, p_flag: float = 0.01) -> pd.DataFrame:
    rows = []
    names = list(corr.index)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            rho = corr.iloc[i, j]
            z = np.arctanh(np.clip(rho, -0.999, 0.999)) * np.sqrt(max(n_obs - 3, 1))
            p = 2 * (1 - stats.norm.cdf(abs(z)))
            rows.append({"a": names[i], "b": names[j], "rho": rho, "p_value": p,
                         "flag": abs(rho) > rho_flag and p < p_flag})
    return pd.DataFrame(rows).sort_values("rho", key=np.abs, ascending=False)


def residual_pca(fm: FactorModel, panel: EquityPanel, use_named: bool = True, window: int = 250, n: int = 5) -> dict:
    U = (fm.resid_named if use_named else fm.resid).iloc[-window:]
    cols = U.columns[(U.notna().mean() > 0.95) & fm.expo.estu.iloc[-1].reindex(U.columns).values]
    A = U[cols].fillna(0)
    A = (A - A.mean()) / A.std().replace(0, np.nan)
    A = A.dropna(axis=1)
    T, N = A.shape
    C = np.corrcoef(A.values.T)
    lam, vec = np.linalg.eigh(C)
    lam, vec = lam[::-1], vec[:, ::-1]
    mp_edge = (1 + np.sqrt(N / T)) ** 2
    ref = panel.ref.loc[A.columns]
    cands = {"theme:" + t: (ref.theme_tag == t).astype(float) for t in ref.theme_tag.unique() if t}
    cands.update({"sector:" + s: (ref.sector == s).astype(float) for s in ref.sector.unique()})
    cands["shortable"] = ref.shortable.astype(float)
    t_last = len(fm.expo.dates) - 1
    for k, sname in enumerate(fm.expo.slow_factors):
        cands["slow:" + sname] = pd.Series(fm.expo.X_slow[t_last, fm.expo.tickers.get_indexer(A.columns), k],
                                           index=A.columns)
    assoc = []
    for k in range(n):
        v = pd.Series(vec[:, k], index=A.columns)
        for name, c in cands.items():
            c = pd.Series(np.asarray(c, float), index=A.columns)
            if c.std() > 0:
                assoc.append({"pc": k + 1, "candidate": name, "corr": v.corr(c)})
    assoc = pd.DataFrame(assoc)
    assoc["abs"] = assoc["corr"].abs()
    top = assoc.sort_values("abs", ascending=False).groupby("pc").head(3).sort_values(["pc", "abs"], ascending=[True, False])
    return {"eigenvalues": pd.Series(lam[:10], index=range(1, 11)), "mp_edge": mp_edge,
            "n_above_edge": int((lam > mp_edge).sum()), "associations": top.drop(columns="abs"),
            "T": T, "N": N}


def shared_residual_shocks(att: AttributionResult, z: float = -2.0, min_strategies: int = 3,
                           window: int = 63) -> pd.DataFrame:
    res = att.by_reporting_day()["specific"].unstack()
    sd = res.rolling(window, min_periods=20).std().shift(1)
    zz = res / sd
    hit = (zz < z)
    out = pd.DataFrame({"n_strategies": hit.sum(axis=1), "residual_pnl": res.where(hit).sum(axis=1),
                        "strategies": hit.apply(lambda r: ",".join(r.index[r]), axis=1)})
    return out[out.n_strategies >= min_strategies]


# --------------------------------------------------------------------------- #
# Drift and model releases
# --------------------------------------------------------------------------- #
def exposure_drift(exposures: pd.DataFrame, factors: list, window: int = 60, short: int = 5,
                   z_alert: float = 3.0) -> pd.DataFrame:
    rows = []
    ex = exposures[exposures.factor.isin(factors)]
    for (s, f), g in ex.groupby(["strategy", "factor"]):
        e = g.set_index("date").exposure_pct_gmv.sort_index()
        base_mu = e.rolling(window, min_periods=30).mean().shift(short)
        base_sd = e.rolling(window, min_periods=30).std().shift(short)
        z = (e.rolling(short).mean() - base_mu) / base_sd.replace(0, np.nan)
        flag = z.abs() > z_alert
        start = flag & ~flag.shift(1, fill_value=False)
        for d in e.index[start.values]:
            rows.append({"date": d, "strategy": s, "factor": f, "z": z.loc[d],
                         "exposure": e.loc[d], "baseline": base_mu.loc[d]})
    return pd.DataFrame(rows).sort_values("date") if rows else pd.DataFrame(
        columns=["date", "strategy", "factor", "z", "exposure", "baseline"])


def release_comparison(exposures: pd.DataFrame, releases: pd.DataFrame, factors: list, window: int = 20) -> pd.DataFrame:
    rows = []
    for r in releases.itertuples():
        ex = exposures[(exposures.strategy == r.strategy) & exposures.factor.isin(factors)]
        for f, g in ex.groupby("factor"):
            e = g.set_index("date").exposure_pct_gmv.sort_index()
            before = e[e.index < r.release_date].tail(window)
            after = e[e.index >= r.release_date].head(window)
            if len(before) < 5 or len(after) < 5:
                continue
            t = stats.ttest_ind(after, before, equal_var=False).statistic
            rows.append({"strategy": r.strategy, "version": r.version, "release_date": r.release_date,
                         "factor": f, "before": before.mean(), "after": after.mean(),
                         "change": after.mean() - before.mean(), "t_stat": t, "material": abs(t) > 3})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Crowding level 2: factor-level crowding (monitoring indicator)
# --------------------------------------------------------------------------- #
def factor_crowding(fm: FactorModel, panel: EquityPanel, cfg=None) -> dict:
    """Comomentum (Lou and Polk): average pairwise correlation of named-model residual
    returns within the top and bottom decile of each core factor over the past ~60 days,
    plus short interest concentrated in the factor's short leg (Hanson and Sunderam).
    A factor is flagged crowded when its comomentum is > z_alert standard deviations above
    its own history; the flag scales up stress tests for that factor."""
    from .config import MODEL
    cfg = cfg or MODEL
    e = fm.expo
    factors = [f for f in e.factors if e.groups[f] in ("style", "statistical")]
    U = fm.resid_named.values
    SI = panel.short_interest_pct.reindex(index=e.dates, columns=e.tickers).values
    W, q = cfg.comomentum_window, cfg.comomentum_decile
    rows = []

    def avg_corr(A):
        A = A - A.mean(0)
        sd = A.std(0)
        A = A[:, sd > 0] / sd[sd > 0]
        n = A.shape[1]
        if n < 5:
            return np.nan
        C = (A.T @ A) / len(A)
        return (C.sum() - np.trace(C)) / (n * (n - 1))

    for t in range(W + 60, len(e.dates), cfg.comomentum_every):
        win = U[t - W:t]
        cover = np.isfinite(win).mean(0) >= 0.9
        base = e.estu.values[t] & cover
        si_all = np.nanmean(SI[t][base]) if base.any() else np.nan
        for f in factors:
            x = e.X[t, :, e.factors.index(f)]
            v = base & np.isfinite(x)
            if v.sum() < 50:
                continue
            hi, lo = np.quantile(x[v], [1 - q, q])
            long_leg, short_leg = v & (x >= hi), v & (x <= lo)
            cl = avg_corr(np.nan_to_num(win[:, long_leg]))
            cs = avg_corr(np.nan_to_num(win[:, short_leg]))
            rows.append({"date": e.dates[t], "factor": f, "como_long": cl, "como_short": cs,
                         "comomentum": np.nanmean([cl, cs]),
                         "si_short_leg_ratio": np.nanmean(SI[t][short_leg]) / si_all if si_all and si_all > 0 else np.nan})
    hist = pd.DataFrame(rows)
    out = []
    for f, g in hist.groupby("factor"):
        g = g.sort_values("date").set_index("date")
        mu = g.comomentum.expanding(26).mean().shift(1)          # ~6 months of 5-day samples
        sd = g.comomentum.expanding(26).std().shift(1).clip(lower=0.005)
        g["z"] = (g.comomentum - mu) / sd
        hist.loc[hist.factor == f, "z"] = g["z"].values
        last = g.iloc[-1]
        out.append({"factor": f, "comomentum": last.comomentum, "z": last.z,
                    "si_short_leg_ratio": last.si_short_leg_ratio, "crowded": bool(last.z > cfg.crowding_z_alert),
                    "stress_multiplier": 1 + 0.25 * float(np.clip(np.nan_to_num(last.z), 0, 4))})
    latest = pd.DataFrame(out).sort_values("z", ascending=False)
    alerts = hist[hist.z > cfg.crowding_z_alert].sort_values("date")
    return {"history": hist, "latest": latest, "alerts": alerts}


# --------------------------------------------------------------------------- #
# Market-wide shock sensitivities (Nagel 2012): are reversal books short vol / liquidity?
# --------------------------------------------------------------------------- #
def shock_sensitivities(att: AttributionResult, models: dict, risk: dict, window: int = 126) -> pd.DataFrame:
    """Two views of each strategy's exposure to the time-series shocks:
    * model-implied: expected P&L given a 3-sigma shock, E[PnL | g_k = 3 s_k] = 3 (F x)_k / s_k,
      which picks up co-movement of other factors (e.g. reversal) with the shock;
    * empirical: regression of the strategy's daily P&L on each shock (unconditional).
    Model-implied numbers feed limits; the empirical ones are the cross-check."""
    rows = []
    for s, b in att.books.items():
        fm, rm = models[b.market], risk[b.market]
        ts = fm.expo.factors_in("timeseries")
        if not ts:
            continue
        d = att.daily.xs(s, level="strategy")
        pnl = d.total_attributed
        g = fm.factor_returns.reindex(pnl.index)[ts].fillna(0)
        last = pnl.index[-1]
        t = b.dates.get_loc(last)
        pr = rm.portfolio(t, b.h.values[t])
        F = pd.DataFrame(rm.F[t], index=rm.factors, columns=rm.factors)
        Fx = F @ pr.exposures
        gmv = np.abs(b.h.values[t]).sum()
        tail = slice(max(0, len(g) - window), len(g))
        for k in ts:
            # unconditional sensitivity (no market control), comparable with the model-implied number
            A = np.column_stack([np.ones(len(g)), g[k].values])
            coef, *_ = np.linalg.lstsq(A, pnl.values, rcond=None)
            res = pnl.values - A @ coef
            se = np.sqrt(res.var() * np.linalg.pinv(A.T @ A)[1, 1])
            coef_r, *_ = np.linalg.lstsq(A[tail], pnl.values[tail], rcond=None)
            sd = fm.factor_returns[k].iloc[-252:].std()
            model = 3 * Fx[k] / np.sqrt(F.loc[k, k])
            rows.append({"strategy": s, "shock": k, "model_pnl_3sd": model, "model_pct_gmv": model / gmv,
                         "empirical_pnl_3sd": coef[1] * 3 * sd, "empirical_t": coef[1] / se,
                         "empirical_recent_pnl_3sd": coef_r[1] * 3 * sd, "gmv": gmv})
    return pd.DataFrame(rows)


def monitor_exposures(att: AttributionResult, models: dict) -> pd.DataFrame:
    """Holdings-weighted exposures to candidate factors (ETF ownership, retail attention) and
    background monitors (13F ownership), per $ of gross - not part of official attribution."""
    rows = []
    for s, b in att.books.items():
        e = models[b.market].expo
        cols = {**e.candidates, **e.monitor}
        if not cols:
            continue
        h = b.h.values
        gmv = np.abs(h).sum(1)
        for name, Z in cols.items():
            v = np.nansum(np.nan_to_num(Z) * h, 1) / np.where(gmv > 0, gmv, np.nan)
            rows.append(pd.DataFrame({"date": b.dates, "strategy": s, "factor": name,
                                      "exposure_pct_gmv": v}).dropna())
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def rolling_shock_betas(att: AttributionResult, models: dict, window: int = 126) -> dict:
    """Rolling unconditional regression of each strategy's daily P&L on each shock series,
    known at the open (lagged one day): strategy -> DataFrame of 3-sigma P&L by shock."""
    out = {}
    for s, b in att.books.items():
        fm = models[b.market]
        ts = fm.expo.factors_in("timeseries")
        if not ts:
            continue
        pnl = att.daily.xs(s, level="strategy").total_attributed
        g = fm.factor_returns.reindex(pnl.index)[ts]
        sd = g.rolling(252, min_periods=60).std()
        beta = pd.DataFrame({k: pnl.rolling(window, min_periods=60).cov(g[k]) / g[k].rolling(window, min_periods=60).var()
                             for k in ts})
        out[s] = (3 * beta * sd).shift(1)
    return out

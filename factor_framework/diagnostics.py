"""Layer 6 - Diagnostics: discovery around the linear core (Section 3.2).

The rule: anything found here that matters is turned into an explicit factor
or interaction term in the linear model.  The ML outputs are *never* used as
official attribution.

* Surrogate model: XGBoost mapping position weights to stock characteristics
  (what is the black box effectively selecting on?).  Explained with exact
  TreeSHAP values and SHAP interaction values; permutation importance is kept as
  a cross-check.  Fit is reported in and out of sample against a linear
  baseline, and for alternative targets (weight rank, held-or-not, held-only).
* SHAP attribution (cross-check, never official): a per-date cross-sectional
  return surrogate (cross-fitted additive XGBoost) plus the weight surrogate give
  an exact two-sided split of holdings P&L, decision driver x return driver.
  Its return side is compared bucket by bucket with the linear attribution.
* Overlap: P&L / residual correlation, hierarchical clustering, position
  overlap, effective number of bets, cross-team exposure stacking.
* Regime detection: Gaussian mixture on market-state features.
* Missing-factor tests: residual correlation across teams, PCA on residuals
  vs the Marchenko-Pastur edge, shared residual shocks.
* Drift: exposure change alerts and model-release before/after comparison.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy import stats
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge, RidgeCV
from sklearn.metrics import r2_score, roc_auc_score
from sklearn.mixture import GaussianMixture
import xgboost as xgb

from .attribution import AttributionResult
from .config import PROMOTED_CANDIDATES
from .data_loader import EquityPanel
from .estimation import FactorModel

FEATURE_TO_FACTOR = {
    "reversal_5d": "st_reversal", "volatility_20d": "volatility", "log_turnover": "liquidity",
    "relative_tick": "liquidity", "log_mcap": "size", "short_interest": "crowding", "borrow_fee": "crowding",
    "utilisation": "crowding", "beta": "beta", "earnings_today": "earnings", "in_play": "in_play",
    "gap_5d": "overnight_gap", "intraday_mom_3d": "st_momentum", "sector": "industry",
    "theme_tag": None, "shortable": None,
}
# Candidate characteristics map to their factor once promoted (config.PROMOTED_CANDIDATES), else stay unmapped
CANDIDATE_FEATURES = {"etf_ownership": "etf_ownership", "retail_share": "retail_attention"}
FEATURE_TO_FACTOR.update({f: c if c in PROMOTED_CANDIDATES else None for f, c in CANDIDATE_FEATURES.items()})
SURROGATE_MIN_R2_OOS = 0.05   # below this the surrogate does not generalise and its explanations are not acted on


# --------------------------------------------------------------------------- #
# Surrogate model
# --------------------------------------------------------------------------- #
FEATURE_SOURCE = {   # surrogate feature -> exposure-builder descriptor (start-of-day, no look-ahead)
    "reversal_5d": "st_reversal", "volatility_20d": "volatility", "log_turnover": "liq_turnover",
    "relative_tick": "liq_tick", "log_mcap": "size", "short_interest": "crowd_si_float",
    "borrow_fee": "crowd_borrow_fee", "utilisation": "crowd_utilisation", "beta": "beta",
    "earnings_today": "earnings", "in_play": "in_play", "gap_5d": "overnight_gap",
    "intraday_mom_3d": "st_momentum", "etf_ownership": "etf_ownership", "retail_share": "retail_attention",
}
NON_FEATURES = ("weight", "t", "i", "ret")


def _feature_frame(panel: EquityPanel, fm: FactorModel, dates) -> pd.DataFrame:
    """One row per (date index t, estimation-universe stock column i) with the surrogate features."""
    d = fm.expo.descriptors
    feats = {k: d[v].values for k, v in FEATURE_SOURCE.items() if v in d}
    theme = (panel.ref.theme_tag != "").astype(float).values
    sector = pd.Categorical(panel.ref.sector).codes.astype(float)
    shortable = panel.ref.shortable.values.astype(float)
    estu = fm.expo.estu.values
    rows = []
    for t in dates:
        m = estu[t]
        blk = {k: v[t][m] for k, v in feats.items()}
        blk["sector"] = sector[m]
        blk["theme_tag"] = theme[m]
        blk["shortable"] = shortable[m]
        blk["t"] = np.full(m.sum(), t)
        blk["i"] = np.flatnonzero(m)
        rows.append(pd.DataFrame(blk))
    return pd.concat(rows, ignore_index=True)


def _surrogate_frame(book, panel: EquityPanel, fm: FactorModel, every: int = 5) -> pd.DataFrame:
    gmv = book.h.abs().sum(axis=1).values
    dates = [t for t in range(len(panel.dates)) if gmv[t] > 0][::every]
    df = _feature_frame(panel, fm, dates)
    df["weight"] = book.h.values[df.t, df.i] / gmv[df.t]
    return df.drop(columns="i")


def _sector_cat(sector: pd.Series, categories: list) -> pd.Categorical:
    """Fixed category set so XGBoost sees the same sector coding at fit and predict time."""
    return pd.Categorical(sector.astype("Int64"), categories=categories)


def _xgb(classifier: bool = False, seed: int = 0):
    kw = dict(max_depth=4, n_estimators=250, learning_rate=0.05, reg_lambda=1.0, tree_method="hist",
              enable_categorical=True, random_state=seed, n_jobs=-1)
    return xgb.XGBClassifier(**kw) if classifier else xgb.XGBRegressor(**kw)


def _linear_design(df: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    return pd.get_dummies(df[feats], columns=["sector"], dtype=float).fillna(0.0)


def _fit_table(tr: pd.DataFrame, te: pd.DataFrame, feats: list[str], y_scale: float, seed: int):
    """In- and out-of-sample fit of the tree surrogate and a linear baseline for several targets.

    weight      signed weight / GMV (the target the explanations use)
    rank        cross-sectional percentile rank of weight per date
    held_only   signed weight, held names only (the 'how much' half of a two-part model)
    held        held vs not held, AUC (the 'whether' half)

    Returns the table and the fitted 'weight' surrogate.
    """
    rank = lambda d: d.groupby("t").weight.rank(pct=True) - 0.5
    rows, weight_model = [], None
    targets = {"weight": (tr, te, lambda d: d.weight / y_scale), "rank": (tr, te, rank),
               "held_only": (tr[tr.weight != 0], te[te.weight != 0], lambda d: d.weight / y_scale)}
    for name, (a, b, y) in targets.items():
        m = _xgb(seed=seed).fit(a[feats], y(a))
        weight_model = m if name == "weight" else weight_model
        rows.append({"target": name, "model": "xgboost", "metric": "R²",
                     "in_sample": r2_score(y(a), m.predict(a[feats])), "out_of_sample": r2_score(y(b), m.predict(b[feats]))})
        xa = _linear_design(a, feats)
        xb = _linear_design(b, feats).reindex(columns=xa.columns, fill_value=0.0)
        lr = RidgeCV(alphas=[0.1, 1.0, 10.0, 100.0]).fit(xa, y(a))
        rows.append({"target": name, "model": "linear", "metric": "R²",
                     "in_sample": lr.score(xa, y(a)), "out_of_sample": lr.score(xb, y(b))})
    ya, yb = tr.weight != 0, te.weight != 0
    if ya.nunique() == 2 and yb.nunique() == 2:
        c = _xgb(classifier=True, seed=seed).fit(tr[feats], ya)
        rows.append({"target": "held", "model": "xgboost", "metric": "AUC",
                     "in_sample": roc_auc_score(ya, c.predict_proba(tr[feats])[:, 1]),
                     "out_of_sample": roc_auc_score(yb, c.predict_proba(te[feats])[:, 1])})
    return pd.DataFrame(rows), weight_model


def surrogate_model(strategy: str, book, panel: EquityPanel, fm: FactorModel, seed: int = 0) -> dict:
    return fit_surrogate(_surrogate_frame(book, panel, fm), strategy, seed=seed)


def fit_surrogate(df: pd.DataFrame, strategy: str = "", seed: int = 0, n_shap: int = 6000,
                  n_interact: int = 1000) -> dict:
    """Fit and explain the weight surrogate. `df` has one row per (date, stock): feature columns
    (including an integer-coded `sector`), `weight` (position / GMV) and `t` (date index)."""
    df = df.replace([np.inf, -np.inf], np.nan)
    sector_categories = sorted(df.sector.dropna().astype(int).unique())
    df["sector"] = _sector_cat(df.sector, sector_categories)
    feats = [c for c in df.columns if c not in NON_FEATURES]
    split = df.t.quantile(0.7)
    tr, te = df[df.t <= split], df[df.t > split]
    y_scale = df.weight.abs().mean()
    fit, model = _fit_table(tr, te, feats, y_scale, seed)
    r2_oos = r2_score(te.weight / y_scale, model.predict(te[feats]))
    r2_is = r2_score(tr.weight / y_scale, model.predict(tr[feats]))

    # Exact TreeSHAP on out-of-sample rows: phi_0 + sum_k phi_k = prediction, in units of weight / GMV
    sample = te.sample(min(len(te), n_shap), random_state=seed)
    booster = model.get_booster()
    contrib = booster.predict(xgb.DMatrix(sample[feats], enable_categorical=True), pred_contribs=True) * y_scale
    phi = pd.DataFrame(contrib[:, :-1], columns=feats, index=sample.index)
    base_value = float(contrib[0, -1])
    mabs = phi.abs().mean()

    pi = permutation_importance(model, sample[feats], sample.weight / y_scale, n_repeats=5, random_state=seed)
    imp = pd.DataFrame({"feature": feats, "mean_abs_shap": mabs.values, "shap_share": (mabs / mabs.sum()).values,
                        "perm_importance": pi.importances_mean, "perm_std": pi.importances_std})
    imp["maps_to_core_factor"] = imp.feature.map(FEATURE_TO_FACTOR)
    imp = imp.sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)

    # SHAP is additive, so correlated features that feed one core factor can be summed before taking |.|
    group = {f: FEATURE_TO_FACTOR.get(f) or f"unmapped:{f}" for f in feats}
    gphi = phi.T.groupby(group).sum().T
    gabs = gphi.abs().mean()
    by_factor = pd.DataFrame({"group": gabs.index, "mean_abs_shap": gabs.values, "shap_share": (gabs / gabs.sum()).values}
                             ).sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)

    # SHAP interaction values: off-diagonal (a, b) + (b, a) is the pair's total interaction effect
    sub = sample.head(n_interact)
    iv = booster.predict(xgb.DMatrix(sub[feats], enable_categorical=True), pred_interactions=True)[:, :-1, :-1] * y_scale
    miv = np.abs(iv).mean(0)
    main = np.abs(iv[:, range(len(feats)), range(len(feats))]).mean(0)
    inter = []
    for i in range(len(feats)):
        for j in range(i + 1, len(feats)):
            inter.append({"a": feats[i], "b": feats[j], "mean_abs_interaction": miv[i, j] + miv[j, i],
                          "rel_to_main": (miv[i, j] + miv[j, i]) / max(min(main[i], main[j]), 1e-12)})
    inter = pd.DataFrame(inter).sort_values("mean_abs_interaction", ascending=False).reset_index(drop=True)

    thresh = 0.1 * imp.mean_abs_shap.max()
    unnamed = imp[(imp.maps_to_core_factor.isna()) & (imp.mean_abs_shap > thresh)].feature.tolist()
    shap_values = pd.concat([sample[["t", "weight"] + feats].rename(columns=lambda c: f"x_{c}" if c in feats else c),
                             phi.rename(columns=lambda c: f"shap_{c}")], axis=1)
    return {"strategy": strategy, "r2_oos": r2_oos, "r2_is": r2_is, "reliable": r2_oos >= SURROGATE_MIN_R2_OOS,
            "fit": fit, "importance": imp,
            "by_factor": by_factor, "interactions": inter, "candidate_factors": unnamed,
            "shap_values": shap_values, "base_value": base_value, "model": model, "y_scale": y_scale,
            "feats": feats, "sector_categories": sector_categories}


# --------------------------------------------------------------------------- #
# SHAP attribution: return surrogate and two-sided P&L decomposition
# --------------------------------------------------------------------------- #
# Per-date cross-sectional return model.  One date's half-universe (~150 names) supports only an additive
# model: depth-1 stumps (non-linear per characteristic, no interactions), >= 10 names per leaf and few rounds.
# Deeper or longer-boosted trees lowered cross-fitted R² on both markets.
RETURN_MODEL_PARAMS = dict(objective="reg:squarederror", max_depth=1, eta=0.1, min_child_weight=10,
                           reg_lambda=10.0, subsample=0.8, nthread=1)
RETURN_MODEL_ROUNDS = 50


def _shap_group(feature: str) -> str:
    return FEATURE_TO_FACTOR.get(feature) or f"unmapped:{feature}"


@dataclass
class ReturnSurrogate:
    """Cross-sectional return model fitted date by date, cross-fitted over two random halves of the universe
    (each stock's SHAP values come from the model trained on the other half, so a stock's own idiosyncratic
    return is not absorbed into the characteristic buckets).

    frame: one row per (t, i): features, `ret`, `base` (phi_0 of the scoring model), `shap_<feature>` and
           `resid`, with base + sum(shap) + resid = ret exactly.
    fit:   per date, cross-fitted R² next to the linear factor model's in-sample R².
    """
    market: str
    feats: list
    frame: pd.DataFrame
    fit: pd.DataFrame


def _fit_return_date(t: int, X: pd.DataFrame, y: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Cross-fitted SHAP contributions (n x features+1, last column phi_0) and cross-fitted ridge predictions
    on the same features as a linear benchmark."""
    n = len(y)
    contrib, lin = np.zeros((n, X.shape[1] + 1)), np.zeros(n)
    if n < 4 * RETURN_MODEL_PARAMS["min_child_weight"]:
        return contrib, lin                              # too few names: everything stays in the residual
    scale = y.std() or 1.0
    Xl = pd.get_dummies(X, columns=["sector"], dtype=float).fillna(0.0).values
    half = np.zeros(n, bool)
    half[np.random.default_rng(seed + t).permutation(n)[: n // 2]] = True
    for score in (half, ~half):
        train = xgb.DMatrix(X[~score], label=y[~score] / scale, enable_categorical=True)
        bst = xgb.train({**RETURN_MODEL_PARAMS, "seed": seed}, train, RETURN_MODEL_ROUNDS)
        contrib[score] = bst.predict(xgb.DMatrix(X[score], enable_categorical=True), pred_contribs=True) * scale
        lin[score] = Ridge(alpha=10.0).fit(Xl[~score], y[~score]).predict(Xl[score])
    return contrib, lin


def fit_return_surrogate(frame: pd.DataFrame, market: str = "", r2_linear: pd.Series | None = None,
                         seed: int = 0, n_jobs: int = -1) -> ReturnSurrogate:
    """`frame`: one row per (t, i) with feature columns (integer-coded `sector`), `t`, `i` and `ret`, the
    return that start-of-day holdings earn on date t.  `r2_linear` is indexed by t."""
    frame = frame.replace([np.inf, -np.inf], np.nan).reset_index(drop=True)
    feats = [c for c in frame.columns if c not in NON_FEATURES]
    X = frame[feats].assign(sector=_sector_cat(frame.sector, sorted(frame.sector.dropna().astype(int).unique())))
    y = frame.ret.values
    by_date = list(frame.groupby("t").indices.items())
    parts = Parallel(n_jobs=n_jobs)(delayed(_fit_return_date)(int(t), X.iloc[ix], y[ix], seed) for t, ix in by_date)
    contrib, lin = np.zeros((len(frame), len(feats) + 1)), np.zeros(len(frame))
    for (_, ix), (c, lp) in zip(by_date, parts):
        contrib[ix], lin[ix] = c, lp
    out = pd.concat([frame, pd.DataFrame(contrib[:, :-1], columns=[f"shap_{f}" for f in feats])], axis=1)
    out["base"] = contrib[:, -1]
    out["resid"] = y - contrib.sum(axis=1)
    sst = ((out.ret - out.groupby("t").ret.transform("mean")) ** 2).groupby(out.t).sum()
    fit = pd.DataFrame({"n": out.groupby("t").size(),
                        "r2_crossfit": 1 - (out.resid ** 2).groupby(out.t).sum() / sst,
                        "r2_crossfit_ridge": 1 - pd.Series((y - lin) ** 2).groupby(out.t).sum() / sst})
    if r2_linear is not None:
        fit["r2_linear_model"] = r2_linear.reindex(fit.index).values
    return ReturnSurrogate(market, feats, out, fit)


def return_surrogate(market: str, panel: EquityPanel, fm: FactorModel, dates, seed: int = 0) -> ReturnSurrogate:
    frame = _feature_frame(panel, fm, dates)
    frame["ret"] = panel.ret.fillna(0.0).values[frame.t, frame.i]     # same return the P&L attribution uses
    r2 = pd.Series(fm.r2_named.reindex(panel.dates).values)
    return fit_return_surrogate(frame, market, r2, seed)


def _by_group(values: np.ndarray, feats: list, base: np.ndarray, residual: np.ndarray) -> pd.DataFrame:
    """Columns: base, one per core-factor / unmapped group (SHAP summed within group), residual."""
    g = pd.DataFrame(values, columns=feats).T.groupby(lambda f: _shap_group(f), sort=False).sum().T
    return pd.concat([pd.DataFrame({"base": base}), g, pd.DataFrame({"residual": residual})], axis=1)


def two_sided_pnl(t: np.ndarray, gmv: np.ndarray, a: pd.DataFrame, b: pd.DataFrame):
    """Exact two-sided decomposition of holdings P&L  sum_i h_i r_i  with h_i = GMV * w_i.

    a: weight decomposition per row (columns sum to w = h / GMV); b: return decomposition (columns sum to
    ret); gmv: the row's date GMV.  M[k, j] = sum of GMV * a_k * b_j over rows: P&L of the position slice
    driven by characteristic k, earned through return driver j.  Column sums are the return-side
    (cross-sectional) attribution with the actual weights; row sums are the weight-side (holdings /
    decision) attribution.  Returns M and the daily return-side and weight-side series (index t).
    """
    usd = a.values * gmv[:, None]
    M = pd.DataFrame(usd.T @ b.values, index=a.columns, columns=b.columns)
    ret_side = pd.DataFrame(usd.sum(axis=1)[:, None] * b.values, columns=b.columns).groupby(t).sum()
    w_side = pd.DataFrame(usd * b.values.sum(axis=1)[:, None], columns=a.columns).groupby(t).sum()
    return M, ret_side, w_side


def _linear_bucket(factor: str, group: str, shap_groups: set) -> str:
    if factor == "market":
        return "base"
    if group == "industry":
        return "industry"
    if factor in shap_groups:
        return factor
    return "slow (linear only)" if group == "slow" else "other (linear only)"


def shap_attribution(strategy: str, book, sur: dict, rs: ReturnSurrogate, att: AttributionResult) -> dict:
    """SHAP-based P&L attribution for one strategy, reported next to the official linear attribution.

    Weight side: the strategy's weight surrogate (fit_surrogate).  Return side: the market's per-date return
    surrogate.  Both are diagnostics; the linear attribution stays the official one.
    """
    h, r = book.h.values, book.ret.values
    gmv = np.abs(h).sum(axis=1)
    daily = att.daily.xs(strategy, level="strategy")
    on = (gmv > 0) & book.dates.isin(daily.index)               # dates with holdings and official P&L
    F = rs.frame[on[rs.frame.t.values]].reset_index(drop=True)
    t, i = F.t.values, F.i.values
    w = h[t, i] / gmv[t]

    X = F[sur["feats"]].assign(sector=_sector_cat(F.sector, sur["sector_categories"]))
    phi = sur["model"].get_booster().predict(xgb.DMatrix(X, enable_categorical=True), pred_contribs=True) \
        * sur["y_scale"]
    a = _by_group(phi[:, :-1], sur["feats"], phi[:, -1], w - phi.sum(axis=1))
    b = _by_group(F[[f"shap_{f}" for f in rs.feats]].values, rs.feats, F.base.values, F.resid.values)
    M, ret_side, w_side = two_sided_pnl(t, gmv[t], a, b)

    live = np.unique(t)
    outside = (h * r).sum(axis=1)[live] - ret_side.sum(axis=1).reindex(live).values
    ret_side["outside_estu"] = outside
    ret_side.index = book.dates[ret_side.index]
    w_side.index = book.dates[w_side.index]

    fp = att.factor_pnl[att.factor_pnl.strategy == strategy]
    groups = set(b.columns) - {"base", "residual"}
    fp = fp.assign(bucket=[_linear_bucket(f, g, groups) for f, g in zip(fp.factor, fp.group)])
    lin = fp.pivot_table(index="date", columns="bucket", values="pnl", aggfunc="sum")
    lin["residual"] = daily.specific
    lin, shp = lin.reindex(ret_side.index).fillna(0.0), ret_side

    order = (["base", "industry"] + [g for g in b.columns if g in FEATURE_TO_FACTOR.values() and g != "industry"]
             + [g for g in b.columns if g.startswith("unmapped:")]
             + [c for c in ("other (linear only)", "slow (linear only)") if c in lin] + ["residual", "outside_estu"])
    lin, shp = lin.reindex(columns=order, fill_value=0.0), shp.reindex(columns=order, fill_value=0.0)
    corr = pd.Series({c: lin[c].corr(shp[c]) if lin[c].std() > 0 and shp[c].std() > 0 else np.nan
                      for c in order})
    comparison = pd.DataFrame({"bucket": order, "linear_usd": lin.sum().values, "shap_usd": shp.sum().values,
                               "daily_corr": corr.values})
    comparison["diff_usd"] = comparison.shap_usd - comparison.linear_usd
    total = {"bucket": "total", "linear_usd": lin.values.sum(), "shap_usd": shp.values.sum(),
             "daily_corr": lin.sum(axis=1).corr(shp.sum(axis=1))}
    total["diff_usd"] = total["shap_usd"] - total["linear_usd"]
    comparison = pd.concat([comparison, pd.DataFrame([total])], ignore_index=True)

    decision = w_side.sum()
    decision["outside_estu"] = outside.sum()
    return {"strategy": strategy, "comparison": comparison, "matrix": M,
            "decision": decision, "daily_linear": lin, "daily_shap": shp,
            "weight_reliable": sur["reliable"], "weight_r2_oos": sur["r2_oos"],
            "return_r2_crossfit": float(rs.fit.r2_crossfit.reindex(live).mean()),
            "return_r2_crossfit_ridge": float(rs.fit.r2_crossfit_ridge.reindex(live).mean()),
            "return_r2_linear_model": float(rs.fit.r2_linear_model.reindex(live).mean())
            if "r2_linear_model" in rs.fit else np.nan}


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

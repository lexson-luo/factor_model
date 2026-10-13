"""Layer 3 - Factor returns.

* ``CrossSectionalRegression``: daily WLS of returns on exposures with the
  industry factor returns constrained to sum to zero (cap weighted), so the
  market (intercept) factor stays identified.
* ``StatisticalResidualFactors``: a few principal components of the named
  model's trailing residuals, estimated without look-ahead, appended as extra
  factors (hybrid model, Section 3.2).
* Time-series shock factors (r = X f + B g + u): g is observed, so only B is
  estimated (exposures layer); B g is removed before the cross-sectional
  regression and g enters the factor-return panel directly.
* ``SlowFactorLayer``: second-stage regression of core residuals on slow-factor
  exposures orthogonalised to the core exposures (monitoring layer, Section 2.3):

      Stage 1: r = X_core f_core + u
      Stage 2: u = X_slow_perp g + e
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import MODEL, ModelConfig
from .exposures import ExposureSet


def _robust_clip(y: np.ndarray, k: float = 6.0) -> np.ndarray:
    med = np.median(y)
    mad = 1.4826 * np.median(np.abs(y - med))
    return np.clip(y, med - k * mad, med + k * mad) if mad > 0 else y


def _constraint_basis(K, ind_idx, ind_cap, active):
    """f = R g: free parameters g for the active factors, last active industry implied by the constraint."""
    act = np.where(active)[0]
    ind_act = [k for k in ind_idx if active[k]]
    if len(ind_act) >= 2:
        last = ind_act[-1]
        free = [k for k in act if k != last]
        R = np.zeros((K, len(free)))
        for j, k in enumerate(free):
            R[k, j] = 1.0
        for k in ind_act[:-1]:
            R[last, free.index(k)] = -ind_cap[k] / ind_cap[last]
    else:
        free = list(act)
        R = np.eye(K)[:, free]
    return R, free


def wls_projection(X, w, ind_idx, ind_cap, active):
    """P (K x n) with f = P y for constrained_wls (ignoring the robust clip of y)."""
    R, _ = _constraint_basis(X.shape[1], ind_idx, ind_cap, active)
    sw = np.sqrt(w)
    return R @ np.linalg.pinv((X @ R) * sw[:, None]) * sw[None, :]


def constrained_wls(y, X, w, ind_idx, ind_cap, active):
    """WLS with sum_j cap_j f_j = 0 over active industries.

    Returns (f [K], se [K], r2, s2). Inactive factors get f = 0, se = NaN.
    """
    K = X.shape[1]
    R, free = _constraint_basis(K, ind_idx, ind_cap, active)
    sw = np.sqrt(w)
    A = (X @ R) * sw[:, None]
    g, *_ = np.linalg.lstsq(A, y * sw, rcond=None)
    f = R @ g
    e = y - X @ f
    dof = max(len(y) - len(free), 1)
    s2 = float(np.sum(w * e ** 2) / dof)
    cov_g = s2 * np.linalg.pinv(A.T @ A)
    se = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", R, cov_g, R), 0))
    se[~active] = np.nan
    ybar = np.average(y, weights=w)
    r2 = 1 - np.sum(w * e ** 2) / np.sum(w * (y - ybar) ** 2)
    return f, se, r2, s2


@dataclass
class RegressionOutput:
    factor_returns: pd.DataFrame
    resid: pd.DataFrame
    r2: pd.Series
    tstats: pd.DataFrame
    n_obs: pd.Series
    projection: np.ndarray | None = None      # T x K x N: f_t = P_t r_t (zero outside the regression)


class CrossSectionalRegression:
    def __init__(self, expo: ExposureSet, cfg: ModelConfig = MODEL):
        self.e, self.cfg = expo, cfg

    def fit(self, returns: pd.DataFrame, factors: list | None = None, min_obs: int = 15,
            t_start: int = 0, keep_projection: bool = False) -> RegressionOutput:
        e = self.e
        factors = factors or e.cs_factors()
        kidx = e.idx(factors)
        ind_idx = [j for j, f in enumerate(factors) if e.groups[f] == "industry"]
        R = returns.reindex(index=e.dates, columns=e.tickers).values
        E, W, C = e.estu.values, np.nan_to_num(e.reg_weight.values), np.nan_to_num(e.cap.values)
        T, N, K = len(e.dates), len(e.tickers), len(factors)
        F = np.full((T, K), np.nan); Tst = np.full((T, K), np.nan)
        U = np.full((T, N), np.nan); r2 = np.full(T, np.nan); nobs = np.zeros(T, int)
        P = np.zeros((T, K, N), np.float32) if keep_projection else None
        for t in range(t_start, T):
            Xt = e.X[t][:, kidx]
            rt = R[t]
            ok = E[t] & np.isfinite(rt) & np.all(np.isfinite(Xt), 1) & (W[t] > 0)
            if ok.sum() < max(min_obs, K // 2):
                continue
            X = Xt[ok]; y = _robust_clip(rt[ok]); w = W[t][ok]
            active = np.zeros(K, bool)
            for j, f in enumerate(factors):
                col = X[:, j]
                g = e.groups[f]
                if g == "market":
                    active[j] = True
                elif f in e.flags:                       # centred event dummy: count the raw flags
                    active[j] = np.count_nonzero(np.nan_to_num(e.flags[f][t][ok])) >= 3
                elif g in ("industry", "event", "market_specific") and np.unique(col).size <= 3:
                    active[j] = np.count_nonzero(col) >= 3
                else:
                    active[j] = col.std() > 1e-8
            ind_cap = np.zeros(K)
            for j in ind_idx:
                ind_cap[j] = C[t][ok][X[:, j] > 0].sum()
            f, se, r2[t], _ = constrained_wls(y, X, w, ind_idx, ind_cap, active)
            if keep_projection:
                P[t][:, ok] = wls_projection(X, w, ind_idx, ind_cap, active) * active[:, None]
            f_out = f.copy()
            f_out[~active] = np.nan          # not estimable today (e.g. no events) -> missing, not zero
            F[t] = f_out
            Tst[t] = f / se
            valid = np.isfinite(rt) & np.all(np.isfinite(Xt), 1)
            U[t, valid] = rt[valid] - Xt[valid] @ f
            nobs[t] = ok.sum()
        idx = e.dates
        return RegressionOutput(
            factor_returns=pd.DataFrame(F, index=idx, columns=factors),
            resid=pd.DataFrame(U, index=idx, columns=e.tickers),
            r2=pd.Series(r2, index=idx), tstats=pd.DataFrame(Tst, index=idx, columns=factors),
            n_obs=pd.Series(nobs, index=idx), projection=P)


class StatisticalResidualFactors:
    """Rolling PCA on named-model residuals; exposures at t use residuals to t-1."""

    def __init__(self, k: int = MODEL.n_stat_factors, window: int = MODEL.stat_factor_window,
                 max_window: int = 250):
        self.k, self.window, self.max_window = k, window, max_window

    def fit(self, expo: ExposureSet, resid_named: pd.DataFrame):
        T, N, k = len(expo.dates), len(expo.tickers), self.k
        U = resid_named.values
        E, W = expo.estu.values, np.nan_to_num(expo.reg_weight.values)
        Xs = np.full((T, N, k), np.nan)
        Fs = np.full((T, k), np.nan)
        self.projection = np.zeros((T, k, N), np.float32)        # f_stat,t = P_t u_t (named residuals)
        U2 = U.copy()
        var_share = np.full((T, k), np.nan)
        prev = None
        for t in range(self.window, T):
            win = U[max(0, t - self.max_window):t]
            win = win[np.isfinite(win).any(axis=1)]            # drop warm-up days with no residuals
            if len(win) < self.window:
                continue
            cover = np.isfinite(win).mean(0)
            cols = E[t] & (cover >= 0.8)
            if cols.sum() < 3 * k + 10:
                continue
            # correlation-based PCA: scale each stock's residuals to unit variance so
            # high-volatility names do not dominate the components
            full = np.nan_to_num(win)
            full = full - full.mean(0)
            sd = full.std(0)
            sd[sd == 0] = np.inf
            A = full[:, cols] / sd[cols]
            u_, s_, vt = np.linalg.svd(A, full_matrices=False)
            pcs = u_[:, :k]                               # unit-norm PC time series
            var_share[t] = s_[:k] ** 2 / np.sum(s_ ** 2)
            # loadings for every stock with history: correlation-scaled projection on PCs
            has = cover >= 0.5
            load = np.full((N, k), np.nan)
            load[has] = (full[:, has] / sd[has]).T @ pcs
            z = load.copy()
            for j in range(k):
                m = cols & np.isfinite(z[:, j])
                mu, sd = z[m, j].mean(), z[m, j].std()
                z[:, j] = np.clip((z[:, j] - mu) / (sd + 1e-12), -4, 4)
                if prev is not None:      # keep sign stable through time
                    both = np.isfinite(prev[:, j]) & np.isfinite(z[:, j])
                    if both.sum() > 10 and np.corrcoef(prev[both, j], z[both, j])[0, 1] < 0:
                        z[:, j] *= -1
            prev = z
            z = np.nan_to_num(z)
            alive = np.all(np.isfinite(expo.X[t]), 1)
            z[~alive] = np.nan
            Xs[t] = z
            ok = E[t] & np.isfinite(U[t]) & alive
            if ok.sum() < 3 * k:
                continue
            sw = np.sqrt(W[t][ok])
            f, *_ = np.linalg.lstsq(z[ok] * sw[:, None], U[t][ok] * sw, rcond=None)
            Fs[t] = f
            self.projection[t][:, ok] = np.linalg.pinv(z[ok] * sw[:, None]) * sw[None, :]
            v = np.isfinite(U[t]) & alive
            U2[t, v] = U[t, v] - z[v] @ f
        names = [f"stat_{j + 1}" for j in range(k)]
        return Xs, pd.DataFrame(Fs, index=expo.dates, columns=names), \
            pd.DataFrame(U2, index=expo.dates, columns=expo.tickers), \
            pd.DataFrame(var_share, index=expo.dates, columns=names)


class SlowFactorLayer:
    """Second-stage regression for slow factors (credit only for what core cannot explain)."""

    def fit(self, expo: ExposureSet, resid: pd.DataFrame):
        T, N = len(expo.dates), len(expo.tickers)
        Ks = len(expo.slow_factors)
        U = resid.values
        E, W = expo.estu.values, np.nan_to_num(expo.reg_weight.values)
        G = np.full((T, Ks), np.nan)
        Xp = np.full((T, N, Ks), np.nan)
        Eres = U.copy()
        for t in range(T):
            Xc, Xs = expo.X[t], expo.X_slow[t]
            rows = np.all(np.isfinite(Xc), 1) & np.all(np.isfinite(Xs), 1)
            ok = rows & E[t] & np.isfinite(U[t])
            if ok.sum() < Xc.shape[1] + Ks + 10:
                continue
            # a descriptor with no cross-sectional dispersion (e.g. 12-1 momentum before a year of
            # history) is not estimable that day: return NaN, not 0, as for inactive core factors
            act = Xs[ok].std(axis=0) > 1e-8
            if not act.any():
                continue
            sw = np.sqrt(W[t][ok])
            B, *_ = np.linalg.lstsq(Xc[ok] * sw[:, None], Xs[ok][:, act] * sw[:, None], rcond=None)
            perp = np.full((N, Ks), np.nan)
            perp[rows] = 0.0
            perp[np.ix_(rows, act)] = Xs[rows][:, act] - Xc[rows] @ B
            Xp[t] = perp
            g, *_ = np.linalg.lstsq(perp[ok][:, act] * sw[:, None], U[t][ok] * sw, rcond=None)
            G[t, act] = g
            v = rows & np.isfinite(U[t])
            Eres[t, v] = U[t, v] - perp[v][:, act] @ g
        return pd.DataFrame(G, index=expo.dates, columns=expo.slow_factors), Xp, \
            pd.DataFrame(Eres, index=expo.dates, columns=expo.tickers)


@dataclass
class FactorModel:
    """Everything estimated for one local model."""
    name: str
    expo: ExposureSet
    returns: pd.DataFrame
    factor_returns: pd.DataFrame          # core (named + statistical)
    resid: pd.DataFrame                   # specific returns after core factors
    resid_named: pd.DataFrame             # residuals of named factors only
    r2_named: pd.Series
    r2_hybrid: pd.Series
    tstats: pd.DataFrame
    stat_var_share: pd.DataFrame
    f_overnight: pd.DataFrame | None = None
    f_intraday: pd.DataFrame | None = None
    slow_returns: pd.DataFrame | None = None
    X_slow_perp: np.ndarray | None = None
    resid_after_slow: pd.DataFrame | None = None
    extras: dict = field(default_factory=dict)


def ts_component(expo: ExposureSet) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Observed shocks g (T x K_ts) and the return explained by them, B g (T x N)."""
    ts = expo.factors_in("timeseries")
    if not ts:
        return pd.DataFrame(index=expo.dates), pd.DataFrame(0.0, index=expo.dates, columns=expo.tickers)
    G = expo.shocks.reindex(expo.dates)[ts]
    Bg = np.einsum("tnk,tk->tn", np.nan_to_num(expo.X[:, :, expo.idx(ts)]), G.fillna(0.0).values)
    return G, pd.DataFrame(Bg, index=expo.dates, columns=expo.tickers)


def noise_loadings(expo: ExposureSet, cs_cols: list, Xcs: np.ndarray, P_cs: np.ndarray,
                   P_stat: np.ndarray | None) -> np.ndarray:
    """Q (T x K x N): estimated factor returns are signal + Q_t e_t, with e the specific returns.

    Cross-sectional factors: the WLS projection.  Statistical factors: their projection applied
    to the named residual, (I - X P) e.  Time-series factors: 0 (their shocks are observed).
    Q_t diag(spec var) Q_t' is the sampling noise in each day's factor returns, which a covariance
    estimated from those returns counts as factor risk although it is specific risk."""
    T, N, K = len(expo.dates), len(expo.tickers), len(expo.factors)
    Q = np.zeros((T, K, N), np.float32)
    Q[:, expo.idx(cs_cols)] = P_cs
    if P_stat is not None:
        stat = expo.idx(expo.factors_in("statistical"))
        for t in range(T):
            if P_stat[t].any():
                Q[t, stat] = P_stat[t] @ (np.eye(N) - Xcs[t] @ P_cs[t])
    return Q


def estimate_local_model(name: str, expo: ExposureSet, returns: pd.DataFrame,
                         ret_on: pd.DataFrame | None = None, ret_id: pd.DataFrame | None = None,
                         cfg: ModelConfig = MODEL, n_stat: int | None = None) -> FactorModel:
    reg = CrossSectionalRegression(expo, cfg)
    G, Bg = ts_component(expo)
    named = reg.fit(returns - Bg.reindex_like(returns), keep_projection=True)
    f_on = reg.fit(ret_on).factor_returns if ret_on is not None else None
    f_id = reg.fit(ret_id).factor_returns if ret_id is not None else None
    k = cfg.n_stat_factors if n_stat is None else n_stat
    cs_cols = list(named.factor_returns.columns)
    Xcs = np.nan_to_num(expo.X[:, :, expo.idx(cs_cols)])
    stat_proj = None
    if k > 0:
        srf = StatisticalResidualFactors(k, cfg.stat_factor_window)
        Xs, Fs, U2, vs = srf.fit(expo, named.resid)
        stat_proj = srf.projection
        # a stock with named exposures but no statistical loading yet has zero stat exposure
        has_named = np.all(np.isfinite(expo.X), 2)
        Xs = np.where(has_named[..., None] & ~np.isfinite(Xs), 0.0, Xs)
        expo.add_factors(list(Fs.columns), Xs, "statistical")
        fr = pd.concat([named.factor_returns, G, Fs], axis=1)
    else:
        fr, U2, vs = pd.concat([named.factor_returns, G], axis=1), named.resid, pd.DataFrame(index=expo.dates)
    fr = fr[expo.factors]                 # same column order as the exposure matrix
    # hybrid R2 on the estimation universe
    W = expo.reg_weight.reindex(index=expo.dates, columns=expo.tickers)
    y = returns.reindex(index=expo.dates, columns=expo.tickers)
    m = expo.estu & y.notna() & U2.notna()
    yw = (y * W).where(m).sum(axis=1) / W.where(m).sum(axis=1)
    ss_tot = (W * (y.sub(yw, axis=0)) ** 2).where(m).sum(axis=1)
    r2_h = 1 - (W * U2 ** 2).where(m).sum(axis=1) / ss_tot
    r2_h[named.r2.isna()] = np.nan
    fm = FactorModel(name=name, expo=expo, returns=returns, factor_returns=fr, resid=U2,
                     resid_named=named.resid, r2_named=named.r2, r2_hybrid=r2_h,
                     tstats=named.tstats, stat_var_share=vs, f_overnight=f_on, f_intraday=f_id)
    fm.extras["ts_explained"] = Bg
    fm.extras["noise_loadings"] = noise_loadings(expo, cs_cols, Xcs, named.projection, stat_proj)
    if expo.X_slow is not None:
        g, Xp, e = SlowFactorLayer().fit(expo, U2)
        fm.slow_returns, fm.X_slow_perp, fm.resid_after_slow = g, Xp, e
    return fm

"""Layer 4 - Risk model.

Factor covariance (forecast for day t made at the close of t-1):

1. EWMA volatilities (short half-life) and EWMA correlations (longer half-life), optionally
   de-noised: the EWMA of each day's regression sampling covariance Q D Q' is subtracted,
   because noise in estimated factor returns is specific risk, not factor risk.
2. Ledoit-Wolf shrinkage of the correlation matrix toward the identity.
3. Eigenfactor risk adjustment (Menchero, Orr & Wang 2011): Monte-Carlo
   estimate of the bias of sample eigenportfolio variances, scaled by 'a'.
4. Volatility regime adjustment: rescale by the EWMA of the cross-sectional
   bias statistic of standardised factor returns.
5. Macro-announcement uplift: on scheduled macro days (known in advance) the
   variance of macro-sensitive factors (market, rates, FX, vol shock) is scaled by
   the historical ratio of standardised squared returns on macro days to other
   days: the market's ratio for all of them, or (macro_per_factor) each factor's
   own ratio shrunk toward 1.

Slow factors (monitoring layer) are part of the covariance as "slow:<name>",
with their core-orthogonalised exposures and second-stage returns, so a slow
tilt is common risk rather than diversifiable specific risk.  Estimation is
unchanged: core factor returns keep priority, slow factors get the leftover.
They are appended by block augmentation (as the global layer links local
models): the core block is estimated on core factors alone and stays exactly
as it would be without the slow layer; only the slow block (plain EWMA vols)
and the slow-core cross block are added.

Specific risk: EWMA time-series estimate (on the residual after the slow
layer) blended with a structural model (log specific vol regressed on size,
volatility, liquidity and industry) for stocks with short histories, a
specific-risk regime adjustment and a multiplier on known event days
(earnings, token unlocks).  Optionally each squared residual is divided by its
expected ratio to the true specific variance (leverage: a stock's own return
pulls the regression fit toward it).

Settings are calibrated against the simulator's true covariance in calibration.py
(run_calibration.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.covariance import ledoit_wolf_shrinkage

from .config import MACRO_SENSITIVE, MODEL, ModelConfig
from .estimation import FactorModel


def _decay(halflife: float) -> float:
    return 0.5 ** (1.0 / halflife)


def eigen_adjustment(F0: np.ndarray, t_eff: int, sims: int, a: float, rng) -> np.ndarray:
    """Return gamma (ascending eigen order) such that adjusted eigenvalues are gamma^2 * d."""
    d0, U0 = np.linalg.eigh(F0)
    d0 = np.clip(d0, 1e-14, None)
    K = len(d0)
    acc = np.zeros(K)
    for _ in range(sims):
        r = (rng.standard_normal((t_eff, K)) * np.sqrt(d0)) @ U0.T
        Fm = r.T @ r / t_eff
        dm, Um = np.linalg.eigh(Fm)
        dm = np.clip(dm, 1e-14, None)
        acc += np.einsum("ik,ij,jk->k", Um, F0, Um) / dm
    lam = np.sqrt(acc / sims)
    return a * (lam - 1.0) + 1.0


@dataclass
class PortfolioRisk:
    total_vol: float
    factor_vol: float
    specific_vol: float
    exposures: pd.Series            # X^T h (USD per unit factor return)
    factor_contrib: pd.Series       # Euler contributions to total vol (USD)
    group_contrib: pd.Series
    specific_contrib: float
    mctr: np.ndarray                # marginal contribution to risk per stock
    stock_contrib: np.ndarray       # h_i * mctr_i (sums to total vol)


@dataclass
class RiskModel:
    name: str
    dates: pd.DatetimeIndex
    factors: list
    groups: dict
    tickers: pd.Index
    X: np.ndarray
    F: np.ndarray                   # T x K x K daily covariance
    spec_var: np.ndarray            # T x N daily specific variance
    vra: pd.Series
    vra_specific: pd.Series
    shrinkage: pd.Series
    eigen_gamma: pd.DataFrame
    raw_factor_vol: pd.DataFrame = field(default_factory=pd.DataFrame)
    macro_mult: pd.Series = field(default_factory=pd.Series)
    factor_returns: pd.DataFrame = field(default_factory=pd.DataFrame)   # the series F is estimated on
    noise_var: np.ndarray | None = None   # T x K sampling variance of each day's estimated factor return
                                          # (removed from F when denoised; add it back to test F against f)
    macro_uplift: pd.DataFrame = field(default_factory=pd.DataFrame)   # per macro-sensitive factor

    def factor_vol(self, t: int) -> pd.Series:
        return pd.Series(np.sqrt(np.clip(np.diag(self.F[t]), 0, None)), index=self.factors)

    def portfolio(self, t: int, h: np.ndarray, unmodelled_vol: float = 0.03) -> PortfolioRisk:
        X = self.X[t]
        valid = np.all(np.isfinite(X), 1)
        hm = np.where(valid, h, 0.0)
        Xv = np.nan_to_num(X)
        x = Xv.T @ hm
        F = self.F[t]
        Fx = F @ x
        fac_var = float(x @ Fx)
        sv = np.where(valid, np.nan_to_num(self.spec_var[t], nan=unmodelled_vol ** 2), unmodelled_vol ** 2)
        spec_var = float(np.sum(h ** 2 * sv))
        tot = np.sqrt(max(fac_var + spec_var, 1e-18))
        contrib = pd.Series(x * Fx / tot, index=self.factors)
        grp = contrib.groupby(pd.Series(self.groups)).sum()
        grp["specific"] = spec_var / tot
        mctr = (Xv @ Fx + sv * h) / tot
        return PortfolioRisk(total_vol=tot, factor_vol=np.sqrt(max(fac_var, 0)), specific_vol=np.sqrt(spec_var),
                             exposures=pd.Series(x, index=self.factors), factor_contrib=contrib,
                             group_contrib=grp, specific_contrib=spec_var / tot, mctr=mctr,
                             stock_contrib=h * mctr)


class RiskModelBuilder:
    def __init__(self, fm: FactorModel, cfg: ModelConfig = MODEL, seed: int = 7,
                 event_factors: tuple | list = (), macro_day: pd.Series | None = None):
        self.fm, self.cfg = fm, cfg
        self.rng = np.random.default_rng(seed)
        self.event_factors = [f for f in event_factors if f in fm.expo.factors or f in fm.expo.flags]
        self.factor_returns, self.X, self.groups = self._with_slow_factors(fm)
        idx = fm.factor_returns.index
        self.macro_day = (macro_day.reindex(idx).fillna(False).astype(bool).values
                          if macro_day is not None else np.zeros(len(idx), bool))
        self.Q = fm.extras.get("noise_loadings")

    def noise_cov(self, t: int, spec_var: np.ndarray) -> np.ndarray:
        """Q_t diag(d_t) Q_t': sampling covariance of day t's estimated core factor returns."""
        Qt = self.Q[t].astype(float)
        return (Qt * np.nan_to_num(spec_var)) @ Qt.T

    def leverage_ratio(self, t: int, d: np.ndarray) -> np.ndarray:
        """kappa_i = var(residual_i) / var(e_i) with residual = (I - X Q) e: below 1 for stocks in the
        regression (their own return pulls the fit toward them), above 1 for stocks outside it."""
        M = -np.nan_to_num(self.fm.expo.X[t]) @ self.Q[t].astype(float)
        M[np.diag_indices_from(M)] += 1.0
        dd = np.nan_to_num(d)
        with np.errstate(invalid="ignore", divide="ignore"):
            k = (M ** 2 @ dd) / dd
        return np.clip(np.where(np.isfinite(k), k, 1.0), 0.3, 3.0)

    @staticmethod
    def _with_slow_factors(fm: FactorModel):
        """Core factor returns and exposures plus the slow layer as "slow:<name>" factors.  Slow exposures
        are the core-orthogonalised ones; a stock the core models but the slow layer skipped gets 0."""
        e = fm.expo
        if fm.slow_returns is None or fm.X_slow_perp is None:
            return fm.factor_returns, e.X, dict(e.groups)
        names = [f"slow:{c}" for c in fm.slow_returns.columns]
        fr = pd.concat([fm.factor_returns, fm.slow_returns.set_axis(names, axis=1)], axis=1)
        core_ok = np.all(np.isfinite(e.X), 2, keepdims=True)
        X = np.concatenate([e.X, np.where(core_ok, np.nan_to_num(fm.X_slow_perp), np.nan)], axis=2)
        return fr, X, {**e.groups, **{n: "slow" for n in names}}

    # ---------------- factor covariance ---------------- #
    def factor_covariance(self, fr: pd.DataFrame, spec_var: np.ndarray | None = None):
        """EWMA covariance with per-factor (and pairwise) weights so factors that are only
        observed on some days (events, limit hits, statistical factors before their window
        fills) get variances conditional on the days they are active.

        With cfg.denoise_factor_cov the EWMA of each day's sampling covariance Q_t D_t Q_t' is
        subtracted: estimated factor returns carry specific noise that a covariance of them counts
        as factor risk, while the same noise is already in specific risk.  It matters when the
        cross-section is small relative to the number of factors (40 tokens, 13 factors)."""
        cfg = self.cfg
        f = fr.values
        T, K = f.shape
        lv, lc, lb = _decay(cfg.vol_halflife), _decay(cfg.corr_halflife), _decay(cfg.vra_halflife)
        Sv = np.zeros(K); wv = np.zeros(K)
        Sc = np.zeros((K, K)); wc = np.zeros((K, K))
        denoise = (cfg.denoise_factor_cov and spec_var is not None and self.Q is not None
                   and self.Q.shape[1] == K)
        Nv = np.zeros(K); Nc = np.zeros((K, K))
        noise_var = np.zeros((T, K))
        B2 = 0.0; wb = 0.0
        F = np.full((T, K, K), np.nan)
        vra = np.full(T, np.nan); shrink = np.full(T, np.nan)
        gam_hist = np.full((T, K), np.nan)
        rawvol = np.full((T, K), np.nan)
        gamma = np.ones(K)
        delta = 0.0
        n = 0
        t_eff = int(1.5 * cfg.corr_halflife)
        history = []
        min_w = 1 - lv ** 10                  # ~10 observations before a factor's own vol is trusted
        names = list(fr.columns)
        macro_idx = [k for k, f in enumerate(names) if f in MACRO_SENSITIVE]
        mkt = names.index("market") if "market" in names else 0
        acc = {True: [0.0, 0], False: [0.0, 0]}       # sum of z^2 and count, macro vs other days
        acc_k = {True: [np.zeros(K), np.zeros(K)], False: [np.zeros(K), np.zeros(K)]}   # per factor
        macro_mult = np.full(T, np.nan)
        Fb = None
        for t in range(T):
            Nt = self.noise_cov(t, spec_var[t]) if denoise else None
            nt = np.diag(Nt) if denoise else np.zeros(K)
            noise_var[t] = nt
            if n >= cfg.cov_min_obs:
                ok = wv > min_w
                Sv_ = np.maximum(Sv - Nv, cfg.denoise_floor * Sv) if denoise else Sv
                var = np.where(ok, Sv_ / np.where(ok, wv, 1), np.nan)
                fallback = np.nanmedian(var) if np.isfinite(var).any() else 1e-4
                var = np.clip(np.where(ok, var, fallback), 1e-14, None)
                okc = wc > (1 - lc ** 20)
                Sc_ = Sc
                if denoise:
                    Sc_ = Sc - Nc
                    np.fill_diagonal(Sc_, np.maximum(np.diag(Sc_), cfg.denoise_floor * np.diag(Sc)))
                C = np.where(okc, Sc_ / np.where(okc, wc, 1), 0.0)
                dc = np.sqrt(np.clip(np.diag(C), 1e-14, None))
                corr = np.clip(C / np.outer(dc, dc), -0.99, 0.99)
                corr[~okc] = 0.0
                # pairs observed together on few days (sparse event factors) are shrunk toward 0
                n_ij = wc / (1 - lc)
                corr = corr * n_ij / (n_ij + 30.0)
                np.fill_diagonal(corr, 1.0)
                if (t % 21 == 0) or delta == 0.0:
                    # intensity estimated on densely observed factors only: sparse event factors
                    # padded with zeros would masquerade as noise and over-shrink every correlation
                    H = np.array(history[-252:])
                    dense = np.isfinite(H).mean(0) >= 0.9
                    Hd = H[:, dense]
                    Hd = Hd[np.all(np.isfinite(Hd), 1)]
                    if len(Hd) > 2 * Hd.shape[1]:
                        Hs = Hd / np.sqrt(np.clip(np.var(Hd, 0), 1e-14, None))
                        delta = min(float(ledoit_wolf_shrinkage(Hs, assume_centered=True)), cfg.lw_max)
                    else:
                        delta = cfg.lw_max
                corr = (1 - delta) * corr + delta * np.eye(K)
                ev, evec = np.linalg.eigh(corr)
                if ev.min() < 1e-4:                # pairwise estimates need not be PSD: clip and
                    corr = (evec * np.clip(ev, 1e-4, None)) @ evec.T          # restore unit diagonal
                    dd = np.sqrt(np.diag(corr))
                    corr = corr / np.outer(dd, dd)
                F0 = corr * np.outer(np.sqrt(var), np.sqrt(var))
                if t % cfg.eigen_every == 0 or np.all(gamma == 1):
                    gamma = eigen_adjustment(F0, t_eff, cfg.eigen_sims, cfg.eigen_scale, self.rng)
                d0, U0 = np.linalg.eigh(F0)
                F1 = (U0 * (np.clip(d0, 1e-14, None) * gamma ** 2)) @ U0.T
                lam2 = B2 / wb if wb > 0 and cfg.vra_factor else 1.0
                Fb = lam2 * F1
                F[t] = Fb
                if self.macro_day[t] and cfg.macro_per_factor and acc_k[False][1][mkt] >= 30:
                    # each macro-sensitive factor gets its own ratio of mean z^2 on macro days to
                    # other days, shrunk toward 1 by macro_prior_obs pseudo-days
                    m_oth = acc_k[False][0] / np.maximum(acc_k[False][1], 1)
                    m_mac = (acc_k[True][0] + cfg.macro_prior_obs * m_oth) / (acc_k[True][1] + cfg.macro_prior_obs)
                    mm_k = np.clip(m_mac / np.maximum(m_oth, 1e-12), 1.0, cfg.macro_mult_cap)
                    sc = np.ones(K); sc[macro_idx] = np.sqrt(mm_k[macro_idx])
                    F[t] = Fb * np.outer(sc, sc)
                    macro_mult[t] = mm_k[mkt]
                elif self.macro_day[t] and not cfg.macro_per_factor and acc[True][1] >= 6 and acc[False][1] >= 30:
                    mm = (acc[True][0] / acc[True][1]) / max(acc[False][0] / acc[False][1], 1e-12)
                    mm = float(np.clip(mm, 1.0, cfg.macro_mult_cap))
                    sc = np.ones(K); sc[macro_idx] = np.sqrt(mm)
                    F[t] = Fb * np.outer(sc, sc)
                    macro_mult[t] = mm
                vra[t] = np.sqrt(lam2); shrink[t] = delta; gam_hist[t] = gamma
                rawvol[t] = np.sqrt(var)
            ft = f[t]
            obs = np.isfinite(ft)
            if not obs.any():
                continue
            if n >= cfg.cov_min_obs and np.isfinite(F[t]).all():
                # an estimated factor return varies by the (denoised) forecast plus today's noise
                fvar = np.diag(Fb) + nt
                if obs[mkt]:
                    z2 = min(ft[mkt] ** 2 / max(fvar[mkt], 1e-14), 25.0)
                    acc[bool(self.macro_day[t])][0] += z2
                    acc[bool(self.macro_day[t])][1] += 1
                z2k = np.where(obs, np.minimum(np.nan_to_num(ft) ** 2 / np.maximum(fvar, 1e-14), 25.0), 0.0)
                acc_k[bool(self.macro_day[t])][0] += z2k
                acc_k[bool(self.macro_day[t])][1] += obs
                sd = np.sqrt(np.clip(np.diag(Fb) / max(vra[t] ** 2, 1e-12) + nt, 1e-14, None))
                active = obs & (wv > min_w)
                if active.sum() > 2:
                    b2 = np.mean((ft[active] / sd[active]) ** 2)
                    B2 = lb * B2 + (1 - lb) * min(b2, 25.0); wb = lb * wb + (1 - lb)
            fz = np.where(obs, ft, 0.0)
            Sv = np.where(obs, lv * Sv + (1 - lv) * fz ** 2, Sv)
            wv = np.where(obs, lv * wv + (1 - lv), wv)
            both = np.outer(obs, obs)
            Sc = np.where(both, lc * Sc + (1 - lc) * np.outer(fz, fz), Sc)
            wc = np.where(both, lc * wc + (1 - lc), wc)
            if denoise:
                Nv = np.where(obs, lv * Nv + (1 - lv) * nt, Nv)
                Nc = np.where(both, lc * Nc + (1 - lc) * Nt, Nc)
            history.append(np.where(obs, ft, np.nan))
            n += 1
        idx = self.fm.factor_returns.index
        self.macro_mult = pd.Series(macro_mult, idx)
        self.noise_var = noise_var
        # end-of-sample uplift per macro-sensitive factor (raw ratio, and as applied)
        m_oth = acc_k[False][0] / np.maximum(acc_k[False][1], 1)
        raw = acc_k[True][0] / np.maximum(acc_k[True][1], 1) / np.maximum(m_oth, 1e-12)
        shrunk = ((acc_k[True][0] + cfg.macro_prior_obs * m_oth) / (acc_k[True][1] + cfg.macro_prior_obs)
                  / np.maximum(m_oth, 1e-12))
        self.macro_uplift = pd.DataFrame({"macro_days": acc_k[True][1][macro_idx], "raw_ratio": raw[macro_idx],
                                          "per_factor": np.clip(shrunk[macro_idx], 1.0, cfg.macro_mult_cap)},
                                         index=[names[k] for k in macro_idx])
        return F, pd.Series(vra, idx), pd.Series(shrink, idx), \
            pd.DataFrame(gam_hist, idx), pd.DataFrame(rawvol, idx, fr.columns)

    def link_slow_block(self, Fc: np.ndarray, shrink: np.ndarray):
        """Block augmentation: append the slow factors to the core covariance Fc without changing it.

        Slow vols are plain EWMA vols on the core vol half-life.  The core regime multiplier is not
        applied: it is calibrated against the eigen-adjusted core forecasts and partly undoes that
        adjustment's inflation, so on the slow block it under-forecasts (bias ~1.15 against ~1.0
        without it; a slow-only multiplier on five factors adds noise and does no better).
        Slow-slow and slow-core correlations use the core correlation half-life, sparse-pair
        shrinkage and that day's Ledoit-Wolf intensity.  The matrix is made valid through the Schur
        complement: the slow block is raised to at least what its covariance with the core implies,
        so the core block and the cross block are kept as is."""
        cfg = self.cfg
        f = self.factor_returns.values                    # core columns first, then slow
        T, K = f.shape
        Kc = Fc.shape[1]
        s = slice(Kc, K)
        lv, lc = _decay(cfg.vol_halflife), _decay(cfg.corr_halflife)
        min_w = 1 - lv ** 10
        Sv = np.zeros(K - Kc); wv = np.zeros(K - Kc)
        Sc = np.zeros((K, K)); wc = np.zeros((K, K))
        F = np.full((T, K, K), np.nan)
        rawvol = np.full((T, K - Kc), np.nan)
        for t in range(T):
            Fct = Fc[t]
            if np.isfinite(Fct).all():
                ok = wv > min_w
                var = np.where(ok, Sv / np.where(ok, wv, 1), np.nan)
                fallback = np.nanmedian(var) if ok.any() else np.median(np.diag(Fct))
                var = np.clip(np.where(ok, var, fallback), 1e-14, None)
                okc = wc > (1 - lc ** 20)
                C = np.where(okc, Sc / np.where(okc, wc, 1), 0.0)
                dc = np.sqrt(np.clip(np.diag(C), 1e-14, None))
                corr = np.where(okc, np.clip(C / np.outer(dc, dc), -0.99, 0.99), 0.0)
                n_ij = wc / (1 - lc)
                corr = corr * n_ij / (n_ij + 30.0) * (1 - shrink[t])
                sd_s = np.sqrt(var)
                sd_c = np.sqrt(np.clip(np.diag(Fct), 0, None))
                Finv = np.linalg.pinv(Fct, rcond=1e-10, hermitian=True)
                if cfg.denoise_factor_cov:
                    # these correlations are between estimated (noisy) returns while the core block is
                    # de-noised; projecting them through its inverse would inflate the slow floor
                    # (~2x).  Regress slow on core with the raw core covariance instead (attenuated,
                    # never inflated) and map the betas through the de-noised core.
                    Rc = corr[:Kc, :Kc].copy()
                    np.fill_diagonal(Rc, 1.0)
                    beta = np.linalg.pinv(Rc * np.outer(dc[:Kc], dc[:Kc]), rcond=1e-10, hermitian=True) \
                        @ (corr[s, :Kc] * np.outer(sd_s, dc[:Kc])).T
                    cross = (Fct @ beta).T
                    implied = beta.T @ Fct @ beta
                else:
                    cross = (corr[s, :Kc] * np.outer(sd_s, sd_c)) @ (Finv @ Fct)    # kept within the core's range
                    implied = cross @ Finv @ cross.T
                Sss = corr[s, s] * np.outer(sd_s, sd_s)
                np.fill_diagonal(Sss, sd_s ** 2)
                d, U = np.linalg.eigh(0.5 * (Sss - implied + (Sss - implied).T))
                Sss = implied + (U * np.clip(d, 1e-4 * np.mean(sd_s ** 2), None)) @ U.T
                F[t, :Kc, :Kc] = Fct
                F[t, s, :Kc] = cross
                F[t, :Kc, s] = cross.T
                F[t, s, s] = Sss
                rawvol[t] = np.sqrt(var)
            ft = f[t]
            obs = np.isfinite(ft)
            if not obs.any():
                continue
            fz = np.where(obs, ft, 0.0)
            Sv = np.where(obs[s], lv * Sv + (1 - lv) * fz[s] ** 2, Sv)
            wv = np.where(obs[s], lv * wv + (1 - lv), wv)
            both = np.outer(obs, obs)
            Sc = np.where(both, lc * Sc + (1 - lc) * np.outer(fz, fz), Sc)
            wc = np.where(both, lc * wc + (1 - lc), wc)
        return F, pd.DataFrame(rawvol, self.factor_returns.index, self.factor_returns.columns[Kc:])

    # ---------------- specific risk ---------------- #
    def specific_risk(self):
        cfg, fm = self.cfg, self.fm
        e = fm.expo
        U = (fm.resid_after_slow if fm.resid_after_slow is not None else fm.resid).values   # slow risk is in F now
        T, N = U.shape
        ls, lb = _decay(cfg.specific_halflife), _decay(cfg.vra_halflife)
        S = np.zeros(N); w = np.zeros(N); n = np.zeros(N)
        out = np.full((T, N), np.nan)
        lam = np.full(T, np.nan)
        B2, wb = 0.0, 0.0
        struct_cols = [f for f in ("size", "volatility", "liquidity") if f in e.factors]
        sc_idx = e.idx(struct_cols) + e.idx(e.industries)
        E = e.estu.values
        cap = np.nan_to_num(e.cap.values)
        ev_names = self.event_factors or None
        lev_adj = cfg.specific_leverage_adj and self.Q is not None
        for t in range(T):
            X = e.X[t]
            valid = np.all(np.isfinite(X), 1)
            if valid.sum() > 20 and (n >= 20).sum() > 20:
                sig_ts = np.where(w > 0, np.sqrt(S / np.where(w > 0, w, 1)), np.nan)
                good = valid & (n >= 60) & E[t] & (sig_ts > 0)
                Z = np.column_stack([np.ones(N), np.nan_to_num(X[:, sc_idx])])
                if good.sum() > len(sc_idx) + 10:
                    b, *_ = np.linalg.lstsq(Z[good], np.log(sig_ts[good]), rcond=None)
                    pred = np.exp(Z @ b)
                    e0 = np.mean(sig_ts[good] / pred[good])
                    sig_str = e0 * pred
                else:
                    sig_str = np.full(N, np.nanmedian(sig_ts))
                g = np.clip((n - 20) / 100, 0, 1)
                sig = np.where(np.isfinite(sig_ts), g * sig_ts + (1 - g) * sig_str, sig_str)
                lam2 = B2 / wb if wb > 0 and cfg.vra_specific else 1.0
                var = lam2 * sig ** 2
                if ev_names is not None:
                    on_event = e.flagged(t, ev_names).any(axis=1)
                    var = np.where(on_event, var * cfg.event_specific_mult ** 2, var)
                var[~valid] = np.nan
                out[t] = var
                lam[t] = np.sqrt(lam2)
            # a regression residual is not the specific return: scale u^2 by its expected ratio kappa
            kap = np.ones(N)
            if lev_adj and np.isfinite(out[t]).any() and self.Q[t].any():
                kap = self.leverage_ratio(t, np.where(np.isfinite(out[t]), out[t], np.nanmedian(out[t])))
            if np.isfinite(out[t]).any():
                ut = U[t]
                ok = E[t] & np.isfinite(ut) & np.isfinite(out[t]) & valid
                if ok.sum() > 20:
                    b2 = np.average(ut[ok] ** 2 / (kap[ok] * out[t][ok]) * lam[t] ** 2, weights=cap[t][ok] + 1e-9)
                    B2 = lb * B2 + (1 - lb) * min(b2, 25.0); wb = lb * wb + (1 - lb)
            ut = U[t]
            m = np.isfinite(ut)
            S[m] = ls * S[m] + (1 - ls) * np.minimum(ut[m] ** 2 / kap[m], 0.25 ** 2)
            w[m] = ls * w[m] + (1 - ls)
            n[m] += 1
        return out, pd.Series(lam, index=fm.resid.index)

    def build(self) -> RiskModel:
        # specific risk first: the factor-return noise removed from F is measured with it.
        # Core block estimated on core factors alone, so adding the slow layer leaves it unchanged
        spec, lam_s = self.specific_risk()
        F, vra, shrink, gam, rawvol = self.factor_covariance(self.fm.factor_returns, spec)
        noise = self.noise_var
        if self.factor_returns.shape[1] > F.shape[1]:
            F, rawvol_slow = self.link_slow_block(F, shrink.values)
            rawvol = pd.concat([rawvol, rawvol_slow], axis=1)
            noise = np.pad(noise, ((0, 0), (0, F.shape[1] - noise.shape[1])))
        e = self.fm.expo
        return RiskModel(name=self.fm.name, dates=e.dates, factors=list(self.factor_returns.columns),
                         groups=self.groups, tickers=e.tickers, X=self.X, F=F, spec_var=spec, vra=vra,
                         vra_specific=lam_s, shrinkage=shrink, eigen_gamma=gam, raw_factor_vol=rawvol,
                         macro_mult=self.macro_mult, factor_returns=self.factor_returns, noise_var=noise,
                         macro_uplift=self.macro_uplift)

"""Layer 2 - Factor exposures.

Builds the exposure matrix X_t (stocks x factors) for every date.  Every
exposure used on date t is computed from information available at the close
of t-1 (or announced in advance, e.g. earnings dates), so the factor
regression of day-t returns on X_t has no look-ahead.

Standardisation follows the Barra convention: robust winsorisation
(median +/- k*MAD), cap-weighted mean zero and equal-weighted unit standard
deviation on the estimation universe, final clip at +/-3.  Collinear pairs are
orthogonalised in the fixed, documented order of ``config.ORTHOGONALISATION``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import (CANDIDATE_FACTORS, CROWDING_INPUTS, CRYPTO_EVENT_FACTORS, CRYPTO_STYLE_FACTORS,
                     EVENT_FACTORS, MARKET_FACTOR, MODEL, ORTHOGONALISATION, PROMOTED_CANDIDATES,
                     SLOW_FACTORS, STYLE_FACTORS, ModelConfig)
from .data_loader import CryptoPanel, EquityPanel


@dataclass
class ExposureSet:
    model: str
    dates: pd.DatetimeIndex
    tickers: pd.Index
    factors: list
    groups: dict
    X: np.ndarray                    # T x N x K (NaN where security not modelled)
    estu: pd.DataFrame               # estimation universe
    reg_weight: pd.DataFrame         # regression weights
    cap: pd.DataFrame                # market cap (USD) for constraints / cap weighting
    beta_pred: pd.DataFrame          # raw predicted beta (for beta-adjusted net exposure)
    industries: list
    slow_factors: list = field(default_factory=list)
    X_slow: np.ndarray | None = None
    descriptors: dict = field(default_factory=dict)
    candidates: dict = field(default_factory=dict)   # medium-priority factors under test (T x N each)
    monitor: dict = field(default_factory=dict)      # background monitors (e.g. 13F ownership)
    shocks: pd.DataFrame | None = None               # observed series g for time-series factors
    flags: dict = field(default_factory=dict)        # raw 0/+-1 values (T x N) of cap-centred event dummies
                                                     # (+ in_play_any, the pre-limit-hit in-play flag)
    extras: dict = field(default_factory=dict)

    @property
    def K(self) -> int:
        return len(self.factors)

    def frame(self, t: int) -> pd.DataFrame:
        return pd.DataFrame(self.X[t], index=self.tickers, columns=self.factors)

    def idx(self, names) -> list[int]:
        return [self.factors.index(n) for n in names]

    def add_factors(self, names: list, X_new: np.ndarray, group: str) -> None:
        self.X = np.concatenate([self.X, X_new], axis=2)
        self.factors = list(self.factors) + list(names)
        for n in names:
            self.groups[n] = group

    def factors_in(self, group: str) -> list:
        return [f for f in self.factors if self.groups[f] == group]

    def flagged(self, t: int, names) -> np.ndarray:
        """N x len(names) bool: stocks carrying each sparse dummy on day t.  Event columns of X are
        cap-centred (every stock is non-zero), so their raw flags are read from ``flags``."""
        return np.column_stack([np.nan_to_num(self.flags[f][t] if f in self.flags
                                              else self.X[t, :, self.factors.index(f)]) != 0 for f in names])

    def cs_factors(self) -> list:
        """Factors whose returns are estimated by the cross-sectional regression."""
        return [f for f in self.factors if self.groups[f] not in ("timeseries", "statistical")]


# --------------------------------------------------------------------------- #
# Cross-sectional transforms
# --------------------------------------------------------------------------- #
def standardize(raw: np.ndarray, estu: np.ndarray, capw: np.ndarray, cfg: ModelConfig = MODEL,
                fill: float = 0.0) -> np.ndarray:
    """Robust winsorise, cap-weighted mean 0, equal-weighted std 1 on estu; missing -> fill."""
    x = np.asarray(raw, float).copy()
    valid = np.isfinite(x)
    e = estu & valid & np.isfinite(capw)
    if e.sum() < 10:
        return np.full_like(x, fill)
    med = np.median(x[e])
    mad = 1.4826 * np.median(np.abs(x[e] - med))
    if mad > 0:
        x = np.clip(x, med - cfg.winsor_mad * mad, med + cfg.winsor_mad * mad)
    for _ in range(2):
        mu = np.average(x[e], weights=capw[e])
        sd = np.std(x[e])
        if not sd > 0:
            return np.full_like(x, fill)
        x = np.clip((x - mu) / sd, -cfg.winsor_z, cfg.winsor_z)
    x[~valid] = fill
    return x


def orthogonalize(y: np.ndarray, Z: np.ndarray, estu: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Remove from y the WLS projection on columns of Z (estimated on estu)."""
    m = estu & np.isfinite(y) & np.all(np.isfinite(Z), 1)
    if m.sum() < Z.shape[1] + 5:
        return y
    Zm = np.column_stack([np.ones(m.sum()), Z[m]])
    sw = np.sqrt(w[m])
    b, *_ = np.linalg.lstsq(Zm * sw[:, None], y[m] * sw, rcond=None)
    return y - np.column_stack([np.ones(len(y)), Z]) @ b


def center_dummy(raw: np.ndarray, estu: np.ndarray, capw: np.ndarray) -> np.ndarray:
    """Subtract the cap-weighted estu mean from a sparse dummy (flagged stocks 1 - s, others -s).

    A raw 0/1 column has a positive cap-weighted mean, so the regression would book part of the market
    move as the event return and the market factor would drift from the cap-weighted universe return on
    event days (worst for option expiry, which flags every index member).  Centring is a per-day
    reparameterisation: the fit, residuals and event return are unchanged; only the market return moves.
    """
    x = np.nan_to_num(np.asarray(raw, float))
    e = estu & (capw > 0)
    return x - np.average(x[e], weights=capw[e]) if e.any() else x


def _ewm_beta(r: pd.DataFrame, m: pd.Series, halflife: int, min_periods: int) -> pd.DataFrame:
    M = r * 0 + m.values[:, None]                      # market aligned to r's missing pattern
    ew = lambda df: df.ewm(halflife=halflife, min_periods=min_periods, ignore_na=True).mean()
    cov = ew(r * M) - ew(r) * ew(M)
    var = ew(M * M) - ew(M) ** 2
    return cov / var


def _ewm_corr(r: pd.DataFrame, m: pd.Series, halflife: int, min_periods: int) -> pd.DataFrame:
    M = r * 0 + m.values[:, None]
    ew = lambda df: df.ewm(halflife=halflife, min_periods=min_periods, ignore_na=True).mean()
    cov = ew(r * M) - ew(r) * ew(M)
    return cov / np.sqrt((ew(r * r) - ew(r) ** 2) * (ew(M * M) - ew(M) ** 2))


# --------------------------------------------------------------------------- #
# Time-series shock betas (Section 3.1: r = X f + B g + u)
# --------------------------------------------------------------------------- #
def time_series_betas(r: pd.DataFrame, market: pd.Series, shocks: pd.DataFrame, sector_idx: np.ndarray,
                      estu: pd.DataFrame, cap: pd.DataFrame, cfg: ModelConfig = MODEL) -> tuple[np.ndarray, dict]:
    """EWMA multivariate betas of each stock to [market, g_1..g_K], keeping the shock betas.

    The market is a regressor so the shock betas are incremental to market beta.  Betas are
    shrunk toward the cap-weighted industry average with Bayesian weights tau^2 / (tau^2 + se^2)
    (noisy time-series betas, Section 3.4), cap-weight demeaned so the market factor stays
    identified, and lagged one day.  Returns (T x N x K) and diagnostics.
    """
    hl, mo = cfg.ts_beta_halflife, cfg.ts_min_obs
    Z = pd.concat([market.rename("_mkt"), shocks], axis=1).reindex(r.index).fillna(0.0)
    cols = list(Z.columns)
    K1 = len(cols)
    ew = lambda x: x.ewm(halflife=hl, min_periods=mo, ignore_na=True).mean()
    Zm = ew(Z)
    Szz = np.zeros((len(r), K1, K1))
    for a in range(K1):
        for b in range(a, K1):
            v = (ew(Z[cols[a]] * Z[cols[b]]) - Zm[cols[a]] * Zm[cols[b]]).values
            Szz[:, a, b] = Szz[:, b, a] = v
    rm = ew(r)
    Szr = np.stack([(ew(r.mul(Z[c], axis=0)) - rm.mul(Zm[c], axis=0)).values for c in cols], axis=-1)
    ok_t = np.all(np.isfinite(Szz.reshape(len(r), -1)), 1)
    inv = np.full_like(Szz, np.nan)
    inv[ok_t] = np.linalg.pinv(Szz[ok_t])
    B = np.einsum("tjk,tnk->tnj", inv, Szr)
    var_r = (ew(r * r) - rm ** 2).values
    expl = np.einsum("tnj,tjk,tnk->tn", B, Szz, B)
    lam = 0.5 ** (1 / hl)
    n_eff = (1 + lam) / (1 - lam)
    s2e = np.clip(var_r - expl, 1e-8, None)
    se2 = s2e[..., None] * np.einsum("tkk->tk", inv)[:, None, :] / n_eff
    nobs = r.notna().cumsum().values
    B[nobs < mo] = np.nan
    B, se2 = B[:, :, 1:], se2[:, :, 1:]                 # drop the market column
    T, N, K = B.shape
    out = np.full((T, N, K), np.nan)
    wbar = np.full((T, K), np.nan)
    E, C = estu.values, np.nan_to_num(cap.values)
    G = sector_idx.max() + 1
    for t in range(T):
        for k in range(K):
            b, s2 = B[t, :, k], se2[t, :, k]
            v = E[t] & np.isfinite(b) & np.isfinite(s2)
            if v.sum() < 3 * G:
                continue
            cw = np.bincount(sector_idx[v], weights=C[t][v], minlength=G)
            mean_g = np.bincount(sector_idx[v], weights=C[t][v] * b[v], minlength=G) / np.maximum(cw, 1e-12)
            cnt = np.bincount(sector_idx[v], minlength=G)
            dev2 = np.bincount(sector_idx[v], weights=(b[v] - mean_g[sector_idx[v]]) ** 2, minlength=G) / np.maximum(cnt, 1)
            se_g = np.bincount(sector_idx[v], weights=s2[v], minlength=G) / np.maximum(cnt, 1)
            tau2 = np.maximum(dev2 - se_g, 0.1 * dev2) + 1e-12
            prior = mean_g[sector_idx]
            w = tau2[sector_idx] / (tau2[sector_idx] + np.nan_to_num(s2, nan=np.inf))
            bs = np.where(np.isfinite(b), w * b + (1 - w) * prior, prior)
            med = np.median(bs[E[t]])
            mad = 1.4826 * np.median(np.abs(bs[E[t]] - med)) + 1e-12
            bs = np.clip(bs, med - 5 * mad, med + 5 * mad)
            bs = bs - np.average(bs[E[t]], weights=C[t][E[t]] + 1e-12)
            out[t, :, k] = bs
            wbar[t, k] = np.mean(w[v])
    out = np.concatenate([np.full((1, N, K), np.nan), out[:-1]], 0)       # known at the open
    return out, {"raw": B, "shrink_weight": pd.DataFrame(wbar, index=r.index, columns=list(shocks.columns))}


# --------------------------------------------------------------------------- #
# Equity exposures
# --------------------------------------------------------------------------- #
class EquityExposureBuilder:
    def __init__(self, panel: EquityPanel, btc_returns: pd.Series | None = None, cfg: ModelConfig = MODEL):
        self.p, self.cfg, self.btc = panel, cfg, btc_returns

    def estimation_universe(self) -> pd.DataFrame:
        p, c = self.p, self.cfg
        hist = p.ret.notna().cumsum().shift(1)
        listed_prev = p.listed.shift(1, fill_value=False)
        age = p.listed.cumsum()
        estu = (p.listed & listed_prev & ~p.halted & (p.close.shift(1) > c.min_price)
                & (p.adv_usd > c.min_adv_usd) & (hist >= c.min_history) & (age > c.min_history))
        return estu.fillna(False)

    def descriptors(self) -> dict:
        with np.errstate(divide="ignore", invalid="ignore"):
            return self._descriptors()

    def _descriptors(self) -> dict:
        p, c = self.p, self.cfg
        r = p.ret
        lr = np.log1p(r)
        cap_prev = p.mcap_usd.shift(1)
        mkt = (r * cap_prev).sum(axis=1) / cap_prev.where(r.notna()).sum(axis=1)
        beta = _ewm_beta(r, mkt, c.beta_halflife, c.min_history).shift(1)
        beta = ((1 - c.beta_shrink) * beta + c.beta_shrink).clip(-0.5, 3.0)
        turnover = (p.volume / p.shares).replace(0, np.nan)
        vol20 = r.rolling(c.vol_window, min_periods=10).std()
        # crowding inputs, lagged to when they are known; no prime-broker coverage -> missing
        borrowable = p.borrow_fee_bps.notna()
        fee = p.borrow_fee_bps
        d = {
            "beta": beta,
            "size": np.log(cap_prev),
            "liq_turnover": np.log(turnover.rolling(c.liquidity_window, min_periods=10).mean()).shift(1),
            "liq_amihud": -np.log((r.abs() / p.dollar_vol_usd.replace(0, np.nan))
                                  .rolling(c.liquidity_window, min_periods=10).mean() + 1e-14).shift(1),
            "liq_spread": -np.log(p.spread_bps.rolling(c.liquidity_window, min_periods=10).mean()).shift(1),
            "liq_tick": np.log(p.close / p.spec.tick_size).shift(1),     # small relative tick = liquid
            "volatility": vol20.shift(1),
            "st_reversal": -lr.rolling(c.reversal_window, min_periods=3).sum().shift(1),
            "st_momentum": np.log1p(p.ret_id).rolling(c.momentum_window, min_periods=2).sum().shift(1),
            "overnight_gap": np.log1p(p.ret_on).rolling(c.gap_window, min_periods=3).sum().shift(1),
            "crowd_si_float": np.log1p(100 * p.short_interest_pct).where(borrowable).shift(1),
            "crowd_days_to_cover": np.log1p(p.days_to_cover).where(borrowable).shift(1),
            "crowd_borrow_fee": np.log(fee).shift(1),
            "crowd_borrow_scarcity": (-np.log(p.borrow_avail_pct.clip(lower=1e-5))).shift(1)
            if p.borrow_avail_pct is not None else None,
            "crowd_utilisation": p.utilisation.shift(1) if p.utilisation is not None else None,
            "earnings": p.earnings.astype(float),
            "index_rebalance": p.index_event,
            "option_expiry": p.index_member.mul(p.option_expiry.astype(float), axis=0)
            if p.index_member is not None else None,
            "corporate_action": p.corporate_action.astype(float) if p.corporate_action is not None else None,
            # unscheduled news without a news feed: abnormal volume plus a price jump yesterday
            "in_play": ((p.volume / p.adv_shares > c.in_play_volume_mult)
                        & (r.abs() > c.in_play_move_sd * vol20.shift(1)) & ~p.earnings).astype(float).shift(1),
            # slow / monitoring-layer descriptors
            "value": np.log(p.book_equity / p.mcap_usd).shift(1),
            "earnings_yield": (4 * p.net_income / p.mcap_usd).shift(1),
            "quality": (4 * p.net_income / p.book_equity).shift(1),
            "momentum_12_1": lr.rolling(231, min_periods=126).sum().shift(22),
            "long_term_reversal": -lr.rolling(504, min_periods=126).sum().shift(253),
            # candidates (medium priority) and background monitors
            "etf_ownership": p.etf_own_pct.shift(1) if p.etf_own_pct is not None else None,
            "retail_attention": np.log(p.retail_share).shift(1) if p.retail_share is not None else None,
            "hf_ownership_13f": p.hf_own_pct.shift(1) if p.hf_own_pct is not None else None,
            "market_return": mkt,
        }
        if "crypto_beta" in p.spec.extra_factors and self.btc is not None:
            cum = self.btc.cumsum()
            btc_d = cum.reindex(p.dates, method="ffill").diff()
            b = _ewm_beta(r, btc_d, c.beta_halflife, c.min_history)
            rho = _ewm_corr(r, btc_d, c.beta_halflife, c.min_history)
            d["crypto_beta"] = (b * (rho.abs() > 0.15)).clip(-2, 2).shift(1)
        d["in_play_any"] = d["in_play"]
        if "limit_hit" in p.spec.extra_factors:
            d["limit_hit"] = p.limit_flag.shift(1)
            # a limit hit is itself a volume spike plus a large move, so it would also trip in_play and the
            # two dummies would be collinear; the limit hit is the more specific explanation and takes the stock
            # (in_play_any keeps the full definition for the specific-risk uplift)
            d["in_play"] = d["in_play"].where(d["limit_hit"].fillna(0) == 0, 0.0)
        return {k: v for k, v in d.items() if v is not None}

    def build(self) -> ExposureSet:
        p, c = self.p, self.cfg
        T, N = len(p.dates), len(p.tickers)
        estu = self.estimation_universe()
        d = self.descriptors()
        cap = p.mcap_usd.shift(1).bfill(limit=1)
        w = np.sqrt(cap)
        w = w.clip(upper=w.quantile(0.95, axis=1), axis=0)
        industries = [f"ind_{s}" for s in p.spec.sectors]
        extra = list(p.spec.extra_factors)
        promoted = [f for f in PROMOTED_CANDIDATES if f in d]
        events = [f for f in EVENT_FACTORS if f in d]
        factors = [MARKET_FACTOR] + industries + list(STYLE_FACTORS) + promoted + events + extra
        groups = {MARKET_FACTOR: "market", **{f: "industry" for f in industries},
                  **{f: "style" for f in list(STYLE_FACTORS) + promoted}, **{f: "event" for f in events},
                  **{f: "market_specific" for f in extra}}
        K = len(factors)
        X = np.full((T, N, K), np.nan)
        Xs = np.full((T, N, len(SLOW_FACTORS)), np.nan)
        cands = [f for f in CANDIDATE_FACTORS if f in d and f not in promoted]   # promoted ones are core now
        Xc = {f: np.full((T, N), np.nan) for f in cands}
        Xm = {f: np.full((T, N), np.nan) for f in ("hf_ownership_13f",) if f in d}
        sec_idx = np.array([p.spec.sectors.index(s) for s in p.ref.sector])
        ind_dummies = np.zeros((N, len(industries)))
        ind_dummies[np.arange(N), sec_idx] = 1.0
        fi = {f: k for k, f in enumerate(factors)}
        D = {k: v.values for k, v in d.items() if isinstance(v, pd.DataFrame)}
        crowd_in = [f"crowd_{n}" for n in CROWDING_INPUTS if f"crowd_{n}" in D]
        liq_in = [n for n in ("liq_turnover", "liq_amihud", "liq_spread", "liq_tick") if n in D]
        E, Wv, C, L = estu.values, w.values, cap.values, (p.listed & p.listed.shift(1, fill_value=False)).values
        crowd_cov = np.zeros(T)
        flags = {f: np.full((T, N), np.nan) for f in events + [f for f in ("limit_hit",) if f in fi]}
        flags["in_play_any"] = np.where(L | E, np.nan_to_num(D["in_play_any"]), np.nan)   # not a factor

        for t in range(T):
            live = L[t] | E[t]
            if live.sum() < 10:
                continue
            e, wt, cw = E[t], np.nan_to_num(Wv[t]), np.nan_to_num(C[t])
            Xt = np.zeros((N, K))
            Xt[:, fi[MARKET_FACTOR]] = 1.0
            Xt[:, fi[industries[0]]:fi[industries[-1]] + 1] = ind_dummies
            st = lambda name, fill=0.0: standardize(D[name][t], e, cw, c, fill=fill)
            Xt[:, fi["beta"]] = st("beta")
            Xt[:, fi["size"]] = st("size")
            Xt[:, fi["liquidity"]] = np.mean([st(n) for n in liq_in], axis=0)
            Xt[:, fi["volatility"]] = st("volatility")
            Xt[:, fi["st_reversal"]] = st("st_reversal")
            Xt[:, fi["st_momentum"]] = st("st_momentum")
            Xt[:, fi["overnight_gap"]] = st("overnight_gap")
            # short-side crowding: average the available standardised inputs; no data -> neutral 0
            if p.spec.short_side_crowding and crowd_in:
                comp = np.vstack([st(n, fill=np.nan) for n in crowd_in])
                has = np.isfinite(comp).any(0)
                crowd = np.where(has, np.nanmean(np.where(np.isfinite(comp), comp, np.nan), 0), 0.0)
                crowd_cov[t] = has[e].mean() if e.any() else 0.0
            else:
                crowd = np.zeros(N)
            Xt[:, fi["crowding"]] = np.nan_to_num(crowd)
            for f in promoted:
                Xt[:, fi[f]] = st(f)
            # orthogonalise in the fixed, documented order, then re-standardise
            for f, on in ORTHOGONALISATION.items():
                if f not in fi:
                    continue
                Xt[:, fi[f]] = orthogonalize(Xt[:, fi[f]], Xt[:, [fi[o] for o in on]], e, wt)
                Xt[:, fi[f]] = standardize(Xt[:, fi[f]], e, cw, c)
            if p.spec.short_side_crowding:
                Xt[:, fi["crowding"]] = np.where(np.isfinite(crowd) & (crowd != 0), Xt[:, fi["crowding"]], 0.0)
            for f in events:
                flags[f][t] = np.where(live, np.nan_to_num(D[f][t]), np.nan)
                Xt[:, fi[f]] = center_dummy(D[f][t], e, cw)
            if "crypto_beta" in fi:
                Xt[:, fi["crypto_beta"]] = np.nan_to_num(D["crypto_beta"][t]) if "crypto_beta" in D else 0.0
            if "limit_hit" in fi:
                flags["limit_hit"][t] = np.where(live, np.nan_to_num(D["limit_hit"][t]), np.nan)
                Xt[:, fi["limit_hit"]] = center_dummy(D["limit_hit"][t], e, cw)
            Xt[~live] = np.nan
            X[t] = Xt
            for k, f in enumerate(SLOW_FACTORS):
                Xs[t, :, k] = np.where(live, st(f), np.nan)
            for f in cands:
                Xc[f][t] = np.where(live, st(f), np.nan)
            for f in Xm:
                Xm[f][t] = np.where(live, st(f), np.nan)

        expo = ExposureSet(model=p.market, dates=p.dates, tickers=p.tickers, factors=factors, groups=groups,
                           X=X, estu=estu, reg_weight=w, cap=cap, beta_pred=d["beta"], industries=industries,
                           slow_factors=list(SLOW_FACTORS), X_slow=Xs,
                           descriptors={k: v for k, v in d.items() if isinstance(v, pd.DataFrame)},
                           candidates=Xc, monitor=Xm, flags=flags)
        expo.extras["crowding_coverage"] = pd.Series(crowd_cov, index=p.dates)
        # time-series shock factors: estimated sensitivities to observed shocks
        if p.shocks is not None and p.shocks.shape[1]:
            B, info = time_series_betas(p.ret, d["market_return"], p.shocks, sec_idx, estu, cap, c)
            alive = np.all(np.isfinite(X), 2)
            B = np.where(alive[..., None], np.nan_to_num(B), np.nan)    # no history yet -> industry prior 0
            expo.add_factors(list(p.shocks.columns), B, "timeseries")
            expo.extras["ts_shrink_weight"] = info["shrink_weight"]
            expo.extras["ts_raw_betas"] = info["raw"]
            expo.shocks = p.shocks
        return expo


# --------------------------------------------------------------------------- #
# Crypto exposures (separate local model, Section 2.5)
# --------------------------------------------------------------------------- #
class CryptoExposureBuilder:
    def __init__(self, panel: CryptoPanel, cfg: ModelConfig = MODEL):
        self.p, self.cfg = panel, cfg

    def build(self) -> ExposureSet:
        p, c = self.p, self.cfg
        T, N = len(p.dates), len(p.symbols)
        r = p.ret
        btc = r["BTC"]
        hist = r.notna().cumsum().shift(1)
        estu = (hist >= 30) & p.spot.notna() & (p.volume_usd.shift(1) > 1e6)
        cap = p.mcap_proxy.shift(1)
        w = np.sqrt(cap)
        d = {
            "btc_beta": _ewm_beta(r, btc, c.beta_halflife, 30).shift(1),
            "size": np.log(cap),
            "momentum": np.log1p(r).rolling(7, min_periods=5).sum().shift(1),
            "funding": p.funding.rolling(3, min_periods=1).mean().shift(1),
            "token_unlock": p.unlock,
            "volatility": r.rolling(20, min_periods=10).std().shift(1),
        }
        sectors = list(dict.fromkeys(p.ref.sector))
        industries = [f"sec_{s}" for s in sectors]
        factors = [MARKET_FACTOR] + industries + list(CRYPTO_STYLE_FACTORS) + list(CRYPTO_EVENT_FACTORS)
        groups = {MARKET_FACTOR: "market", **{f: "industry" for f in industries},
                  **{f: "style" for f in CRYPTO_STYLE_FACTORS}, **{f: "event" for f in CRYPTO_EVENT_FACTORS}}
        X = np.full((T, N, len(factors)), np.nan)
        sec_idx = np.array([sectors.index(s) for s in p.ref.sector])
        dummies = np.zeros((N, len(sectors))); dummies[np.arange(N), sec_idx] = 1
        fi = {f: k for k, f in enumerate(factors)}
        E, C = estu.values, np.nan_to_num(cap.values)
        D = {k: v.values for k, v in d.items()}
        flags = {f: np.full((T, N), np.nan) for f in CRYPTO_EVENT_FACTORS}
        for t in range(T):
            e = E[t]
            if e.sum() < 10:
                continue
            live = e | p.spot.notna().values[t]
            Xt = np.zeros((N, len(factors)))
            Xt[:, 0] = 1.0
            Xt[:, 1:1 + len(sectors)] = dummies
            for f in CRYPTO_STYLE_FACTORS:
                Xt[:, fi[f]] = standardize(D[f][t], e, C[t] + 1e-9, c)
            for f in CRYPTO_EVENT_FACTORS:
                flags[f][t] = np.where(live, np.nan_to_num(D[f][t]), np.nan)
                Xt[:, fi[f]] = center_dummy(D[f][t], e, C[t])
            Xt[~live] = np.nan
            X[t] = Xt
        return ExposureSet(model="CRYPTO", dates=p.dates, tickers=p.symbols, factors=factors, groups=groups,
                           X=X, estu=estu, reg_weight=w, cap=cap, beta_pred=d["btc_beta"],
                           industries=industries, descriptors=d, flags=flags)

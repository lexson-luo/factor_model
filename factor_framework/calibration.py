"""Risk-model calibration against the simulator's true covariance (synthetic data only).

Bias statistics compare forecasts with *realised* returns, so with a few strategy books and
63-day windows they are noisy.  On synthetic data the true conditional covariance of stock
returns is known, so a forecast can be compared with the truth directly, day by day, for any
portfolio:

    true var(h' r_t | t-1) = (A_t' h)' Omega_t (A_t' h) + sum_i h_i^2 D_ti

* A_t      true loadings: simulated factor exposures X_t plus the time-series sensitivities B
           (fx, rates, vol shock, liquidity shock, and the prior US session for China).
* Omega_t  covariance of the factor and shock returns.  Independent draws get their known variance:
           GJR-GARCH state for the market, the regime multiplier, x3 ETF-flow vol on rebalance
           days, macro-day scalings of FX and rates, and BTC variance summed over the calendar
           gap for the crypto factor.  The coupled block (market, reversal, liquidity, crowding,
           vol shock, liquidity shock) is integrated by Monte Carlo from the simulator's own
           equations.
* D_t      specific variance with the known earnings (x3 vol) and in-play (x2.2) multipliers and
           the expected uplift from unscheduled news.

What a forecaster can know at t-1 is used: today's regime is a mixture over the transition
probabilities from yesterday's regime, and deterministic stress shocks are left out (they are
surprises, not variance).  Realised P&L adds noise but is still reported (bias statistic and
Q-statistic) because it is the only yardstick available on real data.

Test portfolios: the strategy books, random dollar-neutral portfolios, the cap-weighted market,
and portfolios optimised with the model's own covariance (minimum variance and mean-variance
optimal for random alphas).  Optimised portfolios load on the directions the model thinks are
safest, so they expose under-forecasts; hedged books expose over-forecasts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from . import synthetic_data as sd
from .config import CN, MODEL, US, ModelConfig
from .risk_model import RiskModel, RiskModelBuilder

MC_DRAWS = 400_000
NEWS_P = 0.008            # daily probability of unscheduled news per stock (synthetic_data._calendars)


# --------------------------------------------------------------------------- #
# True covariance
# --------------------------------------------------------------------------- #
@dataclass
class TrueCovariance:
    market: str
    dates: pd.DatetimeIndex
    tickers: pd.Index
    loadings: list           # names of the columns of A
    A: np.ndarray            # T x N x M
    Omega: np.ndarray        # T x M x M
    D: np.ndarray            # T x N

    def portfolio_var(self, t: int, H: np.ndarray) -> np.ndarray:
        """True variance of each row of H (P x N, same ticker order) on day t."""
        a = H @ self.A[t]
        return np.einsum("pm,mk,pk->p", a, self.Omega[t], a) + (H ** 2) @ self.D[t]

    def aligned(self, dates: pd.DatetimeIndex, tickers: pd.Index) -> "TrueCovariance":
        ti = self.dates.get_indexer(dates)
        ni = self.tickers.get_indexer(tickers)
        if (ti < 0).any() or (ni < 0).any():
            raise ValueError(f"{self.market}: model dates/tickers not in the simulation")
        return replace(self, dates=dates, tickers=tickers, A=self.A[ti][:, ni], Omega=self.Omega[ti],
                       D=self.D[ti][:, ni])


class _KeepExposures(sd.EquitySim):
    """EquitySim that keeps the simulated factor exposures (the parent drops them after use)."""

    def _paths(self):
        self.Xkeep = self.Xgen.copy()
        super()._paths()


def _resimulate(cfg: sd.SimConfig):
    """Re-run the generator's draws in the same order, so every random number matches the data."""
    rng = np.random.default_rng(cfg.seed)
    cs = sd.CryptoSim(cfg, rng, cfg.n_crypto)
    mcal = sd.macro_calendar(cfg)
    macro = sd._macro_series(cfg, rng, mcal)
    us = _KeepExposures(US, cfg, rng, cfg.n_us, cs.btc_log_returns, None, macro, mcal)
    cn = _KeepExposures(CN, cfg, rng, cfg.n_cn, cs.btc_log_returns, us.fut_lr, macro, mcal)
    return cs, mcal, us, cn


def _shock_days(dates: pd.DatetimeIndex, code: str) -> dict:
    out = {}
    for ep in sd.STRESS_EPISODES:
        k = sd._snap(dates, pd.Timestamp(ep["date"]), "right")
        if k is not None and ep.get(code):
            for d in range(ep["days"]):
                if k + d < len(dates):
                    out[k + d] = ep[code]
    return out


def _regime_p1(regime: np.ndarray, stay0: float, stay1: float) -> np.ndarray:
    """P(regime_t = 1 | regime_{t-1})."""
    prev = np.r_[0, regime[:-1]]
    return np.where(prev == 1, stay1, 1 - stay0)


def _gap_sum(daily_var: pd.Series, dates: pd.DatetimeIndex) -> np.ndarray:
    """Variance of a move accumulated over calendar days in (dates[t-1], dates[t]]."""
    c = daily_var.cumsum()
    lvl = c.reindex(c.index.union(dates)).ffill().fillna(0.0).reindex(dates).values
    return np.r_[0.0, np.diff(lvl)]


def _equity_garch(sim) -> np.ndarray:
    """Market GJR-GARCH variance h_t (before the regime multiplier), rebuilt from the market factor."""
    sig = sd.MARKET_VOL[sim.spec.code]
    omega, a_g, g_g, b_g = sig ** 2 * 0.03, 0.02, 0.06, 0.92
    f = (sim.F_on + sim.F_id)["market"].values
    m = np.where(sim.regime == 1, 1.6, 1.0)
    shocks = _shock_days(sim.dates, sim.spec.code)
    h_out = np.full(sim.T, np.nan)
    h, eps_prev = sig ** 2, 0.0
    for t in range(1, sim.T):
        h = omega + (a_g + g_g * (eps_prev < 0)) * eps_prev ** 2 + b_g * h
        h_out[t] = h
        eps = f[t] - 0.0004 - shocks.get(t, {}).get("beta", 0.0) * 0.002
        eps_prev = eps / m[t]
    return h_out


def _coupled_block(code: str, prev_regime: int, macro: bool, c: float, rng) -> np.ndarray:
    """Covariance of (market, st_reversal, liquidity, crowding, vol_shock, liq_shock) by Monte Carlo.

    Market in units of sqrt(h_t); the three styles in units of their base vol; the two shocks in
    their own units.  Mirrors EquitySim._simulate."""
    n = MC_DRAWS
    stay = 0.90 if prev_regime else 0.99
    reg = np.where(rng.random(n) < stay, prev_regime, 1 - prev_regime)
    m = np.where(reg == 1, 1.6, 1.0)
    m_prev = 1.6 if prev_regime else 1.0
    noise = rng.standard_t(5, n) / math.sqrt(5 / 3) * (1.4 if macro else 1.0)
    mkt = m * noise
    a_g, g_g = 0.02, 0.06
    dv = (0.5 * np.log(c + (a_g + g_g * (noise < 0)) * noise ** 2) + 0.7 * np.log(m / m_prev)
          + 0.03 * rng.standard_normal(n))
    dl = 0.06 * 0.35 * reg + 0.035 * rng.standard_normal(n) + 0.08 * np.maximum(-noise - 1.0, 0.0)
    q = rng.standard_normal(n)
    s = m ** 0.8
    rev = s * (math.sqrt(0.7) * rng.standard_normal(n) + math.sqrt(0.3) * q - 0.35 * dl / 0.035 - 0.2 * dv / 0.06)
    liq = s * (rng.standard_normal(n) + 0.3 * dl / 0.035)
    crowd = s * (math.sqrt(0.7) * rng.standard_normal(n) - math.sqrt(0.3) * q)
    return np.cov(np.vstack([mkt, rev, liq, crowd, dv, dl]))


def _equity_truth(sim, cs, mcal: pd.DataFrame, us_truth: TrueCovariance | None, us_sim, rng) -> TrueCovariance:
    code, T, N = sim.spec.code, sim.T, sim.N
    is_cn = code == "CN"
    scale = 1.3 if is_cn else 1.0
    fac = list(sim.fac_names)
    K = len(fac)
    g_names = ["fx", "rates", "vol_shock", "liq_shock"] + (["us_session"] if is_cn else [])
    M = K + len(g_names)
    ix = {f: j for j, f in enumerate(fac + g_names)}

    # loadings
    B = np.column_stack([sim.ts_load[g] for g in g_names])
    live = sim.alive & ~sim.halted
    A = np.concatenate([sim.Xkeep.astype(float), np.broadcast_to(B, (T, N, B.shape[1]))], axis=2)
    A = np.where(live[..., None], A, 0.0)

    # regime mixture and GARCH state
    p1 = _regime_p1(sim.regime, 0.99, 0.90)
    e_m16 = (1 - p1) + p1 * 1.6 ** 1.6            # E[m^1.6]: variance of factors scaled by m^0.8
    e_m1 = (1 - p1) + p1 * 1.6                    # E[m]: specific variance scaled by sqrt(m)
    h = _equity_garch(sim)
    sig = sd.MARKET_VOL[code]
    c_med = float(np.nanmedian(sig ** 2 * 0.03 / h)) + 0.92

    Omega = np.zeros((T, M, M))
    d = np.arange(T)
    for f in fac[1:]:
        j = ix[f]
        if f.startswith("ind_"):
            base = sd.INDUSTRY_VOL * scale
        elif f == "crypto":
            continue
        else:
            base = sd.EQUITY_FACTOR_PARAMS[f][0] * scale
        Omega[d, j, j] = base ** 2 * e_m16
    rebal = np.zeros(T, bool); rebal[sim.rebal_idx] = True
    Omega[rebal, ix["etf_flow"], ix["etf_flow"]] *= 9.0

    # coupled block
    blk = [ix[f] for f in ("market", "st_reversal", "liquidity", "crowding", "vol_shock", "liq_shock")]
    base_vol = np.array([sd.EQUITY_FACTOR_PARAMS["st_reversal"][0] * scale * (1.2 if is_cn else 1.0),
                         sd.EQUITY_FACTOR_PARAMS["liquidity"][0] * scale,
                         sd.EQUITY_FACTOR_PARAMS["crowding"][0] * scale])
    cache = {(r, mac): _coupled_block(code, r, mac, c_med, rng) for r in (0, 1) for mac in (False, True)}
    prev = np.r_[0, sim.regime[:-1]]
    for t in range(1, T):
        S = np.r_[math.sqrt(h[t]), base_vol, 1.0, 1.0]
        Omega[t][np.ix_(blk, blk)] = cache[(int(prev[t]), bool(sim.macro_day[t]))] * np.outer(S, S)

    # crypto factor: BTC variance summed over the calendar gap
    if "crypto" in ix:
        Omega[:, ix["crypto"], ix["crypto"]] = _gap_sum(_btc_daily_var(cs), sim.dates)

    # fx and rates: daily vols with macro-day scaling, summed over the calendar gap
    days = pd.date_range(sim.cfg.start, sim.cfg.end, freq="D")
    wk = (days.dayofweek < 5).astype(float)
    on_us = days.isin(pd.DatetimeIndex(mcal[mcal.market == "US"].date))
    on_cn = days.isin(pd.DatetimeIndex(mcal[mcal.market == "CN"].date))
    if is_cn:
        fx_d = 0.0018 * wk * np.where(on_cn, 1.5, 1.0)
        rt_d = 0.0012 * wk * np.where(on_cn, 2.0, 1.0)
    else:
        fx_d = 0.004 * wk * np.where(on_us, 2.0, 1.0)
        rt_d = 0.0035 * wk * np.where(on_us, 2.5, 1.0)
    Omega[:, ix["fx"], ix["fx"]] = _gap_sum(pd.Series(fx_d ** 2, days), sim.dates)
    Omega[:, ix["rates"], ix["rates"]] = _gap_sum(pd.Series(rt_d ** 2, days), sim.dates)

    # prior US session (China): true variance of the US index over the US days since the last CN close
    if is_cn:
        mc = np.exp(us_sim.logmcap)
        w = np.vstack([mc[:1], mc[:-1]]) * us_sim.alive * ~us_sim.halted
        w = w / w.sum(1, keepdims=True)
        v = np.nan_to_num(np.array([us_truth.portfolio_var(t, w[t:t + 1])[0] for t in range(us_sim.T)])) \
            + 2 * 0.0003 ** 2
        cum = pd.Series(v, us_sim.dates).cumsum()
        before = lambda x: cum[cum.index < x].iloc[-1] if (cum.index < x).any() else 0.0
        lv = np.array([before(x) for x in sim.dates])
        Omega[:, ix["us_session"], ix["us_session"]] = np.r_[0.0, np.diff(lv)]

    # specific variance
    ip = np.vstack([np.zeros((1, N), bool), sim.news[:-1]])
    mult = np.where(sim.earn, 9.0, NEWS_P * 25.0 + (1 - NEWS_P) * np.where(ip, 2.2 ** 2, 1.0))
    D = sim.spec_vol[None, :] ** 2 * e_m1[:, None] * mult
    D = np.where(live, D, 0.0)
    Omega[0] = np.nan
    return TrueCovariance(code, sim.dates, pd.Index(sim.tickers), fac + g_names, A, Omega, D)


def _btc_daily_var(cs) -> pd.Series:
    """BTC conditional daily variance: GARCH(1,1) with t(4) shocks times the crypto regime mixture."""
    f = cs.F["btc"].values
    m = np.where(cs.regime == 1, 1.8, 1.0)
    p1 = _regime_p1(cs.regime, 0.985, 0.93)
    e_m2 = (1 - p1) + p1 * 1.8 ** 2
    out = np.zeros(cs.T)
    h, eps_prev = 0.028 ** 2, 0.0
    for t in range(1, cs.T):
        h = 0.028 ** 2 * 0.03 + 0.07 * eps_prev ** 2 + 0.90 * h
        out[t] = h * e_m2[t]
        eps_prev = (f[t] - 0.0012) / m[t]
    return pd.Series(out, cs.dates)


def _crypto_truth(cs) -> TrueCovariance:
    T, N = cs.T, cs.N
    S = len(sd.CRYPTO_SECTORS)
    names = ["btc", "alt"] + [f"sec_{s}" for s in sd.CRYPTO_SECTORS] + ["size", "momentum", "funding", "token_unlock"]
    M = len(names)
    is_btc = cs.symbols == "BTC"
    A = np.zeros((T, N, M))
    A[:, :, 0] = cs.beta_btc
    A[:, :, 1] = cs.beta_alt
    A[:, np.arange(N), 2 + cs.sector] = 1.0
    for t in range(1, T):
        A[t, :, 2 + S] = sd._z(cs.logmcap[t - 1])
        A[t, :, 3 + S] = sd._z(cs.r[max(0, t - 7):t].sum(0))
        A[t, :, 4 + S] = sd._z(cs.funding[t - 1])
    A[:, :, 5 + S] = cs.unlock
    A[:, is_btc, :] = 0.0
    A[:, is_btc, 0] = 1.0
    p1 = _regime_p1(cs.regime, 0.985, 0.93)
    e_m2 = (1 - p1) + p1 * 1.8 ** 2
    e_m1 = (1 - p1) + p1 * 1.8
    Omega = np.zeros((T, M, M))
    Omega[:, 0, 0] = _btc_daily_var(cs).values
    vols = {1: 0.018, **{2 + j: 0.012 for j in range(S)}, 2 + S: 0.006, 3 + S: 0.008, 4 + S: 0.005}
    for j, v in vols.items():
        Omega[:, j, j] = v ** 2 * e_m2
    Omega[:, 5 + S, 5 + S] = 0.01 ** 2
    D = cs.spec_vol[None, :] ** 2 * e_m1[:, None] * np.ones((T, N))
    D[:, is_btc] = 0.0
    Omega[0] = np.nan
    return TrueCovariance("CRYPTO", cs.dates, pd.Index(cs.symbols), names, A, Omega, D)


def true_covariances(cfg: sd.SimConfig | None = None, seed: int = 11) -> dict[str, TrueCovariance]:
    """Rebuild the true conditional covariance for every market from the simulator."""
    cfg = cfg or sd.SimConfig()
    cs, mcal, us, cn = _resimulate(cfg)
    rng = np.random.default_rng(seed)
    out = {"US": _equity_truth(us, cs, mcal, None, None, rng)}
    out["CN"] = _equity_truth(cn, cs, mcal, out["US"], us, rng)
    out["CRYPTO"] = _crypto_truth(cs)
    return out


def check_truth(truth: TrueCovariance, returns: pd.DataFrame, start: pd.Timestamp) -> dict:
    """Sanity check: realised squared returns divided by the true variance should average 1."""
    R = returns.reindex(index=truth.dates, columns=truth.tickers).values
    t0 = truth.dates.searchsorted(start)
    var = np.einsum("tnm,tmk,tnk->tn", truth.A[t0:], truth.Omega[t0:], truth.A[t0:]) + truth.D[t0:]
    r = R[t0:]
    ok = np.isfinite(r) & (var > 0)
    z2 = r[ok] ** 2 / var[ok]
    return {"mean_z2_stock": float(np.mean(np.clip(z2, 0, 100))), "median_z2_stock": float(np.median(z2))}


# --------------------------------------------------------------------------- #
# Test portfolios
# --------------------------------------------------------------------------- #
@dataclass
class PortfolioSet:
    """Fixed test portfolios for one market: name -> (group, T x N holdings)."""
    market: str
    holdings: dict
    realised_ret: dict        # name -> T x N returns the portfolio earns (book returns for strategies)


def fixed_portfolios(market: str, fm, truth: TrueCovariance, books: dict, n_random: int = 10,
                     seed: int = 0) -> PortfolioSet:
    e = fm.expo
    T, N = len(e.dates), len(e.tickers)
    live = np.all(np.isfinite(e.X), 2) & (truth.D > 0)
    rng = np.random.default_rng(seed)
    R = fm.returns.reindex(index=e.dates, columns=e.tickers).fillna(0.0).values
    H, Rr = {}, {}
    for s, b in books.items():
        H[s] = ("strategy", b.h.reindex(index=e.dates, columns=e.tickers).fillna(0.0).values)
        Rr[s] = b.ret.reindex(index=e.dates, columns=e.tickers).fillna(0.0).values
    for k in range(n_random):
        w = np.where(live, rng.standard_normal(N), 0.0)
        w = w - live * (w.sum(1, keepdims=True) / np.maximum(live.sum(1, keepdims=True), 1))
        w = w / np.maximum(np.abs(w).sum(1, keepdims=True), 1e-12)
        H[f"random_ls_{k}"] = ("random long/short", w)
        Rr[f"random_ls_{k}"] = R
    cap = np.nan_to_num(e.cap.reindex(index=e.dates, columns=e.tickers).values) * live
    H["cap_weighted"] = ("cap-weighted long", cap / np.maximum(cap.sum(1, keepdims=True), 1e-12))
    Rr["cap_weighted"] = R
    return PortfolioSet(market, H, Rr)


def optimised_portfolios(rm: RiskModel, fm, truth: TrueCovariance, days: np.ndarray, n_alpha: int = 5,
                         seed: int = 1) -> dict:
    """Portfolios optimised with the model's own covariance on the given days:
    minimum variance (fully invested) and mean-variance optimal for fixed random alphas."""
    e = fm.expo
    N = len(e.tickers)
    alphas = np.random.default_rng(seed).standard_normal((n_alpha, N))
    out = {"min_variance": np.zeros((len(e.dates), N))}
    out.update({f"opt_alpha_{k}": np.zeros((len(e.dates), N)) for k in range(n_alpha)})
    for t in days:
        X = rm.X[t]
        sv = rm.spec_var[t]
        U = np.all(np.isfinite(X), 1) & np.isfinite(sv) & (sv > 0) & e.estu.values[t] & (truth.D[t] > 0)
        if U.sum() < 30 or not np.isfinite(rm.F[t]).all():
            continue
        # (X F X' + D)^-1 b by Woodbury: D^-1 b - D^-1 X F (I + X' D^-1 X F)^-1 X' D^-1 b
        Xu, F, di = X[U], rm.F[t], 1.0 / sv[U]
        rhs = np.column_stack([np.ones(U.sum()), alphas[:, U].T])
        Db = rhs * di[:, None]
        XtD = Xu.T * di[None, :]
        inner = np.linalg.solve(np.eye(len(F)) + XtD @ Xu @ F, Xu.T @ Db)
        W = Db - (XtD.T @ (F @ inner))
        W = W / np.abs(W).sum(0, keepdims=True)
        out["min_variance"][t, U] = W[:, 0]
        for k in range(n_alpha):
            out[f"opt_alpha_{k}"][t, U] = W[:, 1 + k]
    return out


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def _pred_var(rm: RiskModel, t: int, H: np.ndarray, unmodelled_vol: float = 0.03) -> np.ndarray:
    """RiskModel.portfolio total variance for each row of H (vectorised)."""
    X = rm.X[t]
    valid = np.all(np.isfinite(X), 1)
    x = np.where(valid, H, 0.0) @ np.nan_to_num(X)
    fac = np.einsum("pk,kl,pl->p", x, rm.F[t], x)
    sv = np.where(valid, np.nan_to_num(rm.spec_var[t], nan=unmodelled_vol ** 2), unmodelled_vol ** 2)
    return fac + (H ** 2) @ sv, fac


def evaluate(rm: RiskModel, fm, truth: TrueCovariance, ps: PortfolioSet, start: pd.Timestamp,
             opt_every: int = 5) -> pd.DataFrame:
    """Daily forecast, true and realised outcome for every test portfolio.  Columns:
    portfolio, group, date, pred_vol, pred_factor_vol, true_vol, true_factor_vol, realised."""
    dates = rm.dates
    t0 = int(dates.searchsorted(start))
    days = np.arange(t0, len(dates) - 1)
    days = days[[np.isfinite(rm.F[t]).all() for t in days]]
    opt = optimised_portfolios(rm, fm, truth, days[::opt_every])
    names = list(ps.holdings) + list(opt)
    groups = [ps.holdings[n][0] for n in ps.holdings] + ["optimised: min variance"] + \
        ["optimised: random alpha"] * (len(opt) - 1)
    Hall = np.stack([ps.holdings[n][1] for n in ps.holdings] + [opt[n] for n in opt])     # P x T x N
    R = fm.returns.reindex(index=dates, columns=rm.tickers).fillna(0.0).values
    Rall = np.stack([ps.realised_ret[n] for n in ps.holdings] + [R] * len(opt))
    rows = []
    for t in days:
        H = Hall[:, t]
        keep = np.abs(H).sum(1) > 0
        if not keep.any():
            continue
        pv, pf = _pred_var(rm, t, H)
        a = H @ truth.A[t]
        tf = np.einsum("pm,mk,pk->p", a, truth.Omega[t], a)
        tv = tf + (H ** 2) @ truth.D[t]
        real = (H * Rall[:, t]).sum(1)
        for p in np.flatnonzero(keep & (tv > 0) & (pv > 0)):
            rows.append((names[p], groups[p], dates[t], math.sqrt(pv[p]), math.sqrt(max(pf[p], 0)),
                         math.sqrt(tv[p]), math.sqrt(max(tf[p], 0)), real[p]))
    return pd.DataFrame(rows, columns=["portfolio", "group", "date", "pred_vol", "pred_factor_vol", "true_vol",
                                       "true_factor_vol", "realised"])


def summarise(ev: pd.DataFrame, window: int = MODEL.bias_window) -> pd.DataFrame:
    """Per portfolio: forecast / true vol (geometric mean), its log RMS error, and the realised
    bias statistic and Q-statistic (mean of z^2 - ln z^2, lower is better)."""
    ev = ev.assign(lr=np.log(ev.pred_vol / ev.true_vol), z=ev.realised / ev.pred_vol,
                   zt=ev.realised / ev.true_vol)
    rows = []
    for (g, p), x in ev.groupby(["group", "portfolio"], sort=False):
        z = x.z.values
        z2 = np.clip(z ** 2, 1e-8, None)
        b = [x.z.iloc[i:i + window].std() for i in range(0, len(x) - window + 1, window)]
        rows.append({"group": g, "portfolio": p, "n_days": len(x),
                     "pred_over_true": float(np.exp(x.lr.mean())), "log_rmse": float(np.sqrt((x.lr ** 2).mean())),
                     "factor_pred_over_true": float(np.exp(np.log(x.pred_factor_vol / x.true_factor_vol)
                                                           .replace([np.inf, -np.inf], np.nan).mean())),
                     "bias_realised": float(np.mean(b)) if b else np.nan,
                     "bias_if_true": float(x.zt.std()),
                     "q_stat": float(np.mean(z2 - np.log(z2)))})
    return pd.DataFrame(rows)


def score(summary: pd.DataFrame) -> dict:
    """One number per objective, each group weighted equally (so ten random portfolios do not
    outvote six strategies):  truth = mean log RMS error vs the true vol;  realised = mean Q-statistic."""
    g = summary.groupby("group")
    return {"truth_log_rmse": float(g.log_rmse.mean().mean()),
            "truth_abs_log_bias": float(g.pred_over_true.apply(lambda s: np.abs(np.log(s)).mean()).mean()),
            "realised_q": float(g.q_stat.mean().mean())}


# --------------------------------------------------------------------------- #
# Running a configuration
# --------------------------------------------------------------------------- #
def build_risk(models: dict, panels: dict, cfg: ModelConfig, event_factors: dict) -> dict:
    out = {}
    for m, fm in models.items():
        md = getattr(panels[m], "macro_day", None)
        out[m] = RiskModelBuilder(fm, cfg, event_factors=event_factors[m], macro_day=md).build()
    return out


def run_config(cfg: ModelConfig, models: dict, panels: dict, truths: dict, psets: dict, event_factors: dict,
               start: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    risk = build_risk(models, panels, cfg, event_factors)
    ev = []
    for m in models:
        ev.append(evaluate(risk[m], models[m], truths[m], psets[m], start).assign(market=m))
    ev = pd.concat(ev, ignore_index=True)
    sm = pd.concat([summarise(x).assign(market=m) for m, x in ev.groupby("market")], ignore_index=True)
    return ev, sm


# --------------------------------------------------------------------------- #
# Ablation and tuning
# --------------------------------------------------------------------------- #
# Settings before this calibration, kept so the report can always show the comparison.
PRE_CALIBRATION = dict(lw_max=0.25, eigen_scale=1.4, vra_halflife=21, vol_halflife=21, corr_halflife=84,
                       specific_halflife=42, event_specific_mult=3.0, macro_mult_cap=3.0, macro_prior_obs=10.0,
                       macro_per_factor=False, denoise_factor_cov=False, specific_leverage_adj=False)

TUNING_GRID = {"lw_max": [0.1, 0.25, 0.4, 0.6, 1.0], "eigen_scale": [0.0, 0.5, 1.0, 1.4, 1.8],
               "vra_halflife": [10, 21, 42], "vol_halflife": [15, 21, 42], "corr_halflife": [63, 84, 126, 168],
               "specific_halflife": [21, 42, 84], "event_specific_mult": [2.2, 3.0],
               "macro_mult_cap": [3.0, 6.0], "macro_prior_obs": [5.0, 10.0, 20.0]}


def ablations(base: ModelConfig) -> dict[str, ModelConfig]:
    """Each layer of the risk model switched off on its own, plus everything off."""
    return {
        "current": base,
        "no eigen adjustment": replace(base, eigen_scale=0.0),
        "no Ledoit-Wolf shrinkage": replace(base, lw_max=0.0),
        "no factor VRA": replace(base, vra_factor=False),
        "no specific VRA": replace(base, vra_specific=False),
        "no macro-day uplift": replace(base, macro_mult_cap=1.0),
        "no event-day specific uplift": replace(base, event_specific_mult=1.0),
        "no factor de-noising": replace(base, denoise_factor_cov=False),
        "no specific leverage adjustment": replace(base, specific_leverage_adj=False),
        "raw EWMA (all off)": replace(base, eigen_scale=0.0, lw_max=0.0, vra_factor=False, vra_specific=False,
                                      macro_mult_cap=1.0, event_specific_mult=1.0, denoise_factor_cov=False,
                                      specific_leverage_adj=False),
    }


class Calibrator:
    """Evaluates risk-model configurations on fixed fitted factor models (only the risk layer is rebuilt).

    The evaluation period is split in two: parameters are chosen on the first half ("fit") and
    checked on the second ("test")."""

    def __init__(self, models: dict, panels: dict, books: dict, event_factors: dict, start: pd.Timestamp,
                 truths: dict | None = None, split: pd.Timestamp | None = None):
        self.models, self.panels, self.event_factors, self.start = models, panels, event_factors, start
        truths = truths or true_covariances()
        self.truths = {m: truths[m].aligned(models[m].expo.dates, models[m].expo.tickers) for m in models}
        self.psets = {m: fixed_portfolios(m, models[m], self.truths[m], books.get(m, {})) for m in models}
        end = max(fm.expo.dates[-1] for fm in models.values())
        self.split = split or start + (end - start) / 2
        self._cache: dict = {}

    def evaluate(self, cfg: ModelConfig) -> pd.DataFrame:
        key = repr(cfg)
        if key not in self._cache:
            risk = build_risk(self.models, self.panels, cfg, self.event_factors)
            self._cache[key] = pd.concat([evaluate(risk[m], self.models[m], self.truths[m], self.psets[m],
                                                   self.start).assign(market=m) for m in self.models],
                                         ignore_index=True)
        return self._cache[key]

    @staticmethod
    def summary(ev: pd.DataFrame) -> pd.DataFrame:
        return pd.concat([summarise(x).assign(market=m) for m, x in ev.groupby("market")], ignore_index=True)

    def scores(self, cfg: ModelConfig) -> dict:
        ev = self.evaluate(cfg)
        return {part: score(self.summary(x)) for part, x in
                (("fit", ev[ev.date < self.split]), ("test", ev[ev.date >= self.split]), ("all", ev))}

    def tune(self, base: ModelConfig, grid: dict = TUNING_GRID, rounds: int = 2, min_gain: float = 1e-3,
             log=print) -> tuple[ModelConfig, pd.DataFrame]:
        """Coordinate descent on the truth error of the fit half.  A move is kept only if it lowers
        the fit error by at least min_gain and does not raise the test error by more than min_gain,
        so parameters that only fit the first half's episodes are not adopted."""
        cur, rows = base, []
        for rnd in range(rounds):
            moved = False
            for p, vals in grid.items():
                now = self.scores(cur)
                res = {}
                for v in vals:
                    s = self.scores(replace(cur, **{p: v}))
                    res[v] = s
                    rows.append({"round": rnd, "parameter": p, "value": v, "fit": s["fit"]["truth_log_rmse"],
                                 "test": s["test"]["truth_log_rmse"], "abs_log_bias": s["all"]["truth_abs_log_bias"],
                                 "realised_q": s["all"]["realised_q"]})
                best = min(res, key=lambda v: res[v]["fit"]["truth_log_rmse"])
                gain = now["fit"]["truth_log_rmse"] - res[best]["fit"]["truth_log_rmse"]
                worse = res[best]["test"]["truth_log_rmse"] - now["test"]["truth_log_rmse"]
                if best != getattr(cur, p) and gain >= min_gain and worse <= min_gain:
                    cur = replace(cur, **{p: best})
                    moved = True
                    log(f"  round {rnd}: {p} -> {best} (fit {-gain:+.4f}, test {worse:+.4f})")
            if not moved:
                break
        return cur, pd.DataFrame(rows)

# Macro-day variance scalings in the simulator (synthetic_data._simulate and _macro_series):
# market shock x1.4 (variance x1.96); US: dollar index x2, 10y futures x2.5; CN: USDCNY x1.5, 10y x2.
TRUE_MACRO_UPLIFT = {"US": {"market": 1.96, "fx": 4.0, "rates": 6.25}, "CN": {"market": 1.96, "fx": 2.25, "rates": 4.0}}

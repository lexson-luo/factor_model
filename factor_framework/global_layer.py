"""Global linking layer (Sections 3.2 'Linking local models' and 3.4).

Each local model (US, CN, CRYPTO) keeps its own factor covariance.  The global
layer only estimates the *cross-model* correlations:

1. Local factor returns are aligned on the firm reporting calendar (business
   days): returns between two reporting dates are summed, so CN holidays and
   crypto weekends roll into the next reporting day.
2. Returns are synchronised to the reference (US) close (Burns, Engle and
   Mezrich 1998).  CN closes before the US session, so a CN return reacts to
   US moves its close has not yet seen only on the next CN session.  For each
   early-closing block, P_t = reference returns since the block's last close
   (US sessions after it, up to the US close on t) and
       r~_t = r_t + B_t P_t - B_{t-1} P_{t-1},
   with B the point-in-time EWMA regression of the block's session returns on
   P_{t-1}.  The B P terms telescope, so multi-day returns are unchanged; CN
   holidays carry P forward until the next CN session.
3. Cross correlations: EWMA covariances of the synchronised returns divided
   by the EWMA volatilities of the unsynchronised returns.  The synchronised
   returns get the covariance with the reference market right, but the
   unpredicted part of the catch-up stays in r~ (it is negatively
   autocorrelated, with inflated daily variance); the raw daily variance is
   also what the local models' volatilities estimate.  Diagonal blocks come
   from the local risk models; off-diagonal blocks are cross correlations
   times local volatilities; a final eigenvalue floor removes the
   inconsistency between the local blocks (regime-, eigen- and shrinkage-
   adjusted) and the sample cross-correlations (size kept in ``psd_repair``).
   It bites hardest on near-collinear cross-market pairs, which is why:
4. Factors that are another block's factor seen late are mapped, not carried
   twice: CN:us_session, synchronised, is ~0.98 correlated with US:market.
   Exposure to it goes to US:market (times a point-in-time beta) plus a small
   CN basis factor (the tracking difference), so a CN book's overnight US
   exposure nets against the US books' market exposure (``map_factors``).
   The CN local model, its attribution and its limits keep us_session as is.
5. A currency factor (CNY vs USD) captures FX risk on non-USD holdings.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import MODEL, ModelConfig
from .risk_model import RiskModel


def _psd(M: np.ndarray, floor: float = 1e-12) -> np.ndarray:
    M = 0.5 * (M + M.T)
    d, U = np.linalg.eigh(M)
    return (U * np.clip(d, floor, None)) @ U.T


@dataclass
class FirmRisk:
    date: pd.Timestamp
    total_vol: float
    standalone_vol: pd.Series         # by model block (incl. its specific risk)
    contribution: pd.Series           # Euler contribution by block
    factor_contrib: pd.Series         # by global factor
    diversification: float            # sum of standalone - total
    block_corr: pd.DataFrame


class GlobalRiskLayer:
    def __init__(self, risk_models: dict, factor_returns: dict, usd_per_cny: pd.Series,
                 calendar: pd.DatetimeIndex, cfg: ModelConfig = MODEL):
        self.rms, self.cfg = risk_models, cfg
        self.calendar = calendar
        self.blocks, self.session = {}, {}
        cols, aligned = [], []
        for name, fr in factor_returns.items():
            c = fr.fillna(0).cumsum()
            a = c.reindex(c.index.union(calendar)).ffill().reindex(calendar).diff()
            a.columns = [f"{name}:{f}" for f in fr.columns]
            self.blocks[name] = list(a.columns)
            # calendar days on which the block's market closed (a session ended on or before t
            # and after t-1); for a market on the business calendar that is simply t in its dates
            k = fr.index.searchsorted(calendar, "right")
            self.session[name] = np.r_[k[0] > 0, k[1:] > k[:-1]]
            aligned.append(a)
        fx = np.log(usd_per_cny).reindex(usd_per_cny.index.union(calendar)).ffill().reindex(calendar).diff()
        aligned.append(fx.rename("FX:CNY").to_frame())
        self.blocks["FX"] = ["FX:CNY"]
        self.returns = pd.concat(aligned, axis=1).fillna(0.0)
        self.returns_sync, self.sync_betas = self.synchronise(dict(cfg.sync_leads))
        # estimation frames: global factors after mapping (see map_factors)
        self.local_idx = {n: list(range(len(c))) for n, c in self.blocks.items() if n != "FX"}
        self.est_sync, self.est_raw, self.mapped = self.returns_sync, self.returns, {}
        self.map_factors(dict(cfg.map_factors))
        self.factors = list(self.est_sync.columns)

    def map_factors(self, mapping: dict):
        """Replace each source factor by a basis factor and map its exposure onto the target.

        A source such as CN:us_session is, once synchronised, the target (US:market) seen a day
        late.  Carrying both makes the global matrix hold a ~0.98 cross-block correlation that
        is inconsistent with the local blocks, and the PSD repair dilutes it.  Instead, exposure
        x to the source becomes b_t x to the target plus x to basis_t = r~_source - b_t r_target,
        with b_t the EWMA regression slope on data to t-1.  The basis keeps the tracking risk
        and sits in the source's block (its variance from a short-half-life EWMA)."""
        cfg = self.cfg
        lam = 0.5 ** (1 / cfg.corr_halflife)
        est, est_raw = self.est_sync.copy(), self.est_raw.copy()
        for src, tgt in mapping.items():
            if src not in est or tgt not in est:
                continue
            name = src.split(":")[0]
            s, y = est[src].values, est[tgt].values
            b = np.zeros(len(s))
            sxy = syy = 0.0
            for t in range(len(s)):
                if t >= cfg.cov_min_obs and syy > 0:
                    b[t] = sxy / syy
                sxy = lam * sxy + (1 - lam) * s[t] * y[t]
                syy = lam * syy + (1 - lam) * y[t] ** 2
            basis = f"{src}_basis"
            e = s - b * y
            est = est.drop(columns=src).assign(**{basis: e})
            est_raw = est_raw.drop(columns=src).assign(**{basis: e})
            k = self.blocks[name].index(src)
            self.local_idx[name] = [i for i in self.local_idx[name] if i != self.local_idx[name][k]]
            self.blocks[name] = [c for c in self.blocks[name] if c != src] + [basis]
            self.mapped[src] = (tgt, basis, b)
        self.est_sync, self.est_raw = est, est_raw

    def synchronise(self, leads_by_block: dict) -> tuple[pd.DataFrame, dict]:
        """Synchronise early-closing blocks to the reference close (see module docstring).
        Returns the synchronised returns and, per block, the B_t history (T x K_block x K_lead)."""
        cfg = self.cfg
        out = self.returns.copy()
        betas = {}
        lam = 0.5 ** (1 / cfg.corr_halflife)
        for name, leads in leads_by_block.items():
            leads = [f for f in leads if f in self.returns]
            if name not in self.blocks or not leads:
                continue
            r = self.returns[self.blocks[name]].values
            L = self.returns[leads].values
            sess = self.session[name]
            T, Kb, Kl = len(r), r.shape[1], L.shape[1]
            P = np.zeros((T, Kl))           # reference returns the block's last close has not seen
            for t in range(T):
                P[t] = L[t] + (P[t - 1] if t > 0 and not sess[t] else 0.0)
            B = np.zeros((T, Kb, Kl))
            Spp = np.zeros((Kl, Kl)); Srp = np.zeros((Kb, Kl)); n = 0
            for t in range(1, T):
                if sess[t]:                 # the session return r_t absorbs P_{t-1}
                    Spp = lam * Spp + (1 - lam) * np.outer(P[t - 1], P[t - 1])
                    Srp = lam * Srp + (1 - lam) * np.outer(r[t], P[t - 1])
                    n += 1
                if n >= cfg.cov_min_obs:
                    B[t] = Srp @ np.linalg.pinv(Spp)
                else:
                    B[t] = 0.0
            BP = np.einsum("tkl,tl->tk", B, P)
            adj = BP - np.r_[np.zeros((1, Kb)), BP[:-1]]
            out[self.blocks[name]] = r + adj
            betas[name] = {"leads": leads, "B": B, "P": P}
        return out, betas

    def lead_lag(self) -> pd.DataFrame:
        r, rs = self.returns, self.returns_sync
        rows = []
        pairs = [("US:market", "CN:market"), ("US:market", "CRYPTO:market"), ("CRYPTO:market", "US:crypto_beta"),
                 ("US:crypto_beta", "CRYPTO:market")]
        for a, b in pairs:
            if a in r and b in r:
                wk = r[[a, b]].resample("W-FRI").sum()
                rows.append({"leader": a, "follower": b, "corr_same_day": r[a].corr(r[b]),
                             "corr_leader_lag1": r[a].shift(1).corr(r[b]),
                             "corr_same_day_synchronised": rs[a].corr(rs[b]),
                             "corr_weekly": wk[a].corr(wk[b])})
        return pd.DataFrame(rows)

    def build(self):
        cfg = self.cfg
        R, R_raw = self.est_sync.values, self.est_raw.values
        T, K = R.shape
        lam = 0.5 ** (1 / cfg.corr_halflife)
        G0 = np.zeros((K, K)); V = np.zeros(K); w = 0.0
        self.G = np.full((T, K, K), np.nan)
        self.psd_repair = np.full(T, np.nan)
        sv = np.zeros(K); sw = 0.0             # short-half-life variances (FX, basis factors)
        lv = 0.5 ** (1 / cfg.vol_halflife)
        for t in range(T):
            if t > cfg.cov_min_obs:
                S = G0 / w
                sd = np.sqrt(np.clip(V / w, 1e-14, None))
                C = S / np.outer(sd, sd)
                np.fill_diagonal(C, 1.0)
                vol = np.zeros(K)
                M = np.zeros((K, K))
                for name, cols in self.blocks.items():
                    ii = [self.factors.index(c) for c in cols]
                    if name == "FX":
                        vol[ii] = np.sqrt(sv[ii] / max(sw, 1e-12))
                        M[np.ix_(ii, ii)] = np.diag(vol[ii] ** 2)
                        continue
                    loc = self.local_idx[name]
                    nl = len(loc)
                    rm: RiskModel = self.rms[name]
                    k = rm.dates.searchsorted(self.calendar[t], "right") - 1
                    Floc = rm.F[k] if k >= 0 else None
                    if Floc is None or not np.isfinite(Floc).all():
                        Floc = np.diag(sd[ii[:nl]] ** 2)
                    else:
                        Floc = Floc[np.ix_(loc, loc)]
                    Fb = np.zeros((len(ii), len(ii)))
                    Fb[:nl, :nl] = Floc
                    for j in range(nl, len(ii)):          # basis factors: own variance only
                        Fb[j, j] = sv[ii[j]] / max(sw, 1e-12)
                    M[np.ix_(ii, ii)] = Fb
                    vol[ii] = np.sqrt(np.clip(np.diag(Fb), 0, None))
                cross = C * np.outer(vol, vol)
                for name, cols in self.blocks.items():
                    ii = [self.factors.index(c) for c in cols]
                    cross[np.ix_(ii, ii)] = M[np.ix_(ii, ii)]
                self.G[t] = _psd(cross)
                self.psd_repair[t] = np.linalg.norm(self.G[t] - cross) / np.linalg.norm(cross)
            rt = R[t]
            G0 = lam * G0 + (1 - lam) * np.outer(rt, rt)
            V = lam * V + (1 - lam) * R_raw[t] ** 2
            w = lam * w + (1 - lam)
            sv = lv * sv + (1 - lv) * R_raw[t] ** 2; sw = lv * sw + (1 - lv)
        return self

    def firm_risk(self, t: int, x_by_model: dict, spec_var_by_model: dict) -> FirmRisk:
        """x_by_model: model -> pd.Series of USD exposures (local factor names); FX handled via 'FX'.
        Exposure to a mapped factor goes to its target (times the beta) and to its basis."""
        x = np.zeros(len(self.factors))
        for name, ex in x_by_model.items():
            for f, v in ex.items():
                key = f"{name}:{f}" if name != "FX" else f
                if key in self.mapped:
                    tgt, basis, b = self.mapped[key]
                    x[self.factors.index(tgt)] += b[t] * v
                    x[self.factors.index(basis)] += v
                elif key in self.factors:
                    x[self.factors.index(key)] += v
        G = self.G[t]
        Gx = G @ x
        spec_total = sum(spec_var_by_model.values())
        var = float(x @ Gx) + spec_total
        tot = np.sqrt(max(var, 1e-18))
        fc = pd.Series(x * Gx / tot, index=self.factors)
        contrib, standalone, xb = {}, {}, {}
        for name, cols in self.blocks.items():
            ii = [self.factors.index(c) for c in cols]
            sv = spec_var_by_model.get(name, 0.0)
            contrib[name] = fc.iloc[ii].sum() + sv / tot
            xi = np.zeros_like(x); xi[ii] = x[ii]
            xb[name] = xi
            standalone[name] = np.sqrt(max(xi @ G @ xi + sv, 0))
        names = list(self.blocks)
        bc = pd.DataFrame(np.eye(len(names)), index=names, columns=names)
        for a in names:
            for b in names:
                if a != b and standalone[a] > 0 and standalone[b] > 0:
                    bc.loc[a, b] = (xb[a] @ G @ xb[b]) / (standalone[a] * standalone[b])
        sa = pd.Series(standalone)
        return FirmRisk(date=self.calendar[t], total_vol=tot, standalone_vol=sa, contribution=pd.Series(contrib),
                        factor_contrib=fc, diversification=sa.sum() - tot, block_corr=bc)
